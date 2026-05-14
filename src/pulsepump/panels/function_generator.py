"""Function generator panel — placeholder for waveform controls."""

from __future__ import annotations

from .base import ConfigPanel


class FunctionGeneratorPanel(ConfigPanel):
    title = "Function generator"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.body.addStretch(1)
