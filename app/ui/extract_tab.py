"""Extract tab — select archives (.ufz plus zip/7z/rar/tar/... auto-detected) and unpack."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.formats import SUPPORTED_PATTERNS
from app.core.unpacker import UnpackOptions
from app.ui import settings_tab
from app.ui.widgets import PathPickerRow, make_card
from app.utils.path_utils import default_output_folder
from app.workers.unpack_worker import UnpackWorker


class ExtractTab(QWidget):
    log_emitted = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._thread: QThread | None = None
        self._worker: UnpackWorker | None = None
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        in_card, in_layout = make_card("Archives (.ufz plus zip/7z/rar/tar etc. auto-detected; separate multiple with ;)")
        self.input_row = PathPickerRow("Select archives to extract (multi-select supported)", "Select Archives")
        self.input_row.button.clicked.connect(self._choose_archive)
        in_layout.addWidget(self.input_row)
        root.addWidget(in_card)

        out_card, out_layout = make_card("Output Folder")
        self.output_row = PathPickerRow("Folder to extract into (for multiple archives: one subfolder each)", "Browse")
        self.output_row.button.clicked.connect(self._choose_output)
        out_layout.addWidget(self.output_row)
        root.addWidget(out_card)

        opt_card, opt_layout = make_card("Extraction Options")
        opt_row = QHBoxLayout()
        opt_row.setSpacing(16)

        label = QLabel("Worker threads (.ufz only)")
        label.setProperty("role", "fieldLabel")
        opt_row.addWidget(label)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, max(64, (os.cpu_count() or 1) * 2))
        self.threads_spin.setSpecialValueText(f"Auto ({os.cpu_count() or 1} CPU cores)")
        self.threads_spin.setValue(
            settings_tab.load_int("extract/threads", settings_tab.default_threads())
        )
        opt_row.addWidget(self.threads_spin)

        self.overwrite_check = QCheckBox("Overwrite existing files")
        self.overwrite_check.setChecked(settings_tab.load_bool("extract/overwrite", False))
        opt_row.addWidget(self.overwrite_check)

        self.open_after_check = QCheckBox("Open folder after extraction")
        self.open_after_check.setChecked(settings_tab.load_bool("extract/open_after", True))
        opt_row.addWidget(self.open_after_check)

        self.threads_spin.valueChanged.connect(self._save_prefs)
        self.overwrite_check.toggled.connect(self._save_prefs)
        self.open_after_check.toggled.connect(self._save_prefs)

        opt_row.addStretch(1)
        opt_layout.addLayout(opt_row)
        root.addWidget(opt_card)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "fieldLabel")
        root.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        button_row.addWidget(self.cancel_button)

        self.start_button = QPushButton("Start Extraction")
        self.start_button.setProperty("role", "primary")
        self.start_button.clicked.connect(self._start)
        button_row.addWidget(self.start_button)
        root.addLayout(button_row)
        root.addStretch(1)

    def _save_prefs(self) -> None:
        settings_tab.save_value("extract/threads", self.threads_spin.value())
        settings_tab.save_value("extract/overwrite", self.overwrite_check.isChecked())
        settings_tab.save_value("extract/open_after", self.open_after_check.isChecked())

    def _input_archives(self) -> list[str]:
        """Split the input field text on ';' into an archive list."""
        return [p.strip() for p in self.input_row.path().split(";") if p.strip()]

    # ------------------------------------------------------------- actions
    def _choose_archive(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Archives (multi-select supported)", "",
            f"Archives ({SUPPORTED_PATTERNS});;UFZ files (*.ufz);;All files (*.*)",
        )
        if not paths:
            return
        self.input_row.set_path("; ".join(paths))
        if len(paths) == 1:
            self.output_row.set_path(str(default_output_folder(Path(paths[0]))))
        else:
            # Multi-select: output field holds the parent folder for per-archive subfolders
            self.output_row.set_path(str(Path(paths[0]).parent))

    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.output_row.path())
        if folder:
            self.output_row.set_path(folder)

    def _start(self) -> None:
        archives = self._input_archives()
        out = self.output_row.path()
        if not archives:
            QMessageBox.warning(self, "Input Required", "Select archives to extract first.")
            return
        missing = [f for f in archives if not Path(f).is_file()]
        if missing:
            QMessageBox.critical(
                self, "Error", "Archives do not exist:\n" + "\n".join(missing)
            )
            return

        # Build (archive, output folder) job list
        if len(archives) == 1:
            if not out:
                out = str(default_output_folder(Path(archives[0])))
                self.output_row.set_path(out)
            jobs = [(Path(archives[0]), Path(out))]
        else:
            out_root = Path(out) if out else Path(archives[0]).parent
            jobs = [(Path(f), out_root / default_output_folder(Path(f)).name) for f in archives]

        options = UnpackOptions(
            threads=self.threads_spin.value(),
            overwrite=self.overwrite_check.isChecked(),
        )

        self._worker = UnpackWorker(jobs, options)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress_changed.connect(self.progress.setValue)
        self._worker.status_changed.connect(self._show_status)
        self._worker.log_emitted.connect(self.log_emitted)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)

        self.progress.setValue(0)
        self._set_running(True)
        if len(jobs) == 1:
            self.log_emitted.emit("info", f"Extraction started: {jobs[0][0]}")
        else:
            self.log_emitted.emit("info", f"Batch extraction started: {len(jobs)} archives")
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.log_emitted.emit("warning", "Cancellation requested...")

    def _on_finished(self) -> None:
        if self._worker is not None and not self._worker.was_cancelled:
            out = self.output_row.path()
            QMessageBox.information(self, "Done", "Extraction completed.")
            if self.open_after_check.isChecked() and out:
                QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Extraction Failed", message)

    def _show_status(self, name: str) -> None:
        metrics = self.status_label.fontMetrics()
        width = max(120, self.status_label.width() - 12)
        self.status_label.setText(metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, width))

    def _cleanup(self) -> None:
        self._set_running(False)
        self.status_label.setText("")
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.input_row.button.setEnabled(not running)
        self.output_row.button.setEnabled(not running)

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()
