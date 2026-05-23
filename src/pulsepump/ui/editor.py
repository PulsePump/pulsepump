from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from .document import Document


class EditorWidget(QPlainTextEdit):
    """A plain-text YAML editor bound to a Document."""

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self._syncing = False

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.setFont(font)
        self.setPlainText(document.content)

        self.textChanged.connect(self._on_text_changed)
        document.content_changed.connect(self._on_document_content_changed)

    @property
    def document_model(self) -> Document:
        return self._document

    def _on_text_changed(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        self._document.content = self.toPlainText()
        self._syncing = False

    def _on_document_content_changed(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.setPlainText(self._document.content)
        self._syncing = False
