import csv
import json
import logging
from collections import Counter
from pathlib import Path

from docx import Document

from ibd_reports.parsing.section_splitter import split_sections
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import DATA_ROOT, PARSED_DIR

logger = logging.getLogger(__name__)

SUBSET_DIR: Path = DATA_ROOT / "_subset30_originals_docx"


def main() -> None:
    log_file = setup_logging("run_splitter_subset")
    logger.info("Log: %s", log_file)
    logger.info("Input:  %s", SUBSET_DIR)
    logger.info("Output: %s", PARSED_DIR)

    docx_files = sorted(SUBSET_DIR.glob("*.docx"))
    logger.info("Found %d .docx files", len(docx_files))

    jsonl_path = PARSED_DIR / "subset30_parsed.jsonl"
    csv_path = PARSED_DIR / "subset30_flags_summary.csv"

    records: list[dict] = []

    with jsonl_path.open("w", encoding="utf-8") as jf:
        for path in docx_files:
            logger.debug("Parsing %s", path.name)
            doc = Document(path)
            result = split_sections(doc)
            result["source_filename"] = path.name
            jf.write(json.dumps(result) + "\n")
            records.append(result)
            logger.debug("Flags for %s: %s", path.name, result["parse_flags"])

    logger.info("Wrote %s", jsonl_path)

    csv_rows = sorted(
        [
            {
                "filename": r["source_filename"],
                "n_flags": len(r["parse_flags"]),
                "flags": ";".join(r["parse_flags"]),
            }
            for r in records
        ],
        key=lambda row: row["n_flags"],
        reverse=True,
    )

    with csv_path.open("w", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=["filename", "n_flags", "flags"])
        writer.writeheader()
        writer.writerows(csv_rows)

    logger.info("Wrote %s", csv_path)

    total = len(records)
    zero_flags = sum(1 for r in records if not r["parse_flags"])
    flag_counter: Counter[str] = Counter(
        flag for r in records for flag in r["parse_flags"]
    )

    print(f"Total files processed : {total}")
    print(f"Files with zero flags : {zero_flags}")
    print(f"Files with 1+ flags   : {total - zero_flags}")
    print("\nTop 5 flags:")
    for flag, count in flag_counter.most_common(5):
        print(f"  {flag}: {count}")


if __name__ == "__main__":
    main()
