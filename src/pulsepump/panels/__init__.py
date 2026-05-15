"""Dockable configuration panels."""

from .base import ConfigPanel
from .julia_console import JuliaConsolePanel
from .pressure_sensors import PressureSensorsPanel
from .sampling import SamplingPanel
from .waveform_generator import WaveformGeneratorPanel

__all__ = [
    "ConfigPanel",
    "JuliaConsolePanel",
    "PressureSensorsPanel",
    "SamplingPanel",
    "WaveformGeneratorPanel",
]
