"""Triage phase2_recall_report.csv name hits into self-token vs cross-patient.

Read-only. For each 'name' hit row (record_index, token), decide whether the
token is one of that record's OWN filename tokens (_build_union_tokens over its
own filename = a genuine self-leak the scrub should have removed) or a token
that belongs only to other patients (a word collision; locked recon says
cross-report name references never occur, so these are ordinary-word matches).

Writes phase2_recall_triage.csv (self-token hits only, the real concern) and
prints aggregate counts. Self-token output stays in DEID_DIR (PHI zone).
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.phase2_d1 import _build_union_tokens
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import DEID_DIR, PARSED_DIR

logger = logging.getLogger(__name__)

_RECALL_CSV = "phase2_recall_report.csv"
_ROSTER_JSONL = "phase1_parsed.jsonl"
_TRIAGE_CSV = "phase2_recall_triage.csv"


def run() -> None:
    roster_path = PARSED_DIR / _ROSTER_JSONL
    recall_path = DEID_DIR / _RECALL_CSV

    own_tokens: list[set[str]] = []
    with roster_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                fn = json.loads(line).get("filename", "")
                own_tokens.append(set(_build_union_tokens(fn)))
    logger.info("Loaded own-token sets for %d records", len(own_tokens))

    self_rows: list[tuple] = []
    cross_token_counter: Counter = Counter()
    self_token_counter: Counter = Counter()
    n_name = 0

    with recall_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row["check_type"] != "name":
                continue
            n_name += 1
            idx = int(row["record_index"])
            token = row["token_or_pattern"]
            count = int(row["count"])
            if token in own_tokens[idx]:
                self_rows.append((idx, token, row["field"], count))
                self_token_counter[token] += 1
            else:
                cross_token_counter[token] += 1

    out_path = DEID_DIR / _TRIAGE_CSV
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["record_index", "token", "field", "count"])
        for r in sorted(self_rows):
            w.writerow(r)

    print("=" * 60)
    print("Recall-hit triage")
    print("=" * 60)
    print(f"Total 'name' hit rows        : {n_name}")
    print(f"Self-token hits (REAL leak?) : {len(self_rows)}  rows")
    print(f"  distinct self tokens       : {len(self_token_counter)}")
    print(f"  records affected           : {len({r[0] for r in self_rows})}")
    print(f"Cross-patient hits (collide) : {n_name - len(self_rows)}  rows")
    print(f"  distinct collision tokens  : {len(cross_token_counter)}")
    print()
    print("Top 25 cross-patient collision tokens (ordinary words, safe):")
    for tok, c in cross_token_counter.most_common(25):
        print(f"  {tok:<20} {c:>5}")
    print()
    print(f"Self-token detail written to: {out_path}")


def main() -> None:
    setup_logging("phase2_triage_recall")
    run()


if __name__ == "__main__":
    main()
