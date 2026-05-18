from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QWidget,
)

from .base import FIELD_WIDTH, ConfigPanel, apply_field_width

_SETTINGS_ORG = "pulsepump"
_SETTINGS_APP = "pulsepump"
_RATE_KEY = "sampling/rateHz"
_PIN1_KEY = "sampling/pin1Gp"
_PIN2_KEY = "sampling/pin2Gp"
_DEFAULT_HZ = 500
_MIN_HZ = 50
_MAX_HZ = 5000
_STEP_HZ = 50
_DEBOUNCE_MS = 250
_TIME_WIDTH_KEY = "sampling/timeWidthS"
_DEFAULT_TIME_WIDTH = 5.0
_MIN_TIME_WIDTH = 1.0
_MAX_TIME_WIDTH = 60.0
_VIS1_KEY = "sampling/ch1Visible"
_VIS2_KEY = "sampling/ch2Visible"

# RP2040 ADC-capable GPIOs.
_ADC_PINS: tuple[tuple[str, int], ...] = (
    ("GP26 (ADC0)", 26),
    ("GP27 (ADC1)", 27),
    ("GP28 (ADC2)", 28),
)
_DEFAULT_PIN1 = 26
_DEFAULT_PIN2 = 27


def _load_int(settings: QSettings, key: str, default: int) -> int:
    raw = settings.value(key, default)
    try:
        return int(str(raw))
    except TypeError, ValueError:
        return default


def _load_float(settings: QSettings, key: str, default: float) -> float:
    raw = settings.value(key, default)
    try:
        return float(str(raw))
    except TypeError, ValueError:
        return default


class SamplingPanel(ConfigPanel):
    title = "Analogue sampling"

    sampleRateChanged = Signal(int)
    pinChanged = Signal(int, int)  # (channel, gp)
    timeWidthChanged = Signal(float)
    channelVisibilityChanged = Signal(int, bool)  # (channel, visible)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        initial_hz = _load_int(self._settings, _RATE_KEY, _DEFAULT_HZ)
        initial_hz = max(_MIN_HZ, min(_MAX_HZ, initial_hz))

        self.rate_spin = QSpinBox(self)
        self.rate_spin.setRange(_MIN_HZ, _MAX_HZ)
        self.rate_spin.setSingleStep(_STEP_HZ)
        self.rate_spin.setSuffix(" Hz")
        self.rate_spin.setAccelerated(True)
        self.rate_spin.setKeyboardTracking(False)
        self.rate_spin.setFixedWidth(FIELD_WIDTH)
        self.rate_spin.setValue(initial_hz)

        initial_time_width = _load_float(self._settings, _TIME_WIDTH_KEY, _DEFAULT_TIME_WIDTH)
        initial_time_width = max(_MIN_TIME_WIDTH, min(_MAX_TIME_WIDTH, initial_time_width))
        self.time_width_spin = QDoubleSpinBox(self)
        self.time_width_spin.setRange(_MIN_TIME_WIDTH, _MAX_TIME_WIDTH)
        self.time_width_spin.setSingleStep(1.0)
        self.time_width_spin.setSuffix(" s")
        self.time_width_spin.setKeyboardTracking(False)
        self.time_width_spin.setFixedWidth(FIELD_WIDTH)
        self.time_width_spin.setValue(initial_time_width)

        pin1_initial = _load_int(self._settings, _PIN1_KEY, _DEFAULT_PIN1)
        pin2_initial = _load_int(self._settings, _PIN2_KEY, _DEFAULT_PIN2)
        if pin1_initial == pin2_initial:
            pin2_initial = next(gp for _, gp in _ADC_PINS if gp != pin1_initial)

        self.pin1_combo = self._build_pin_combo(pin1_initial)
        self.pin2_combo = self._build_pin_combo(pin2_initial)

        ch1_vis_initial = self._settings.value(_VIS1_KEY, True)
        ch2_vis_initial = self._settings.value(_VIS2_KEY, True)
        self.ch1_check = QCheckBox("Show", self)
        self.ch1_check.setChecked(ch1_vis_initial not in (False, "false"))
        self.ch2_check = QCheckBox("Show", self)
        self.ch2_check.setChecked(ch2_vis_initial not in (False, "false"))

        rate_group = QGroupBox(parent=self)
        rate_form = QFormLayout(rate_group)
        rate_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        rate_form.addRow("Sample rate", self.rate_spin)
        rate_form.addRow("Time width", self.time_width_spin)
        self.body.addWidget(rate_group)

        pins_group = QGroupBox("Pins", self)
        pins_form = QFormLayout(pins_group)
        pins_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        pins_form.addRow("Pressure sensor 1", self.pin1_combo)
        pins_form.addRow("", self.ch1_check)
        pins_form.addRow("Pressure sensor 2", self.pin2_combo)
        pins_form.addRow("", self.ch2_check)
        self.body.addWidget(pins_group)

        self.body.addStretch(1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_rate)

        self._time_width_debounce = QTimer(self)
        self._time_width_debounce.setSingleShot(True)
        self._time_width_debounce.setInterval(_DEBOUNCE_MS)
        self._time_width_debounce.timeout.connect(self._emit_time_width)

        self.rate_spin.valueChanged.connect(self._on_rate_changed)
        self.time_width_spin.valueChanged.connect(self._time_width_debounce.start)
        self.pin1_combo.currentIndexChanged.connect(lambda _i: self._on_pin_changed(1))
        self.pin2_combo.currentIndexChanged.connect(lambda _i: self._on_pin_changed(2))
        self.ch1_check.toggled.connect(lambda checked: self._on_visibility_changed(1, checked))
        self.ch2_check.toggled.connect(lambda checked: self._on_visibility_changed(2, checked))

        self._refresh_pin_availability()

    def _build_pin_combo(self, selected_gp: int) -> QComboBox:
        combo = QComboBox(self)
        for label, gp in _ADC_PINS:
            combo.addItem(label, gp)
        idx = combo.findData(selected_gp)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        apply_field_width(combo)
        return combo

    def current_rate(self) -> int:
        return self.rate_spin.value()

    def current_pin(self, channel: int) -> int:
        combo = self.pin1_combo if channel == 1 else self.pin2_combo
        return int(combo.currentData())

    def current_time_width(self) -> float:
        return self.time_width_spin.value()

    def current_channel_visibility(self, channel: int) -> bool:
        return (self.ch1_check if channel == 1 else self.ch2_check).isChecked()

    def _on_rate_changed(self, _value: int) -> None:
        self._debounce.start()

    def _emit_rate(self) -> None:
        hz = self.rate_spin.value()
        self._settings.setValue(_RATE_KEY, hz)
        self.sampleRateChanged.emit(hz)

    def _emit_time_width(self) -> None:
        seconds = self.time_width_spin.value()
        self._settings.setValue(_TIME_WIDTH_KEY, seconds)
        self.timeWidthChanged.emit(seconds)

    def _on_visibility_changed(self, channel: int, visible: bool) -> None:
        self._settings.setValue(_VIS1_KEY if channel == 1 else _VIS2_KEY, visible)
        self.channelVisibilityChanged.emit(channel, visible)

    def _on_pin_changed(self, channel: int) -> None:
        gp = self.current_pin(channel)
        self._settings.setValue(_PIN1_KEY if channel == 1 else _PIN2_KEY, gp)
        self._refresh_pin_availability()
        self.pinChanged.emit(channel, gp)

    def _refresh_pin_availability(self) -> None:
        pairs = ((self.pin1_combo, self.pin2_combo), (self.pin2_combo, self.pin1_combo))
        for combo, other in pairs:
            taken = other.currentData()
            model = combo.model()
            if not isinstance(model, QStandardItemModel):
                continue
            for i in range(combo.count()):
                item = model.item(i)
                if item is not None:
                    item.setEnabled(combo.itemData(i) != taken)
