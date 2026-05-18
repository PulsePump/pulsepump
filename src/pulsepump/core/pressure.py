"""ADC-to-pressure conversion for the PulsePump sensor chain.

Converts raw 16-bit ADC counts from the Raspberry Pi Pico into calibrated
pressure values using a two-stage pipeline: counts → sensor voltage (via the
resistor divider ratio and ADC reference) → pressure (via a linear map from
the sensor's voltage span to its full-scale pressure range).

All conversion parameters are held in a module-level singleton; call
:func:`update` to change them at runtime. Changes take effect immediately
for all subsequent calls to :func:`counts_to_pressure` and
:func:`counts_to_pressure_arr`.
"""

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
        """Initialise with module-level defaults."""
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
        """Update one or more conversion parameters and recompute derived state.

        Only keyword arguments that are not ``None`` are applied; omitted
        arguments leave the current value unchanged.

        :param v_sensor_min: Sensor voltage at zero pressure, in volts.
        :param v_sensor_max: Sensor voltage at full-scale pressure, in volts;
                             must be greater than *v_sensor_min*.
        :param p_full_scale: Full-scale pressure in the active units.
        :param divider_ratio: Resistor-divider ratio between sensor supply and
                              ADC reference (``V_adc / V_supply``).
        :param units: Display unit string, e.g. ``"kPa"``.
        """
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
        """Recompute cached derived quantities after a parameter change."""
        self._v_span = max(self.v_sensor_max - self.v_sensor_min, 1e-9)
        self._counts_to_v = self.adc_vref / (self.adc_full_scale * self.divider_ratio)


_cfg = _Config()


def counts_to_pressure(raw: int) -> float:
    """Convert a single raw ADC count to a calibrated pressure value.

    :param raw: 16-bit ADC count in ``[0, 65535]``.
    :returns: Pressure in the current unit (see :func:`units`).
    """
    v_sensor = raw * _cfg._counts_to_v
    return (v_sensor - _cfg.v_sensor_min) / _cfg._v_span * _cfg.p_full_scale


def counts_to_pressure_arr(arr: np.ndarray) -> np.ndarray:
    """Convert an array of raw ADC counts to calibrated pressure values.

    Vectorised equivalent of :func:`counts_to_pressure`.

    :param arr: Array of 16-bit ADC counts.
    :returns: Float array of pressure values in the current unit.
    """
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
    """Update the module-level conversion parameters.

    Delegates to :meth:`_Config.update`; see that method for parameter
    descriptions.
    """
    _cfg.update(
        v_sensor_min=v_sensor_min,
        v_sensor_max=v_sensor_max,
        p_full_scale=p_full_scale,
        divider_ratio=divider_ratio,
        units=units,
    )


def units() -> str:
    """Return the current pressure unit string."""
    return _cfg.units
