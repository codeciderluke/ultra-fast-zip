"""Ultra Fast Zip entry point — run with ``python app/main.py``."""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root so `app.*` imports work when run directly as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET


def asset_path(name: str) -> Path:
    """Resolve an assets file path in both dev and PyInstaller bundles."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ultra Fast Zip")
    app.setOrganizationName("UltraFastZip")
    app.setStyleSheet(STYLESHEET)
    icon_file = asset_path("icon.png")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
