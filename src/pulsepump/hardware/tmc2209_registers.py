"""Host-side TMC2209 register constants and current-conversion helpers."""

from __future__ import annotations

import math

GCONF = 0x00
GSTAT = 0x01
IFCNT = 0x02
IOIN = 0x06
IHOLD_IRUN = 0x10
TSTEP = 0x12
TPWMTHRS = 0x13
TCOOLTHRS = 0x14
MSCNT = 0x6A
MSCURACT = 0x6B
CHOPCONF = 0x6C
DRV_STATUS = 0x6F
PWMCONF = 0x70
PWM_SCALE = 0x71
SGTHRS = 0x40
SG_RESULT = 0x41

MICROSTEP_OPTIONS: list[int] = [1, 2, 4, 8, 16, 32, 64, 128, 256]

_VFS_FULL = 0.325  # V  (vsense=False)
_VFS_REDUCED = 0.180  # V  (vsense=True)


def irun_to_amps(irun: int, rsense_ohm: float = 0.11, vsense: bool = False) -> float:
    """Return RMS current for a given IRUN code (0-31).

    I_RMS = ((irun + 1) / 32) * (V_FS / (R_SENSE + 0.02)) / sqrt(2)
    """
    vfs = _VFS_REDUCED if vsense else _VFS_FULL
    return ((irun + 1) / 32.0) * (vfs / (rsense_ohm + 0.02)) / math.sqrt(2)


def amps_to_irun(amps: float, rsense_ohm: float = 0.11, vsense: bool = False) -> int:
    """Return IRUN code (0-31) closest to the requested RMS current."""
    vfs = _VFS_REDUCED if vsense else _VFS_FULL
    irun = (amps * math.sqrt(2) * (rsense_ohm + 0.02) / vfs) * 32.0 - 1
    return max(0, min(31, round(irun)))
