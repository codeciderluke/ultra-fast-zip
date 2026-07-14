"""Inspect tab — show .ufz archive metadata and file list."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.models import ArchiveInfo
from app.ui.widgets import PathPickerRow, make_card
from app.utils.format_utils import format_ratio, format_timestamp, human_size
from app.workers.inspect_worker import InspectWorker

_SUMMARY_FIELDS = [
    ("version", "Format Version"),
    ("codec", "Codec"),
    ("file_count", "Files"),
    ("block_count", "Blocks"),
    ("total_size", "Original Size"),
    ("compressed_size", "Compressed Size"),
    ("ratio", "Ratio"),
    ("created", "Created"),
    ("block_size", "Block Size"),
]


class InspectTab(QWidget):
    log_emitted = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._thread: QThread | None = None
        self._worker: InspectWorker | None = None
        self._info: ArchiveInfo | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        pick_card, pick_layout = make_card("Archive (.ufz)")
        self.input_row = PathPickerRow("Select a .ufz file to inspect", "Select Archive")
        self.input_row.button.clicked.connect(self._choose_archive)
        pick_layout.addWidget(self.input_row)
        root.addWidget(pick_card)

        summary_card, summary_layout = make_card("Archive Summary")
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(8)
        self._summary_values: dict[str, QLabel] = {}
        for index, (key, title) in enumerate(_SUMMARY_FIELDS):
            row, col = divmod(index, 4)
            title_label = QLabel(title)
            title_label.setProperty("role", "fieldLabel")
            value_label = QLabel("-")
            value_label.setProperty("role", "statValue")
            grid.addWidget(title_label, row * 2, col)
            grid.addWidget(value_label, row * 2 + 1, col)
            self._summary_values[key] = value_label
        summary_layout.addLayout(grid)
        root.addWidget(summary_card)

        list_card, list_layout = make_card("File List")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Search file paths...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        list_layout.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Path", "Size", "Block", "Modified"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        list_layout.addWidget(self.table, 1)
        root.addWidget(list_card, 1)

    # ------------------------------------------------------------- actions
    def _choose_archive(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Archive", "", "UFZ files (*.ufz);;All files (*.*)"
        )
        if not path:
            return
        self.input_row.set_path(path)
        self._load(Path(path))

    def _load(self, archive_path: Path) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        self._worker = InspectWorker(archive_path)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log_emitted.connect(self.log_emitted)
        self._worker.result_ready.connect(self._show_info)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    def _show_info(self, info: ArchiveInfo) -> None:
        self._info = info
        self._summary_values["version"].setText(str(info.version))
        self._summary_values["codec"].setText(info.codec)
        self._summary_values["file_count"].setText(f"{info.file_count:,}")
        self._summary_values["block_count"].setText(f"{info.block_count:,}")
        self._summary_values["total_size"].setText(human_size(info.total_size))
        self._summary_values["compressed_size"].setText(human_size(info.compressed_size))
        self._summary_values["ratio"].setText(format_ratio(info.total_size, info.compressed_size))
        self._summary_values["created"].setText(format_timestamp(info.created))
        self._summary_values["block_size"].setText(human_size(info.block_size))
        self._populate_table()
        self.log_emitted.emit(
            "success",
            f"Inspection done: {info.file_count:,} files, ratio {format_ratio(info.total_size, info.compressed_size)}",
        )

    def _populate_table(self) -> None:
        info = self._info
        if info is None:
            return
        keyword = self.filter_edit.text().strip().lower()
        rows = [
            entry
            for entry in info.files
            if not keyword or keyword in entry.path.lower()
        ]

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(entry.path))
            size_item = QTableWidgetItem(human_size(entry.size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 1, size_item)
            block_item = QTableWidgetItem(str(entry.block))
            block_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, block_item)
            self.table.setItem(row, 3, QTableWidgetItem(format_timestamp(entry.mtime)))
        self.table.setUpdatesEnabled(True)

    def _apply_filter(self) -> None:
        self._populate_table()

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Inspection Failed", message)

    def _cleanup(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
