"""Log console helpers — level definitions and optional file logging."""
from __future__ import annotations

import time
from pathlib import Path

LEVELS = ("info", "success", "warning", "error")


class LogFileWriter:
    """Writes log lines to a file when file logging is enabled."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self._fp = None

    def write(self, level: str, message: str) -> None:
        if self._fp is None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            name = time.strftime("ufz_%Y%m%d_%H%M%S.log")
            self._fp = open(self.log_dir / name, "a", encoding="utf-8")
        stamp = time.strftime("%H:%M:%S")
        self._fp.write(f"[{stamp}] [{level.upper():7}] {message}\n")
        self._fp.flush()

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None
