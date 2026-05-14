"""Sampling panel — placeholder for sample-rate / buffer controls."""

from __future__ import annotations

from .base import ConfigPanel


class SamplingPanel(ConfigPanel):
    title = "Sampling"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.body.addStretch(1)
