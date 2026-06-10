"""Phase 2 pre-flight: date and physician-marker reconnaissance (read-only)."""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import LOGS_DIR, PARSED_DIR

logger = logging.getLogger(__name__)

_JSONL = "phase1_parsed.jsonl"
_FIELDS = ["clinical_info", "previous_imaging", "findings", "impression"]
_SNIPPET_HALF = 30
_MAX_EX = 5

# Date patterns -- ordered most-specific first (redaction applies in this order too)
_DATE_PATS: dict[str, re.Pattern] = {
    "month_name": re.compile(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"[\s,]+(?:19|20)\d{2}\b",
        re.IGNORECASE,
    ),
    "numeric": re.compile(
        r"\b(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2})\b"
    ),
    "year_only": re.compile(r"\b(?:19|20)\d{2}\b"),
}

# Physician-marker patterns
_PHYS_PATS: dict[str, re.Pattern] = {
    "Radmard": re.compile(r"\bRadmard\b", re.IGNORECASE),
    "MD": re.compile(r"\bMD\b"),
    "Dr": re.compile(r"\bDr\b"),
    "Prof": re.compile(r"\bProf\b", re.IGNORECASE),
}

_RADMARD_RE = re.compile(r"\bRadmard\b", re.IGNORECASE)
# Two or more consecutive Title-Case words (likely a name)
_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})+\b")


def _redact(text: str) -> str:
    for pat in _DATE_PATS.values():
        text = pat.sub("<DATE>", text)
    text = _RADMARD_RE.sub("<NAME>", text)
    text = _NAME_RE.sub("<NAME>", text)
    return text


def _snippet(text: str, m: re.Match) -> str:
    s = max(0, m.start() - _SNIPPET_HALF)
    e = min(len(text), m.end() + _SNIPPET_HALF)
    prefix = "..." if s > 0 else ""
    suffix = "..." if e < len(text) else ""
    raw = prefix + text[s:e].replace("\n", " ") + suffix
    return _redact(raw).strip()


def _on_radmard_line(text: str, m: re.Match) -> bool:
    ls = text.rfind("\n", 0, m.start())
    ls = ls + 1 if ls >= 0 else 0
    le = text.find("\n", m.end())
    le = le if le >= 0 else len(text)
    return bool(_RADMARD_RE.search(text[ls:le]))


def run() -> None:
    jsonl_path = PARSED_DIR / _JSONL
    if not jsonl_path.exists():
        logger.error("Input not found: %s", jsonl_path)
        sys.exit(1)

    records: list[dict] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    records.sort(key=lambda r: r.get("filename", ""))
    total = len(records)
    logger.info("Loaded %d records from %s", total, jsonl_path)

    # Q1: date_counts[pat][field] = total occurrences
    date_counts: dict[str, dict[str, int]] = {
        p: {f: 0 for f in _FIELDS} for p in _DATE_PATS
    }
    # examples keyed by (pat, field) -- only non-previous_imaging
    date_ex: dict[str, list[tuple[str, str]]] = {p: [] for p in _DATE_PATS}

    # Q2: phys_counts[marker][field] = total occurrences
    phys_counts: dict[str, dict[str, int]] = {
        mk: {f: 0 for f in _FIELDS} for mk in _PHYS_PATS
    }
    # non-Radmard-signoff examples per marker
    off_signoff_ex: dict[str, list[tuple[str, str]]] = {
        mk: [] for mk in ("Radmard", "MD", "Dr", "Prof")
    }
    off_signoff_total: dict[str, int] = {mk: 0 for mk in ("Radmard", "MD", "Dr", "Prof")}

    for rec in records:
        for field in _FIELDS:
            text: str = rec.get(field) or ""
            if not text:
                continue

            # Q1
            for pat_name, pat in _DATE_PATS.items():
                matches = list(pat.finditer(text))
                date_counts[pat_name][field] += len(matches)
                if field != "previous_imaging":
                    for m in matches:
                        if len(date_ex[pat_name]) < _MAX_EX:
                            date_ex[pat_name].append((field, _snippet(text, m)))

            # Q2
            for marker, pat in _PHYS_PATS.items():
                matches = list(pat.finditer(text))
                phys_counts[marker][field] += len(matches)
                for m in matches:
                    if not _on_radmard_line(text, m):
                        off_signoff_total[marker] += 1
                        if len(off_signoff_ex[marker]) < _MAX_EX:
                            off_signoff_ex[marker].append((field, _snippet(text, m)))

    logger.info(
        "Q1 non-previous_imaging date hits: %d",
        sum(
            date_counts[p][f]
            for p in _DATE_PATS
            for f in _FIELDS
            if f != "previous_imaging"
        ),
    )
    for mk in _PHYS_PATS:
        logger.info(
            "Q2 %s total=%d off-signoff=%d",
            mk,
            sum(phys_counts[mk].values()),
            off_signoff_total[mk],
        )

    # --- stdout report ---
    SEP = "=" * 66
    sep = "-" * 66

    print(f"\n{SEP}")
    print("Phase 2 Pre-flight Reconnaissance")
    print(f"{SEP}")
    print(f"Total records scanned : {total}")
    print(f"Input                 : {jsonl_path}")

    # Q1 table
    print(f"\n{sep}")
    print("Q1 -- DATE SHAPES  (match counts, all records)")
    print(sep)
    fw = 12  # field column width
    hdr = f"{'Pattern':<12}" + "".join(f"{f:>{fw}}" for f in _FIELDS) + f"{'TOTAL':>10}"
    print(hdr)
    print("-" * len(hdr))
    non_prev_total = 0
    for pat_name in _DATE_PATS:
        vals = [date_counts[pat_name][f] for f in _FIELDS]
        row_tot = sum(vals)
        non_prev = sum(date_counts[pat_name][f] for f in _FIELDS if f != "previous_imaging")
        non_prev_total += non_prev
        print(f"{pat_name:<12}" + "".join(f"{v:>{fw}}" for v in vals) + f"{row_tot:>10}")
    col_tots = [sum(date_counts[p][f] for p in _DATE_PATS) for f in _FIELDS]
    grand = sum(col_tots)
    print("-" * len(hdr))
    print(f"{'TOTAL':<12}" + "".join(f"{v:>{fw}}" for v in col_tots) + f"{grand:>10}")
    print(f"\nDate hits OUTSIDE previous_imaging: {non_prev_total}")

    print("\nExamples from non-previous_imaging fields (redacted):")
    any_ex = False
    for pat_name, examples in date_ex.items():
        if examples:
            any_ex = True
            print(f"  [{pat_name}]")
            for field, snip in examples:
                print(f"    [{field}] {snip}")
    if not any_ex:
        print("  (none)")

    # Q2 table
    print(f"\n{sep}")
    print("Q2 -- PHYSICIAN MARKERS  (match counts, all records)")
    print(sep)
    hdr2 = f"{'Marker':<12}" + "".join(f"{f:>{fw}}" for f in _FIELDS) + f"{'TOTAL':>10}"
    print(hdr2)
    print("-" * len(hdr2))
    for marker in _PHYS_PATS:
        vals = [phys_counts[marker][f] for f in _FIELDS]
        row_tot = sum(vals)
        print(f"{marker:<12}" + "".join(f"{v:>{fw}}" for v in vals) + f"{row_tot:>10}")

    print()
    for marker in ("MD", "Dr", "Prof"):
        tot = off_signoff_total[marker]
        print(f"Non-Radmard {marker} hits (off sign-off line): {tot}")
        if tot > 0:
            print(f"  Examples (redacted):")
            for field, snip in off_signoff_ex[marker]:
                print(f"    [{field}] {snip}")

    radmard_off = off_signoff_total["Radmard"]
    print(f"\nRadmard hits NOT on sign-off line: {radmard_off}")
    if radmard_off:
        print("  Examples (redacted):")
        for field, snip in off_signoff_ex["Radmard"]:
            print(f"    [{field}] {snip}")

    print(f"\n{SEP}\n")


if __name__ == "__main__":
    setup_logging("phase2_recon")
    run()
