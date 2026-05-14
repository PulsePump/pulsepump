"""Pressure sensors panel — placeholder for sensor settings."""

from __future__ import annotations

from .base import ConfigPanel


class PressureSensorsPanel(ConfigPanel):
    title = "Pressure sensors"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.body.addStretch(1)
