"""Pressure sensors panel — live calibration from the sensor datasheet."""

from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QWidget,
)

from pulsepump import pressure

from .base import ConfigPanel

_SETTINGS_ORG = "pulsepump"
_SETTINGS_APP = "pulsepump"
_VMIN_KEY = "pressure/vSensorMin"
_VMAX_KEY = "pressure/vSensorMax"
_PFS_KEY = "pressure/pFullScale"
_UNITS_KEY = "pressure/units"
_DIV_KEY = "pressure/dividerRatio"
_DEBOUNCE_MS = 250

_PRESSURE_UNITS: tuple[str, ...] = (
    "Pa",
    "kPa",
    "MPa",
    "bar",
    "mbar",
    "psi",
    "mmHg",
    "atm",
)


def _load_float(settings: QSettings, key: str, default: float) -> float:
    raw = settings.value(key, default)
    try:
        return float(str(raw))
    except TypeError, ValueError:
        return default


def _load_str(settings: QSettings, key: str, default: str) -> str:
    raw = settings.value(key, default)
    return default if raw is None else str(raw)


class PressureSensorsPanel(ConfigPanel):
    title = "Pressure sensors"

    paramsChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        v_min = _load_float(self._settings, _VMIN_KEY, pressure.V_SENSOR_MIN)
        v_max = _load_float(self._settings, _VMAX_KEY, pressure.V_SENSOR_MAX)
        p_fs = _load_float(self._settings, _PFS_KEY, pressure.P_FULL_SCALE)
        units = _load_str(self._settings, _UNITS_KEY, pressure.P_UNITS)
        divider = _load_float(self._settings, _DIV_KEY, pressure.DIVIDER_RATIO)

        self.vmin_spin = self._build_volt_spin(v_min)
        self.vmax_spin = self._build_volt_spin(v_max)

        self.pfs_spin = QDoubleSpinBox(self)
        self.pfs_spin.setRange(0.0, 100_000.0)
        self.pfs_spin.setDecimals(2)
        self.pfs_spin.setSingleStep(1.0)
        self.pfs_spin.setAccelerated(True)
        self.pfs_spin.setKeyboardTracking(False)
        self.pfs_spin.setValue(p_fs)

        self.units_combo = QComboBox(self)
        self.units_combo.addItems(_PRESSURE_UNITS)
        idx = self.units_combo.findText(units)
        if idx < 0:
            self.units_combo.addItem(units)
            idx = self.units_combo.count() - 1
        self.units_combo.setCurrentIndex(idx)

        datasheet_group = QGroupBox("Datasheet", self)
        form = QFormLayout(datasheet_group)
        form.addRow("V at min pressure", self.vmin_spin)
        form.addRow("V at max pressure", self.vmax_spin)
        form.addRow("Full-scale pressure", self.pfs_spin)
        form.addRow("Units", self.units_combo)
        self.body.addWidget(datasheet_group)

        self.divider_spin = QDoubleSpinBox(self)
        self.divider_spin.setRange(0.01, 1.0)
        self.divider_spin.setDecimals(3)
        self.divider_spin.setSingleStep(0.01)
        self.divider_spin.setAccelerated(True)
        self.divider_spin.setKeyboardTracking(False)
        self.divider_spin.setValue(divider)
        # Reserve enough room for the widest displayed value plus the step buttons.
        sample_width = self.divider_spin.fontMetrics().horizontalAdvance("0.000")
        self.divider_spin.setMinimumWidth(sample_width + 40)
        self.divider_spin.setToolTip(
            "Ratio of ADC input voltage to raw sensor voltage. "
            "For a sensor that swings 0-5 V scaled to fit the Pico's 3.3 V ADC, "
            "this is typically ~0.6 (depends on resistor values)."
        )

        board_group = QGroupBox("Board", self)
        board_form = QFormLayout(board_group)
        board_form.addRow("Voltage divider ratio", self.divider_spin)
        self.body.addWidget(board_group)

        self.body.addStretch(1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._commit)

        self.vmin_spin.valueChanged.connect(self._schedule_commit)
        self.vmax_spin.valueChanged.connect(self._schedule_commit)
        self.pfs_spin.valueChanged.connect(self._schedule_commit)
        self.units_combo.currentIndexChanged.connect(self._schedule_commit)
        self.divider_spin.valueChanged.connect(self._schedule_commit)

        self._apply_to_pressure_module()
        self._refresh_pfs_suffix()

    def _build_volt_spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(0.0, 10.0)
        spin.setDecimals(3)
        spin.setSingleStep(0.1)
        spin.setSuffix(" V")
        spin.setAccelerated(True)
        spin.setKeyboardTracking(False)
        spin.setValue(value)
        return spin

    def _schedule_commit(self, *_args: object) -> None:
        self._debounce.start()

    def _current_units(self) -> str:
        return self.units_combo.currentText() or pressure.P_UNITS

    def _commit(self) -> None:
        v_min = self.vmin_spin.value()
        v_max = self.vmax_spin.value()
        p_fs = self.pfs_spin.value()
        units = self._current_units()

        self._settings.setValue(_VMIN_KEY, v_min)
        self._settings.setValue(_VMAX_KEY, v_max)
        self._settings.setValue(_PFS_KEY, p_fs)
        self._settings.setValue(_UNITS_KEY, units)
        self._settings.setValue(_DIV_KEY, self.divider_spin.value())

        self._apply_to_pressure_module()
        self._refresh_pfs_suffix()
        self.paramsChanged.emit()

    def _apply_to_pressure_module(self) -> None:
        pressure.update(
            v_sensor_min=self.vmin_spin.value(),
            v_sensor_max=self.vmax_spin.value(),
            p_full_scale=self.pfs_spin.value(),
            divider_ratio=self.divider_spin.value(),
            units=self._current_units(),
        )

    def _refresh_pfs_suffix(self) -> None:
        self.pfs_spin.setSuffix(f" {self._current_units()}")
