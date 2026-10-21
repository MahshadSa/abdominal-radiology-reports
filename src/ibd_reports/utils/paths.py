from pathlib import Path

_REPO_ROOT: Path = Path(__file__).parent.parent.parent.parent.resolve()

DATA_ROOT: Path = (_REPO_ROOT / "../ibd-reports-data").resolve()
ARCHIVE_READONLY: Path = DATA_ROOT / "00_archive_readonly"
WORKING_COPY: Path = DATA_ROOT / "01_working_copy"
WORKING_REPORTS: Path = WORKING_COPY / "reports"
METADATA_DIR: Path = DATA_ROOT / "02_metadata"
PARSED_DIR: Path = DATA_ROOT / "03_parsed"
LOGS_DIR: Path = DATA_ROOT / "04_logs"
DEID_DIR: Path = DATA_ROOT / "05_deidentified"
QUARANTINE_DIR: Path = DATA_ROOT / "99_quarantine"

REKEY_JSONL: Path = DEID_DIR / "phase2_rekeyed.jsonl"
REKEY_CSV: Path = DEID_DIR / "phase2_rekeyed.csv"
REC_MAP_CSV: Path = METADATA_DIR / "rec_id_map.csv"
PATCH21_JSONL: Path = DEID_DIR / "phase2_1_rekeyed.jsonl"
PATCH21_CSV: Path = DEID_DIR / "phase2_1_rekeyed.csv"

STOPLIST_PATH: Path = Path(__file__).resolve().parent.parent / "stoplist.txt"


def verify_data_tree() -> None:
    """Check that all expected data directories exist."""
    dirs = {
        "DATA_ROOT": DATA_ROOT,
        "ARCHIVE_READONLY": ARCHIVE_READONLY,
        "WORKING_COPY": WORKING_COPY,
        "WORKING_REPORTS": WORKING_REPORTS,
        "METADATA_DIR": METADATA_DIR,
        "PARSED_DIR": PARSED_DIR,
        "LOGS_DIR": LOGS_DIR,
        "QUARANTINE_DIR": QUARANTINE_DIR,
    }
    missing = [f"{name} ({path})" for name, path in dirs.items() if not path.is_dir()]
    if missing:
        raise FileNotFoundError(
            "Missing expected data directories:\n" + "\n".join(f"  {m}" for m in missing)
        )
