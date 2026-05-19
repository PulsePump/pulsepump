from __future__ import annotations

from typing import cast

import numpy as np
import pyqtgraph as pg
import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pulsepump.core.programme import (
    Block,
    FunctionGeneratorSource,
    PressureUnits,
    Programme,
    decode_samples,
    encode_samples,
)
from pulsepump.core.waveform import Interpolation, WaveformType, sample_one_cycle

from .document import Document

_COLOURS = ["#4C9BE8", "#E8854C", "#4CE87A", "#E84C9B", "#C8E84C"]


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
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch()

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

    def set_programme(self, programme: Programme) -> None:
        self._pressure_units = programme.pressure_units
        self.setLabel("left", "Pressure", units=programme.pressure_units)
        self._clear_items()

        t_cursor = 0.0
        dt = 1.0 / programme.sampling_rate_hz
        for i, block in enumerate(programme.blocks):
            cycle = decode_samples(block.samples_f32_b64)
            full = np.tile(cycle, block.repeat_count)
            n_total = full.size
            t_vals = t_cursor + np.arange(n_total) * dt
            step = max(1, n_total // 2000)
            item = self.plot(
                t_vals[::step],
                full[::step],
                pen=pg.mkPen(_COLOURS[i % len(_COLOURS)], width=1.5),
            )
            self._items.append(item)
            sep = pg.InfiniteLine(
                pos=t_cursor,
                angle=90,
                pen=pg.mkPen("#888888", width=1, style=Qt.PenStyle.DashLine),
            )
            self.addItem(sep)
            self._items.append(sep)
            t_cursor += n_total * dt

        self._total_duration = t_cursor
        self.getPlotItem().setTitle("")
        self.getViewBox().setLimits(xMin=0.0, xMax=t_cursor)
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


# Which parameters each waveform type exposes (beyond name/repeat/offset/bpm)
_TYPE_HAS_AMPLITUDE = {
    WaveformType.CONSTANT: False,
    WaveformType.SINE: True,
    WaveformType.SQUARE: True,
    WaveformType.TRIANGLE: True,
    WaveformType.SAWTOOTH: True,
    WaveformType.PULSE: True,
}
_TYPE_HAS_BPM = {
    WaveformType.CONSTANT: False,
    WaveformType.SINE: True,
    WaveformType.SQUARE: True,
    WaveformType.TRIANGLE: True,
    WaveformType.SAWTOOTH: True,
    WaveformType.PULSE: True,
}
_TYPE_HAS_DUTY = {
    WaveformType.CONSTANT: False,
    WaveformType.SINE: False,
    WaveformType.SQUARE: True,
    WaveformType.TRIANGLE: False,
    WaveformType.SAWTOOTH: False,
    WaveformType.PULSE: True,
}
_TYPE_HAS_SYMMETRY = {
    WaveformType.CONSTANT: False,
    WaveformType.SINE: False,
    WaveformType.SQUARE: False,
    WaveformType.TRIANGLE: True,
    WaveformType.SAWTOOTH: True,
    WaveformType.PULSE: False,
}
_TYPE_HAS_PHASE = {
    WaveformType.CONSTANT: False,
    WaveformType.SINE: True,
    WaveformType.SQUARE: True,
    WaveformType.TRIANGLE: True,
    WaveformType.SAWTOOTH: True,
    WaveformType.PULSE: True,
}

_WAVEFORM_LABELS = {
    WaveformType.CONSTANT: "Constant",
    WaveformType.SINE: "Sine",
    WaveformType.SQUARE: "Square",
    WaveformType.TRIANGLE: "Triangle",
    WaveformType.SAWTOOTH: "Sawtooth",
    WaveformType.PULSE: "Pulse",
}
_WAVEFORM_ORDER = [
    WaveformType.CONSTANT,
    WaveformType.SINE,
    WaveformType.SQUARE,
    WaveformType.TRIANGLE,
    WaveformType.SAWTOOTH,
    WaveformType.PULSE,
]


class InspectorPanel(QWidget):
    programme_changed = Signal()  # programme-level fields (name, sample rate) edited
    block_changed = Signal()  # per-block fields edited

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._syncing = False
        self._block: Block | None = None

        # --- placeholder ---
        self._placeholder = QLabel("No block selected")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: gray;")

        # --- programme-level controls ---
        self._programme_name_edit = QLineEdit()
        self._programme_name_edit.setPlaceholderText("Untitled")

        self._sample_rate_spin = QDoubleSpinBox()
        self._sample_rate_spin.setMinimum(1.0)
        self._sample_rate_spin.setMaximum(100000.0)
        self._sample_rate_spin.setDecimals(1)
        self._sample_rate_spin.setSingleStep(10.0)
        self._sample_rate_spin.setSuffix(" Hz")

        self._pressure_units_combo = QComboBox()
        for u in ("Pa", "kPa", "mmHg", "psi", "bar"):
            self._pressure_units_combo.addItem(u)

        # --- per-block controls ---
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Untitled block")

        self._repeat_spin = QSpinBox()
        self._repeat_spin.setMinimum(1)
        self._repeat_spin.setMaximum(99999)

        self._type_combo = QComboBox()
        for wt in _WAVEFORM_ORDER:
            self._type_combo.addItem(_WAVEFORM_LABELS[wt], userData=wt)

        self._amplitude_spin = QDoubleSpinBox()
        self._amplitude_spin.setMinimum(-1e6)
        self._amplitude_spin.setMaximum(1e6)
        self._amplitude_spin.setDecimals(3)
        self._amplitude_spin.setSingleStep(1.0)

        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setMinimum(-1e6)
        self._offset_spin.setMaximum(1e6)
        self._offset_spin.setDecimals(3)
        self._offset_spin.setSingleStep(1.0)

        self._bpm_spin = QDoubleSpinBox()
        self._bpm_spin.setMinimum(1.0)
        self._bpm_spin.setMaximum(1000.0)
        self._bpm_spin.setDecimals(2)
        self._bpm_spin.setSingleStep(1.0)

        self._duty_spin = QDoubleSpinBox()
        self._duty_spin.setMinimum(0.01)
        self._duty_spin.setMaximum(0.99)
        self._duty_spin.setDecimals(3)
        self._duty_spin.setSingleStep(0.05)

        self._symmetry_spin = QDoubleSpinBox()
        self._symmetry_spin.setMinimum(0.01)
        self._symmetry_spin.setMaximum(0.99)
        self._symmetry_spin.setDecimals(3)
        self._symmetry_spin.setSingleStep(0.05)

        self._phase_spin = QDoubleSpinBox()
        self._phase_spin.setMinimum(0.0)
        self._phase_spin.setMaximum(0.999)
        self._phase_spin.setDecimals(3)
        self._phase_spin.setSingleStep(0.05)

        fm = QFontMetrics(self.font())
        label_w = max(
            fm.horizontalAdvance(t)
            for t in (
                "Name",
                "Sample rate",
                "Pressure units",
                "Repeat count",
                "Type",
                "Amplitude",
                "Offset",
                "BPM",
                "Duty",
                "Symmetry",
                "Phase",
            )
        )
        label_w += 4

        _L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        _R = Qt.AlignmentFlag.AlignVCenter

        def _make_group_grid() -> QGridLayout:
            g = QGridLayout()
            g.setContentsMargins(8, 8, 8, 8)
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(6)
            g.setColumnMinimumWidth(0, label_w)
            g.setColumnStretch(0, 0)
            g.setColumnStretch(1, 1)
            return g

        programme_grid = _make_group_grid()
        r = 0
        programme_grid.addWidget(QLabel("Name"), r, 0, alignment=_L)
        programme_grid.addWidget(self._programme_name_edit, r, 1, alignment=_R)
        r += 1
        programme_grid.addWidget(QLabel("Sample rate"), r, 0, alignment=_L)
        programme_grid.addWidget(self._sample_rate_spin, r, 1, alignment=_R)
        r += 1
        programme_grid.addWidget(QLabel("Pressure units"), r, 0, alignment=_L)
        programme_grid.addWidget(self._pressure_units_combo, r, 1, alignment=_R)
        programme_box = QGroupBox("Programme")
        programme_box.setLayout(programme_grid)

        general_grid = _make_group_grid()
        r = 0
        general_grid.addWidget(QLabel("Name"), r, 0, alignment=_L)
        general_grid.addWidget(self._name_edit, r, 1, alignment=_R)
        r += 1
        general_grid.addWidget(QLabel("Repeat count"), r, 0, alignment=_L)
        general_grid.addWidget(self._repeat_spin, r, 1, alignment=_R)
        general_box = QGroupBox("Block")
        general_box.setLayout(general_grid)

        waveform_grid = _make_group_grid()
        r = 0
        self._type_label = QLabel("Type")
        waveform_grid.addWidget(self._type_label, r, 0, alignment=_L)
        waveform_grid.addWidget(self._type_combo, r, 1, alignment=_R)
        r += 1
        self._amplitude_label = QLabel("Amplitude")
        waveform_grid.addWidget(self._amplitude_label, r, 0, alignment=_L)
        waveform_grid.addWidget(self._amplitude_spin, r, 1, alignment=_R)
        r += 1
        self._offset_label = QLabel("Offset")
        waveform_grid.addWidget(self._offset_label, r, 0, alignment=_L)
        waveform_grid.addWidget(self._offset_spin, r, 1, alignment=_R)
        r += 1
        self._bpm_label = QLabel("BPM")
        waveform_grid.addWidget(self._bpm_label, r, 0, alignment=_L)
        waveform_grid.addWidget(self._bpm_spin, r, 1, alignment=_R)
        r += 1
        self._duty_label = QLabel("Duty")
        waveform_grid.addWidget(self._duty_label, r, 0, alignment=_L)
        waveform_grid.addWidget(self._duty_spin, r, 1, alignment=_R)
        r += 1
        self._symmetry_label = QLabel("Symmetry")
        waveform_grid.addWidget(self._symmetry_label, r, 0, alignment=_L)
        waveform_grid.addWidget(self._symmetry_spin, r, 1, alignment=_R)
        r += 1
        self._phase_label = QLabel("Phase")
        waveform_grid.addWidget(self._phase_label, r, 0, alignment=_L)
        waveform_grid.addWidget(self._phase_spin, r, 1, alignment=_R)
        waveform_box = QGroupBox("Waveform")
        waveform_box.setLayout(waveform_grid)

        # Programme box is always visible; block/waveform boxes are in a stacked widget
        self._block_container = QWidget()
        block_layout = QVBoxLayout(self._block_container)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(8)
        block_layout.addWidget(general_box)
        block_layout.addWidget(waveform_box)

        form_container = QWidget()
        outer = QVBoxLayout(form_container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(programme_box)
        outer.addWidget(self._block_container)
        outer.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(form_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._form = scroll

        self._stack = QStackedWidget()
        self._stack.addWidget(self._placeholder)  # index 0
        self._stack.addWidget(self._form)  # index 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._stack)

        self._programme_name_edit.textEdited.connect(self._on_programme_field_changed)
        self._sample_rate_spin.valueChanged.connect(self._on_programme_field_changed)
        self._pressure_units_combo.currentTextChanged.connect(self._on_programme_field_changed)
        self._name_edit.textEdited.connect(self._on_block_field_changed)
        self._repeat_spin.valueChanged.connect(self._on_block_field_changed)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._amplitude_spin.valueChanged.connect(self._on_block_field_changed)
        self._offset_spin.valueChanged.connect(self._on_block_field_changed)
        self._bpm_spin.valueChanged.connect(self._on_block_field_changed)
        self._duty_spin.valueChanged.connect(self._on_block_field_changed)
        self._symmetry_spin.valueChanged.connect(self._on_block_field_changed)
        self._phase_spin.valueChanged.connect(self._on_block_field_changed)

    def _current_waveform_type(self) -> WaveformType:
        return self._type_combo.currentData()

    def _apply_type_visibility(self, wt: WaveformType) -> None:
        self._amplitude_label.setVisible(_TYPE_HAS_AMPLITUDE[wt])
        self._amplitude_spin.setVisible(_TYPE_HAS_AMPLITUDE[wt])
        self._bpm_label.setVisible(_TYPE_HAS_BPM[wt])
        self._bpm_spin.setVisible(_TYPE_HAS_BPM[wt])
        self._duty_label.setVisible(_TYPE_HAS_DUTY[wt])
        self._duty_spin.setVisible(_TYPE_HAS_DUTY[wt])
        self._symmetry_label.setVisible(_TYPE_HAS_SYMMETRY[wt])
        self._symmetry_spin.setVisible(_TYPE_HAS_SYMMETRY[wt])
        self._phase_label.setVisible(_TYPE_HAS_PHASE[wt])
        self._phase_spin.setVisible(_TYPE_HAS_PHASE[wt])

    def _on_type_changed(self) -> None:
        if self._syncing:
            return
        self._apply_type_visibility(self._current_waveform_type())
        self._on_block_field_changed()

    def _on_programme_field_changed(self) -> None:
        if self._syncing:
            return
        self.programme_changed.emit()

    def _on_block_field_changed(self) -> None:
        if self._syncing:
            return
        self.block_changed.emit()

    def show_programme(self, programme: Programme) -> None:
        self._syncing = True
        self._programme_name_edit.setText(programme.name)
        self._sample_rate_spin.setValue(programme.sampling_rate_hz)
        idx = self._pressure_units_combo.findText(programme.pressure_units)
        if idx >= 0:
            self._pressure_units_combo.setCurrentIndex(idx)
        self._syncing = False

    def show_block(self, block: Block) -> None:
        self._block = block
        src = block.source
        if not isinstance(src, FunctionGeneratorSource):
            self._block_container.setVisible(False)
            self._stack.setCurrentIndex(1)
            return
        self._syncing = True
        self._name_edit.setText(block.name)
        self._repeat_spin.setValue(block.repeat_count)
        idx = _WAVEFORM_ORDER.index(src.type)
        self._type_combo.setCurrentIndex(idx)
        self._amplitude_spin.setValue(src.amplitude)
        self._offset_spin.setValue(src.offset)
        self._bpm_spin.setValue(src.bpm)
        self._duty_spin.setValue(src.duty)
        self._symmetry_spin.setValue(src.symmetry)
        self._phase_spin.setValue(src.phase)
        self._apply_type_visibility(src.type)
        self._syncing = False
        self._block_container.setVisible(True)
        self._stack.setCurrentIndex(1)

    def show_programme_only(self, programme: Programme) -> None:
        """Show programme fields without a selected block."""
        self.show_programme(programme)
        self._block_container.setVisible(False)
        self._stack.setCurrentIndex(1)

    def clear(self) -> None:
        self._block = None
        self._placeholder.setText("No block selected")
        self._stack.setCurrentIndex(0)

    def current_programme_values(self) -> tuple[str, float, str] | None:
        if self._stack.currentIndex() != 1:
            return None
        return (
            self._programme_name_edit.text(),
            self._sample_rate_spin.value(),
            self._pressure_units_combo.currentText(),
        )

    def current_block_values(
        self,
    ) -> tuple[str, int, WaveformType, float, float, float, float, float, float] | None:
        if self._stack.currentIndex() != 1 or not self._block_container.isVisible():
            return None
        wt = self._current_waveform_type()
        return (
            self._name_edit.text(),
            self._repeat_spin.value(),
            wt,
            self._amplitude_spin.value(),
            self._offset_spin.value(),
            self._bpm_spin.value(),
            self._duty_spin.value(),
            self._symmetry_spin.value(),
            self._phase_spin.value(),
        )


def _make_default_constant_block(sampling_rate_hz: float, name: str = "") -> Block:
    src = FunctionGeneratorSource(
        kind="function_generator",
        type=WaveformType.CONSTANT,
        bpm=60.0,
        amplitude=0.0,
        offset=0.0,
        duty=0.5,
        symmetry=0.5,
        phase=0.0,
        sample_rate_hz=sampling_rate_hz,
        interpolation=Interpolation.FIRST_ORDER_HOLD,
    )
    _, y = sample_one_cycle(src.to_waveform_config())
    return Block(name=name, repeat_count=1, samples_f32_b64=encode_samples(y), source=src)


class ProgrammeEditorWidget(QWidget):
    status_message = Signal(str, int)  # message, timeout_ms (0 = persistent)
    remove_block_enabled = Signal(bool)  # tracks whether remove is currently valid

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self._programme: Programme | None = None
        self._selected_index: int | None = None
        self._syncing = False

        self._block_list = BlockListPanel()
        self._waveform = WaveformView()
        self._inspector = InspectorPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._block_list)
        splitter.addWidget(self._waveform)
        splitter.addWidget(self._inspector)
        splitter.setSizes([200, 500, 260])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self._block_list.block_selected.connect(self._on_block_selected)
        self._block_list.add_block_requested.connect(self.add_block)
        self._block_list.remove_block_requested.connect(self.remove_block)
        self._inspector.programme_changed.connect(self._on_programme_inspector_changed)
        self._inspector.block_changed.connect(self._on_block_inspector_changed)
        document.content_changed.connect(self._on_document_content_changed)

        self._parse_programme()
        self._rebuild_all()

    # --- document sync ---

    def _parse_programme(self) -> None:
        content = self._document.content
        if not content.strip():
            self._programme = None
            return
        try:
            raw = yaml.safe_load(content)
            self._programme = Programme.model_validate(raw)
            n = len(self._programme.blocks)
            self.status_message.emit(f"Loaded {n} block{'s' if n != 1 else ''}", 3000)
        except Exception as exc:
            self._programme = None
            self.status_message.emit(f"Parse error: {exc}", 0)

    def _serialize_programme(self) -> None:
        if self._programme is None:
            return
        self._syncing = True
        self._document.content = yaml.dump(
            self._programme.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        )
        self._syncing = False

    def _on_document_content_changed(self) -> None:
        if self._syncing:
            return
        self._parse_programme()
        self._rebuild_all()

    # --- rebuilds ---

    def _rebuild_all(self) -> None:
        self._selected_index = None
        self._block_list.clear_selection()
        if self._programme is None:
            self._block_list.set_blocks([])
            self._waveform.clear()
            self._inspector.clear()
            return
        self._block_list.set_blocks(self._programme.blocks)
        self._waveform.set_programme(self._programme)
        self._inspector.show_programme_only(self._programme)

    def _rebuild_waveform(self) -> None:
        if self._programme is not None:
            self._waveform.set_programme(self._programme)
            if self._selected_index is not None:
                self._waveform.pan_to_block(self._selected_index, self._programme)

    def _update_block_list_labels(self) -> None:
        if self._programme is not None:
            self._block_list.set_blocks(self._programme.blocks)

    # --- block selection ---

    def _on_block_selected(self, index: int) -> None:
        self._selected_index = index
        if self._programme is None:
            return
        self._waveform.pan_to_block(index, self._programme)
        self._inspector.show_programme(self._programme)
        self._inspector.show_block(self._programme.blocks[index])
        self._emit_remove_enabled()

    # --- inspector edits ---

    def _on_programme_inspector_changed(self) -> None:
        if self._programme is None:
            return
        pvals = self._inspector.current_programme_values()
        if pvals is None:
            return
        prog_name, sample_rate, pressure_units = pvals
        sample_rate_changed = sample_rate != self._programme.sampling_rate_hz
        self._programme.name = prog_name
        self._programme.pressure_units = cast(PressureUnits, pressure_units)
        self._programme.sampling_rate_hz = sample_rate
        if sample_rate_changed:
            # Re-resample every block at the new rate so all block durations stay consistent.
            for i, block in enumerate(self._programme.blocks):
                src = block.source
                if isinstance(src, FunctionGeneratorSource):
                    new_src = src.model_copy(update={"sample_rate_hz": sample_rate})
                    cfg = new_src.to_waveform_config()
                    _, y = sample_one_cycle(cfg)
                    self._programme.blocks[i] = block.model_copy(
                        update={"samples_f32_b64": encode_samples(y), "source": new_src}
                    )
            # Refresh inspector block fields after re-resample.
            if self._selected_index is not None:
                self._inspector.show_block(self._programme.blocks[self._selected_index])
        self._rebuild_waveform()
        self._serialize_programme()
        self.status_message.emit("Modified", 2000)

    def _on_block_inspector_changed(self) -> None:
        if self._programme is None or self._selected_index is None:
            return
        values = self._inspector.current_block_values()
        if values is None:
            return
        name, repeat_count, waveform_type, amplitude, offset, bpm, duty, symmetry, phase = values
        old_block = self._programme.blocks[self._selected_index]
        src = old_block.source
        if not isinstance(src, FunctionGeneratorSource):
            return
        new_src = src.model_copy(
            update={
                "type": waveform_type,
                "amplitude": amplitude,
                "offset": offset,
                "bpm": bpm,
                "duty": duty,
                "symmetry": symmetry,
                "phase": phase,
            }
        )
        cfg = new_src.to_waveform_config()
        _, y = sample_one_cycle(cfg)
        new_block = old_block.model_copy(
            update={
                "name": name,
                "repeat_count": repeat_count,
                "samples_f32_b64": encode_samples(y),
                "source": new_src,
            }
        )
        self._programme.blocks[self._selected_index] = new_block
        self._update_block_list_labels()
        self._block_list.select_block(self._selected_index)
        self._rebuild_waveform()
        self._serialize_programme()
        self.status_message.emit("Modified", 2000)

    # --- public actions (also wired to menu bar) ---

    def add_block(self) -> None:
        if self._programme is None:
            block_name = "Untitled block 1"
            self._programme = Programme(
                name="Untitled",
                sampling_rate_hz=100.0,
                pressure_units="Pa",
                blocks=[_make_default_constant_block(100.0, name=block_name)],
            )
        else:
            n = len(self._programme.blocks) + 1
            block_name = f"Untitled block {n}"
            new_block = _make_default_constant_block(
                self._programme.sampling_rate_hz, name=block_name
            )
            self._programme.blocks.append(new_block)
        new_index = len(self._programme.blocks) - 1
        self._rebuild_all()
        self._block_list.select_block(new_index)
        self._inspector.show_programme(self._programme)
        self._inspector.show_block(self._programme.blocks[new_index])
        self._selected_index = new_index
        self._waveform.pan_to_block(new_index, self._programme)
        self._serialize_programme()
        self.status_message.emit("Block added", 2000)
        self._emit_remove_enabled()

    def remove_block(self, index: int | None = None) -> None:
        if self._programme is None or len(self._programme.blocks) <= 1:
            return
        i = index if index is not None else self._selected_index
        if i is None:
            return
        del self._programme.blocks[i]
        self._selected_index = None
        self._rebuild_all()
        self._serialize_programme()
        self.status_message.emit("Block removed", 2000)
        self._emit_remove_enabled()

    def zoom_to_fit(self) -> None:
        self._waveform.zoom_to_fit()

    def _emit_remove_enabled(self) -> None:
        can_remove = (
            self._programme is not None
            and len(self._programme.blocks) > 1
            and self._selected_index is not None
        )
        self.remove_block_enabled.emit(can_remove)
