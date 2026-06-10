"""Move oversized .docx files out of the working copy into quarantine.

Run from the repo root:
    python scripts/quarantine_large_files.py
"""

import csv
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import METADATA_DIR, QUARANTINE_DIR, WORKING_REPORTS

logger = logging.getLogger(__name__)

SIZE_THRESHOLD = 200_000
REASON = "large_file_likely_mr_elastography"
METADATA_CSV = METADATA_DIR / "phase0_metadata.csv"
QUARANTINE_CSV = METADATA_DIR / "phase0_quarantined.csv"
FIELDNAMES = ["filename", "size_bytes_doc", "reason", "quarantined_at_iso"]


def main() -> None:
    setup_logging("quarantine_large")

    with METADATA_CSV.open(newline="", encoding="utf-8") as f:
        targets = [
            row for row in csv.DictReader(f)
            if int(row["size_bytes_doc"]) > SIZE_THRESHOLD
        ]

    logger.info("Found %d files above %d bytes in phase0_metadata.csv", len(targets), SIZE_THRESHOLD)

    now = datetime.now(timezone.utc).isoformat()
    write_header = not QUARANTINE_CSV.exists()
    moved = 0
    total_bytes = 0

    with QUARANTINE_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()

        for row in targets:
            src = WORKING_REPORTS / f"{row['filename']}.docx"
            shutil.move(src, QUARANTINE_DIR / src.name)
            logger.info("Quarantined: %s", src.name)
            size = int(row["size_bytes_doc"])
            writer.writerow({
                "filename": row["filename"],
                "size_bytes_doc": size,
                "reason": REASON,
                "quarantined_at_iso": now,
            })
            moved += 1
            total_bytes += size

    total_mb = total_bytes / 1_048_576
    logger.info("Done: %d files quarantined, %.2f MB", moved, total_mb)
    print(f"Moved: {moved} files, {total_mb:.2f} MB total (doc sizes)")


if __name__ == "__main__":
    main()
