from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget

from pulsepump import pressure
from pulsepump.waveform import Interpolation, WaveformConfig, sample_one_cycle

from .base import ConfigPanel

# Cap rendering work so high sample rates with low BPM don't drag the UI.
_MAX_PREVIEW_SAMPLES = 5000


class WaveformPreviewPanel(ConfigPanel):
    title = "Waveform preview"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)

        self.plot = pg.PlotWidget(self)
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel("bottom", "t", units="s")
        self.plot.setLabel("left", "Pressure", units=pressure.units())
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()

        self._pen = pg.mkPen("#1f77b4", width=2)
        self.curve = self.plot.plot(pen=self._pen)
        # Sample markers — small enough to vanish at high sample counts.
        self.markers = self.plot.plot(
            pen=None,
            symbol="o",
            symbolSize=4,
            symbolBrush="#1f77b4",
            symbolPen=None,
        )
        self.body.addWidget(self.plot, stretch=1)

    @Slot(object)
    def set_waveform(self, config: WaveformConfig) -> None:
        n = min(config.samples_per_cycle, _MAX_PREVIEW_SAMPLES)
        t, y = sample_one_cycle(config, n=n)
        # ZOH = staircase via stepMode="right"; FOH = straight lines between samples.
        step_mode = "right" if config.interpolation == Interpolation.ZERO_ORDER_HOLD else None
        self.curve.setData(t, y, stepMode=step_mode, pen=self._pen)
        # Hide markers once the dots would crowd into noise.
        if n <= 200:
            self.markers.setData(t, y)
        else:
            self.markers.clear()
        self.plot.getPlotItem().setXRange(0.0, config.period_s, padding=0.02)

    @Slot()
    def refresh_units(self) -> None:
        self.plot.setLabel("left", "Pressure", units=pressure.units())
