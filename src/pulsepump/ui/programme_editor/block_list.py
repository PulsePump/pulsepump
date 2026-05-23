from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pulsepump.core.programme import Block


class BlockListPanel(QWidget):
    block_selected = Signal(int)
    add_block_requested = Signal()
    remove_block_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suppressing = False

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.setFrameShape(QListWidget.Shape.NoFrame)

        self._add_btn = QPushButton("Add")
        self._add_btn.clicked.connect(self.add_block_requested)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove_clicked)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(4)
        btn_row.addStretch()
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        layout.addWidget(self._list)
        layout.addLayout(btn_row)

    def set_blocks(self, blocks: list[Block]) -> None:
        self._suppressing = True
        self._list.clear()
        for i, block in enumerate(blocks):
            label = block.name if block.name.strip() else f"Block {i + 1}"
            self._list.addItem(QListWidgetItem(label))
        self._suppressing = False
        self._update_remove_btn()

    def select_block(self, index: int) -> None:
        self._suppressing = True
        self._list.setCurrentRow(index)
        self._suppressing = False
        self._update_remove_btn()

    def clear_selection(self) -> None:
        self._suppressing = True
        self._list.clearSelection()
        self._list.setCurrentRow(-1)
        self._suppressing = False
        self._update_remove_btn()

    def _on_row_changed(self, row: int) -> None:
        self._update_remove_btn()
        if self._suppressing or row < 0:
            return
        self.block_selected.emit(row)

    def _on_remove_clicked(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self.remove_block_requested.emit(row)

    def _update_remove_btn(self) -> None:
        selected = self._list.currentRow() >= 0
        has_more_than_one = self._list.count() > 1
        self._remove_btn.setEnabled(selected and has_more_than_one)
