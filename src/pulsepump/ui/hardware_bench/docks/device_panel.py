"""Per-device control + pin editor panels (one dock per configured device)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ....hardware.bench.config import (
    PressureSensorConfig,
    ServoConfig,
    StepperConfig,
)
from ....hardware.bench.controller import BenchController
from ....hardware.bench.devices import (
    BenchDevice,
    PressureSensorDevice,
    ServoDevice,
    StepperDevice,
)


def _section(title: str, *, parent: QWidget | None = None) -> tuple[QGroupBox, QFormLayout]:
    box = QGroupBox(title, parent)
    form = QFormLayout(box)
    form.setSpacing(4)
    return box, form


class DevicePanel(QDockWidget):
    """Wraps a per-device editor + control panel + live readings table.

    The actual contents depend on the device kind; we dispatch from the
    controller's device type. Pin/rate edits are *staged* in the spinboxes;
    "Apply Live" pushes them through :meth:`BenchController.reconfigure_device`.
    """

    def __init__(
        self,
        controller: BenchController,
        device: BenchDevice,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(f"{device.device_type}: {device.id}", parent)
        self.setObjectName(f"HardwareBench.DevicePanel.{device.id}")
        # Closing the dock only hides it; reopen via View → Device Panels.
        # Actual removal of the device is done via the Remove button or
        # BenchController.remove_device.
        self._controller = controller
        self._device = device
        self._readings: dict[str, QLabel] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_pins_group())
        layout.addWidget(self._build_controls_group())
        layout.addWidget(self._build_readings_group())

        remove_btn = QPushButton(f"Remove {device.id}")
        remove_btn.clicked.connect(self._on_remove)
        layout.addWidget(remove_btn)
        layout.addStretch()
        scroll.setWidget(body)
        self.setWidget(scroll)

        controller.signals.samples_appended.connect(self._on_sample)

    # -- pins / rate ------------------------------------------------------

    def _build_pins_group(self) -> QGroupBox:
        box, form = _section("Pin Assignment")
        self._pin_spins: dict[str, QSpinBox] = {}
        self._microsteps_combo: QComboBox | None = None

        cfg = self._device.config

        def _pin(default: int) -> QSpinBox:
            s = QSpinBox()
            s.setRange(0, 29)
            s.setValue(default)
            s.setPrefix("GP")
            return s

        if isinstance(cfg, PressureSensorConfig):
            self._pin_spins["adc_pin"] = _pin(cfg.adc_pin)
            form.addRow("ADC pin:", self._pin_spins["adc_pin"])
        elif isinstance(cfg, ServoConfig):
            self._pin_spins["pwm_pin"] = _pin(cfg.pwm_pin)
            form.addRow("PWM pin:", self._pin_spins["pwm_pin"])

            def _us_spin(default: int) -> QSpinBox:
                s = QSpinBox()
                s.setRange(500, 3000)
                s.setSingleStep(50)
                s.setSuffix(" µs")
                s.setValue(default)
                return s

            self._pin_spins["min_us"] = _us_spin(cfg.min_us)
            self._pin_spins["max_us"] = _us_spin(cfg.max_us)
            form.addRow("Min pulse (0°):", self._pin_spins["min_us"])
            form.addRow("Max pulse (180°):", self._pin_spins["max_us"])
        elif isinstance(cfg, StepperConfig):
            for key, default in [
                ("tx_pin", cfg.tx_pin),
                ("rx_pin", cfg.rx_pin),
                ("step_pin", cfg.step_pin),
                ("dir_pin", cfg.dir_pin),
                ("en_pin", cfg.en_pin),
            ]:
                spin = _pin(default)
                self._pin_spins[key] = spin
                form.addRow(f"{key.replace('_', ' ').title()}:", spin)

            for key, lo, hi, suffix, default in [
                ("run_current", 0, 31, " /31", cfg.run_current),
                ("hold_current", 0, 31, " /31", cfg.hold_current),
            ]:
                s = QSpinBox()
                s.setRange(lo, hi)
                s.setSuffix(suffix)
                s.setValue(default)
                self._pin_spins[key] = s
                form.addRow(f"{key.replace('_', ' ').title()}:", s)

            ms_values = [1, 2, 4, 8, 16, 32, 64, 128, 256]
            self._microsteps_combo = QComboBox()
            for ms in ms_values:
                self._microsteps_combo.addItem(str(ms), ms)
            idx = ms_values.index(cfg.microsteps) if cfg.microsteps in ms_values else 4
            self._microsteps_combo.setCurrentIndex(idx)
            form.addRow("Microsteps:", self._microsteps_combo)

        rate = QDoubleSpinBox()
        rate.setRange(0.1, 5000.0)
        rate.setDecimals(1)
        rate.setSuffix(" Hz")
        rate.setValue(self._device.sample_rate_hz)
        self._rate_spin = rate
        form.addRow("Sample rate:", rate)

        apply_btn = QPushButton("Apply Live")
        apply_btn.clicked.connect(self._on_apply_live)
        form.addRow("", apply_btn)
        return box

    def _on_apply_live(self) -> None:
        cfg = self._device.config
        data = cfg.model_dump()
        for key, spin in self._pin_spins.items():
            data[key] = spin.value()
        data["sample_rate_hz"] = self._rate_spin.value()
        if self._microsteps_combo is not None:
            data["microsteps"] = self._microsteps_combo.currentData()
        new_cfg = type(cfg).model_validate(data)
        try:
            self._controller.reconfigure_device(self._device.id, new_cfg)
        except (KeyError, ValueError) as exc:
            self._controller.error.emit(str(exc))

    # -- controls ---------------------------------------------------------

    def _build_controls_group(self) -> QGroupBox:
        if isinstance(self._device, PressureSensorDevice):
            return self._pressure_controls()
        if isinstance(self._device, ServoDevice):
            return self._servo_controls()
        if isinstance(self._device, StepperDevice):
            return self._stepper_controls()
        box, _ = _section("Controls")
        return box

    def _pressure_controls(self) -> QGroupBox:
        box, form = _section("Controls")
        info = QLabel(
            "Read-only sensor. Use the global pressure calibration panel\n"
            "to tune voltage→pressure mapping."
        )
        info.setStyleSheet("color: #888;")
        form.addRow(info)
        return box

    def _servo_controls(self) -> QGroupBox:
        assert isinstance(self._device, ServoDevice)
        servo = self._device
        box, form = _section("Controls")
        max_deg = int(servo.config.max_angle_deg)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, max_deg)
        spin = QSpinBox()
        spin.setRange(0, max_deg)
        spin.setSuffix(" deg")
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(lambda v, dev=servo: dev.set_angle(float(v)))
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(spin)
        form.addRow("Angle:", row)
        return box

    def _stepper_controls(self) -> QGroupBox:
        assert isinstance(self._device, StepperDevice)
        stepper = self._device
        box, form = _section("Controls")
        steps = QSpinBox()
        steps.setRange(1, 1_000_000)
        steps.setValue(200)
        rate = QSpinBox()
        rate.setRange(1, 100_000)
        rate.setValue(1000)
        rate.setSuffix(" Hz")
        direction = QCheckBox("Reverse")
        params_row = QHBoxLayout()
        params_row.addWidget(QLabel("Steps"))
        params_row.addWidget(steps)
        params_row.addSpacing(8)
        params_row.addWidget(QLabel("Rate"))
        params_row.addWidget(rate)
        params_row.addWidget(direction)
        form.addRow("Move:", params_row)

        enable_chk = QCheckBox("Enabled")
        enable_chk.toggled.connect(stepper.set_enabled)
        form.addRow("", enable_chk)

        move_btn = QPushButton("Move")

        def _do_move() -> None:
            stepper.step(
                steps.value(),
                rate.value(),
                0 if direction.isChecked() else 1,
            )

        move_btn.clicked.connect(_do_move)
        form.addRow("", move_btn)

        # Diagnostic: force one immediate sample-frame round-trip. Watch the
        # ifcnt reading below — it increments on every successful UART write.
        read_btn = QPushButton("Read Now (diagnostic)")
        read_btn.setToolTip(
            "Force the firmware to emit one stepper sample frame.\n"
            "If ifcnt increments after a Move, host→driver UART is alive.\n"
            "If tstep changes when the motor turns, RX is alive too."
        )
        read_btn.clicked.connect(stepper.read_now)
        form.addRow("", read_btn)
        return box

    # -- readings ---------------------------------------------------------

    def _build_readings_group(self) -> QGroupBox:
        box, form = _section("Live readings")
        for desc in self._device.signals_for():
            lbl = QLabel("--")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet("font-family: monospace;")
            form.addRow(f"{desc.name} ({desc.units}):" if desc.units else f"{desc.name}:", lbl)
            self._readings[f"{self._device.id}.{desc.name}"] = lbl
        return box

    def _on_sample(self, signal_id: str) -> None:
        lbl = self._readings.get(signal_id)
        if lbl is None:
            return
        val = self._controller.signals.latest(signal_id)
        if val is None:
            return
        lbl.setText(f"{val:.4g}")

    # -- remove ----------------------------------------------------------

    def _on_remove(self) -> None:
        self._controller.remove_device(self._device.id)
