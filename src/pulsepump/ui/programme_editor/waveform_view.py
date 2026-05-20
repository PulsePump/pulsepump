from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from pulsepump.core.programme import Programme, decode_samples

_COLOURS = ["#4C9BE8", "#E8854C", "#4CE87A", "#E84C9B", "#C8E84C"]


class WaveformView(pg.PlotWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        super().__init__(parent)
        self._items: list[pg.PlotDataItem | pg.InfiniteLine] = []
        self._pressure_units: str = "Pa"
        self._total_duration: float = 0.0

        self.setLabel("bottom", "Time", units="s")
        self.showGrid(x=True, y=True, alpha=0.3)
        self.getPlotItem().layout.setContentsMargins(0, 0, 0, 0)

        self.clear()

    def set_programme(
        self,
        programme: Programme,
        unsimulated_indices: Iterable[int] = (),
    ) -> None:
        """Render the programme. Blocks listed in ``unsimulated_indices`` are
        left as a visible gap on the time axis — their duration still advances
        the cursor so neighbours keep correct timing, but no samples are drawn.
        """
        unsimulated = set(unsimulated_indices)
        self._pressure_units = programme.pressure_units
        self.setLabel("left", "Pressure", units=programme.pressure_units)
        self._clear_items()

        t_cursor = 0.0
        dt = 1.0 / programme.sampling_rate_hz
        for i, block in enumerate(programme.blocks):
            cycle = decode_samples(block.samples_f32_b64)
            n_total = cycle.size * block.repeat_count
            block_duration = n_total * dt

            sep = pg.InfiniteLine(
                pos=t_cursor,
                angle=90,
                pen=pg.mkPen("#888888", width=1, style=Qt.PenStyle.DashLine),
            )
            self.addItem(sep)
            self._items.append(sep)

            if i not in unsimulated:
                full = np.tile(cycle, block.repeat_count)
                t_vals = t_cursor + np.arange(n_total) * dt
                step = max(1, n_total // 2000)
                item = self.plot(
                    t_vals[::step],
                    full[::step],
                    pen=pg.mkPen(_COLOURS[i % len(_COLOURS)], width=1.5),
                )
                self._items.append(item)

            t_cursor += block_duration

        # Mean-pressure overlay: only when every block has samples we can
        # trust (i.e. no unsimulated openBF blocks waiting on a run).
        if not unsimulated and programme.blocks:
            total_samples = 0
            weighted_sum = 0.0
            for block in programme.blocks:
                cycle = decode_samples(block.samples_f32_b64)
                weight = cycle.size * block.repeat_count
                weighted_sum += float(cycle.mean()) * weight
                total_samples += weight
            if total_samples > 0:
                mean = weighted_sum / total_samples
                mean_line = pg.InfiniteLine(
                    pos=mean,
                    angle=0,
                    pen=pg.mkPen("#444", width=1, style=Qt.PenStyle.DashLine),
                    label=f"mean: {mean:.1f} {programme.pressure_units}",
                    labelOpts={"position": 0.02, "color": "#444"},
                )
                self.addItem(mean_line)
                self._items.append(mean_line)

        self._total_duration = t_cursor
        self.getPlotItem().setTitle("")
        self.getViewBox().setLimits(xMin=0.0, xMax=max(t_cursor, 1e-9))
        self.autoRange()

    def pan_to_block(self, index: int, programme: Programme) -> None:
        dt = 1.0 / programme.sampling_rate_hz
        t_start = sum(
            decode_samples(programme.blocks[j].samples_f32_b64).size
            * programme.blocks[j].repeat_count
            * dt
            for j in range(index)
        )
        cycle_duration = decode_samples(programme.blocks[index].samples_f32_b64).size * dt
        self.getViewBox().setXRange(t_start, t_start + cycle_duration, padding=0.05)

    def zoom_to_fit(self) -> None:
        self.autoRange()

    def clear(self) -> None:
        self._total_duration = 0.0
        self._clear_items()
        self.getViewBox().setLimits(xMin=None, xMax=None)
        self.getPlotItem().setTitle("Add a block to get started")

    def _clear_items(self) -> None:
        for item in self._items:
            self.removeItem(item)
        self._items.clear()
