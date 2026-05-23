"""PlotDock — pyqtgraph plot that accepts signal drops; all share x-axis."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ....hardware.bench.signals import SignalRegistry
from .signals_dock import SIGNAL_MIME

_COLOURS = ["#4C9BE8", "#E8854C", "#4CE87A", "#E84C9B", "#C8E84C", "#8B4CE8"]


class _DropPlotWidget(pg.PlotWidget):
    def __init__(self, dock: PlotDock) -> None:
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        super().__init__()
        self._dock = dock
        self.setAcceptDrops(True)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("bottom", "Time", units="s")

    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:
        if ev.mimeData().hasFormat(SIGNAL_MIME):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(SIGNAL_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasFormat(SIGNAL_MIME):
            event.ignore()
            return
        signal_id = bytes(event.mimeData().data(SIGNAL_MIME).data()).decode("utf-8")
        self._dock.add_trace(signal_id)
        event.acceptProposedAction()


class PlotDock(QDockWidget):
    """One plot. Drag signals from the SignalsDock to add traces.

    All :class:`PlotDock` instances in the same window share the x-axis: when
    a new dock is created, the window calls :meth:`link_x_to` to bind it to
    the first plot's ViewBox.
    """

    status_message = Signal(str)
    _counter = 0

    def __init__(self, registry: SignalRegistry, parent: QWidget | None = None) -> None:
        PlotDock._counter += 1
        self._index = PlotDock._counter
        super().__init__(f"Plot {self._index}", parent)
        self.setObjectName(f"HardwareBench.PlotDock.{self._index}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._registry = registry
        self._plot = _DropPlotWidget(self)
        self._traces: dict[str, pg.PlotDataItem] = {}
        self._next_colour = 0

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        top = QHBoxLayout()
        top.setContentsMargins(4, 0, 4, 0)
        self._hint = QLabel("Drag signals here…")
        self._hint.setStyleSheet("color: #888;")
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(64)
        clear_btn.clicked.connect(self.clear_traces)
        top.addWidget(self._hint, 1)
        top.addWidget(clear_btn)
        outer.addLayout(top)
        outer.addWidget(self._plot, 1)
        self.setWidget(body)

        self._refresh = QTimer(self)
        self._refresh.setInterval(33)  # ~30 Hz
        self._refresh.timeout.connect(self._redraw)
        self._refresh.start()

        registry.signal_removed.connect(self._on_signal_removed)

    # -- public API -------------------------------------------------------

    def plot_widget(self) -> pg.PlotWidget:
        return self._plot

    def link_x_to(self, other: PlotDock) -> None:
        if other is self:
            return
        self._plot.setXLink(other.plot_widget())

    def add_trace(self, signal_id: str) -> None:
        if signal_id in self._traces:
            return
        desc = self._registry.descriptor(signal_id)
        if desc is None:
            return
        colour = _COLOURS[self._next_colour % len(_COLOURS)]
        self._next_colour += 1
        item = self._plot.plot(
            [],
            [],
            pen=pg.mkPen(colour, width=1.5),
            name=signal_id,
        )
        self._traces[signal_id] = item
        plot_item = self._plot.plotItem
        if plot_item is not None and plot_item.legend is None:
            self._plot.addLegend(offset=(8, 8))
        self._hint.setText(f"{len(self._traces)} trace(s)")
        self.status_message.emit(f"Plot {self._index}: added {signal_id}")

    def clear_traces(self) -> None:
        n = len(self._traces)
        for sid in list(self._traces.keys()):
            self._remove_trace(sid)
        self._hint.setText("Drag signals here…")
        if n:
            self.status_message.emit(f"Plot {self._index}: cleared {n} trace(s)")

    def _remove_trace(self, signal_id: str) -> None:
        item = self._traces.pop(signal_id, None)
        if item is not None:
            self._plot.removeItem(item)

    def _on_signal_removed(self, signal_id: str) -> None:
        self._remove_trace(signal_id)

    def _redraw(self) -> None:
        if not self._traces:
            return
        for sid, item in self._traces.items():
            snap = self._registry.snapshot(sid)
            if snap is None:
                continue
            t, v = snap
            if t.size:
                item.setData(t, v)
