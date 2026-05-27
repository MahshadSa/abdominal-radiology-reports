import argparse
import csv
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import METADATA_DIR, WORKING_REPORTS, verify_data_tree

logger = logging.getLogger(__name__)

_CSV_NAME = "phase0_metadata.csv"
_FIELDS = [
    "filename",
    "doc_source_path",
    "docx_working_path",
    "mtime_iso",
    "ctime_iso",
    "size_bytes_doc",
    "size_bytes_docx",
]


def _index_originals(source_doc: Path) -> dict[str, Path]:
    """Return stem -> Path for all .doc and .docx files in source_doc.

    If a stem has both extensions, .doc takes precedence (it carries the real mtime).
    """
    index: dict[str, Path] = {}
    for p in sorted(source_doc.glob("*.docx")):
        index[p.stem] = p
    for p in sorted(source_doc.glob("*.doc")):
        index[p.stem] = p  # overwrites .docx if both exist
    return index


def _pair_stems(
    source_doc: Path, source_docx: Path
) -> tuple[dict[str, Path], set[str], set[str]]:
    """Return (paired, orig_only, docx_only).

    paired maps stem -> original Path (the mtime source).
    orig_only: stems in source_doc with no matching docx conversion.
    docx_only: stems in source_docx with no matching original.
    """
    originals = _index_originals(source_doc)
    docx_stems = {p.stem for p in source_docx.glob("*.docx")}
    orig_stems = set(originals)
    paired = {stem: originals[stem] for stem in orig_stems & docx_stems}
    orig_only = orig_stems - docx_stems
    docx_only = docx_stems - orig_stems
    return paired, orig_only, docx_only


def _build_row(
    stem: str,
    original: Path,
    docx_dest: Path,
) -> dict:
    st = original.stat()
    return {
        "filename": stem,
        "doc_source_path": str(original.resolve()),
        "docx_working_path": str(docx_dest),
        "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "ctime_iso": datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
        "size_bytes_doc": st.st_size,
        "size_bytes_docx": docx_dest.stat().st_size,
    }


def run(
    source_doc: Path,
    source_docx: Path,
    force: bool,
    dry_run: bool,
) -> None:
    paired, orig_only, docx_only = _pair_stems(source_doc, source_docx)

    for stem in sorted(orig_only):
        logger.warning("Unpaired original (no matching docx): %s", stem)
    for stem in sorted(docx_only):
        logger.warning("Unpaired docx (no matching original): %s.docx", stem)

    logger.info(
        "Pairs: %d paired, %d original-only, %d docx-only",
        len(paired),
        len(orig_only),
        len(docx_only),
    )

    would_copy = 0
    would_skip = 0
    for stem in sorted(paired):
        dest = WORKING_REPORTS / f"{stem}.docx"
        if dest.exists():
            would_skip += 1
        else:
            would_copy += 1

    if dry_run:
        logger.info(
            "Dry run summary -- pairs: %d, would-copy: %d, would-skip: %d, "
            "unpaired-original: %d, unpaired-docx: %d",
            len(paired),
            would_copy,
            would_skip,
            len(orig_only),
            len(docx_only),
        )
        return

    csv_path = METADATA_DIR / _CSV_NAME
    if csv_path.exists() and not force:
        logger.error("%s already exists; pass --force to overwrite", csv_path)
        raise SystemExit(1)

    copied = 0
    skipped = 0
    for stem in sorted(paired):
        src = source_docx / f"{stem}.docx"
        dest = WORKING_REPORTS / f"{stem}.docx"
        if dest.exists():
            logger.warning("Skip (already exists): %s.docx", stem)
            skipped += 1
            continue
        logger.debug("Copy: %s -> %s", src, dest)
        shutil.copy2(src, dest)
        copied += 1

    logger.info("Copy complete: %d copied, %d skipped", copied, skipped)

    rows = []
    for stem in sorted(paired):
        dest = WORKING_REPORTS / f"{stem}.docx"
        rows.append(_build_row(stem, paired[stem], dest))

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Metadata CSV written: %s (%d rows)", csv_path, len(rows))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 0: pair .doc/.docx files, copy to working copy, write metadata CSV."
    )
    parser.add_argument(
        "--source-doc",
        required=True,
        type=Path,
        help="Directory containing the original files (.doc or .docx; mtime source).",
    )
    parser.add_argument(
        "--source-docx",
        required=True,
        type=Path,
        help="Directory containing the converted .docx files (content source).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing metadata CSV if present.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions and print counts without writing any files.",
    )
    args = parser.parse_args()

    if args.dry_run:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            stream=sys.stderr,
        )
        logger.info("DRY RUN: no files will be written")
    else:
        log_file = setup_logging("phase0")
        logger.info("Logging to %s", log_file)

    verify_data_tree()

    source_doc = args.source_doc.resolve()
    source_docx = args.source_docx.resolve()

    for label, path in (("--source-doc", source_doc), ("--source-docx", source_docx)):
        if not path.is_dir():
            logger.error("%s is not a directory: %s", label, path)
            raise SystemExit(1)

    logger.info("Phase 0 start -- doc: %s | docx: %s", source_doc, source_docx)

    run(source_doc, source_docx, force=args.force, dry_run=args.dry_run)

    logger.info("Phase 0 complete")


if __name__ == "__main__":
    main()
