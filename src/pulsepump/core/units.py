"""Pressure-unit conversion shared across the codebase.

Single source of truth for the Pa-per-unit constants. Anywhere else in the
codebase that needs to convert between pressure units should call
:func:`convert` rather than inlining its own constants.
"""

from __future__ import annotations

from typing import Literal, cast

import numpy as np

PressureUnits = Literal["Pa", "mmHg", "psi", "bar"]

# Pascals per unit. Values from NIST.
PA_PER_UNIT: dict[str, float] = {
    "Pa": 1.0,
    "mmHg": 133.322387415,
    "psi": 6_894.757293168,
    "bar": 100_000.0,
}


def convert[T: (float, np.ndarray)](value: T, from_unit: str, to_unit: str) -> T:
    """Convert ``value`` from ``from_unit`` to ``to_unit``.

    Accepts a scalar float or a numpy array. Unknown units fall back to Pa
    on either side.
    """
    if from_unit == to_unit:
        return value
    in_pa = PA_PER_UNIT.get(from_unit, PA_PER_UNIT["Pa"])
    out_pa = PA_PER_UNIT.get(to_unit, PA_PER_UNIT["Pa"])
    return cast(T, value * (in_pa / out_pa))
