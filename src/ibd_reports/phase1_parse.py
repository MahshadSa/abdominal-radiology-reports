"""Phase 1: parse docx reports into structured sections."""
import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from docx import Document

from ibd_reports.parsing.section_splitter import split_sections
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import METADATA_DIR, PARSED_DIR, verify_data_tree

logger = logging.getLogger(__name__)

_JSONL_NAME = "phase1_parsed.jsonl"
_CSV_NAME = "phase1_parsed.csv"
_FLAGS_SUMMARY_NAME = "phase1_flags_summary.csv"


def _check_no_overwrite(force: bool) -> None:
    existing = [
        PARSED_DIR / name
        for name in (_JSONL_NAME, _CSV_NAME, _FLAGS_SUMMARY_NAME)
        if (PARSED_DIR / name).exists()
    ]
    if existing and not force:
        for p in existing:
            logger.error("Output exists (pass --force to overwrite): %s", p)
        raise SystemExit(1)


def _load_quarantined() -> set[str]:
    path = METADATA_DIR / "phase0_quarantined.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str)
    return set(df["filename"].dropna())


def run(force: bool) -> None:
    _check_no_overwrite(force)

    meta_path = METADATA_DIR / "phase0_metadata.csv"
    logger.info("Loading metadata: %s", meta_path)
    meta_df = pd.read_csv(meta_path, dtype=str)
    meta_df = meta_df.sort_values("filename").reset_index(drop=True)
    logger.info("Metadata rows: %d", len(meta_df))

    quarantined = _load_quarantined()
    if quarantined:
        logger.info("Quarantine list loaded: %d filenames will be skipped", len(quarantined))

    records: list[dict] = []
    skipped = 0

    for _, row in meta_df.iterrows():
        filename: str = row["filename"]

        if filename in quarantined:
            skipped += 1
            continue

        docx_path = Path(row["docx_working_path"])
        logger.debug("Parsing: %s", filename)

        doc = Document(docx_path)
        try:
            sections = split_sections(doc)
        except Exception:
            logger.error("Failed to parse: %s", filename)
            raise

        records.append({
            "filename": filename,
            "mtime_iso": row["mtime_iso"],
            "ctime_iso": row["ctime_iso"],
            **sections,
        })

        n_parsed = len(records)
        if n_parsed % 500 == 0:
            logger.info("Progress: %d files parsed", n_parsed)

    if quarantined:
        logger.info("Skipped %d quarantined files", skipped)

    logger.info("Parsing complete: %d records", len(records))

    # JSONL: parse_flags stays a JSON array
    jsonl_path = PARSED_DIR / _JSONL_NAME
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.info("JSONL written: %s (%d records)", jsonl_path, len(records))

    # Flat CSV: parse_flags semicolon-joined
    csv_path = PARSED_DIR / _CSV_NAME
    df = pd.DataFrame(records)
    df["parse_flags"] = df["parse_flags"].apply(lambda flags: ";".join(flags))
    df.to_csv(csv_path, index=False, encoding="utf-8")
    logger.info("CSV written: %s", csv_path)

    # Flags summary: only flagged rows, sorted by n_flags desc
    flags_rows = [
        {
            "filename": rec["filename"],
            "n_flags": len(rec["parse_flags"]),
            "flags": ";".join(rec["parse_flags"]),
        }
        for rec in records
        if rec["parse_flags"]
    ]
    flags_df = (
        pd.DataFrame(flags_rows, columns=["filename", "n_flags", "flags"])
        .sort_values("n_flags", ascending=False)
        .reset_index(drop=True)
    )
    flags_summary_path = PARSED_DIR / _FLAGS_SUMMARY_NAME
    flags_df.to_csv(flags_summary_path, index=False, encoding="utf-8")
    logger.info(
        "Flags summary written: %s (%d flagged records)",
        flags_summary_path,
        len(flags_df),
    )

    # Stdout summary
    total = len(records)
    zero_flag = sum(1 for r in records if not r["parse_flags"])
    one_plus_flag = total - zero_flag
    empty_findings = sum(1 for r in records if not r["findings"].strip())

    flag_counter: Counter[str] = Counter()
    for r in records:
        flag_counter.update(r["parse_flags"])

    print(f"Total parsed:   {total}")
    print(f"Zero flags:     {zero_flag}")
    print(f"1+ flags:       {one_plus_flag}")
    print(f"Empty findings: {empty_findings}")
    print("Top 10 flags:")
    for flag, count in flag_counter.most_common(10):
        print(f"  {flag}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 1: parse docx reports into structured sections."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files if present.",
    )
    args = parser.parse_args()

    log_file = setup_logging("phase1")
    logger.info("Logging to %s", log_file)

    verify_data_tree()

    logger.info("Phase 1 start")
    run(force=args.force)
    logger.info("Phase 1 complete")


if __name__ == "__main__":
    main()
