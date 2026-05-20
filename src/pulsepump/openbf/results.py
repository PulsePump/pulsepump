from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pulsepump.core import pressure
from pulsepump.core.units import convert

# Per openBF's output.jl, the five spatial sample columns are taken at vessel
# nodes 1, round(M*0.25), round(M*0.5), round(M*0.75), M — i.e. the inlet
# node, three interior quartile nodes, and the outlet node. The first column
# is therefore at x ≈ 1/M (not exactly 0); the error is negligible for
# typical M and we treat it as 0.
_XS = np.array([0.0, 0.25, 0.5, 0.75, 1.0])


@dataclass(frozen=True)
class VesselPressureResult:
    vessel: str
    t: np.ndarray  # shape (N,)
    p_pa: np.ndarray  # shape (N, 5) — Pa at x=[0, .25, .5, .75, 1]


def parse_vessel_pressure(
    run_dir: Path, vessel: str, gauge_offset_pa: float = 0.0
) -> VesselPressureResult:
    """Parse a ``{vessel}_P.last`` file written by openBF.

    The ``.last`` file holds the most recently simulated cardiac cycle only
    (openBF overwrites it on every cycle). Columns are ``t p0 p1 p2 p3 p4``.

    openBF writes transmural pressure ``P - Pout``, not absolute pressure. If
    your downstream use needs an absolute baseline (e.g. systemic mean
    pressure), pass it via ``gauge_offset_pa``; the value is added to every
    pressure sample.
    """
    path = run_dir / f"{vessel}_P.last"
    data = np.loadtxt(path)
    t = data[:, 0]
    p_pa = data[:, 1:6] + gauge_offset_pa
    return VesselPressureResult(vessel=vessel, t=t, p_pa=p_pa)


def interpolate_x(result: VesselPressureResult, x_frac: float) -> np.ndarray:
    """Return pressure array (Pa) interpolated to fractional position x_frac in [0, 1]."""
    xf = float(np.clip(x_frac, 0.0, 1.0))
    idx = int(min(np.searchsorted(_XS, xf, side="right") - 1, 3))
    w = (xf - _XS[idx]) / (_XS[idx + 1] - _XS[idx])
    return (1 - w) * result.p_pa[:, idx] + w * result.p_pa[:, idx + 1]


def convert_pressure(p_pa: np.ndarray, units: str) -> np.ndarray:
    """Convert a Pa array to ``units``. Unknown units fall back to Pa."""
    return convert(p_pa, "Pa", units)


def to_display_units(p_pa: np.ndarray) -> np.ndarray:
    return convert_pressure(p_pa, pressure.units())
