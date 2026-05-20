from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class Document(QObject):
    """Holds the in-memory state of a single text file.

    Tracks content, the backing file path, and whether unsaved changes exist.
    Emits signals when any of those three pieces of state change so views and
    window chrome can stay in sync without polling.

    Signals:
        - modified_changed(bool): Emitted when the modified flag flips.
        - path_changed: Emitted when the backing file path changes.
        - content_changed: Emitted when the text content changes.
    """

    modified_changed = Signal(bool)
    path_changed = Signal()
    content_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._content: str = ""
        self._modified: bool = False

    @property
    def path(self) -> Path | None:
        """Backing file path, or None for an unsaved document."""

        return self._path

    @property
    def display_name(self) -> str:
        """File name for use in titles and tabs; falls back to 'Untitled'."""

        return self._path.name if self._path else "Untitled"

    @property
    def content(self) -> str:
        """Current text content."""

        return self._content

    @content.setter
    def content(self, value: str) -> None:
        """Set text content and mark the document as modified."""

        if value == self._content:
            return
        self._content = value
        self._set_modified(True)
        self.content_changed.emit()

    @property
    def modified(self) -> bool:
        """True when there are unsaved changes."""

        return self._modified

    def read_from(self, path: Path) -> None:
        """Replace content with the file at *path* and clear the modified flag."""

        self._content = path.read_text(encoding="utf-8")
        self._path = path
        self._set_modified(False)
        self.path_changed.emit()
        self.content_changed.emit()

    def write_to(self, path: Path) -> None:
        """Write content to *path*, updating the backing path if it changed."""

        path.write_text(self._content, encoding="utf-8")
        if path != self._path:
            self._path = path
            self.path_changed.emit()
        self._set_modified(False)

    def clear_modified(self) -> None:
        """Reset the modified flag without touching content or path."""

        self._set_modified(False)

    def _set_modified(self, value: bool) -> None:
        if value == self._modified:
            return
        self._modified = value
        self.modified_changed.emit(value)
