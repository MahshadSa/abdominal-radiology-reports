"""Phase 2 rekey: replace filename keys with per-report REC_ IDs."""
from __future__ import annotations

import json
import logging
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import DEID_DIR, REC_MAP_CSV, REKEY_CSV, REKEY_JSONL

logger = logging.getLogger(__name__)

REC_SEED: int = 20261021

_DEID_JSONL = "phase2_deid.jsonl"
_INPUT_KEYS: tuple[str, ...] = (
    "filename",
    "mtime_iso",
    "ctime_iso",
    "modality",
    "clinical_info",
    "previous_imaging",
    "findings",
    "impression",
    "parse_flags",
)


def assign_rec_ids(filenames: list[str], seed: int = REC_SEED) -> dict[str, str]:
    """Map each filename to a REC_ ID, shuffled with a fixed seed so IDs carry no alphabetical order."""
    if len(set(filenames)) != len(filenames):
        raise ValueError("filenames contains duplicates")
    ordered = sorted(filenames)
    random.Random(seed).shuffle(ordered)
    return {fn: f"REC_{i:05d}" for i, fn in enumerate(ordered, start=1)}


def rekey_records(records: list[dict], mapping: dict[str, str]) -> list[dict]:
    """Drop filename, put rec_id first, keep other fields in schema order; sorted by rec_id."""
    bad_schema = sum(1 for rec in records if tuple(rec) != _INPUT_KEYS)
    if bad_schema:
        raise ValueError(f"{bad_schema} record(s) do not match the expected key schema")
    missing = sum(1 for rec in records if rec["filename"] not in mapping)
    if missing:
        raise KeyError(f"{missing} record filename(s) missing from mapping")
    out = [
        {"rec_id": mapping[rec["filename"]], **{k: rec[k] for k in _INPUT_KEYS[1:]}}
        for rec in records
    ]
    return sorted(out, key=lambda r: r["rec_id"])


def run(deid_jsonl: Path, out_jsonl: Path, out_csv: Path, map_csv: Path) -> None:
    """Mint REC_ IDs once and write the rekeyed corpus plus the filename -> rec_id map."""
    for path in (out_jsonl, out_csv, map_csv):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {path.name}")

    with deid_jsonl.open(encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    logger.info("Loaded %d records", len(records))

    mapping = assign_rec_ids([rec["filename"] for rec in records])
    rekeyed = rekey_records(records, mapping)

    with out_jsonl.open("w", encoding="utf-8") as fh:
        for rec in rekeyed:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.info("Wrote rekeyed jsonl (%d records)", len(rekeyed))

    pd.DataFrame(rekeyed).to_csv(out_csv, index=False, encoding="utf-8")
    logger.info("Wrote rekeyed csv (%d records)", len(rekeyed))

    map_df = pd.DataFrame(
        sorted(mapping.items(), key=lambda kv: kv[1]), columns=["filename", "rec_id"]
    )
    map_df.to_csv(map_csv, index=False, encoding="utf-8")
    logger.info("Wrote mapping csv (%d rows)", len(map_df))


def main() -> None:
    log_file = setup_logging("phase2_rekey")
    logger.info("Logging to %s", log_file)
    logger.info("Phase 2 rekey start")
    run(DEID_DIR / _DEID_JSONL, REKEY_JSONL, REKEY_CSV, REC_MAP_CSV)
    logger.info("Phase 2 rekey complete")


if __name__ == "__main__":
    main()
