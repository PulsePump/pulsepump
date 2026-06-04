"""ADC-to-pressure conversion for the PulsePump sensor chain.

Two-stage pipeline:
  counts → voltage:  voltage = 0.5 + (counts / 2**16) * (4.5 - 0.5)
  voltage → mmHg:    mmhg    = 151 * voltage - 85.7
"""

from __future__ import annotations

import numpy as np

_UNITS = "mmHg"


def counts_to_voltage(raw: int | float) -> float:
    return 0.5 + (raw / 2**16) * (4.5 - 0.5)


def counts_to_pressure(raw: int) -> float:
    voltage = counts_to_voltage(raw)
    return 151 * voltage - 85.7


def counts_to_pressure_arr(arr: np.ndarray) -> np.ndarray:
    voltage = 0.5 + (arr / 2**16) * (4.5 - 0.5)
    return 151 * voltage - 85.7


def units() -> str:
    return _UNITS
