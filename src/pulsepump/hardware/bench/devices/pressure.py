"""Analog pressure sensor device (ADC + pressure.py calibration)."""

from __future__ import annotations

from pulsepump.core import pressure

from ..config import PressureSensorConfig
from ..signals import SignalDescriptor
from .base import BenchDevice


class PressureSensorDevice(BenchDevice[PressureSensorConfig]):
    """One MG-style analog pressure sensor on a Pico ADC pin.

    The firmware emits raw 16-bit ADC ``counts``; voltage and pressure are
    derived host-side via :mod:`pulsepump.core.pressure` so the calibration
    can be tuned without re-flashing.
    """

    device_type = "pressure"

    def signals_for(self) -> list[SignalDescriptor]:
        return [
            SignalDescriptor(self.id, "counts", "ADC", "reading", "u2", "Raw 16-bit ADC count"),
            SignalDescriptor(
                self.id, "voltage", "V", "reading", "f4", "Sensor voltage after divider correction"
            ),
            SignalDescriptor(
                self.id, "pressure", pressure.units(), "reading", "f4", "Calibrated pressure"
            ),
        ]

    def ingest(self, t_s: float, data: dict) -> dict[str, float]:
        raw = int(data.get("counts", 0))
        voltage = raw * pressure._cfg._counts_to_v  # type: ignore[attr-defined]
        pres = pressure.counts_to_pressure(raw)
        return {
            "counts": float(raw),
            "voltage": float(voltage),
            "pressure": float(pres),
        }
