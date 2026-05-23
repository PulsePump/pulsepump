"""TMC2209 stepper device — logs every readable signal."""

from __future__ import annotations

from ..config import StepperConfig
from ..signals import SignalDescriptor
from .base import BenchDevice

# Names of DRV_STATUS bits decoded by the firmware. Each is logged as a
# 0.0/1.0 float so it slots into the same parquet schema as numeric readings.
_DRV_STATUS_BITS = (
    "otpw",
    "ot",
    "s2ga",
    "s2gb",
    "s2vsa",
    "s2vsb",
    "ola",
    "olb",
    "t120",
    "t143",
    "t150",
    "t157",
    "stealth",
    "stst",
)
_IOIN_BITS = ("enn", "ms1", "ms2", "diag", "pdn_uart", "step_pin", "spread_en", "dir_pin")


class StepperDevice(BenchDevice[StepperConfig]):
    """One TMC2209 — every register readable over single-wire UART is logged.

    Inputs (host → device): commanded step count, target step rate, direction,
    enable. Readings: TSTEP, SG_RESULT, MSCNT, MSCURACT (cur_a/cur_b),
    cs_actual, IFCNT. Status bits: DRV_STATUS flags + IOIN bits + stealth/stst.
    """

    device_type = "stepper"

    def signals_for(self) -> list[SignalDescriptor]:
        sigs: list[SignalDescriptor] = [
            # Inputs
            SignalDescriptor(
                self.id,
                "commanded_step",
                "step",
                "input",
                "f4",
                "Cumulative commanded step count (signed)",
            ),
            SignalDescriptor(
                self.id, "step_rate_hz", "Hz", "input", "f4", "Most recent commanded step rate"
            ),
            SignalDescriptor(self.id, "dir", "", "input", "f4", "Direction pin level"),
            SignalDescriptor(
                self.id, "enabled", "", "input", "f4", "1.0 if ENN is asserted low (motor enabled)"
            ),
            # Numeric readings
            SignalDescriptor(
                self.id,
                "tstep",
                "ticks",
                "reading",
                "f4",
                "TSTEP register — step interval (256 = motor stopped)",
            ),
            SignalDescriptor(
                self.id, "sg_result", "", "reading", "f4", "StallGuard4 load reading (0..510)"
            ),
            SignalDescriptor(
                self.id, "mscnt", "ms", "reading", "f4", "Microstep counter (0..1023)"
            ),
            SignalDescriptor(
                self.id, "cur_a", "", "reading", "f4", "MSCURACT phase-A current (-256..255)"
            ),
            SignalDescriptor(
                self.id, "cur_b", "", "reading", "f4", "MSCURACT phase-B current (-256..255)"
            ),
            SignalDescriptor(
                self.id,
                "cs_actual",
                "",
                "reading",
                "f4",
                "DRV_STATUS CS_ACTUAL (current scaling 0..31)",
            ),
            SignalDescriptor(
                self.id,
                "ifcnt",
                "",
                "status",
                "f4",
                "UART write counter — increments on successful host writes",
            ),
        ]
        for bit in _DRV_STATUS_BITS:
            sigs.append(SignalDescriptor(self.id, bit, "", "status", "f4", f"DRV_STATUS.{bit}"))
        for bit in _IOIN_BITS:
            sigs.append(SignalDescriptor(self.id, f"ioin_{bit}", "", "status", "f4", f"IOIN.{bit}"))
        return sigs

    def ingest(self, t_s: float, data: dict) -> dict[str, float]:
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float, bool))}

    # -- command methods --------------------------------------------------

    def step(self, steps: int, rate_hz: int, direction: int) -> None:
        self._send(
            {
                "cmd": "step",
                "id": self.id,
                "steps": int(steps),
                "rate_hz": int(rate_hz),
                "dir": 1 if direction else 0,
            }
        )
        self.input_changed.emit("step_rate_hz", float(rate_hz))
        self.input_changed.emit("dir", 1.0 if direction else 0.0)
        dir_label = "CW" if direction else "CCW"
        self.status_message.emit(f"{self.id}: move {steps} steps @ {rate_hz} Hz ({dir_label})")

    def set_enabled(self, enabled: bool) -> None:
        self._send(
            {
                "cmd": "set",
                "id": self.id,
                "field": "enabled",
                "value": bool(enabled),
            }
        )
        self.input_changed.emit("enabled", 1.0 if enabled else 0.0)
        self.status_message.emit(f"{self.id}: {'enabled' if enabled else 'disabled'}")

    def read_now(self) -> None:
        """Force the firmware to emit one immediate sample for this stepper.

        Useful for diagnostics: confirms UART round-trip is alive and updates
        all read-back signals (IFCNT, SG_RESULT, DRV_STATUS, …) without waiting
        for the next scheduled tick.
        """
        self._send({"cmd": "read_now", "id": self.id})
        self.status_message.emit(f"{self.id}: read_now requested")
