from __future__ import annotations

import numpy as np
import pytest

from pulsepump.core.units import PA_PER_UNIT, convert
from pulsepump.openbf.results import convert_pressure


@pytest.mark.parametrize("unit", ["Pa", "mmHg", "psi", "bar"])
def test_identity(unit: str) -> None:
    assert convert(123.0, unit, unit) == 123.0


@pytest.mark.parametrize("unit", ["Pa", "mmHg", "psi", "bar"])
def test_round_trip_through_pa(unit: str) -> None:
    value = 42.5
    pa = convert(value, unit, "Pa")
    back = convert(pa, "Pa", unit)
    assert back == pytest.approx(value, rel=1e-12)


def test_known_constants() -> None:
    # NIST values that the module should match.
    assert PA_PER_UNIT["mmHg"] == pytest.approx(133.322387415, rel=1e-12)
    assert PA_PER_UNIT["psi"] == pytest.approx(6_894.757293168, rel=1e-9)
    assert PA_PER_UNIT["bar"] == 100_000.0
    assert PA_PER_UNIT["Pa"] == 1.0
    assert "kPa" not in PA_PER_UNIT


def test_convert_pressure_matches_old_behaviour() -> None:
    p_pa = np.array([1000.0, 5000.0, 13332.2387415])
    assert np.allclose(convert_pressure(p_pa, "bar"), p_pa / 100_000.0)
    assert convert_pressure(p_pa, "mmHg") == pytest.approx(p_pa / 133.322, rel=3e-6)
    assert convert_pressure(p_pa, "psi") == pytest.approx(p_pa / 6_894.76, rel=3e-6)
    # Unknown fallback → Pa.
    assert np.allclose(convert_pressure(p_pa, "unknown"), p_pa)


def test_array_inputs() -> None:
    arr = np.array([0.0, 1.0, 100.0])
    out = convert(arr, "mmHg", "Pa")
    assert isinstance(out, np.ndarray)
    assert out[0] == 0.0
    assert out[1] == pytest.approx(133.322387415, rel=1e-12)
