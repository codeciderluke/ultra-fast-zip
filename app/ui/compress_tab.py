"""Compress tab — select folders and pack into .ufz archives."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.core.packer import PackOptions
from app.ui import settings_tab
from app.ui.widgets import PathPickerRow, make_card
from app.utils.path_utils import default_output_archive
from app.workers.pack_worker import PackWorker


class CompressTab(QWidget):
    log_emitted = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._thread: QThread | None = None
        self._worker: PackWorker | None = None
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        in_card, in_layout = make_card("Input Folders (separate multiple with ;)")
        self.input_row = PathPickerRow("Select folders to compress (Ctrl/Shift for multi-select)", "Select Folder")
        self.input_row.button.clicked.connect(self._choose_folder)
        in_layout.addWidget(self.input_row)
        root.addWidget(in_card)

        out_card, out_layout = make_card("Output (.ufz)")
        self.output_row = PathPickerRow("Output file path (for multiple folders: output folder)", "Browse")
        self.output_row.button.clicked.connect(self._choose_output)
        out_layout.addWidget(self.output_row)
        root.addWidget(out_card)

        opt_card, opt_layout = make_card("Compression Options")
        opt_row = QHBoxLayout()
        opt_row.setSpacing(16)

        opt_row.addWidget(self._field_label("Block Size"))
        self.block_combo = QComboBox()
        for mb in settings_tab.BLOCK_SIZE_CHOICES_MB:
            self.block_combo.addItem(f"{mb} MB", mb)
        saved_block = settings_tab.load_int(
            "compress/block_size_mb", settings_tab.default_block_size_mb()
        )
        idx = self.block_combo.findData(saved_block)
        self.block_combo.setCurrentIndex(idx if idx >= 0 else 2)
        opt_row.addWidget(self.block_combo)

        opt_row.addWidget(self._field_label("Compression Level"))
        self.level_combo = QComboBox()
        for value, text in settings_tab.LEVEL_CHOICES:
            self.level_combo.addItem(text, value)
        saved_level = settings_tab.load_int("compress/level", settings_tab.default_level())
        idx = self.level_combo.findData(saved_level)
        self.level_combo.setCurrentIndex(idx if idx >= 0 else 1)
        opt_row.addWidget(self.level_combo)

        opt_row.addWidget(self._field_label("Worker Threads"))
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, max(64, (os.cpu_count() or 1) * 2))
        self.threads_spin.setSpecialValueText(f"Auto ({os.cpu_count() or 1} CPU cores)")
        self.threads_spin.setValue(
            settings_tab.load_int("compress/threads", settings_tab.default_threads())
        )
        opt_row.addWidget(self.threads_spin)

        self.hidden_check = QCheckBox("Include hidden files")
        self.hidden_check.setChecked(settings_tab.load_bool("compress/include_hidden", True))
        opt_row.addWidget(self.hidden_check)

        self.empty_dirs_check = QCheckBox("Include empty folders")
        self.empty_dirs_check.setChecked(
            settings_tab.load_bool("compress/include_empty_dirs", True)
        )
        opt_row.addWidget(self.empty_dirs_check)

        self.block_combo.currentIndexChanged.connect(self._save_prefs)
        self.level_combo.currentIndexChanged.connect(self._save_prefs)
        self.threads_spin.valueChanged.connect(self._save_prefs)
        self.hidden_check.toggled.connect(self._save_prefs)
        self.empty_dirs_check.toggled.connect(self._save_prefs)

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

        self.start_button = QPushButton("Start Compression")
        self.start_button.setProperty("role", "primary")
        self.start_button.clicked.connect(self._start)
        button_row.addWidget(self.start_button)
        root.addLayout(button_row)
        root.addStretch(1)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "fieldLabel")
        return label

    def _save_prefs(self) -> None:
        settings_tab.save_value("compress/block_size_mb", self.block_combo.currentData())
        settings_tab.save_value("compress/level", self.level_combo.currentData())
        settings_tab.save_value("compress/threads", self.threads_spin.value())
        settings_tab.save_value("compress/include_hidden", self.hidden_check.isChecked())
        settings_tab.save_value("compress/include_empty_dirs", self.empty_dirs_check.isChecked())

    def _input_folders(self) -> list[str]:
        """Split the input field text on ';' into a folder list."""
        return [p.strip() for p in self.input_row.path().split(";") if p.strip()]

    # ------------------------------------------------------------- actions
    def _choose_folder(self) -> None:
        # Native Windows dialog cannot multi-select folders, so use Qt's dialog
        dialog = QFileDialog(self, "Select Folders to Compress (Ctrl/Shift for multi-select)")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        for view in dialog.findChildren(QListView) + dialog.findChildren(QTreeView):
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if not dialog.exec():
            return
        folders = [f for f in dialog.selectedFiles() if Path(f).is_dir()]
        if not folders:
            return
        self.input_row.set_path("; ".join(folders))
        if len(folders) == 1:
            self.output_row.set_path(str(default_output_archive(Path(folders[0]))))
        else:
            # Multi-select: output field holds the folder where .ufz files are created
            self.output_row.set_path(str(Path(folders[0]).parent))

    def _choose_output(self) -> None:
        if len(self._input_folders()) > 1:
            folder = QFileDialog.getExistingDirectory(
                self, "Select Output Folder (each folder becomes <name>.ufz)", self.output_row.path()
            )
            if folder:
                self.output_row.set_path(folder)
            return
        suggested = self.output_row.path() or self.input_row.path()
        path, _ = QFileDialog.getSaveFileName(
            self, "Select Output File", suggested, "UFZ files (*.ufz)"
        )
        if path:
            if not path.lower().endswith(".ufz"):
                path += ".ufz"
            self.output_row.set_path(path)

    def _start(self) -> None:
        folders = self._input_folders()
        out = self.output_row.path()
        if not folders:
            QMessageBox.warning(self, "Input Required", "Select folders to compress first.")
            return
        missing = [f for f in folders if not Path(f).is_dir()]
        if missing:
            QMessageBox.critical(self, "Error", "Input folders do not exist:\n" + "\n".join(missing))
            return

        # Build (input folder, output file) job list
        if len(folders) == 1:
            if not out:
                out = str(default_output_archive(Path(folders[0])))
                self.output_row.set_path(out)
            jobs = [(Path(folders[0]), Path(out))]
        else:
            out_dir = Path(out) if out else Path(folders[0]).parent
            if out_dir.suffix.lower() == ".ufz":
                QMessageBox.warning(
                    self, "Check Output", "Multiple folders selected; specify a folder as the output."
                )
                return
            jobs = [(Path(f), out_dir / f"{Path(f).name}.ufz") for f in folders]

        existing = [str(dst) for _, dst in jobs if dst.exists()]
        if existing:
            answer = QMessageBox.question(
                self,
                "Confirm Overwrite",
                f"{len(existing)} output file(s) already exist. Overwrite?\n\n"
                + "\n".join(existing[:5])
                + ("\n..." if len(existing) > 5 else ""),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        options = PackOptions(
            block_size=int(self.block_combo.currentData()) * 1024 * 1024,
            level=int(self.level_combo.currentData()),
            include_hidden=self.hidden_check.isChecked(),
            include_empty_dirs=self.empty_dirs_check.isChecked(),
            threads=self.threads_spin.value(),
        )

        self._worker = PackWorker(jobs, options)
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
            self.log_emitted.emit("info", f"Compression started: {jobs[0][0]}")
        else:
            self.log_emitted.emit("info", f"Batch compression started: {len(jobs)} folders")
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.log_emitted.emit("warning", "Cancellation requested...")

    def _on_finished(self) -> None:
        if self._worker is not None and not self._worker.was_cancelled:
            QMessageBox.information(self, "Done", "Compression completed.")

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Compression Failed", message)

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
