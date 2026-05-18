from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy, QWidget

from .base import ConfigPanel

_MAX_BLOCKS = 5000


class JuliaConsolePanel(ConfigPanel):
    title = "Julia console"
    min_width = 320

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)

        self._console = QPlainTextEdit(self)
        self._console.setReadOnly(True)
        self._console.setMaximumBlockCount(_MAX_BLOCKS)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        self._console.setFont(font)
        self._console.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.body.addWidget(self._console, stretch=1)

        self._stderr_fmt = QTextCharFormat()
        self._stderr_fmt.setForeground(QColor("#c0392b"))
        self._stdout_fmt = QTextCharFormat()

    @Slot(str, str)
    def append_line(self, stream: str, line: str) -> None:
        fmt = self._stderr_fmt if stream == "stderr" else self._stdout_fmt
        scrollbar = self._console.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4

        cursor = self._console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(line + "\n", fmt)

        if at_bottom:
            self._console.ensureCursorVisible()
            scrollbar.setValue(scrollbar.maximum())
