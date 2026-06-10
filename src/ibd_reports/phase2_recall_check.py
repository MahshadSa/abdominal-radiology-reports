"""Phase 2 recall check: full-roster cross-report name search + regex sweeps.

Independent safety net for phase2_scrub.py. Read-only on the de-identified
corpus (DEID_DIR / phase2_deid.jsonl): searches every roster name token
(union of _build_union_tokens over every report's own filename, no stoplist)
against every de-identified record's four scrubbed fields, plus regex sweeps
confirming the date/email/phone backstops left no residue.
"""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.phase2_d1 import _YEAR4, _build_union_tokens, _make_token_patterns
from ibd_reports.phase2_scrub import (
    _DATE2,
    _DATE4_YEAR_FIRST,
    _DATE4_YEAR_LAST,
    _EMAIL,
    _PHONE,
)
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import DEID_DIR, PARSED_DIR

logger = logging.getLogger(__name__)

_DEID_JSONL = "phase2_deid.jsonl"
_ROSTER_JSONL = "phase1_parsed.jsonl"
_REPORT_CSV = "phase2_recall_report.csv"

_FIELDS = ["clinical_info", "previous_imaging", "findings", "impression"]
_SWEEP_TYPES = ["date_4digit", "date_2digit", "year_only", "email", "phone"]

_WORD = re.compile(r"\b\w+\b")


def build_roster(filenames: list[str]) -> set[str]:
    """Union of _build_union_tokens over every filename, deduplicated. No stoplist applied."""
    tokens: set[str] = set()
    for filename in filenames:
        tokens.update(_build_union_tokens(filename))
    return tokens


def _field_words(text: str) -> set[str]:
    """Lowercased whole-word set of a field, for fast roster-token pre-filtering."""
    return {w.lower() for w in _WORD.findall(text)}


def regex_sweep_counts(text: str) -> dict[str, int]:
    """Count date/email/phone sweep matches in one field of de-identified text."""
    return {
        "date_4digit": len(_DATE4_YEAR_FIRST.findall(text)) + len(_DATE4_YEAR_LAST.findall(text)),
        "date_2digit": len(_DATE2.findall(text)),
        "year_only": len(_YEAR4.findall(text)),
        "email": len(_EMAIL.findall(text)),
        "phone": len(_PHONE.findall(text)),
    }


def search_record(
    record: dict,
    roster_tokens: set[str],
    token_patterns: dict[str, re.Pattern],
) -> list[tuple[str, str, int]]:
    """Search _FIELDS of one de-identified record for roster tokens.

    Pre-filters with a whole-word set intersection -- exactly equivalent to
    \\b<token>\\b for the single-word tokens _build_union_tokens produces --
    then confirms and counts with the same compiled patterns
    _make_token_patterns produces. Returns (token, field, count) rows.
    """
    rows: list[tuple[str, str, int]] = []
    for field in _FIELDS:
        text: str = record.get(field) or ""
        if not text:
            continue
        candidates = roster_tokens & _field_words(text)
        for token in candidates:
            count = len(token_patterns[token].findall(text))
            if count:
                rows.append((token, field, count))
    return rows


def run() -> None:
    deid_path = DEID_DIR / _DEID_JSONL
    roster_path = PARSED_DIR / _ROSTER_JSONL

    if not deid_path.exists():
        logger.error("Input not found: %s", deid_path)
        sys.exit(1)
    if not roster_path.exists():
        logger.error("Input not found: %s", roster_path)
        sys.exit(1)

    roster_filenames: list[str] = []
    with roster_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                roster_filenames.append(json.loads(line).get("filename", ""))
    logger.info("Loaded %d roster filenames from %s", len(roster_filenames), roster_path)

    roster_tokens = build_roster(roster_filenames)
    logger.info("Distinct roster tokens: %d", len(roster_tokens))

    token_patterns = dict(_make_token_patterns(list(roster_tokens)))

    deid_records: list[dict] = []
    with deid_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                deid_records.append(json.loads(line))
    logger.info("Loaded %d de-identified records from %s", len(deid_records), deid_path)

    name_hit_rows: list[tuple[int, str, str, int]] = []
    token_totals: dict[str, dict] = defaultdict(lambda: {"total": 0, "records": set()})
    sweep_totals: dict[str, int] = {k: 0 for k in _SWEEP_TYPES}

    for idx, rec in enumerate(deid_records):
        for token, field, count in search_record(rec, roster_tokens, token_patterns):
            name_hit_rows.append((idx, token, field, count))
            token_totals[token]["total"] += count
            token_totals[token]["records"].add(idx)

        for field in _FIELDS:
            text = rec.get(field) or ""
            if not text:
                continue
            sweeps = regex_sweep_counts(text)
            for k, v in sweeps.items():
                sweep_totals[k] += v

    logger.info(
        "Done: %d records, %d name hit rows, sweeps=%s",
        len(deid_records),
        len(name_hit_rows),
        sweep_totals,
    )

    DEID_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEID_DIR / _REPORT_CSV
    with report_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["check_type", "record_index", "token_or_pattern", "field", "count"])
        for idx, token, field, count in sorted(name_hit_rows):
            writer.writerow(["name", idx, token, field, count])
        for check_type in _SWEEP_TYPES:
            writer.writerow([check_type, "", "", "", sweep_totals[check_type]])
    logger.info("Report written: %s", report_path)

    SEP = "=" * 60
    sep = "-" * 60
    print(f"\n{SEP}")
    print("Phase 2 Recall Check -- Full-Roster Cross-Search + Regex Sweeps")
    print(SEP)
    print(f"Distinct roster tokens : {len(roster_tokens)}")
    print(f"Records scanned        : {len(deid_records)}")
    print(f"Total name hits        : {len(name_hit_rows)}")

    if token_totals:
        print(f"\n{sep}")
        print("Name hits by token (descending total count):")
        print(f"{'token':<25} {'total':>8} {'records':>9}")
        print(sep)
        for token, stats in sorted(token_totals.items(), key=lambda kv: -kv[1]["total"]):
            print(f"{token:<25} {stats['total']:>8} {len(stats['records']):>9}")
    else:
        print("\nNo name hits found.")

    print(f"\n{sep}")
    print("Regex sweeps (deid text):")
    print(f"  date_4digit (pass-1 shape, expect 0)    : {sweep_totals['date_4digit']}")
    print(f"  date_2digit (pass-2 shape, expect 0)    : {sweep_totals['date_2digit']}")
    print(f"  year_only   (residual year, expect > 0) : {sweep_totals['year_only']}")
    print(f"  email       (expect 0)                  : {sweep_totals['email']}")
    print(f"  phone       (expect 0)                  : {sweep_totals['phone']}")
    print(f"\nReport written to: {report_path}")
    print(f"{SEP}\n")


def main() -> None:
    log_file = setup_logging("phase2_recall_check")
    logger.info("Logging to %s", log_file)
    logger.info("Phase 2 recall check start")
    run()
    logger.info("Phase 2 recall check complete")


if __name__ == "__main__":
    main()
