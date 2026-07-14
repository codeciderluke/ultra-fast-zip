"""Ultra Fast Zip main window."""
from __future__ import annotations

import html
import time
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui import settings_tab as settings_module
from app.ui.compress_tab import CompressTab
from app.ui.extract_tab import ExtractTab
from app.ui.inspect_tab import InspectTab
from app.ui.settings_tab import SettingsTab
from app.ui.theme import LOG_COLORS, TEXT_MUTED
from app.utils.logger import LogFileWriter


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ultra Fast Zip")
        self.resize(960, 720)
        self._log_writer = LogFileWriter(Path.cwd() / "logs")

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        title = QLabel("Ultra Fast Zip")
        title.setProperty("role", "appTitle")
        subtitle = QLabel("High-speed archive tool for massive file trees")
        subtitle.setProperty("role", "appSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.compress_tab = CompressTab()
        self.extract_tab = ExtractTab()
        self.inspect_tab = InspectTab()
        self.settings_tab = SettingsTab()
        self.tabs.addTab(self.compress_tab, "Compress")
        self.tabs.addTab(self.extract_tab, "Extract")
        self.tabs.addTab(self.inspect_tab, "Inspect")
        self.tabs.addTab(self.settings_tab, "Settings")
        root.addWidget(self.tabs, 1)

        self.log_console = QTextEdit()
        self.log_console.setProperty("role", "logConsole")
        self.log_console.setReadOnly(True)
        self.log_console.setFixedHeight(160)
        root.addWidget(self.log_console)

        self.setCentralWidget(central)

        for tab in (self.compress_tab, self.extract_tab, self.inspect_tab):
            tab.log_emitted.connect(self.append_log)

        self.append_log("info", "Ultra Fast Zip ready.")

    def append_log(self, level: str, message: str) -> None:
        color = LOG_COLORS.get(level, LOG_COLORS["info"])
        stamp = time.strftime("%H:%M:%S")
        self.log_console.append(
            f'<span style="color:{TEXT_MUTED}">[{stamp}]</span> '
            f'<span style="color:{color}">{html.escape(message)}</span>'
        )
        scrollbar = self.log_console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        if settings_module.save_logs_enabled():
            try:
                self._log_writer.write(level, message)
            except OSError:
                pass

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.compress_tab.is_busy() or self.extract_tab.is_busy():
            answer = QMessageBox.question(
                self,
                "Task in Progress",
                "A compression/extraction task is still running. Quit anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._log_writer.close()
        event.accept()
