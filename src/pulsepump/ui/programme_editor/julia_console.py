from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class JuliaConsoleWindow(QMainWindow):
    """Floating window that streams Julia/openBF stdout+stderr and allows kill."""

    kill_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("openBF — Julia Console")
        self.resize(700, 450)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = self._log.font()
        font.setFamily("Menlo, Consolas, monospace")
        font.setPointSize(11)
        self._log.setFont(font)

        self._kill_btn = QPushButton("Kill simulation")
        self._kill_btn.clicked.connect(self.kill_requested)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._log)
        layout.addWidget(self._kill_btn)
        self.setCentralWidget(container)

    def append_stdout(self, line: str) -> None:
        self._log.appendPlainText(line)
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def append_stderr(self, line: str) -> None:
        self._log.appendPlainText(f"[stderr] {line}")
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def set_running(self, running: bool) -> None:
        self._kill_btn.setEnabled(running)
        self._kill_btn.setText("Kill simulation" if running else "Simulation ended")

    def clear(self) -> None:
        self._log.clear()
