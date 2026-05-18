"""Base class for dockable configuration panels."""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

# Shared width for every editable form field (spin boxes, combo boxes) so each
# panel lines up consistently regardless of the value being shown.
FIELD_WIDTH = 140


def apply_field_width(combo: QComboBox) -> None:
    """Pin a combo box and its dropdown view to FIELD_WIDTH."""
    combo.setFixedWidth(FIELD_WIDTH)
    combo.view().setMinimumWidth(FIELD_WIDTH)
    combo.view().setMaximumWidth(FIELD_WIDTH)


class ConfigPanel(QWidget):
    """Plain widget that knows nothing about docking.

    Subclasses set `title` and populate `self.body` (a `QVBoxLayout`).
    """

    title: ClassVar[str] = "Panel"
    min_width: ClassVar[int] = 320

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(self.min_width)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(8, 8, 8, 8)
        self.body.setSpacing(6)
