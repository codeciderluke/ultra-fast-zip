"""Background worker for inspecting archive metadata."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.core.inspector import inspect
from app.core.models import ArchiveInfo


class InspectWorker(QObject):
    progress_changed = Signal(int)
    log_emitted = Signal(str, str)  # (level, message)
    result_ready = Signal(object)   # ArchiveInfo
    finished = Signal()
    failed = Signal(str)

    def __init__(self, archive_path: Path):
        super().__init__()
        self._archive_path = Path(archive_path)

    @Slot()
    def run(self) -> None:
        try:
            self.log_emitted.emit("info", f"Inspecting archive: {self._archive_path.name}")
            info: ArchiveInfo = inspect(self._archive_path)
        except Exception as exc:  # noqa: BLE001 — surface all errors to the UI
            self.log_emitted.emit("error", f"Inspection failed: {exc}")
            self.failed.emit(str(exc))
        else:
            self.result_ready.emit(info)
            self.finished.emit()
