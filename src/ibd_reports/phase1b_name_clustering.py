"""Phase 1b: cluster filename stems to find suspected same-patient duplicates."""
import csv
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import PARSED_DIR

logger = logging.getLogger(__name__)

_INPUT_JSONL = "phase1_parsed.jsonl"
_OUTPUT_CSV = "phase1b_name_groups.csv"
_FUZZY_THRESHOLD = 0.85
# Derived: for ratio >= T, need min_len/max_len >= T/(2-T)
_MIN_LEN_RATIO = _FUZZY_THRESHOLD / (2.0 - _FUZZY_THRESHOLD)

_SUFFIX_PAT = re.compile(r"\s*[\(\[]?\d+[\)\]]?$")
_PUNCT_PAT = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")


def _strip_suffix(s: str) -> str:
    return _SUFFIX_PAT.sub("", s)


def _fold_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _collapse_repeats(s: str) -> str:
    """Collapse consecutive identical alpha chars: hoob -> hob."""
    result: list[str] = []
    for ch in s:
        if result and ch == result[-1] and ch.isalpha():
            continue
        result.append(ch)
    return "".join(result)


def _compute_names(stem: str) -> tuple[str, str]:
    """Return (base_name, norm_name) for a filename stem."""
    lowered = _MULTI_SPACE.sub(" ", stem.strip().lower())
    base = _strip_suffix(lowered).strip()
    no_punct = _PUNCT_PAT.sub("", base)
    folded = _fold_accents(no_punct)
    collapsed = _collapse_repeats(folded)
    tokens = sorted(_MULTI_SPACE.sub(" ", collapsed).strip().split())
    norm = " ".join(tokens)
    return base, norm


# Union-find with path compression
def _make_uf(n: int) -> list[int]:
    return list(range(n))


def _find(uf: list[int], x: int) -> int:
    while uf[x] != x:
        uf[x] = uf[uf[x]]
        x = uf[x]
    return x


def _union(uf: list[int], a: int, b: int) -> None:
    uf[_find(uf, a)] = _find(uf, b)


def _fuzzy_cluster(
    distinct_norms: list[str],
    norm_rep: dict[str, int],
    uf: list[int],
) -> None:
    """Merge components whose norm_names are within the fuzzy threshold."""
    m = len(distinct_norms)
    for i in range(m):
        ni = distinct_norms[i]
        li = len(ni)
        ri = norm_rep[ni]
        for j in range(i + 1, m):
            nj = distinct_norms[j]
            rj = norm_rep[nj]
            if _find(uf, ri) == _find(uf, rj):
                continue
            lj = len(nj)
            if li == 0 or lj == 0:
                continue
            short, long_ = (li, lj) if li <= lj else (lj, li)
            if short / long_ < _MIN_LEN_RATIO:
                continue
            sm = SequenceMatcher(None, ni, nj, autojunk=False)
            if sm.quick_ratio() < _FUZZY_THRESHOLD:
                continue
            if sm.ratio() >= _FUZZY_THRESHOLD:
                _union(uf, ri, rj)


def run() -> None:
    input_path = PARSED_DIR / _INPUT_JSONL
    output_path = PARSED_DIR / _OUTPUT_CSV

    logger.info("Loading: %s", input_path)
    records: list[dict] = []
    with input_path.open(encoding="utf-8") as fh:
        for line in fh:
            records.append(json.loads(line))
    n = len(records)
    logger.info("Records loaded: %d", n)

    stems = [r["filename"] for r in records]
    base_names: list[str] = []
    norm_names: list[str] = []
    for stem in stems:
        base, norm = _compute_names(stem)
        base_names.append(base)
        norm_names.append(norm)

    uf = _make_uf(n)

    # Exact grouping by norm_name
    norm_to_indices: dict[str, list[int]] = defaultdict(list)
    for i, norm in enumerate(norm_names):
        norm_to_indices[norm].append(i)

    for indices in norm_to_indices.values():
        if len(indices) > 1:
            root = indices[0]
            for idx in indices[1:]:
                _union(uf, root, idx)

    # Fuzzy grouping across distinct norm_names
    distinct_norms = list(norm_to_indices.keys())
    norm_rep = {norm: indices[0] for norm, indices in norm_to_indices.items()}
    logger.info("Distinct norm_names: %d; running fuzzy pass...", len(distinct_norms))
    _fuzzy_cluster(distinct_norms, norm_rep, uf)
    logger.info("Fuzzy pass complete")

    # Gather components
    root_to_members: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        root_to_members[_find(uf, i)].append(i)

    multi_roots = {root for root, members in root_to_members.items() if len(members) > 1}

    # Assign stable group_ids by sorting the root indices
    root_to_gid: dict[int, int] = {
        root: gid + 1 for gid, root in enumerate(sorted(multi_roots))
    }

    # Determine confidence: exact_base if all members share one norm_name, else fuzzy
    root_confidence: dict[int, str] = {}
    for root in multi_roots:
        distinct = {norm_names[i] for i in root_to_members[root]}
        root_confidence[root] = "exact_base" if len(distinct) == 1 else "fuzzy"

    # Build per-record annotations
    group_ids: list[int | str] = []
    group_sizes: list[int | str] = []
    confidences: list[str] = []
    for i in range(n):
        root = _find(uf, i)
        if root in multi_roots:
            group_ids.append(root_to_gid[root])
            group_sizes.append(len(root_to_members[root]))
            confidences.append(root_confidence[root])
        else:
            group_ids.append("")
            group_sizes.append("")
            confidences.append("")

    # Sort: grouped records first (by group_id, then stem), singletons after (by stem)
    order = sorted(
        range(n),
        key=lambda i: (
            group_ids[i] == "",
            group_ids[i] if group_ids[i] != "" else 0,
            stems[i],
        ),
    )

    base_keys = list(records[0].keys())
    extra_keys = ["group_id", "group_size", "match_confidence", "base_name", "norm_name"]
    fieldnames = base_keys + extra_keys

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for i in order:
            row = dict(records[i])
            if isinstance(row.get("parse_flags"), list):
                row["parse_flags"] = ";".join(row["parse_flags"])
            row["group_id"] = group_ids[i]
            row["group_size"] = group_sizes[i]
            row["match_confidence"] = confidences[i]
            row["base_name"] = base_names[i]
            row["norm_name"] = norm_names[i]
            writer.writerow(row)

    logger.info("CSV written: %s", output_path)

    # Summary stats
    total_in_groups = sum(1 for g in group_ids if g != "")
    n_multi = len(multi_roots)
    exact_groups = sum(1 for c in root_confidence.values() if c == "exact_base")
    fuzzy_groups = n_multi - exact_groups

    size_dist: Counter[int] = Counter(
        len(root_to_members[root]) for root in multi_roots
    )

    print(f"Total records:           {n}")
    print(f"Records in any group:    {total_in_groups}")
    print(f"Multi-member groups:     {n_multi}")
    print(f"  exact_base groups:     {exact_groups}")
    print(f"  fuzzy groups:          {fuzzy_groups}")
    print("Group size distribution:")
    for sz in sorted(size_dist):
        print(f"  size {sz}: {size_dist[sz]} groups")


def main() -> None:
    log_file = setup_logging("phase1b")
    logger.info("Logging to %s", log_file)
    logger.info("Phase 1b start")
    run()
    logger.info("Phase 1b complete")


if __name__ == "__main__":
    main()
