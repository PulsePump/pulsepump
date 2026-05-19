"""QApplication entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .ui.manager import DocumentManager


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PulsePump")
    app.setOrganizationName("PulsePump")

    # Prevent Qt from quitting automatically when the last window closes;
    # DocumentManager drives the lifecycle instead.
    app.setQuitOnLastWindowClosed(False)

    manager = DocumentManager.instance()

    paths = [Path(a) for a in sys.argv[1:] if Path(a).exists()]
    if paths:
        for path in paths:
            manager.open_file(path)
    else:
        manager.new_window()

    return app.exec()
