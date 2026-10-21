"""Phase 2.1 patch: blank modality values that hold patient names or letter salutations."""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ibd_reports.phase2_rekey import write_rekeyed
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import PATCH21_CSV, PATCH21_JSONL, REKEY_JSONL

logger = logging.getLogger(__name__)

FLAG_PHI = "modality_phi_removed"
FLAG_LETTER = "non_report_letter"

# Modality is never scrubbed in Phase 2; any Arabic-script text there is a name, not an exam title.
_ARABIC_SCRIPT = re.compile("[؀-ۿ]")
_SALUTATION = re.compile(r"^\s*dear\s+(dr|prof)\b", re.IGNORECASE)


def patch_record(rec: dict) -> tuple[dict, str | None]:
    """Return (record, flag applied or None); only modality and parse_flags can change."""
    modality = rec["modality"] or ""
    if _ARABIC_SCRIPT.search(modality):
        flag = FLAG_PHI
    elif _SALUTATION.search(modality):
        flag = FLAG_LETTER
    else:
        return rec, None
    return {**rec, "modality": "", "parse_flags": [*rec["parse_flags"], flag]}, flag


def run(in_jsonl: Path, out_jsonl: Path, out_csv: Path) -> None:
    """Apply the modality patch to every record and write the patched corpus."""
    for path in (out_jsonl, out_csv):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {path.name}")

    with in_jsonl.open(encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    logger.info("Loaded %d records", len(records))

    patched = []
    counts: Counter[str] = Counter()
    for rec in records:
        out, flag = patch_record(rec)
        patched.append(out)
        if flag:
            counts[flag] += 1
    logger.info(
        "Patched %d records: %s=%d, %s=%d",
        sum(counts.values()), FLAG_PHI, counts[FLAG_PHI], FLAG_LETTER, counts[FLAG_LETTER],
    )

    write_rekeyed(patched, out_jsonl, out_csv)


def main() -> None:
    log_file = setup_logging("phase2_1_patch")
    logger.info("Logging to %s", log_file)
    logger.info("Phase 2.1 patch start")
    run(REKEY_JSONL, PATCH21_JSONL, PATCH21_CSV)
    logger.info("Phase 2.1 patch complete")


if __name__ == "__main__":
    main()
