"""Phase 2 recon follow-up: bucket numeric date hits by group count."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import LOGS_DIR, PARSED_DIR

logger = logging.getLogger(__name__)

_JSONL = "phase1_parsed.jsonl"
_SNIPPET_HALF = 30
_MAX_PARTIAL_EX = 10
_MAX_FULL_EX = 300   # show all clinical_info full_date hits
_MAX_TWO_GROUP_EX = 20  # total across all fields, sampled 5 per field

_NUMERIC_DATE = re.compile(
    r"\b(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2})\b"
)
_SEP_SPLIT = re.compile(r"[/\-.]")
_RADMARD_RE = re.compile(r"\bRadmard\b", re.IGNORECASE)
_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})+\b")
_MONTH_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[\s,]+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# Broad 2-group pattern (no trailing year); space included per spec
_TWO_GROUP = re.compile(r"\b\d{1,2}[/ .\-]\d{1,2}\b")


def _classify(match_str: str) -> str:
    n = len(_SEP_SPLIT.split(match_str))
    if n == 3:
        return "full_date"
    if n == 2:
        return "partial"
    return "other"


def _structure_match(s: str) -> str:
    """Show separator-preserved shape: digits -> <D> (1-2) or <Y> (4)."""
    parts = _SEP_SPLIT.split(s)
    seps = _SEP_SPLIT.findall(s)
    out = []
    for i, part in enumerate(parts):
        if re.fullmatch(r"\d{4}", part):
            out.append("<Y>")
        elif re.fullmatch(r"\d{1,2}", part):
            out.append("<D>")
        else:
            out.append(f"<{part}>")
        if i < len(seps):
            out.append(seps[i])
    return "".join(out)


def _redact_context(text: str) -> str:
    text = _MONTH_RE.sub("<DATE>", text)
    text = _NUMERIC_DATE.sub("<DATE>", text)
    text = _YEAR_RE.sub("<DATE>", text)
    text = _RADMARD_RE.sub("<NAME>", text)
    text = _NAME_RE.sub("<NAME>", text)
    return text


def _snippet(text: str, m: re.Match) -> str:
    s = max(0, m.start() - _SNIPPET_HALF)
    e = min(len(text), m.end() + _SNIPPET_HALF)
    prefix = "..." if s > 0 else ""
    suffix = "..." if e < len(text) else ""
    before = text[s : m.start()].replace("\n", " ")
    after = text[m.end() : e].replace("\n", " ")
    structured = _structure_match(m.group())
    return _redact_context(prefix + before + structured + after + suffix).strip()


def _three_group_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _NUMERIC_DATE.finditer(text)]


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    s, e = span
    return any(s < es and e > ss for ss, es in spans)


def _scan_two_group(records: list[dict], field: str) -> list[tuple[str, re.Match]]:
    """2-group hits that do NOT overlap any already-counted 3-group span."""
    hits: list[tuple[str, re.Match]] = []
    for rec in records:
        text: str = rec.get(field) or ""
        if not text:
            continue
        three_spans = _three_group_spans(text)
        for m in _TWO_GROUP.finditer(text):
            if not _overlaps((m.start(), m.end()), three_spans):
                hits.append((text, m))
    return hits


def _scan(records: list[dict], field: str) -> dict[str, list[tuple[str, re.Match]]]:
    buckets: dict[str, list] = {"full_date": [], "partial": [], "other": []}
    for rec in records:
        text: str = rec.get(field) or ""
        for m in _NUMERIC_DATE.finditer(text):
            buckets[_classify(m.group())].append((text, m))
    return buckets


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
    logger.info("Loaded %d records", len(records))

    SEP = "=" * 66
    sep = "-" * 66

    print(f"\n{SEP}")
    print("Phase 2 Recon Follow-up: Numeric Date Classification")
    print(f"{SEP}\n")

    # --- clinical_info: full detail + snippets ---
    ci = _scan(records, "clinical_info")
    ci_total = sum(len(v) for v in ci.values())
    print(f"clinical_info  ({ci_total} hits)")
    print(sep)
    for label in ("full_date", "partial", "other"):
        print(f"  {label:<12}: {len(ci[label])}")

    print("\nSnippets (partial-heavy; match shown as <D>/<D>/<Y> etc., context redacted):")
    shown: list[tuple[str, str]] = []
    for text, m in ci["partial"][:_MAX_PARTIAL_EX]:
        shown.append(("partial", _snippet(text, m)))
    for text, m in ci["full_date"][:_MAX_FULL_EX]:
        shown.append(("full_date", _snippet(text, m)))
    for text, m in ci["other"][:3]:
        shown.append(("other", _snippet(text, m)))

    if shown:
        for label, snip in shown:
            print(f"  [{label}] {snip}")
    else:
        print("  (none)")

    # log counts
    logger.info(
        "clinical_info: full_date=%d partial=%d other=%d",
        len(ci["full_date"]), len(ci["partial"]), len(ci["other"]),
    )

    # --- findings and impression: counts + conditional snippets ---
    print(f"\n{sep}")
    print("findings / impression  (counts; snippets only if partial > 5)")
    print(sep)

    for field in ("findings", "impression"):
        buckets = _scan(records, field)
        total = sum(len(v) for v in buckets.values())
        print(f"\n{field}  ({total} hits)")
        for label in ("full_date", "partial", "other"):
            print(f"  {label:<12}: {len(buckets[label])}")
        logger.info(
            "%s: full_date=%d partial=%d other=%d",
            field, len(buckets["full_date"]), len(buckets["partial"]), len(buckets["other"]),
        )
        if len(buckets["partial"]) > 5:
            print("  Partial snippets (redacted):")
            for text, m in buckets["partial"][:_MAX_PARTIAL_EX]:
                print(f"    {_snippet(text, m)}")

    # --- SECOND PASS: broad 2-group hits (excluding full-date overlaps) ---
    all_fields = ["clinical_info", "previous_imaging", "findings", "impression"]
    print(f"\n{sep}")
    print("PASS 2 -- BROAD 2-GROUP HITS  (\\d{{1,2}}[/ .-]\\d{{1,2}}, no trailing year)")
    print("         Excludes spans already covered by 3-group matches.")
    print(sep)

    field_hits: dict[str, list] = {}
    two_group_total = 0
    for field in all_fields:
        hits = _scan_two_group(records, field)
        field_hits[field] = hits
        two_group_total += len(hits)
        logger.info("2-group %s: %d hits", field, len(hits))

    fw2 = 20
    print(f"\n{'Field':<22} {'2-group hits':>14}")
    print("-" * 38)
    for field in all_fields:
        print(f"  {field:<20} {len(field_hits[field]):>14}")
    print(f"  {'TOTAL':<20} {two_group_total:>14}")

    print(f"\nUp to {_MAX_TWO_GROUP_EX} snippets sampled across fields")
    print("(match shown as <D>/<D> etc., context redacted):\n")
    per_field_cap = _MAX_TWO_GROUP_EX // len(all_fields)
    for field in all_fields:
        shown_count = 0
        for text, m in field_hits[field]:
            if shown_count >= per_field_cap:
                break
            print(f"  [{field}] {_snippet(text, m)}")
            shown_count += 1

    print(f"\n{SEP}\n")


if __name__ == "__main__":
    setup_logging("phase2_recon_dates")
    run()
