"""Dark theme color palette and global QSS."""
from __future__ import annotations

import sys

BACKGROUND = "#0F1117"
SURFACE = "#161A23"
SURFACE_ELEVATED = "#1E2430"
BORDER = "#2A3140"
PRIMARY = "#7C5CFF"
PRIMARY_HOVER = "#8D72FF"
ACCENT = "#00D4FF"
TEXT_PRIMARY = "#F5F7FA"
TEXT_SECONDARY = "#A8B0C2"
TEXT_MUTED = "#6F7787"
SUCCESS = "#31D0AA"
WARNING = "#FFB020"
ERROR = "#FF5C7A"
LOG_BACKGROUND = "#090B10"

LOG_COLORS = {
    "info": TEXT_SECONDARY,
    "success": SUCCESS,
    "warning": WARNING,
    "error": ERROR,
}


def ui_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "SF Pro Text"
    return "Inter, Noto Sans"


STYLESHEET = f"""
* {{
    font-family: "{ui_font_family()}";
}}

QMainWindow, QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}

QLabel {{
    background: transparent;
}}

QLabel[role="appTitle"] {{
    font-size: 20px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}

QLabel[role="appSubtitle"] {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}

QLabel[role="cardTitle"] {{
    font-size: 13px;
    font-weight: 600;
    color: {ACCENT};
}}

QLabel[role="fieldLabel"] {{
    color: {TEXT_SECONDARY};
}}

QLabel[role="statValue"] {{
    font-size: 15px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

QFrame[role="card"] {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QTabWidget::pane {{
    border: none;
    background: transparent;
}}

QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 18px;
    margin-right: 6px;
    font-weight: 600;
}}

QTabBar::tab:hover {{
    color: {TEXT_PRIMARY};
    background: {SURFACE_ELEVATED};
}}

QTabBar::tab:selected {{
    color: {TEXT_PRIMARY};
    background: {SURFACE_ELEVATED};
    border: 1px solid {BORDER};
}}

QPushButton {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 18px;
    font-weight: 600;
}}

QPushButton:hover {{
    border-color: {PRIMARY};
}}

QPushButton:disabled {{
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

QPushButton[role="primary"] {{
    background-color: {PRIMARY};
    color: #FFFFFF;
    border: none;
}}

QPushButton[role="primary"]:hover {{
    background-color: {PRIMARY_HOVER};
}}

QPushButton[role="primary"]:disabled {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_MUTED};
}}

QPushButton[role="danger"] {{
    background-color: transparent;
    color: {ERROR};
    border: 1px solid {ERROR};
}}

QLineEdit, QComboBox, QSpinBox {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {PRIMARY};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {PRIMARY};
}}

QLineEdit:read-only {{
    color: {TEXT_SECONDARY};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    selection-background-color: {PRIMARY};
    outline: none;
}}

QCheckBox {{
    color: {TEXT_SECONDARY};
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {SURFACE_ELEVATED};
}}

QCheckBox::indicator:checked {{
    background-color: {PRIMARY};
    border-color: {PRIMARY};
}}

QProgressBar {{
    background-color: {SURFACE_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 16px;
    text-align: center;
    color: {TEXT_PRIMARY};
    font-size: 11px;
}}

QProgressBar::chunk {{
    background-color: {PRIMARY};
    border-radius: 7px;
}}

QTextEdit[role="logConsole"] {{
    background-color: {LOG_BACKGROUND};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 6px;
}}

QTableWidget {{
    background-color: {SURFACE};
    alternate-background-color: {SURFACE_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: {BORDER};
}}

QTableWidget::item:selected {{
    background-color: {PRIMARY};
    color: #FFFFFF;
}}

QHeaderView::section {{
    background-color: {SURFACE_ELEVATED};
    color: {TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 600;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 24px;
}}
"""
