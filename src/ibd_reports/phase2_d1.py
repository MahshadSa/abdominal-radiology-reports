"""Phase 2 D1: per-record self-search for name tokens (no stoplist -- reconnaissance only)."""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.phase1b_name_clustering import _collapse_repeats, _fold_accents
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import DEID_DIR, PARSED_DIR

logger = logging.getLogger(__name__)

_JSONL = "phase1_parsed.jsonl"
_HITS_CSV = "phase2_d1_hits.csv"
_TOKEN_CSV = "phase2_d1_token_summary.csv"
_TOKENS_MAP_CSV = "phase2_d1_tokens_map.csv"

_FIELDS = ["clinical_info", "previous_imaging", "findings", "impression"]
_MIN_TOKEN_LEN = 3

# --- filename cleaning patterns (applied in order in _clean_filename) ---

# 3-part numeric date anywhere in the string: 1402.7.9, 12/03/2021, 2021-05-30
_DATE3 = re.compile(r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}")

# Bare 4-digit years: Iranian (13xx, 14xx) and western (19xx, 20xx)
_YEAR4 = re.compile(r"\b(?:13|14|19|20)\d{2}\b")

# Separator characters used to join appended junk to the name
_SEP = re.compile(r"[_\-&/]+")

# Modality tags -- applied after SEP replacement so hyphens are already spaces.
# Negative look-behind/ahead on [a-zA-Z] so "MR" doesn't fire inside "Morteza".
# CTE before CT so the greedy |CT| doesn't consume the C leaving "TE".
_MODALITY = re.compile(
    r"(?<![a-zA-Z])"
    r"(?:MR(?:CP|E|I)?|CTE|CT|PET(?:\s+CT)?|US|ultrasound|angiography|angio|scan)"
    r"(?![a-zA-Z])",
    re.IGNORECASE,
)

# Anatomy / region tags
_ANATOMY = re.compile(
    r"(?<![a-zA-Z])"
    r"(?:neck|chest|abdomen|abdominal|pelvis|pelvic|brain|liver|biliary"
    r"|small\s+bowel|enterography|rectal|gyn(?:a?ecological)?"
    r"|spine|shoulder|knee|hip|wrist|ankle|elbow|foot|hand"
    r"|sacrum|sacroiliac|si\s+joint|lumbar|thoracic|cervical)"
    r"(?![a-zA-Z])",
    re.IGNORECASE,
)

# Status / acquisition / misc tags (applied after anatomy)
_STATUS = re.compile(
    r"(?<![a-zA-Z])"
    r"(?:without\s+contrast|with\s+contrast|follow\s+up|followup"
    r"|new|old|repeat|redo|control|pre|post|contrast|limited|portable)"
    r"(?![a-zA-Z])",
    re.IGNORECASE,
)

# Trailing space-separated digit tokens left after separator normalisation
# e.g. "Name 1 2" -- the " 1 2" tail
_TRAIL_NUM = re.compile(r"(?:\s+\d+)+$")

# Generic punctuation and whitespace helpers
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def _clean_filename(raw: str) -> str:
    """Strip all non-name junk from a filename stem, return the name portion only.

    Steps (in order):
      1  strip leading/trailing whitespace
      2  remove embedded 3-part dates
      3  remove bare 4-digit years (Iranian 13xx/14xx, western 19xx/20xx)
      4  replace separator chars _ - & / with space
      5  normalise whitespace
      6  remove modality tags (incl. scan)
      7  remove anatomy / region tags (incl. musculoskeletal)
      8  remove status / acquisition / misc tags
      9  strip trailing standalone digit tokens
      10 final whitespace normalisation
    """
    s = raw.strip()
    s = _DATE3.sub(" ", s)
    s = _YEAR4.sub(" ", s)
    s = _SEP.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    s = _MODALITY.sub(" ", s)
    s = _ANATOMY.sub(" ", s)
    s = _STATUS.sub(" ", s)
    s = _TRAIL_NUM.sub("", s)
    return _WS.sub(" ", s).strip()


def _build_tokens(raw_filename: str) -> list[str]:
    """Derive name search tokens from a filename stem.

    Cleans the filename, then lowercases, strips accents, collapses repeated
    adjacent letters, and returns tokens of length >= _MIN_TOKEN_LEN.
    """
    s = _clean_filename(raw_filename)
    s = s.lower()
    s = _PUNCT.sub(" ", s)
    s = _fold_accents(s)
    s = _collapse_repeats(s)
    s = _WS.sub(" ", s).strip()
    return [t for t in s.split() if len(t) >= _MIN_TOKEN_LEN]


def _build_tokens_uncollapsed(raw_filename: str) -> list[str]:
    """Same pipeline as _build_tokens but skips collapse-repeats.

    Preserves real double-letter spellings (Abbas, Hossein) so that the union
    search set catches both romanisation variants in body text.
    """
    s = _clean_filename(raw_filename)
    s = s.lower()
    s = _PUNCT.sub(" ", s)
    s = _fold_accents(s)
    s = _WS.sub(" ", s).strip()
    return [t for t in s.split() if len(t) >= _MIN_TOKEN_LEN]


def _build_union_tokens(raw_filename: str) -> list[str]:
    """Union of collapsed and un-collapsed name tokens, collapsed-first, deduped."""
    collapsed = _build_tokens(raw_filename)
    uncollapsed = _build_tokens_uncollapsed(raw_filename)
    return list(dict.fromkeys(collapsed + uncollapsed))


def _make_token_patterns(tokens: list[str]) -> list[tuple[str, re.Pattern]]:
    """Compile a whole-word case-insensitive regex for each token."""
    return [
        (tok, re.compile(r"\b" + re.escape(tok) + r"\b", re.IGNORECASE))
        for tok in tokens
    ]


def _search_record(
    record: dict,
    token_patterns: list[tuple[str, re.Pattern]],
) -> dict[str, dict[str, int]]:
    """Search _FIELDS of a single record for each token pattern.

    Returns hits[token][field] = count; absent entries mean zero.
    """
    hits: dict[str, dict[str, int]] = {}
    for token, pat in token_patterns:
        for field in _FIELDS:
            text: str = record.get(field) or ""
            count = len(pat.findall(text))
            if count:
                hits.setdefault(token, {})[field] = count
    return hits


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

    hit_rows: list[tuple[str, str, str, int]] = []
    token_stats: dict[str, dict] = defaultdict(
        lambda: {"total_hits": 0, "record_count": 0, "fields": set()}
    )
    records_with_hits = 0

    # (filename, cleaned, collapsed_tokens, uncollapsed_tokens, union_tokens)
    token_map_rows: list[tuple[str, str, str, str, str]] = []
    hit_filenames: set[str] = set()

    for rec in records:
        filename: str = rec.get("filename", "")
        cleaned = _clean_filename(filename)
        collapsed = _build_tokens(filename)
        uncollapsed = _build_tokens_uncollapsed(filename)
        tokens = _build_union_tokens(filename)
        token_map_rows.append(
            (filename, cleaned, " ".join(collapsed), " ".join(uncollapsed), " ".join(tokens))
        )

        if not tokens:
            continue
        token_patterns = _make_token_patterns(tokens)
        hits = _search_record(rec, token_patterns)
        if not hits:
            continue

        records_with_hits += 1
        hit_filenames.add(filename)
        for token, field_counts in hits.items():
            for field, count in field_counts.items():
                logger.info(
                    "HIT filename=%r token=%r field=%s count=%d",
                    filename,
                    token,
                    field,
                    count,
                )
                hit_rows.append((filename, token, field, count))
                token_stats[token]["total_hits"] += count
                token_stats[token]["record_count"] += 1
                token_stats[token]["fields"].add(field)

    logger.info(
        "Done: %d records scanned, %d with hits, %d token-field hit rows",
        total,
        records_with_hits,
        len(hit_rows),
    )

    DEID_DIR.mkdir(parents=True, exist_ok=True)

    # Tokens map CSV: raw -> cleaned -> collapsed / uncollapsed / union tokens
    tokens_map_path = DEID_DIR / _TOKENS_MAP_CSV
    with tokens_map_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["filename", "cleaned_name", "collapsed_tokens", "uncollapsed_tokens", "union_tokens"])
        for row in token_map_rows:
            writer.writerow(row)
    logger.info("Token map written: %s (%d rows)", tokens_map_path, total)

    # Hit detail CSV
    hits_path = DEID_DIR / _HITS_CSV
    with hits_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["filename", "token", "field", "count"])
        for row in sorted(hit_rows):
            writer.writerow(row)
    logger.info("Hit detail written: %s (%d rows)", hits_path, len(hit_rows))

    # Token summary CSV
    token_path = DEID_DIR / _TOKEN_CSV
    with token_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["token", "total_hits", "records_with_hits", "fields"])
        for token, stats in sorted(
            token_stats.items(), key=lambda kv: -kv[1]["total_hits"]
        ):
            writer.writerow(
                [
                    token,
                    stats["total_hits"],
                    stats["record_count"],
                    ";".join(sorted(stats["fields"])),
                ]
            )
    logger.info("Token summary written: %s (%d tokens)", token_path, len(token_stats))

    SEP = "=" * 60
    sep = "-" * 60
    print(f"\n{SEP}")
    print("Phase 2 D1 -- Name Token Self-Search (no stoplist)")
    print(SEP)
    print(f"Records scanned      : {total}")
    print(f"Records with hits    : {records_with_hits}")
    print(f"Token-field hit rows : {len(hit_rows)}")
    print(f"\nToken map (check raw->tokens): {tokens_map_path}")
    print(f"Hit detail           : {hits_path}")
    print(f"Token summary        : {token_path}")

    if token_stats:
        print(f"\n{sep}")
        print("Top 30 tokens by total hits (review for stoplist candidates):")
        print(f"{'token':<25} {'total':>8} {'records':>9}  fields")
        print(sep)
        for token, stats in sorted(
            token_stats.items(), key=lambda kv: -kv[1]["total_hits"]
        )[:30]:
            print(
                f"{token:<25} {stats['total_hits']:>8} {stats['record_count']:>9}"
                f"  {';'.join(sorted(stats['fields']))}"
            )
    else:
        print("\nNo token hits found in body text.")

    # Print raw->tokens for records that still have hits so they can be reviewed inline.
    if hit_filenames:
        print(f"\n{sep}")
        print("Filename -> union token set  (only records with hits):")
        print(sep)
        for fn, cleaned, collapsed, uncollapsed, union in token_map_rows:
            if fn in hit_filenames:
                print(f"  raw        : {fn!r}")
                print(f"  cleaned    : {cleaned!r}")
                print(f"  collapsed  : {collapsed!r}")
                print(f"  uncollapsed: {uncollapsed!r}")
                print(f"  union      : {union!r}")
                print()

    print(f"\n{SEP}\n")


def main() -> None:
    log_file = setup_logging("phase2_d1")
    logger.info("Logging to %s", log_file)
    logger.info("Phase 2 D1 start")
    run()
    logger.info("Phase 2 D1 complete")


if __name__ == "__main__":
    main()
