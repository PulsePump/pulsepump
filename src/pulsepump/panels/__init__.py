"""Dockable configuration panels."""

from .base import ConfigPanel
from .function_generator import FunctionGeneratorPanel
from .pressure_sensors import PressureSensorsPanel
from .sampling import SamplingPanel
from .waveform_preview import WaveformPreviewPanel

__all__ = [
    "ConfigPanel",
    "FunctionGeneratorPanel",
    "PressureSensorsPanel",
    "SamplingPanel",
    "WaveformPreviewPanel",
]
