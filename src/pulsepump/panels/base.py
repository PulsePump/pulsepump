"""Base class for dockable configuration panels."""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtWidgets import QVBoxLayout, QWidget


class ConfigPanel(QWidget):
    """Plain widget that knows nothing about docking.

    Subclasses set `title` and populate `self.body` (a `QVBoxLayout`).
    """

    title: ClassVar[str] = "Panel"
    min_width: ClassVar[int] = 240

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(8, 8, 8, 8)
        self.body.setSpacing(6)
