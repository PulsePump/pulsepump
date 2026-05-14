"""QApplication entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .main_window import MainWindow
from .pico_loader import PicoLoader, PicoNotFoundError


def run() -> int:
    app = QApplication(sys.argv)

    loader = PicoLoader()
    try:
        loader.start()
    except PicoNotFoundError as e:
        QMessageBox.critical(None, "pulsepump", str(e))
        return 1
    except OSError as e:
        QMessageBox.critical(None, "pulsepump", f"Failed to launch mpremote: {e}")
        return 1

    window = MainWindow(loader)
    window.show()
    return app.exec()
