"""Shared UI components used across tabs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def make_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Create a rounded card frame with its inner layout."""
    card = QFrame()
    card.setProperty("role", "card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    title_label = QLabel(title)
    title_label.setProperty("role", "cardTitle")
    layout.addWidget(title_label)
    return card, layout


class PathPickerRow(QWidget):
    """Single row of a path QLineEdit plus a picker button."""

    def __init__(self, placeholder: str, button_text: str, editable: bool = True):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setReadOnly(not editable)
        self.button = QPushButton(button_text)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, value: str) -> None:
        self.edit.setText(value)
