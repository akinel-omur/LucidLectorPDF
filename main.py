"""Entry point for AkinelPDF."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from pdf_reader.main_window import MainWindow


APP_NAME = "LucidLectorPDF"


def _resource_path(rel: str) -> Path:
    """Resolve a resource path whether running from source or a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    icon_path = _resource_path("resources/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.showMaximized()
    if len(sys.argv) > 1:
        window.open_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
