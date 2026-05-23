"""Pydantic config types for the Hardware Bench.

A :class:`BenchConfig` is a list of :class:`DeviceConfig` instances —
a discriminated union over the three device kinds. Configs round-trip to
YAML and form the body of the firmware ``configure`` RPC.
"""

from __future__ import annotations

from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, NonNegativeInt, PositiveFloat, PositiveInt

# ---------------------------------------------------------------------------
# Per-device configs
# ---------------------------------------------------------------------------


class PressureSensorConfig(BaseModel):
    """One analog pressure sensor on a Pico ADC pin."""

    model_config = {"extra": "forbid"}

    type: Literal["pressure"] = "pressure"
    id: str
    adc_pin: NonNegativeInt = 26  # Pico ADC0/1/2 = GP26/27/28
    sample_rate_hz: PositiveFloat = 200.0


class ServoConfig(BaseModel):
    """One PWM servo (e.g. MG996R), open-loop."""

    model_config = {"extra": "forbid"}

    type: Literal["servo"] = "servo"
    id: str
    pwm_pin: NonNegativeInt = 15
    pwm_freq_hz: PositiveInt = 50
    min_us: PositiveInt = 1000  # pulse width at 0°
    max_us: PositiveInt = 2000  # pulse width at 180°
    max_angle_deg: PositiveFloat = 180.0
    sample_rate_hz: PositiveFloat = 50.0


class StepperConfig(BaseModel):
    """One TMC2209 over UART + STEP/DIR/EN pins."""

    model_config = {"extra": "forbid"}

    type: Literal["stepper"] = "stepper"
    id: str
    uart_id: Literal[0, 1] = 0
    tx_pin: NonNegativeInt = 0
    rx_pin: NonNegativeInt = 1
    step_pin: NonNegativeInt = 2
    dir_pin: NonNegativeInt = 4
    en_pin: NonNegativeInt = 3
    slave_addr: NonNegativeInt = 0
    sample_rate_hz: PositiveFloat = 20.0
    run_current: int = Field(default=16, ge=0, le=31)
    hold_current: int = Field(default=8, ge=0, le=31)
    microsteps: Literal[1, 2, 4, 8, 16, 32, 64, 128, 256] = 16


DeviceConfig = Annotated[
    PressureSensorConfig | ServoConfig | StepperConfig,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


class BenchConfig(BaseModel):
    """Full Hardware Bench configuration."""

    model_config = {"extra": "forbid"}

    devices: list[DeviceConfig] = Field(default_factory=list)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> BenchConfig:
        data = yaml.safe_load(text) or {}
        return cls.model_validate(data)

    def count_of(self, kind: str) -> int:
        return sum(1 for d in self.devices if d.type == kind)

    def find(self, device_id: str) -> DeviceConfig | None:
        return next((d for d in self.devices if d.id == device_id), None)


MAX_PER_KIND = 2
"""At most 2 of each device kind (servo, stepper, pressure)."""
