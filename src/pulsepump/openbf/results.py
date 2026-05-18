from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pulsepump.core import pressure

_XS = np.array([0.0, 0.25, 0.5, 0.75, 1.0])


@dataclass(frozen=True)
class VesselPressureResult:
    vessel: str
    t: np.ndarray  # shape (N,)
    p_pa: np.ndarray  # shape (N, 5) — Pa at x=[0, .25, .5, .75, 1]


def parse_vessel_pressure(run_dir: Path, vessel: str) -> VesselPressureResult:
    path = run_dir / f"{vessel}_P.last"
    data = np.loadtxt(path)
    # Columns: t p0 p1 p2 p3 p4
    t = data[:, 0]
    p_pa = data[:, 1:6]
    return VesselPressureResult(vessel=vessel, t=t, p_pa=p_pa)


def interpolate_x(result: VesselPressureResult, x_frac: float) -> np.ndarray:
    """Return pressure array (Pa) interpolated to fractional position x_frac in [0, 1]."""
    xf = float(np.clip(x_frac, 0.0, 1.0))
    idx = int(min(np.searchsorted(_XS, xf, side="right") - 1, 3))
    w = (xf - _XS[idx]) / (_XS[idx + 1] - _XS[idx])
    return (1 - w) * result.p_pa[:, idx] + w * result.p_pa[:, idx + 1]


def convert_pressure(p_pa: np.ndarray, units: str) -> np.ndarray:
    match units:
        case "Pa":
            return p_pa
        case "kPa":
            return p_pa / 1_000.0
        case "mmHg":
            return p_pa / 133.322
        case "psi":
            return p_pa / 6_894.76
        case "bar":
            return p_pa / 100_000.0
        case _:
            return p_pa / 1_000.0


def to_display_units(p_pa: np.ndarray) -> np.ndarray:
    return convert_pressure(p_pa, pressure.units())
