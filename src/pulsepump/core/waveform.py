"""Waveform synthesis for the PulsePump function generator.

Provides :class:`WaveformConfig`, an immutable parameter snapshot, and two
sampling functions — :func:`sample` for arbitrary time arrays and
:func:`sample_one_cycle` for a single period at the configured update rate.
Six waveform shapes are supported via :class:`WaveformType`.

.. code-block:: python

    cfg = WaveformConfig(type=WaveformType.SINE, bpm=60.0, amplitude=10.0,
                         offset=50.0, duty=0.5, symmetry=0.5, phase=0.0,
                         sample_rate_hz=100.0, interpolation=Interpolation.FIRST_ORDER_HOLD)
    t, y = sample_one_cycle(cfg)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class WaveformType(StrEnum):
    """Waveform shape identifiers for the function generator."""

    CONSTANT = "constant"
    SINE = "sine"
    SQUARE = "square"
    TRIANGLE = "triangle"
    SAWTOOTH = "sawtooth"
    PULSE = "pulse"


class Interpolation(StrEnum):
    """Interpolation mode used when rendering waveform samples for display."""

    ZERO_ORDER_HOLD = "zoh"
    FIRST_ORDER_HOLD = "foh"


@dataclass(frozen=True, slots=True)
class WaveformConfig:
    """Immutable snapshot of every function-generator parameter.

    Amplitude and offset are in the user's chosen pressure units; the math is
    unit-agnostic. ``duty``, ``symmetry``, and ``phase`` are normalised to
    ``[0, 1]``. ``sample_rate_hz`` is the setpoint update rate the fluid
    simulation will consume.

    :param type: Waveform shape.
    :param bpm: Cycle rate in beats per minute; must be greater than zero.
    :param amplitude: Peak-to-centre displacement in pressure units.
    :param offset: DC offset in pressure units.
    :param duty: High-level fraction of the cycle for SQUARE and PULSE shapes,
                 in ``[0, 1]``.
    :param symmetry: Rise/fall split for TRIANGLE and SAWTOOTH, in ``[0, 1]``.
                     At 0.5 the triangle is symmetric; approaching 1 gives a
                     rising ramp.
    :param phase: Initial phase offset in cycles, in ``[0, 1)``.
    :param sample_rate_hz: Output sample rate in Hz.
    :param interpolation: Interpolation mode used by the UI preview.
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
        """Cycle period in seconds derived from :attr:`bpm`."""
        return 60.0 / max(self.bpm, 1e-6)

    @property
    def samples_per_cycle(self) -> int:
        """Number of samples in one cycle at the configured sample rate."""
        return max(round(self.sample_rate_hz * self.period_s), 1)


def _shape(config: WaveformConfig, u: np.ndarray) -> np.ndarray:
    """Evaluate the unit-amplitude waveform shape at normalised phase.

    :param config: Waveform parameters; only :attr:`~WaveformConfig.type`,
                   :attr:`~WaveformConfig.duty`, and
                   :attr:`~WaveformConfig.symmetry` are used.
    :param u: Normalised phase array with values in ``[0, 1)``.
    :returns: Unit-amplitude output array of the same shape as *u*.
    """
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
    """Evaluate the waveform at an arbitrary array of times.

    :param config: Waveform parameters.
    :param t: Time values in seconds.
    :returns: Pressure samples in the same units as
              :attr:`~WaveformConfig.amplitude` and
              :attr:`~WaveformConfig.offset`.
    """
    u = ((t / config.period_s) + config.phase) % 1.0
    return config.amplitude * _shape(config, u) + config.offset


# Per-type defaults targeting a 80-120 mmHg oscillation at 60 BPM. For shapes
# that swing symmetrically around zero (sine/square/triangle/sawtooth) this is
# amplitude=20, offset=100. PULSE's _shape returns 0/1 (asymmetric), so to get
# baseline=80 peak=120 we use amplitude=40 offset=80.
_DEFAULT_FG_PARAMS: dict[WaveformType, dict[str, float]] = {
    WaveformType.CONSTANT: {"amplitude": 0.0, "offset": 100.0, "duty": 0.5, "symmetry": 0.5},
    WaveformType.SINE: {"amplitude": 20.0, "offset": 100.0, "duty": 0.5, "symmetry": 0.5},
    WaveformType.SQUARE: {"amplitude": 20.0, "offset": 100.0, "duty": 0.5, "symmetry": 0.5},
    WaveformType.TRIANGLE: {"amplitude": 20.0, "offset": 100.0, "duty": 0.5, "symmetry": 0.5},
    WaveformType.SAWTOOTH: {"amplitude": 20.0, "offset": 100.0, "duty": 0.5, "symmetry": 0.5},
    WaveformType.PULSE: {"amplitude": 40.0, "offset": 80.0, "duty": 0.2, "symmetry": 0.5},
}


def default_fg_config(
    type: WaveformType,
    sample_rate_hz: float,
    bpm: float = 60.0,
    phase: float = 0.0,
    interpolation: Interpolation = Interpolation.FIRST_ORDER_HOLD,
) -> WaveformConfig:
    """Return a :class:`WaveformConfig` populated with physiological defaults.

    Amplitude/offset are chosen so the wave oscillates between 80 and 120
    (assumed mmHg by the inspector's default). Callers in other unit systems
    should treat these as numeric defaults and adjust as needed.
    """
    p = _DEFAULT_FG_PARAMS[type]
    return WaveformConfig(
        type=type,
        bpm=bpm,
        amplitude=p["amplitude"],
        offset=p["offset"],
        duty=p["duty"],
        symmetry=p["symmetry"],
        phase=phase,
        sample_rate_hz=sample_rate_hz,
        interpolation=interpolation,
    )


def sample_one_cycle(config: WaveformConfig, n: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return time and sample arrays covering exactly one complete cycle.

    The time axis starts at zero and ends just before ``config.period_s``
    (endpoint excluded), matching the periodicity of the waveform.

    :param config: Waveform parameters.
    :param n: Number of samples; defaults to
              :attr:`~WaveformConfig.samples_per_cycle`.
    :returns: Tuple ``(t, y)`` where *t* is in seconds and *y* is in
              the programme's pressure units.
    """
    if n is None:
        n = config.samples_per_cycle
    t = np.linspace(0.0, config.period_s, n, endpoint=False)
    return t, sample(config, t)
