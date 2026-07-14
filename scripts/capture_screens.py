"""Capture staged English GUI screenshots for the user manual.

Renders each tab of the real application window with representative demo
content and saves PNGs to docs/img/.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.inspector import inspect
from app.core.packer import PackOptions, pack
from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET

OUT = PROJECT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)


def pump(app, n=6):
    for _ in range(n):
        app.processEvents()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Ultra Fast Zip")
    app.setOrganizationName("UltraFastZip")
    app.setStyleSheet(STYLESHEET)
    icon = PROJECT / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    window = MainWindow()
    window.show()
    pump(app, 10)

    # Demo archive for the Inspect tab
    demo_root = Path(tempfile.mkdtemp(prefix="ufz_demo_"))
    src = demo_root / "my_project"
    (src / "src" / "components").mkdir(parents=True)
    (src / "assets" / "images").mkdir(parents=True)
    (src / "src" / "components" / "Dashboard.tsx").write_text("export const x = 1;\n" * 200)
    (src / "src" / "app.py").write_text("print('hello')\n" * 150)
    (src / "assets" / "images" / "logo.png").write_bytes(b"\x89PNG demo" * 400)
    (src / "README.md").write_text("# demo\n" * 60)
    demo_ufz = demo_root / "my_project.ufz"
    pack(src, demo_ufz, PackOptions())

    # --- Compress tab
    window.tabs.setCurrentIndex(0)
    t = window.compress_tab
    t.input_row.set_path(r"C:\Projects\my_project")
    t.output_row.set_path(r"C:\Projects\my_project.ufz")
    t.progress.setValue(62)
    t.status_label.setText("src/components/Dashboard.tsx")
    window.append_log("info", r"Compression started: C:\Projects\my_project")
    window.append_log("info", "Found 70,208 files, 1,053,105,443 bytes total")
    pump(app)
    window.grab().save(str(OUT / "tab_compress.png"))

    # --- Extract tab
    window.tabs.setCurrentIndex(1)
    t = window.extract_tab
    t.input_row.set_path(r"C:\Projects\my_project.ufz")
    t.output_row.set_path(r"C:\Projects\my_project_extracted")
    t.progress.setValue(45)
    t.status_label.setText("assets/images/logo.png")
    window.append_log("info", "Detected UFZ: my_project.ufz")
    window.append_log("info", "Extracting: 70,208 files, 121 blocks, 24 decompress + 24 write workers (pipeline)")
    pump(app)
    window.grab().save(str(OUT / "tab_extract.png"))

    # --- Inspect tab (real metadata from the demo archive)
    window.tabs.setCurrentIndex(2)
    t = window.inspect_tab
    t.input_row.set_path(r"C:\Projects\my_project.ufz")
    t._show_info(inspect(demo_ufz))
    window.append_log("success", "Inspected archive: my_project.ufz")
    pump(app)
    window.grab().save(str(OUT / "tab_inspect.png"))

    # --- Settings tab
    window.tabs.setCurrentIndex(3)
    pump(app)
    window.grab().save(str(OUT / "tab_settings.png"))

    print("saved 4 screenshots to", OUT)
    window.close()


if __name__ == "__main__":
    main()
