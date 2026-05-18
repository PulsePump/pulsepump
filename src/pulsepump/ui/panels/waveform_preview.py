from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget

from pulsepump.core import pressure
from pulsepump.core.waveform import Interpolation, WaveformConfig, sample_one_cycle

from .base import ConfigPanel

# Cap rendering work so high sample rates with low BPM don't drag the UI.
_MAX_PREVIEW_SAMPLES = 5000

_MODE_FUNCTION = "Function"
_MODE_OPENBF = "openBF"


class WaveformPreviewPanel(ConfigPanel):
    title = "Waveform preview"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)

        self._active_mode: str = _MODE_FUNCTION

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

    @Slot(str)
    def set_mode(self, mode: str) -> None:
        self._active_mode = mode
        self.curve.clear()
        self.markers.clear()

    @Slot(object)
    def set_waveform(self, config: WaveformConfig) -> None:
        if self._active_mode != _MODE_FUNCTION:
            return
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

    @Slot(object, object)
    def set_samples(self, t: np.ndarray, y: np.ndarray) -> None:
        if self._active_mode != _MODE_OPENBF:
            return
        if len(t) == 0:
            self.curve.setData(x=[], y=[])
            self.markers.setData(x=[], y=[])
            return
        self.curve.setData(t, y, stepMode=None, pen=self._pen)
        self.markers.clear()
        if len(t) >= 2:
            self.plot.getPlotItem().setXRange(float(t[0]), float(t[-1]), padding=0.02)

    @Slot()
    def refresh_units(self) -> None:
        self.plot.setLabel("left", "Pressure", units=pressure.units())
