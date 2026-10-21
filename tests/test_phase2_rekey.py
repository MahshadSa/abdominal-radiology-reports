"""Tests for phase2_rekey -- synthetic data built in code, no real data."""
import json
import random
from pathlib import Path

import pandas as pd
import pytest

from ibd_reports.phase2_rekey import assign_rec_ids, rekey_records, run

_FIELDS = [
    "mtime_iso",
    "ctime_iso",
    "modality",
    "clinical_info",
    "previous_imaging",
    "findings",
    "impression",
    "parse_flags",
]


def _names(n: int) -> list[str]:
    return [f"Synthetic Patient {i:03d}" for i in range(n)]


def _record(filename: str) -> dict:
    return {
        "filename": filename,
        "mtime_iso": "2024-01-01T00:00:00+00:00",
        "ctime_iso": "2026-01-01T00:00:00+00:00",
        "modality": "MRI small bowel",
        "clinical_info": f"Synthetic clinical info for {filename}.\nSecond line.",
        "previous_imaging": "",
        "findings": "Synthetic findings, text with a comma.",
        "impression": "Synthetic impression.",
        "parse_flags": [],
    }


def test_determinism():
    names = _names(20)
    shuffled = names[:]
    random.Random(1).shuffle(shuffled)
    assert assign_rec_ids(names) == assign_rec_ids(names)
    assert assign_rec_ids(shuffled) == assign_rec_ids(names)


def test_format_contiguous_unique():
    n = 7
    ids = assign_rec_ids(_names(n)).values()
    assert sorted(ids) == [f"REC_{i:05d}" for i in range(1, n + 1)]


def test_not_alphabetical():
    names = _names(50)
    mapping = assign_rec_ids(names)
    rec_order = sorted(names, key=lambda fn: mapping[fn])
    assert rec_order != sorted(names)


def test_rekeyed_record_shape():
    rec = _record("Synthetic Patient A")
    out = rekey_records([rec], assign_rec_ids([rec["filename"]]))[0]
    assert "filename" not in out
    assert list(out.keys()) == ["rec_id"] + _FIELDS
    assert all(out[k] == rec[k] for k in _FIELDS)


def test_duplicate_filenames_raise():
    with pytest.raises(ValueError):
        assign_rec_ids(["Synthetic A", "Synthetic B", "Synthetic A"])


def test_missing_from_mapping_raises():
    records = [_record("Synthetic A"), _record("Synthetic B")]
    with pytest.raises(KeyError):
        rekey_records(records, assign_rec_ids(["Synthetic A"]))


def test_output_sorted_by_rec_id():
    names = _names(30)
    out = rekey_records([_record(fn) for fn in names], assign_rec_ids(names))
    ids = [r["rec_id"] for r in out]
    assert ids == sorted(ids)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def test_run_refuses_existing_outputs(tmp_path: Path):
    deid = tmp_path / "deid.jsonl"
    _write_jsonl(deid, [_record("Synthetic A")])
    outs = [tmp_path / "out.jsonl", tmp_path / "out.csv", tmp_path / "map.csv"]
    for existing in outs:
        existing.write_text("", encoding="utf-8")
        with pytest.raises(FileExistsError):
            run(deid, *outs)
        existing.unlink()


def test_run_end_to_end(tmp_path: Path):
    records = [_record(fn) for fn in _names(12)]
    deid = tmp_path / "deid.jsonl"
    _write_jsonl(deid, records)
    out_jsonl, out_csv, map_csv = tmp_path / "out.jsonl", tmp_path / "out.csv", tmp_path / "map.csv"

    run(deid, out_jsonl, out_csv, map_csv)

    assert len(pd.read_csv(map_csv)) == len(records)
    with out_jsonl.open(encoding="utf-8") as fh:
        out = [json.loads(line) for line in fh]
    assert len(out) == len(records)
    assert all("filename" not in r for r in out)


def test_schema_mismatch_raises():
    extra = {**_record("Synthetic A"), "extra_key": "x"}
    with pytest.raises(ValueError):
        rekey_records([extra], assign_rec_ids(["Synthetic A"]))
    missing = _record("Synthetic B")
    del missing["impression"]
    with pytest.raises(ValueError):
        rekey_records([missing], assign_rec_ids(["Synthetic B"]))
