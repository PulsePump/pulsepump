"""QApplication entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .main_window import MainWindow
from .pico_loader import PicoLoader, PicoNotFoundError


def run() -> int:
    app = QApplication(sys.argv)

    loader = PicoLoader()
    window = MainWindow(loader)
    window.show()

    try:
        loader.start()
    except PicoNotFoundError as e:
        window.show_disconnected(str(e))
        QMessageBox.critical(window, "pulsepump", str(e))
    except OSError as e:
        msg = f"Failed to launch mpremote: {e}"
        window.show_disconnected(msg)
        QMessageBox.critical(window, "pulsepump", msg)
    else:
        window.attach_reader()

    return app.exec()
