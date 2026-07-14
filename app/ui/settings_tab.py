"""Settings tab — persists default options via QSettings."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import make_card

ORG = "UltraFastZip"
APP = "UltraFastZip"

BLOCK_SIZE_CHOICES_MB = [1, 4, 8, 16, 32]
LEVEL_CHOICES = [(1, "1 (Fast)"), (3, "3"), (6, "6 (Default)"), (12, "12"), (19, "19 (Max Compression)")]

KEY_BLOCK_SIZE_MB = "defaults/block_size_mb"
KEY_LEVEL = "defaults/level"
KEY_THREADS = "defaults/threads"
KEY_THEME = "ui/theme"
KEY_SAVE_LOGS = "log/save_to_file"


def settings() -> QSettings:
    return QSettings(ORG, APP)


def default_block_size_mb() -> int:
    return int(settings().value(KEY_BLOCK_SIZE_MB, 8))


def default_level() -> int:
    return int(settings().value(KEY_LEVEL, 6))


def default_threads() -> int:
    return int(settings().value(KEY_THREADS, 0))


def save_logs_enabled() -> bool:
    return settings().value(KEY_SAVE_LOGS, "false") in (True, "true", "1")


def load_int(key: str, default: int) -> int:
    try:
        return int(settings().value(key, default))
    except (TypeError, ValueError):
        return default


def load_bool(key: str, default: bool) -> bool:
    value = settings().value(key, None)
    if value is None:
        return default
    return value in (True, "true", "1")


def save_value(key: str, value) -> None:
    """Store bools as strings for QSettings compatibility."""
    if isinstance(value, bool):
        value = "true" if value else "false"
    settings().setValue(key, value)


class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        card, layout = make_card("Default Settings")
        form = QFormLayout()
        form.setSpacing(12)

        self.block_combo = QComboBox()
        for mb in BLOCK_SIZE_CHOICES_MB:
            self.block_combo.addItem(f"{mb} MB", mb)
        self.block_combo.setCurrentIndex(BLOCK_SIZE_CHOICES_MB.index(default_block_size_mb()))
        form.addRow(self._label("Default Block Size"), self.block_combo)

        self.level_combo = QComboBox()
        for value, text in LEVEL_CHOICES:
            self.level_combo.addItem(text, value)
        self._select_data(self.level_combo, default_level())
        form.addRow(self._label("Default Compression Level"), self.level_combo)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, max(64, (os.cpu_count() or 1) * 2))
        self.threads_spin.setSpecialValueText(f"Auto ({os.cpu_count() or 1} CPU cores)")
        self.threads_spin.setValue(default_threads())
        form.addRow(self._label("Default Worker Threads"), self.threads_spin)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark (Default)", "dark")
        self.theme_combo.setEnabled(False)
        form.addRow(self._label("Theme"), self.theme_combo)

        self.save_logs_check = QCheckBox("Save task logs to file (logs folder)")
        self.save_logs_check.setChecked(save_logs_enabled())
        form.addRow(self._label("Log Saving"), self.save_logs_check)

        layout.addLayout(form)
        hint = QLabel("Settings are saved immediately and apply to new tasks.")
        hint.setProperty("role", "fieldLabel")
        layout.addWidget(hint)

        root.addWidget(card)
        root.addStretch(1)

        credit = QLabel("Designed by Codecider Lab, Ver 1.0")
        credit.setProperty("role", "appSubtitle")
        credit.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(credit)

        self.block_combo.currentIndexChanged.connect(self._save)
        self.level_combo.currentIndexChanged.connect(self._save)
        self.threads_spin.valueChanged.connect(self._save)
        self.save_logs_check.toggled.connect(self._save)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "fieldLabel")
        return label

    @staticmethod
    def _select_data(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _save(self) -> None:
        s = settings()
        s.setValue(KEY_BLOCK_SIZE_MB, self.block_combo.currentData())
        s.setValue(KEY_LEVEL, self.level_combo.currentData())
        s.setValue(KEY_THREADS, self.threads_spin.value())
        s.setValue(KEY_THEME, "dark")
        s.setValue(KEY_SAVE_LOGS, "true" if self.save_logs_check.isChecked() else "false")
