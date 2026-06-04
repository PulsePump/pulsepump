"""Servo device (Pico PWM, open-loop)."""

from __future__ import annotations

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
        self._sweeping = False

    @property
    def sweeping(self) -> bool:
        return self._sweeping

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

    def start_sweep(self, freq_hz: float) -> None:
        self._send({"cmd": "set", "id": self.id, "field": "sweep_freq_hz", "value": freq_hz})
        self._sweeping = True

    def stop_sweep(self) -> None:
        self._send({"cmd": "set", "id": self.id, "field": "sweep_stop", "value": 1})
        self._sweeping = False
