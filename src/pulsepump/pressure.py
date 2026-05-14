from __future__ import annotations

import os

import numpy as np
from dotenv import load_dotenv

load_dotenv()

ADC_VREF = float(os.getenv("ADC_VREF", "3.3"))
ADC_FULL_SCALE = float(os.getenv("ADC_FULL_SCALE", "65535"))
DIVIDER_RATIO = float(os.getenv("DIVIDER_RATIO", "0.6"))
V_SENSOR_MIN = float(os.getenv("V_SENSOR_MIN", "0.5"))
V_SENSOR_MAX = float(os.getenv("V_SENSOR_MAX", "4.5"))
P_FULL_SCALE = float(os.getenv("P_FULL_SCALE", "100.0"))
P_UNITS = os.getenv("P_UNITS", "kPa")

_V_SPAN = V_SENSOR_MAX - V_SENSOR_MIN
_COUNTS_TO_V_SENSOR = ADC_VREF / (ADC_FULL_SCALE * DIVIDER_RATIO)


def counts_to_pressure(raw: int) -> float:
    v_sensor = raw * _COUNTS_TO_V_SENSOR
    return (v_sensor - V_SENSOR_MIN) / _V_SPAN * P_FULL_SCALE


def counts_to_pressure_arr(arr: np.ndarray) -> np.ndarray:
    v_sensor = arr * _COUNTS_TO_V_SENSOR
    return (v_sensor - V_SENSOR_MIN) / _V_SPAN * P_FULL_SCALE
