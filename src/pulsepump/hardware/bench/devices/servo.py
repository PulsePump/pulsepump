"""Servo device (Pico PWM, open-loop)."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QTimer

from ..config import ServoConfig
from ..signals import SignalDescriptor
from .base import BenchDevice


class ServoDevice(BenchDevice[ServoConfig]):
    """One PWM servo (e.g. MG996R).

    Open-loop: the host commands an angle; the firmware writes a pulse width.
    Both the commanded angle and the resulting pulse width / duty are logged
    so post-hoc analysis can recover the exact waveform that was applied.
    """

    device_type = "servo"

    def __init__(self, config: ServoConfig, parent=None) -> None:
        super().__init__(config, parent)
        self._sweep_timer = QTimer(self)
        self._sweep_timer.timeout.connect(self._on_sweep_tick)
        self._sweep_freq_hz: float = 1.0
        self._sweep_start_time: float = 0.0

    @property
    def sweeping(self) -> bool:
        return self._sweep_timer.isActive()

    def start_sweep(self, freq_hz: float) -> None:
        self._sweep_freq_hz = max(freq_hz, 1e-3)
        self._sweep_start_time = time.monotonic()
        interval_ms = max(1, int(1000.0 / self.sample_rate_hz))
        self._sweep_timer.start(interval_ms)

    def stop_sweep(self) -> None:
        self._sweep_timer.stop()

    def _on_sweep_tick(self) -> None:
        elapsed = time.monotonic() - self._sweep_start_time
        angle = (self._config.max_angle_deg / 2.0) * (
            1.0 + math.sin(2.0 * math.pi * self._sweep_freq_hz * elapsed)
        )
        self.set_angle(angle)

    def signals_for(self) -> list[SignalDescriptor]:
        return [
            SignalDescriptor(
                self.id, "commanded_angle_deg", "deg", "input", "f4", "Host-commanded servo angle"
            ),
            SignalDescriptor(
                self.id, "pulse_us", "us", "reading", "f4", "Pulse width applied by firmware"
            ),
            SignalDescriptor(
                self.id, "duty_u16", "", "reading", "f4", "16-bit PWM duty applied by firmware"
            ),
            SignalDescriptor(self.id, "pwm_freq_hz", "Hz", "status", "f4", "PWM carrier frequency"),
        ]

    def ingest(self, t_s: float, data: dict) -> dict[str, float]:
        # Firmware reports whatever it actually applied; some keys may be
        # missing on synthetic transports (just commanded_angle_deg).
        out: dict[str, float] = {}
        for key in ("commanded_angle_deg", "pulse_us", "duty_u16", "pwm_freq_hz"):
            if key in data:
                out[key] = float(data[key])
        return out

    # -- command methods --------------------------------------------------

    def set_angle(self, deg: float) -> None:
        deg = max(0.0, min(self._config.max_angle_deg, float(deg)))
        self._send({"cmd": "set", "id": self.id, "field": "angle_deg", "value": deg})
        self.input_changed.emit("commanded_angle_deg", deg)
        self.status_message.emit(f"{self.id}: angle → {deg:.1f}°")
