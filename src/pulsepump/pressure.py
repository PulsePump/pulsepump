from __future__ import annotations

import numpy as np

ADC_VREF = 3.3
ADC_FULL_SCALE = 65535.0

# Defaults for parameters owned by the Pressure Sensors panel. The panel
# overrides these at runtime via `update(...)`; values persist across launches
# via QSettings.
DIVIDER_RATIO = 0.66  # 3.3 V ADC / 5 V sensor supply
V_SENSOR_MIN = 0.5
V_SENSOR_MAX = 4.5
P_FULL_SCALE = 100.0
P_UNITS = "kPa"


class _Config:
    """Mutable pressure-conversion parameters, recomputed on update."""

    def __init__(self) -> None:
        self.adc_vref = ADC_VREF
        self.adc_full_scale = ADC_FULL_SCALE
        self.divider_ratio = DIVIDER_RATIO
        self.v_sensor_min = V_SENSOR_MIN
        self.v_sensor_max = V_SENSOR_MAX
        self.p_full_scale = P_FULL_SCALE
        self.units = P_UNITS
        self._recompute()

    def update(
        self,
        *,
        v_sensor_min: float | None = None,
        v_sensor_max: float | None = None,
        p_full_scale: float | None = None,
        divider_ratio: float | None = None,
        units: str | None = None,
    ) -> None:
        if v_sensor_min is not None:
            self.v_sensor_min = v_sensor_min
        if v_sensor_max is not None:
            self.v_sensor_max = v_sensor_max
        if p_full_scale is not None:
            self.p_full_scale = p_full_scale
        if divider_ratio is not None:
            self.divider_ratio = divider_ratio
        if units is not None:
            self.units = units
        self._recompute()

    def _recompute(self) -> None:
        self._v_span = max(self.v_sensor_max - self.v_sensor_min, 1e-9)
        self._counts_to_v = self.adc_vref / (self.adc_full_scale * self.divider_ratio)


_cfg = _Config()


def counts_to_pressure(raw: int) -> float:
    v_sensor = raw * _cfg._counts_to_v
    return (v_sensor - _cfg.v_sensor_min) / _cfg._v_span * _cfg.p_full_scale


def counts_to_pressure_arr(arr: np.ndarray) -> np.ndarray:
    v_sensor = arr * _cfg._counts_to_v
    return (v_sensor - _cfg.v_sensor_min) / _cfg._v_span * _cfg.p_full_scale


def update(
    *,
    v_sensor_min: float | None = None,
    v_sensor_max: float | None = None,
    p_full_scale: float | None = None,
    divider_ratio: float | None = None,
    units: str | None = None,
) -> None:
    _cfg.update(
        v_sensor_min=v_sensor_min,
        v_sensor_max=v_sensor_max,
        p_full_scale=p_full_scale,
        divider_ratio=divider_ratio,
        units=units,
    )


def units() -> str:
    return _cfg.units
