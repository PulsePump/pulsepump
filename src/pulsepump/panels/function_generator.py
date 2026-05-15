from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QWidget,
)

from pulsepump import pressure
from pulsepump.waveform import Interpolation, WaveformConfig, WaveformType

from .base import FIELD_WIDTH, ConfigPanel, apply_field_width

_SETTINGS_ORG = "pulsepump"
_SETTINGS_APP = "pulsepump"
_TYPE_KEY = "funcgen/type"
_BPM_KEY = "funcgen/bpm"
_AMP_KEY = "funcgen/amplitude"
_OFFSET_KEY = "funcgen/offset"
_DUTY_KEY = "funcgen/duty"
_SYMMETRY_KEY = "funcgen/symmetry"
_PHASE_KEY = "funcgen/phase"
_SAMPLE_RATE_KEY = "funcgen/sampleRateHz"
_INTERP_KEY = "funcgen/interpolation"

_DEBOUNCE_MS = 250

_DEFAULT_TYPE = WaveformType.SINE
_DEFAULT_BPM = 60.0
_DEFAULT_AMPLITUDE = 20.0
_DEFAULT_OFFSET = 80.0
_DEFAULT_DUTY = 0.5
_DEFAULT_SYMMETRY = 0.5
_DEFAULT_PHASE = 0.0
_DEFAULT_SAMPLE_RATE = 1000.0
_DEFAULT_INTERPOLATION = Interpolation.ZERO_ORDER_HOLD

_INTERPOLATION_LABELS: dict[Interpolation, str] = {
    Interpolation.ZERO_ORDER_HOLD: "Zero-order hold",
    Interpolation.FIRST_ORDER_HOLD: "First-order hold",
}

_WAVEFORM_ORDER: tuple[WaveformType, ...] = (
    WaveformType.SINE,
    WaveformType.SQUARE,
    WaveformType.TRIANGLE,
    WaveformType.SAWTOOTH,
    WaveformType.PULSE,
    WaveformType.CONSTANT,
)

_WAVEFORM_LABELS: dict[WaveformType, str] = {
    WaveformType.SINE: "Sine",
    WaveformType.SQUARE: "Square",
    WaveformType.TRIANGLE: "Triangle",
    WaveformType.SAWTOOTH: "Sawtooth",
    WaveformType.PULSE: "Pulse",
    WaveformType.CONSTANT: "Constant (DC)",
}


def _load_float(settings: QSettings, key: str, default: float) -> float:
    raw = settings.value(key, default)
    try:
        return float(str(raw))
    except TypeError, ValueError:
        return default


def _load_str(settings: QSettings, key: str, default: str) -> str:
    raw = settings.value(key, default)
    return default if raw is None else str(raw)


def _load_type(settings: QSettings) -> WaveformType:
    raw = _load_str(settings, _TYPE_KEY, _DEFAULT_TYPE.value)
    try:
        return WaveformType(raw)
    except ValueError:
        return _DEFAULT_TYPE


def _load_interpolation(settings: QSettings) -> Interpolation:
    raw = _load_str(settings, _INTERP_KEY, _DEFAULT_INTERPOLATION.value)
    try:
        return Interpolation(raw)
    except ValueError:
        return _DEFAULT_INTERPOLATION


class FunctionGeneratorPanel(ConfigPanel):
    title = "Function generator"

    waveformChanged = Signal(object)  # carries a WaveformConfig

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        wtype = _load_type(self._settings)
        bpm = _load_float(self._settings, _BPM_KEY, _DEFAULT_BPM)
        amplitude = _load_float(self._settings, _AMP_KEY, _DEFAULT_AMPLITUDE)
        offset = _load_float(self._settings, _OFFSET_KEY, _DEFAULT_OFFSET)
        duty = _load_float(self._settings, _DUTY_KEY, _DEFAULT_DUTY)
        symmetry = _load_float(self._settings, _SYMMETRY_KEY, _DEFAULT_SYMMETRY)
        phase = _load_float(self._settings, _PHASE_KEY, _DEFAULT_PHASE)
        sample_rate = _load_float(self._settings, _SAMPLE_RATE_KEY, _DEFAULT_SAMPLE_RATE)
        interpolation = _load_interpolation(self._settings)

        waveform_group = QGroupBox(self)
        waveform_form = QFormLayout(waveform_group)
        waveform_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.type_combo = QComboBox(waveform_group)
        for w in _WAVEFORM_ORDER:
            self.type_combo.addItem(_WAVEFORM_LABELS[w], w.value)
        idx = self.type_combo.findData(wtype.value)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        apply_field_width(self.type_combo)
        waveform_form.addRow("Waveform", self.type_combo)
        self.body.addWidget(waveform_group)

        params_group = QGroupBox("Parameters", self)
        self._params_form = QFormLayout(params_group)
        self._params_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.bpm_spin = self._spin(
            value=bpm, minimum=1.0, maximum=600.0, step=1.0, decimals=1, suffix=" BPM"
        )
        self.period_label = QLabel("", params_group)
        self.sample_rate_spin = self._spin(
            value=sample_rate, minimum=10.0, maximum=20_000.0, step=100.0, decimals=0, suffix=" Hz"
        )
        self.sample_rate_spin.setToolTip(
            "Setpoint update rate the fluid sim will consume (samples per second)."
        )

        self.amp_spin = self._spin(
            value=amplitude, minimum=0.0, maximum=10_000.0, step=1.0, decimals=2
        )
        self.offset_spin = self._spin(
            value=offset, minimum=-10_000.0, maximum=10_000.0, step=1.0, decimals=2
        )
        self.phase_spin = self._spin(
            value=phase, minimum=0.0, maximum=1.0, step=0.05, decimals=3, suffix=" cyc"
        )
        self.phase_spin.setWrapping(True)
        self.duty_spin = self._spin(value=duty, minimum=0.01, maximum=0.99, step=0.05, decimals=2)
        self.duty_spin.setToolTip("Fraction of the cycle where the output is high.")
        self.symmetry_spin = self._spin(
            value=symmetry, minimum=0.0, maximum=1.0, step=0.05, decimals=2
        )
        self.symmetry_spin.setToolTip(
            "Triangle: 0.5 is symmetric, 1.0 a rising ramp, 0.0 a falling ramp. "
            "Sawtooth: > 0.5 rises, ≤ 0.5 falls."
        )

        self._params_form.addRow("Rate", self.bpm_spin)
        self._params_form.addRow("Period", self.period_label)
        self._params_form.addRow("Sample rate", self.sample_rate_spin)
        self._params_form.addRow("Amplitude", self.amp_spin)
        self._params_form.addRow("Offset", self.offset_spin)
        self._params_form.addRow("Phase", self.phase_spin)
        self._params_form.addRow("Duty cycle", self.duty_spin)
        self._params_form.addRow("Symmetry", self.symmetry_spin)

        self.body.addWidget(params_group)

        preview_group = QGroupBox("Preview", self)
        preview_form = QFormLayout(preview_group)
        preview_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.interp_combo = QComboBox(preview_group)
        for interp in (Interpolation.ZERO_ORDER_HOLD, Interpolation.FIRST_ORDER_HOLD):
            self.interp_combo.addItem(_INTERPOLATION_LABELS[interp], interp.value)
        idx = self.interp_combo.findData(interpolation.value)
        if idx >= 0:
            self.interp_combo.setCurrentIndex(idx)
        apply_field_width(self.interp_combo)
        preview_form.addRow("Interpolation", self.interp_combo)
        self.body.addWidget(preview_group)

        self.body.addStretch(1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._commit)

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.bpm_spin.valueChanged.connect(self._on_bpm_changed)
        self.sample_rate_spin.valueChanged.connect(self._schedule_commit)
        self.amp_spin.valueChanged.connect(self._schedule_commit)
        self.offset_spin.valueChanged.connect(self._schedule_commit)
        self.phase_spin.valueChanged.connect(self._schedule_commit)
        self.duty_spin.valueChanged.connect(self._schedule_commit)
        self.symmetry_spin.valueChanged.connect(self._schedule_commit)
        self.interp_combo.currentIndexChanged.connect(self._schedule_commit)

        self._refresh_period_label()
        self._refresh_shape_visibility()
        self.refresh_units()

    def _spin(
        self,
        *,
        value: float,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        if suffix:
            spin.setSuffix(suffix)
        spin.setAccelerated(True)
        spin.setKeyboardTracking(False)
        spin.setFixedWidth(FIELD_WIDTH)
        spin.setValue(value)
        return spin

    def current_type(self) -> WaveformType:
        data = self.type_combo.currentData()
        try:
            return WaveformType(data)
        except ValueError:
            return _DEFAULT_TYPE

    def current_interpolation(self) -> Interpolation:
        data = self.interp_combo.currentData()
        try:
            return Interpolation(data)
        except ValueError:
            return _DEFAULT_INTERPOLATION

    def current_config(self) -> WaveformConfig:
        return WaveformConfig(
            type=self.current_type(),
            bpm=self.bpm_spin.value(),
            amplitude=self.amp_spin.value(),
            offset=self.offset_spin.value(),
            duty=self.duty_spin.value(),
            symmetry=self.symmetry_spin.value(),
            phase=self.phase_spin.value(),
            sample_rate_hz=self.sample_rate_spin.value(),
            interpolation=self.current_interpolation(),
        )

    def refresh_units(self) -> None:
        suffix = f" {pressure.units()}"
        self.amp_spin.setSuffix(suffix)
        self.offset_spin.setSuffix(suffix)

    def _on_type_changed(self, _idx: int) -> None:
        self._refresh_shape_visibility()
        self._schedule_commit()

    def _on_bpm_changed(self, _value: float) -> None:
        self._refresh_period_label()
        self._schedule_commit()

    def _schedule_commit(self, *_args: object) -> None:
        self._debounce.start()

    def _refresh_period_label(self) -> None:
        period = 60.0 / max(self.bpm_spin.value(), 1e-6)
        self.period_label.setText(f"{period:.3f} s")

    def _refresh_shape_visibility(self) -> None:
        wtype = self.current_type()
        show_duty = wtype in (WaveformType.SQUARE, WaveformType.PULSE)
        show_symmetry = wtype in (WaveformType.TRIANGLE, WaveformType.SAWTOOTH)
        self._params_form.setRowVisible(self.duty_spin, show_duty)
        self._params_form.setRowVisible(self.symmetry_spin, show_symmetry)

    def _commit(self) -> None:
        config = self.current_config()
        self._settings.setValue(_TYPE_KEY, config.type.value)
        self._settings.setValue(_BPM_KEY, config.bpm)
        self._settings.setValue(_AMP_KEY, config.amplitude)
        self._settings.setValue(_OFFSET_KEY, config.offset)
        self._settings.setValue(_DUTY_KEY, config.duty)
        self._settings.setValue(_SYMMETRY_KEY, config.symmetry)
        self._settings.setValue(_PHASE_KEY, config.phase)
        self._settings.setValue(_SAMPLE_RATE_KEY, config.sample_rate_hz)
        self._settings.setValue(_INTERP_KEY, config.interpolation.value)
        self.waveformChanged.emit(config)
