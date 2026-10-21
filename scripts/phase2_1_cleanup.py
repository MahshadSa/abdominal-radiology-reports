"""Remove leaked Phase 2.1 modality strings from Claude Code's local files, then delete the superseded rekeyed files.

Also scans VS Code's %APPDATA%/Code folder, report-only: nothing there is ever deleted,
and any match there keeps the rekeyed files.

Run from the repo root, with Claude Code closed:
    python scripts/phase2_1_cleanup.py            # dry run, deletes nothing
    python scripts/phase2_1_cleanup.py --delete
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import stat
import sys
from pathlib import Path

from ibd_reports.phase2_1_patch import patch_record
from ibd_reports.utils.logging_setup import setup_logging
from ibd_reports.utils.paths import PATCH21_JSONL, REKEY_CSV, REKEY_JSONL

logger = logging.getLogger(__name__)

CLAUDE_DIR = Path.home() / ".claude"
CONTEXT_MODE_DIR = CLAUDE_DIR / "context-mode" / "content"
CONTEXT_MODE_PREFIX = "fd33ccb5069271d3.db"
EXPECTED_VALUES = 27

_WS = re.compile(r"\s+")
_LOWER_HEX_ESCAPE = re.compile(r"\\u([0-9a-f]{4})")


def leaked_values() -> list[str]:
    """Modality values in REKEY_JSONL that the Phase 2.1 patch rules blank."""
    with REKEY_JSONL.open(encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    return [rec["modality"] for rec in records if patch_record(rec)[1]]


def build_needles(values: list[str]) -> set[bytes]:
    """Raw UTF-8 and lower/upper-hex JSON-escaped bytes of each value."""
    needles: set[bytes] = set()
    for value in values:
        # The recon printed modality lowercased and whitespace-collapsed, so search that form too.
        for form in {value, _WS.sub(" ", value).strip().lower()}:
            escaped = json.dumps(form)[1:-1]
            needles.add(form.encode("utf-8"))
            needles.add(escaped.encode("ascii"))
            needles.add(
                _LOWER_HEX_ESCAPE.sub(lambda m: "\\u" + m.group(1).upper(), escaped).encode("ascii")
            )
    # An empty needle would match every file.
    needles.discard(b"")
    return needles


def vscode_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    path = Path(appdata) / "Code"
    return path if path.is_dir() else None


def scan(root: Path, needles: set[bytes]) -> tuple[int, list[Path], list[Path]]:
    """Return (files scanned, files containing any needle, unreadable files) under root."""
    scanned = 0
    matches = []
    unreadable = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        scanned += 1
        # Files held open by a running app (e.g. VS Code databases) cannot be read; report, do not crash.
        try:
            data = path.read_bytes()
        except OSError:
            unreadable.append(path)
            continue
        if any(needle in data for needle in needles):
            matches.append(path)
    return scanned, matches, unreadable


def report_scan(label: str, root: Path, needles: set[bytes]) -> tuple[list[Path], list[Path]]:
    """Scan root, log its counts and matching paths under a heading; return (matches, unreadable)."""
    scanned, matches, unreadable = scan(root, needles)
    logger.info("== %s: %s ==", label, root)
    logger.info("Files scanned: %d | matching: %d | unreadable: %d", scanned, len(matches), len(unreadable))
    for path in matches:
        logger.info("  match %12d  %s", path.stat().st_size, path)
    for path in unreadable:
        logger.info("  unreadable  %s", path)
    return matches, unreadable


def context_mode_files() -> list[Path]:
    if not CONTEXT_MODE_DIR.is_dir():
        return []
    return sorted(p for p in CONTEXT_MODE_DIR.iterdir() if p.is_file() and p.name.startswith(CONTEXT_MODE_PREFIX))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delete", action="store_true", help="delete matching .claude files (default: dry run)")
    args = parser.parse_args()

    setup_logging("phase2_1_cleanup")
    logger.info("Mode: %s", "DELETE" if args.delete else "dry run")

    values = leaked_values()
    logger.info("Leaked modality values: %d (expected %d)", len(values), EXPECTED_VALUES)
    if len(values) != EXPECTED_VALUES:
        logger.error("Unexpected value count, aborting")
        return 1
    needles = build_needles(values)
    logger.info("Needle byte forms: %d", len(needles))

    matches, unreadable = report_scan("Claude Code (delete target)", CLAUDE_DIR, needles)

    ctx = context_mode_files()
    logger.info("Context-mode files to remove: %d", len(ctx))
    for path in ctx:
        logger.info("  context-mode %12d  %s", path.stat().st_size, path)

    vscode = vscode_dir()
    if vscode is None:
        logger.info("VS Code root not found, skipped")
        vs_matches, vs_unreadable = [], []
    else:
        vs_matches, vs_unreadable = report_scan("VS Code (REPORT-ONLY, never deleted)", vscode, needles)

    for path in (REKEY_JSONL, REKEY_CSV):
        logger.info("%s exists: %s", path.name, path.exists())

    if not args.delete:
        logger.info("Dry run complete, nothing deleted")
        return 0

    targets = sorted(set(matches) | set(ctx))
    failed = 0
    for path in targets:
        try:
            path.unlink()
        except OSError as exc:
            failed += 1
            logger.error("Could not delete %s: %s", path, exc)
    logger.info("Deleted %d files, %d failed", len(targets) - failed, failed)

    remaining, unreadable = report_scan("Claude Code rescan", CLAUDE_DIR, needles)
    logger.info("Rescan matching files: %d (expected 0)", len(remaining))

    keep_reasons = []
    if failed or remaining:
        keep_reasons.append("leaked strings remain under .claude")
    if unreadable:
        keep_reasons.append("unreadable files under .claude")
    if vs_matches:
        keep_reasons.append("VS Code root has matches (report-only, not deleted)")
    if vs_unreadable:
        keep_reasons.append("unreadable files under the VS Code root")
    if not PATCH21_JSONL.exists():
        keep_reasons.append(f"{PATCH21_JSONL.name} missing")
    if keep_reasons:
        logger.error("Rekeyed files NOT deleted: %s", "; ".join(keep_reasons))
        return 1

    for path in (REKEY_JSONL, REKEY_CSV):
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
        path.unlink()
        logger.info("%s gone: %s", path.name, not path.exists())
    return 0


if __name__ == "__main__":
    sys.exit(main())
