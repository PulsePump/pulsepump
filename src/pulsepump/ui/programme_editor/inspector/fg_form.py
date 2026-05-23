from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QWidget,
)

from pulsepump.core.waveform import WaveformType

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
WAVEFORM_ORDER = [
    WaveformType.CONSTANT,
    WaveformType.SINE,
    WaveformType.SQUARE,
    WaveformType.TRIANGLE,
    WaveformType.SAWTOOTH,
    WaveformType.PULSE,
]


class FunctionGeneratorForm(QWidget):
    """All function-generator-specific parameter controls."""

    changed = Signal()
    layout_changed = Signal()  # Visibility of fields changed (e.g. on type switch)

    def __init__(self, label_min_width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._syncing = False

        self._type_combo = QComboBox()
        for wt in WAVEFORM_ORDER:
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

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnMinimumWidth(0, label_min_width)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        _L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        _R = Qt.AlignmentFlag.AlignVCenter

        r = 0
        grid.addWidget(QLabel("Waveform"), r, 0, alignment=_L)
        grid.addWidget(self._type_combo, r, 1, alignment=_R)
        r += 1
        self._amplitude_label = QLabel("Amplitude")
        grid.addWidget(self._amplitude_label, r, 0, alignment=_L)
        grid.addWidget(self._amplitude_spin, r, 1, alignment=_R)
        r += 1
        self._offset_label = QLabel("Offset")
        grid.addWidget(self._offset_label, r, 0, alignment=_L)
        grid.addWidget(self._offset_spin, r, 1, alignment=_R)
        r += 1
        self._bpm_label = QLabel("BPM")
        grid.addWidget(self._bpm_label, r, 0, alignment=_L)
        grid.addWidget(self._bpm_spin, r, 1, alignment=_R)
        r += 1
        self._duty_label = QLabel("Duty")
        grid.addWidget(self._duty_label, r, 0, alignment=_L)
        grid.addWidget(self._duty_spin, r, 1, alignment=_R)
        r += 1
        self._symmetry_label = QLabel("Symmetry")
        grid.addWidget(self._symmetry_label, r, 0, alignment=_L)
        grid.addWidget(self._symmetry_spin, r, 1, alignment=_R)
        r += 1
        self._phase_label = QLabel("Phase")
        grid.addWidget(self._phase_label, r, 0, alignment=_L)
        grid.addWidget(self._phase_spin, r, 1, alignment=_R)
        self.setLayout(grid)

        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        for spin in (
            self._amplitude_spin,
            self._offset_spin,
            self._bpm_spin,
            self._duty_spin,
            self._symmetry_spin,
            self._phase_spin,
        ):
            spin.valueChanged.connect(self._emit_changed)

    def _emit_changed(self) -> None:
        if not self._syncing:
            self.changed.emit()

    def _on_type_changed(self) -> None:
        self._apply_visibility(self.current_type())
        self.layout_changed.emit()
        self._emit_changed()

    def current_type(self) -> WaveformType:
        return self._type_combo.currentData()

    def _apply_visibility(self, wt: WaveformType) -> None:
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

    def set_values(
        self,
        type_: WaveformType,
        amplitude: float,
        offset: float,
        bpm: float,
        duty: float,
        symmetry: float,
        phase: float,
    ) -> None:
        self._syncing = True
        self._type_combo.setCurrentIndex(WAVEFORM_ORDER.index(type_))
        self._amplitude_spin.setValue(amplitude)
        self._offset_spin.setValue(offset)
        self._bpm_spin.setValue(bpm)
        self._duty_spin.setValue(duty)
        self._symmetry_spin.setValue(symmetry)
        self._phase_spin.setValue(phase)
        self._apply_visibility(type_)
        self._syncing = False

    def values(self) -> tuple[WaveformType, float, float, float, float, float, float]:
        return (
            self.current_type(),
            self._amplitude_spin.value(),
            self._offset_spin.value(),
            self._bpm_spin.value(),
            self._duty_spin.value(),
            self._symmetry_spin.value(),
            self._phase_spin.value(),
        )

    def set_pressure_units(self, units: str) -> None:
        suffix = f" {units}" if units else ""
        self._amplitude_spin.setSuffix(suffix)
        self._offset_spin.setSuffix(suffix)

    def set_editable(self, editable: bool) -> None:
        for w in (
            self._type_combo,
            self._amplitude_spin,
            self._offset_spin,
            self._bpm_spin,
            self._duty_spin,
            self._symmetry_spin,
            self._phase_spin,
        ):
            w.setEnabled(editable)
