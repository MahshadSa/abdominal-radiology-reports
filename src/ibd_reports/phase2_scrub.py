"""Phase 2 scrubber: names, dates, email, phone (subset validation run)."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.phase2_d1 import _build_union_tokens, _make_token_patterns
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import DEID_DIR, PARSED_DIR, STOPLIST_PATH

logger = logging.getLogger(__name__)

_DEFAULT_JSONL = "subset30_parsed.jsonl"
_SCRUB_FIELDS = ["clinical_info", "previous_imaging", "findings", "impression"]

# Pass 1: 3-group date with a 4-digit year group.
# [/.] only -- avoids matching hyphenated shapes like CA 19-9 or measurements.
# Year-first (1402.7.9) and year-last (03.01.2021) handled as two sub-passes.
_DATE4_YEAR_FIRST = re.compile(r"\b(\d{4})[/.]\d{1,2}[/.]\d{1,2}\b")
_DATE4_YEAR_LAST = re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.](\d{4})\b")

# Pass 2: 2-digit-year 3-group date (per CLAUDE.md spec).
_DATE2 = re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2}\b")

# Stoplist: common words that collide with surnames -- loaded once at startup.
def _load_stoplist() -> set[str]:
    if not STOPLIST_PATH.exists():
        return set()
    lines = STOPLIST_PATH.read_text(encoding="utf-8").splitlines()
    return {
        line.strip().lower()
        for line in lines
        if line.strip() and not line.startswith("#")
    }

_STOPLIST = _load_stoplist()

# Backstops
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(
    r"(?<!\w)(?:\+98|0098|0)9[\s.-]?\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b"
    r"|(?<!\w)(?:\+98|0098|0)\d{2,3}[\s.-]?\d{3,4}[\s.-]?\d{4}\b"
)


def _get_filename(record: dict) -> str:
    """Return name stem: 'filename' field, or 'source_filename' with .docx stripped."""
    if "filename" in record:
        return record["filename"]
    return record.get("source_filename", "").removesuffix(".docx")


def _scrub_text(
    text: str,
    token_patterns: list[tuple[str, re.Pattern]],
) -> tuple[str, int, int, int, int, int]:
    """Apply all scrub passes to one field in the required order.

    Returns (scrubbed_text, names, dates_4digit, dates_2digit, email, phone).
    """
    # Step 1: names -- whole-word, case-insensitive
    names = 0
    for _tok, pat in token_patterns:
        text, n = pat.subn("[NAME]", text)
        names += n

    # Step 2: dates pass 1 -- year-first sub-pass then year-last sub-pass
    dates_4 = 0
    text, n = _DATE4_YEAR_FIRST.subn(lambda m: m.group(1), text)
    dates_4 += n
    text, n = _DATE4_YEAR_LAST.subn(lambda m: m.group(1), text)
    dates_4 += n

    # Step 3: dates pass 2 -- 2-digit-year (runs after pass 1 has consumed 4-digit-year forms)
    text, dates_2 = _DATE2.subn("[DATE]", text)

    # Step 4: email backstop
    text, email = _EMAIL.subn("[EMAIL]", text)

    # Step 5: phone backstop (mobile and landline, combined count)
    text, phone = _PHONE.subn("[PHONE]", text)

    return text, names, dates_4, dates_2, email, phone


def _scrub_record(record: dict) -> tuple[dict, dict]:
    """Scrub the 4 target fields of one record. Returns (scrubbed_record, counts)."""
    filename = _get_filename(record)
    tokens = [t for t in _build_union_tokens(filename) if t not in _STOPLIST]
    patterns = _make_token_patterns(tokens)

    out = dict(record)
    if "source_filename" in out and "filename" not in out:
        out["filename"] = filename
        del out["source_filename"]

    totals: dict[str, int] = {
        "names": 0,
        "dates_4digit": 0,
        "dates_2digit": 0,
        "email": 0,
        "phone": 0,
    }
    for field in _SCRUB_FIELDS:
        text = record.get(field) or ""
        scrubbed, nm, d4, d2, em, ph = _scrub_text(text, patterns)
        out[field] = scrubbed
        totals["names"] += nm
        totals["dates_4digit"] += d4
        totals["dates_2digit"] += d2
        totals["email"] += em
        totals["phone"] += ph

    return out, totals


def run(jsonl_path: Path) -> None:
    if not jsonl_path.exists():
        logger.error("Input not found: %s", jsonl_path)
        sys.exit(1)

    records: list[dict] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    records.sort(key=_get_filename)
    logger.info("Loaded %d records from %s", len(records), jsonl_path)

    DEID_DIR.mkdir(parents=True, exist_ok=True)

    deid_records: list[dict] = []
    audit_rows: list[dict] = []
    run_totals: dict[str, int] = {
        "names": 0,
        "dates_4digit": 0,
        "dates_2digit": 0,
        "email": 0,
        "phone": 0,
    }
    flag_counts: dict[str, int] = {}

    for idx, record in enumerate(records):
        scrubbed, counts = _scrub_record(record)
        deid_records.append(scrubbed)

        flags: list[str] = []
        if counts["names"] >= 3:
            flags.append("name_hits_ge_3")
        if any(
            (record.get(f) or "").strip() and not (scrubbed.get(f) or "").strip()
            for f in _SCRUB_FIELDS
        ):
            flags.append("empty_field_after_scrub")
        if counts["email"] > 0 or counts["phone"] > 0:
            flags.append("email_or_phone_fired")

        audit_rows.append({"record_index": idx, **counts, "flags": flags})

        for k, v in counts.items():
            run_totals[k] += v
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

        if any(v > 0 for v in counts.values()) or flags:
            logger.info(
                "idx=%d names=%d dates_4=%d dates_2=%d email=%d phone=%d flags=%s",
                idx,
                counts["names"],
                counts["dates_4digit"],
                counts["dates_2digit"],
                counts["email"],
                counts["phone"],
                flags,
            )

    # De-identified JSONL
    deid_jsonl = DEID_DIR / "phase2_deid.jsonl"
    with deid_jsonl.open("w", encoding="utf-8") as fh:
        for rec in deid_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.info("Wrote %s (%d records)", deid_jsonl, len(deid_records))

    # De-identified CSV
    deid_csv = DEID_DIR / "phase2_deid.csv"
    pd.DataFrame(deid_records).to_csv(deid_csv, index=False, encoding="utf-8")
    logger.info("Wrote %s", deid_csv)

    # Audit JSONL (non-PHI: no filenames, no redacted text)
    audit_jsonl = DEID_DIR / "phase2_audit.jsonl"
    with audit_jsonl.open("w", encoding="utf-8") as fh:
        for row in audit_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info("Wrote %s (%d rows)", audit_jsonl, len(audit_rows))

    # Audit CSV (flags serialised as semicolon-joined string)
    audit_csv = DEID_DIR / "phase2_audit.csv"
    audit_flat = [
        {k: v for k, v in row.items() if k != "flags"} | {"flags": ";".join(row["flags"])}
        for row in audit_rows
    ]
    pd.DataFrame(audit_flat).to_csv(audit_csv, index=False, encoding="utf-8")
    logger.info("Wrote %s", audit_csv)

    # Run summary
    summary = {
        "total_records": len(deid_records),
        "totals": run_totals,
        "flag_record_counts": flag_counts,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    summary_path = DEID_DIR / "phase2_run_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Wrote %s", summary_path)

    SEP = "=" * 60
    sep = "-" * 60
    print(f"\n{SEP}")
    print("Phase 2 Scrubber")
    print(SEP)
    print(f"Input   : {jsonl_path}")
    print(f"Records : {len(deid_records)}")
    print(f"{sep}")
    for k, v in run_totals.items():
        print(f"  {k:<16}: {v}")
    if flag_counts:
        print(f"{sep}")
        print("Flags:")
        for flag, n in sorted(flag_counts.items()):
            print(f"  {flag}: {n} record(s)")
    print(f"{sep}")
    print(f"Outputs in {DEID_DIR}:")
    for p in (deid_jsonl, deid_csv, audit_jsonl, audit_csv, summary_path):
        print(f"  {p.name}")
    print(f"{SEP}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 scrubber (names, dates, backstops)")
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=PARSED_DIR / _DEFAULT_JSONL,
        help="Input JSONL (default: subset30_parsed.jsonl)",
    )
    args = parser.parse_args()

    log_file = setup_logging("phase2_scrub")
    logger.info("Logging to %s", log_file)
    logger.info("Phase 2 scrub start, input=%s", args.jsonl)
    run(args.jsonl)
    logger.info("Phase 2 scrub complete")


if __name__ == "__main__":
    main()
