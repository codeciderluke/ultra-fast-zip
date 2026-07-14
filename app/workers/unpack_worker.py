"""Background unpack worker; runs off the GUI thread and supports batch jobs."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.core.archive import OperationCancelled
from app.core.formats import extract_archive
from app.core.unpacker import UnpackOptions


class UnpackWorker(QObject):
    progress_changed = Signal(int)
    status_changed = Signal(str)    # path of file currently being restored
    log_emitted = Signal(str, str)  # (level, message)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, jobs: list[tuple[Path, Path]], options: UnpackOptions):
        """``jobs``: list of (archive file, output folder); processed sequentially.

        Formats are auto-detected (.ufz plus zip/7z/rar/tar/gz/cab/iso etc.).
        """
        super().__init__()
        self._jobs = [(Path(archive), Path(out)) for archive, out in jobs]
        self._options = options
        self._cancel = threading.Event()
        self.was_cancelled = False

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        total = len(self._jobs)
        try:
            for index, (archive_path, out_dir) in enumerate(self._jobs):
                if self._cancel.is_set():
                    raise OperationCancelled("Cancelled by user.")
                if total > 1:
                    self.log_emitted.emit("info", f"[{index + 1}/{total}] Extracting {archive_path.name}")
                base = index * 100
                extract_archive(
                    archive_path,
                    out_dir,
                    self._options,
                    progress_cb=lambda p, base=base: self.progress_changed.emit(
                        int((base + p) / total)
                    ),
                    log_cb=self.log_emitted.emit,
                    cancel=self._cancel,
                    status_cb=self.status_changed.emit,
                )
        except OperationCancelled:
            self.was_cancelled = True
            self.log_emitted.emit("warning", "Extraction cancelled.")
            self.finished.emit()
        except Exception as exc:  # noqa: BLE001 — surface all errors to the UI
            self.log_emitted.emit("error", f"Extraction failed: {exc}")
            self.failed.emit(str(exc))
        else:
            self.finished.emit()
