"""Bench device drivers (host-side)."""

from .base import BenchDevice
from .pressure import PressureSensorDevice
from .servo import ServoDevice
from .stepper import StepperDevice

__all__ = [
    "BenchDevice",
    "PressureSensorDevice",
    "ServoDevice",
    "StepperDevice",
]


def device_for(config) -> BenchDevice:
    """Factory: instantiate the right device class for a DeviceConfig."""
    from ..config import PressureSensorConfig, ServoConfig, StepperConfig

    if isinstance(config, PressureSensorConfig):
        return PressureSensorDevice(config)
    if isinstance(config, ServoConfig):
        return ServoDevice(config)
    if isinstance(config, StepperConfig):
        return StepperDevice(config)
    raise TypeError(f"unknown device config: {type(config).__name__}")
