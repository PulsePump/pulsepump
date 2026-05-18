"""PyQtGraph plot with two scrolling ring-buffered traces."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Slot

from pulsepump.core import pressure


class PlotView(pg.PlotWidget):
    def __init__(self, redraw_hz: int = 30, parent=None) -> None:
        super().__init__(parent)
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("bottom", "t", units="s")
        self.setLabel("left", "Pressure", units=pressure.units())
        self.legend = self.addLegend()

        self._sample_rate: int = 500
        self._time_width_s: float = 5.0
        self.n = 0
        self.t = np.zeros(0, dtype=np.float64)
        self.v0 = np.zeros(0, dtype=np.float32)
        self.v1 = np.zeros(0, dtype=np.float32)
        self.idx = 0
        self.filled = 0
        self._resize_buffer()

        self.curve0 = self.plot(pen=pg.mkPen("#1f77b4", width=2), name="P1 (GP26)")
        self.curve1 = self.plot(pen=pg.mkPen("#d62728", width=2), name="P2 (GP27)")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.redraw)
        self.timer.start(1000 // redraw_hz)

    def _resize_buffer(self) -> None:
        new_n = max(int(self._sample_rate * self._time_width_s * 1.2), 200)
        self.n = new_n
        self.t = np.zeros(self.n, dtype=np.float64)
        self.v0 = np.zeros(self.n, dtype=np.float32)
        self.v1 = np.zeros(self.n, dtype=np.float32)
        self.idx = 0
        self.filled = 0

    @Slot(int)
    def set_sample_rate(self, hz: int) -> None:
        self._sample_rate = hz
        self._resize_buffer()

    @Slot(float)
    def set_time_width(self, seconds: float) -> None:
        self._time_width_s = seconds
        self._resize_buffer()

    @Slot(int, bool)
    def set_channel_visible(self, channel: int, visible: bool) -> None:
        (self.curve0 if channel == 1 else self.curve1).setVisible(visible)

    @Slot(int, int, int)
    def append(self, t_us: int, v0: int, v1: int) -> None:
        i = self.idx
        self.t[i] = t_us / 1_000_000.0
        self.v0[i] = v0
        self.v1[i] = v1
        self.idx = (i + 1) % self.n
        if self.filled < self.n:
            self.filled += 1

    def redraw(self) -> None:
        if self.filled == 0:
            return
        if self.filled < self.n:
            t = self.t[: self.filled]
            v0 = self.v0[: self.filled]
            v1 = self.v1[: self.filled]
        else:
            order = np.r_[self.idx : self.n, 0 : self.idx]
            t = self.t[order]
            v0 = self.v0[order]
            v1 = self.v1[order]
        self.curve0.setData(t, pressure.counts_to_pressure_arr(v0))
        self.curve1.setData(t, pressure.counts_to_pressure_arr(v1))
        self.getPlotItem().setXRange(t[-1] - self._time_width_s, t[-1], padding=0)

    def refresh_units(self) -> None:
        """Re-pull the units string from pressure config and update the y-axis label."""
        self.setLabel("left", "Pressure", units=pressure.units())

    def set_channel_pin(self, channel: int, gp: int) -> None:
        """Update the legend label for a channel (1 or 2) to reflect its GP pin."""
        curve = self.curve0 if channel == 1 else self.curve1
        name = f"P{channel} (GP{gp})"
        self.legend.removeItem(curve)
        curve.opts["name"] = name
        self.legend.addItem(curve, name)
