"""Background pack worker; runs off the GUI thread and supports batch jobs."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.core.archive import OperationCancelled
from app.core.packer import PackOptions, pack


class PackWorker(QObject):
    progress_changed = Signal(int)
    status_changed = Signal(str)    # path of file currently being packed
    log_emitted = Signal(str, str)  # (level, message)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, jobs: list[tuple[Path, Path]], options: PackOptions):
        """``jobs``: list of (input folder, output .ufz path); processed sequentially."""
        super().__init__()
        self._jobs = [(Path(src), Path(out)) for src, out in jobs]
        self._options = options
        self._cancel = threading.Event()
        self.was_cancelled = False

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        total = len(self._jobs)
        try:
            for index, (src_dir, out_path) in enumerate(self._jobs):
                if self._cancel.is_set():
                    raise OperationCancelled("Cancelled by user.")
                if total > 1:
                    self.log_emitted.emit("info", f"[{index + 1}/{total}] Packing {src_dir.name}")
                base = index * 100
                pack(
                    src_dir,
                    out_path,
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
            self.log_emitted.emit("warning", "Packing cancelled. Partial output files were removed.")
            self.finished.emit()
        except Exception as exc:  # noqa: BLE001 — surface all errors to the UI
            self.log_emitted.emit("error", f"Packing failed: {exc}")
            self.failed.emit(str(exc))
        else:
            self.finished.emit()
