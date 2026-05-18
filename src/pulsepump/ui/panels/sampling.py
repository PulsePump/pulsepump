from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QSpinBox, QWidget

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


class SamplingPanel(ConfigPanel):
    title = "Analogue sampling"

    sampleRateChanged = Signal(int)
    pinChanged = Signal(int, int)  # (channel, gp)

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

        pin1_initial = _load_int(self._settings, _PIN1_KEY, _DEFAULT_PIN1)
        pin2_initial = _load_int(self._settings, _PIN2_KEY, _DEFAULT_PIN2)
        if pin1_initial == pin2_initial:
            pin2_initial = next(gp for _, gp in _ADC_PINS if gp != pin1_initial)

        self.pin1_combo = self._build_pin_combo(pin1_initial)
        self.pin2_combo = self._build_pin_combo(pin2_initial)

        rate_group = QGroupBox(parent=self)
        rate_form = QFormLayout(rate_group)
        rate_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        rate_form.addRow("Sample rate", self.rate_spin)
        self.body.addWidget(rate_group)

        pins_group = QGroupBox("Pins", self)
        pins_form = QFormLayout(pins_group)
        pins_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        pins_form.addRow("Pressure sensor 1", self.pin1_combo)
        pins_form.addRow("Pressure sensor 2", self.pin2_combo)
        self.body.addWidget(pins_group)

        self.body.addStretch(1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_rate)

        self.rate_spin.valueChanged.connect(self._on_rate_changed)
        self.pin1_combo.currentIndexChanged.connect(lambda _i: self._on_pin_changed(1))
        self.pin2_combo.currentIndexChanged.connect(lambda _i: self._on_pin_changed(2))

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

    def _on_rate_changed(self, _value: int) -> None:
        self._debounce.start()

    def _emit_rate(self) -> None:
        hz = self.rate_spin.value()
        self._settings.setValue(_RATE_KEY, hz)
        self.sampleRateChanged.emit(hz)

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
