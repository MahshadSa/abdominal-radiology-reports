import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ibd_reports.utils.paths import LOGS_DIR


def setup_logging(phase_name: str) -> Path:
    """Configure root logger for stderr and a timestamped file. Returns the log file path."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"{phase_name}_{timestamp}.log"

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)

    return log_file
