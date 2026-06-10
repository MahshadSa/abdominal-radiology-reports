"""Phase 2 recon: targeted 2-digit-year date pass (read-only)."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import PARSED_DIR

logger = logging.getLogger(__name__)

_JSONL = "phase1_parsed.jsonl"
_FIELDS = ["clinical_info", "previous_imaging", "findings", "impression"]
_SNIPPET_HALF = 30
_MAX_SNIPPETS = 15
_PER_CELL_CAP = 3   # max snippets per (pattern, field) cell

_FULL_DATE = re.compile(
    r"\b(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2})\b"
)
# A: year-last 2-digit  e.g. 15.6.21  or  15/06/21
_PAT_A = re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2}\b")
# B: year-first 2-digit  e.g. 21.6.15  or  21/06/15
_PAT_B = re.compile(r"\b\d{2}[/.]\d{1,2}[/.]\d{1,2}\b")

_SEP_RE = re.compile(r"[/.]")
# False-positive guards
_CA_PREFIX_RE = re.compile(r"\bCA\s*$", re.IGNORECASE)
_MEAS_SUFFIX_RE = re.compile(r"^\s*(?:mm|cm|ml|mL|mg|kg|cc|l)\b")

_RADMARD_RE = re.compile(r"\bRadmard\b", re.IGNORECASE)
_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})+\b")
_MONTH_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[\s,]+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _three_group_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _FULL_DATE.finditer(text)]


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    s, e = span
    return any(s < es and e > ss for ss, es in spans)


def _structure_match(s: str, pat_label: str) -> str:
    """Preserve separators; tag digits as <D>, <YY>, or <Y>."""
    parts = _SEP_RE.split(s)
    seps = _SEP_RE.findall(s)
    out: list[str] = []
    for i, part in enumerate(parts):
        if re.fullmatch(r"\d{4}", part):
            tag = "<Y>"
        elif re.fullmatch(r"\d{2}", part):
            is_year_pos = (pat_label == "B" and i == 0) or (pat_label == "A" and i == 2)
            tag = "<YY>" if is_year_pos else "<D>"
        else:
            tag = "<D>"
        out.append(tag)
        if i < len(seps):
            out.append(seps[i])
    return "".join(out)


def _redact_context(text: str) -> str:
    text = _MONTH_RE.sub("<DATE>", text)
    text = _FULL_DATE.sub("<DATE>", text)
    text = _YEAR_RE.sub("<DATE>", text)
    text = _PAT_A.sub("<DATE>", text)
    text = _PAT_B.sub("<DATE>", text)
    text = _RADMARD_RE.sub("<NAME>", text)
    text = _NAME_RE.sub("<NAME>", text)
    return text


def _snippet(text: str, m: re.Match, pat_label: str) -> str:
    s = max(0, m.start() - _SNIPPET_HALF)
    e = min(len(text), m.end() + _SNIPPET_HALF)
    prefix = "..." if s > 0 else ""
    suffix = "..." if e < len(text) else ""
    before = text[s : m.start()].replace("\n", " ")
    after = text[m.end() : e].replace("\n", " ")
    structured = _structure_match(m.group(), pat_label)
    return _redact_context(prefix + before + structured + after + suffix).strip()


def _is_ca(text: str, m: re.Match) -> bool:
    window = text[max(0, m.start() - 6) : m.start()]
    return bool(_CA_PREFIX_RE.search(window))


def _is_meas(text: str, m: re.Match) -> bool:
    window = text[m.end() : m.end() + 12]
    return bool(_MEAS_SUFFIX_RE.match(window))


def _scan_field(
    records: list[dict], field: str, pat: re.Pattern, pat_label: str
) -> dict:
    hits: list[dict] = []
    ca_n = 0
    meas_n = 0
    for rec in records:
        text: str = rec.get(field) or ""
        if not text:
            continue
        three_spans = _three_group_spans(text)
        for m in pat.finditer(text):
            if _overlaps((m.start(), m.end()), three_spans):
                continue
            ca = _is_ca(text, m)
            meas = _is_meas(text, m)
            ca_n += ca
            meas_n += meas
            hits.append(
                {"text": text, "match": m, "ca": ca, "meas": meas,
                 "pat": pat_label, "field": field}
            )
    return {"hits": hits, "ca_n": ca_n, "meas_n": meas_n}


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

    SEP = "=" * 70
    sep = "-" * 70

    print(f"\n{SEP}")
    print("Phase 2 Recon: Targeted 2-Digit-Year Date Pass")
    print(f"{SEP}\n")

    fw = 8
    hdr = (
        f"{'Field':<22}"
        f"{'A count':>{fw}} {'A-CA':>6} {'A-meas':>7}"
        f"   {'B count':>{fw}} {'B-CA':>6} {'B-meas':>7}"
    )
    print(hdr)
    print("-" * len(hdr))

    all_hits: list[dict] = []
    totals: dict[str, int] = dict(a=0, b=0, a_ca=0, b_ca=0, a_meas=0, b_meas=0)

    for field in _FIELDS:
        ra = _scan_field(records, field, _PAT_A, "A")
        rb = _scan_field(records, field, _PAT_B, "B")
        na, nb = len(ra["hits"]), len(rb["hits"])
        totals["a"] += na
        totals["b"] += nb
        totals["a_ca"] += ra["ca_n"]
        totals["b_ca"] += rb["ca_n"]
        totals["a_meas"] += ra["meas_n"]
        totals["b_meas"] += rb["meas_n"]
        print(
            f"  {field:<20}"
            f"{na:>{fw}} {ra['ca_n']:>6} {ra['meas_n']:>7}"
            f"   {nb:>{fw}} {rb['ca_n']:>6} {rb['meas_n']:>7}"
        )
        all_hits.extend(ra["hits"])
        all_hits.extend(rb["hits"])
        logger.info(
            "%s: A=%d (ca=%d meas=%d)  B=%d (ca=%d meas=%d)",
            field, na, ra["ca_n"], ra["meas_n"], nb, rb["ca_n"], rb["meas_n"],
        )

    print("-" * len(hdr))
    print(
        f"  {'TOTAL':<20}"
        f"{totals['a']:>{fw}} {totals['a_ca']:>6} {totals['a_meas']:>7}"
        f"   {totals['b']:>{fw}} {totals['b_ca']:>6} {totals['b_meas']:>7}"
    )

    def _contam(ca: int, meas: int, total: int) -> str:
        if total == 0:
            return "n/a"
        return f"{ca + meas}/{total} = {(ca + meas) / total * 100:.1f}%"

    print(
        f"\n  A contamination (CA+meas): "
        f"{_contam(totals['a_ca'], totals['a_meas'], totals['a'])}"
    )
    print(
        f"  B contamination (CA+meas): "
        f"{_contam(totals['b_ca'], totals['b_meas'], totals['b'])}"
    )

    # --- snippets: sample up to _PER_CELL_CAP per (pat, field) cell ---
    print(f"\n{sep}")
    print(f"Snippets (up to {_MAX_SNIPPETS} total, <={_PER_CELL_CAP} per pattern x field cell)")
    print("Structure: <D>=1-2 digit day/month  <YY>=2-digit year  sep preserved")
    print(f"B-pattern hits first (expected to dominate).")
    print(sep)

    # Interleave B then A within each field so B gets priority
    ordered: list[dict] = []
    for field in _FIELDS:
        field_b = [h for h in all_hits if h["pat"] == "B" and h["field"] == field]
        field_a = [h for h in all_hits if h["pat"] == "A" and h["field"] == field]
        ordered.extend(field_b)
        ordered.extend(field_a)

    cell_counts: dict[tuple, int] = {}
    shown = 0
    for hit in ordered:
        cell = (hit["pat"], hit["field"])
        if cell_counts.get(cell, 0) >= _PER_CELL_CAP:
            continue
        cell_counts[cell] = cell_counts.get(cell, 0) + 1
        snip = _snippet(hit["text"], hit["match"], hit["pat"])
        flag = " [CA-prefix]" if hit["ca"] else (" [meas-suffix]" if hit["meas"] else "")
        print(f"  [PAT-{hit['pat']}][{hit['field']}]{flag} {snip}")
        shown += 1
        if shown >= _MAX_SNIPPETS:
            break

    if shown == 0:
        print("  (no hits)")

    print(f"\n{SEP}\n")


if __name__ == "__main__":
    setup_logging("phase2_recon_2digit")
    run()
