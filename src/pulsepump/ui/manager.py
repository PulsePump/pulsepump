from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .document import Document
from .window import DocumentWindow


class DocumentManager:
    """Singleton tracking all open DocumentWindows."""

    _instance: DocumentManager | None = None

    @classmethod
    def instance(cls) -> DocumentManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._windows: list[DocumentWindow] = []

    def new_window(self) -> DocumentWindow:
        """Open a new window with an empty untitled document."""

        doc = Document()
        window = DocumentWindow(doc)
        self._windows.append(window)
        window.show()
        return window

    def open_file(self, path: Path) -> DocumentWindow:
        """Open a file in a new window, or focus it if already open."""

        for window in self._windows:
            if window.document.path == path:
                window.activateWindow()
                window.raise_()
                return window
        doc = Document()
        with contextlib.suppress(OSError):
            doc.read_from(path)
        window = DocumentWindow(doc)
        self._windows.append(window)
        window.show()
        return window

    def on_window_closed(self, window: DocumentWindow) -> None:
        """Remove window from the tracked set and quit when none remain."""

        if window in self._windows:
            self._windows.remove(window)
        if not self._windows:
            QApplication.quit()
