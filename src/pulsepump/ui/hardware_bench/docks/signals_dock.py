"""SignalsView — tree of every live signal; drag source for plots.

Used as the QMainWindow central widget so the signal catalog is always
visible. The file is named ``signals_dock`` for backwards compatibility
with imports; the exported class is now :class:`SignalsView` (a plain
QWidget). The ``SignalsDock`` alias remains for any external callers.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....hardware.bench.controller import BenchController

SIGNAL_MIME = "application/x-pulsepump-signal"


class _SignalTree(QTreeWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Signal", "Latest", "Units"])
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        header = self.header()
        header.setStretchLastSection(False)
        header.resizeSection(0, 240)
        header.resizeSection(1, 100)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        item = self.currentItem()
        if item is None or item.parent() is None:
            return
        signal_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not signal_id:
            return
        mime = QMimeData()
        mime.setData(SIGNAL_MIME, signal_id.encode("utf-8"))
        mime.setText(signal_id)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class SignalsView(QWidget):
    """Tree of registered signals grouped by device.

    Drag a leaf onto a :class:`PlotDock` to add a trace.
    """

    def __init__(self, controller: BenchController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._tree = _SignalTree(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)

        self._device_items: dict[str, QTreeWidgetItem] = {}
        self._signal_items: dict[str, QTreeWidgetItem] = {}

        registry = controller.signals
        registry.signal_added.connect(self._on_signal_added)
        registry.signal_removed.connect(self._on_signal_removed)
        registry.samples_appended.connect(self._on_sample)

    def _on_signal_added(self, signal_id: str) -> None:
        desc = self._controller.signals.descriptor(signal_id)
        if desc is None:
            return
        dev_item = self._device_items.get(desc.device_id)
        if dev_item is None:
            dev_item = QTreeWidgetItem([desc.device_id, "", ""])
            self._tree.addTopLevelItem(dev_item)
            dev_item.setExpanded(True)
            self._device_items[desc.device_id] = dev_item
        leaf = QTreeWidgetItem([desc.name, "", desc.units])
        leaf.setData(0, Qt.ItemDataRole.UserRole, signal_id)
        leaf.setToolTip(0, f"{signal_id}\n{desc.description}")
        dev_item.addChild(leaf)
        self._signal_items[signal_id] = leaf

    def _on_signal_removed(self, signal_id: str) -> None:
        leaf = self._signal_items.pop(signal_id, None)
        if leaf is None:
            return
        parent = leaf.parent()
        if parent is not None:
            parent.removeChild(leaf)
            if parent.childCount() == 0:
                dev_id = next((k for k, v in self._device_items.items() if v is parent), None)
                if dev_id is not None:
                    self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(parent))
                    del self._device_items[dev_id]

    def _on_sample(self, signal_id: str) -> None:
        leaf = self._signal_items.get(signal_id)
        if leaf is None:
            return
        val = self._controller.signals.latest(signal_id)
        if val is None:
            return
        leaf.setText(1, f"{val:.3g}")


# Back-compat alias — older code referenced SignalsDock.
SignalsDock = SignalsView
