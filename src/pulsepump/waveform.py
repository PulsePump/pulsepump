from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class WaveformType(StrEnum):
    CONSTANT = "constant"
    SINE = "sine"
    SQUARE = "square"
    TRIANGLE = "triangle"
    SAWTOOTH = "sawtooth"
    PULSE = "pulse"


class Interpolation(StrEnum):
    ZERO_ORDER_HOLD = "zoh"
    FIRST_ORDER_HOLD = "foh"


@dataclass(frozen=True, slots=True)
class WaveformConfig:
    """Immutable snapshot of every function-generator parameter.

    Amplitude and offset are in the user's chosen pressure units; the math here
    is unit-agnostic. `duty`, `symmetry`, and `phase` are normalized to [0, 1].
    `sample_rate_hz` is the setpoint update rate the fluid sim will consume.
    """

    type: WaveformType
    bpm: float
    amplitude: float
    offset: float
    duty: float
    symmetry: float
    phase: float
    sample_rate_hz: float
    interpolation: Interpolation

    @property
    def period_s(self) -> float:
        return 60.0 / max(self.bpm, 1e-6)

    @property
    def samples_per_cycle(self) -> int:
        return max(round(self.sample_rate_hz * self.period_s), 1)


def _shape(config: WaveformConfig, u: np.ndarray) -> np.ndarray:
    """Evaluate the unit-amplitude shape at normalized phase u in [0, 1)."""
    match config.type:
        case WaveformType.CONSTANT:
            return np.zeros_like(u)
        case WaveformType.SINE:
            return np.sin(2.0 * np.pi * u)
        case WaveformType.SQUARE:
            return np.where(u < config.duty, 1.0, -1.0)
        case WaveformType.TRIANGLE:
            # Symmetry s splits the cycle into a rising part [0, s) and a falling
            # part [s, 1). At s=0.5 it's a symmetric triangle; s→1 makes it a
            # rising ramp, s→0 a falling ramp.
            s = float(np.clip(config.symmetry, 1e-6, 1.0 - 1e-6))
            rising = 2.0 * (u / s) - 1.0
            falling = 1.0 - 2.0 * ((u - s) / (1.0 - s))
            return np.where(u < s, rising, falling)
        case WaveformType.SAWTOOTH:
            # Direction toggle: symmetry > 0.5 → rising, otherwise → falling.
            return 2.0 * u - 1.0 if config.symmetry > 0.5 else 1.0 - 2.0 * u
        case WaveformType.PULSE:
            # Narrow positive burst on a zero baseline; duty controls width.
            return np.where(u < config.duty, 1.0, 0.0)


def sample(config: WaveformConfig, t: np.ndarray) -> np.ndarray:
    """Evaluate the waveform at times `t` (seconds)."""
    u = ((t / config.period_s) + config.phase) % 1.0
    return config.amplitude * _shape(config, u) + config.offset


def sample_one_cycle(config: WaveformConfig, n: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return (t, y) covering exactly one cycle, t in [0, period_s).

    Defaults to `config.samples_per_cycle` so the result matches the setpoint
    update rate the fluid sim will see. Pass `n` to override.
    """
    if n is None:
        n = config.samples_per_cycle
    t = np.linspace(0.0, config.period_s, n, endpoint=False)
    return t, sample(config, t)
