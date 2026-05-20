"""MicroPython TMC2209 UART driver for single-wire half-duplex communication."""

from machine import UART, Pin
import time

GCONF      = 0x00
GSTAT      = 0x01
IFCNT      = 0x02
IOIN       = 0x06
IHOLD_IRUN = 0x10
TSTEP      = 0x12
TPWMTHRS   = 0x13
TCOOLTHRS  = 0x14
MSCNT      = 0x6A
MSCURACT   = 0x6B
CHOPCONF   = 0x6C
DRV_STATUS = 0x6F
PWMCONF    = 0x70
PWM_SCALE  = 0x71
SGTHRS     = 0x40
SG_RESULT  = 0x41

_SYNC     = 0x05
_WRITE    = 0x80

_MRES_MAP = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}


class TMC2209:
    def __init__(self, uart_id=0, tx_pin=0, rx_pin=1, slave_addr=0, baudrate=115200):
        self._addr = slave_addr
        self._uart = UART(
            uart_id,
            baudrate=baudrate,
            tx=Pin(tx_pin),
            rx=Pin(rx_pin),
            bits=8,
            parity=None,
            stop=1,
        )
        # Allow UART to settle
        time.sleep_ms(10)

    def _crc8(self, data: bytes) -> int:
        crc = 0
        for byte in data:
            for _ in range(8):
                if (crc >> 7) ^ (byte & 1):
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
                byte >>= 1
        return crc

    def _write_reg(self, reg: int, value: int) -> None:
        data = bytes([
            _SYNC, self._addr, reg | _WRITE,
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])
        datagram = data + bytes([self._crc8(data)])
        self._uart.write(datagram)
        # Discard the 8 echo bytes that appear on RX due to single-wire loopback
        time.sleep_ms(2)
        self._uart.read(8)

    def _read_reg(self, reg: int) -> int:
        req = bytes([_SYNC, self._addr, reg])
        req = req + bytes([self._crc8(req)])
        self._uart.write(req)
        # Discard 4 echo bytes
        time.sleep_ms(2)
        self._uart.read(4)
        # Read 8-byte response from TMC2209
        time.sleep_ms(3)
        resp = self._uart.read(8)
        if resp is None or len(resp) != 8:
            raise OSError("TMC2209 read timeout")
        expected_crc = self._crc8(resp[:7])
        if resp[7] != expected_crc:
            raise OSError("TMC2209 CRC error")
        return (resp[3] << 24) | (resp[4] << 16) | (resp[5] << 8) | resp[6]

    def init(self) -> None:
        gconf = self._read_reg(GCONF)
        # pdn_disable=1 (bit 6), mstep_reg_select=1 (bit 7)
        gconf |= (1 << 6) | (1 << 7)
        self._write_reg(GCONF, gconf)

    def enable(self) -> None:
        self.set_chopper_config()

    def disable(self) -> None:
        chopconf = self._read_reg(CHOPCONF)
        chopconf &= ~0xF  # TOFF = 0
        self._write_reg(CHOPCONF, chopconf)

    def set_current(self, irun: int, ihold: int, iholddelay: int = 6) -> None:
        value = (iholddelay << 16) | (irun << 8) | ihold
        self._write_reg(IHOLD_IRUN, value)

    def set_microsteps(self, ms: int) -> None:
        if ms not in _MRES_MAP:
            raise ValueError("ms must be one of 1,2,4,8,16,32,64,128,256")
        mres = _MRES_MAP[ms]
        chopconf = self._read_reg(CHOPCONF)
        chopconf = (chopconf & ~(0xF << 24)) | (mres << 24)
        self._write_reg(CHOPCONF, chopconf)

    def set_spreadcycle(self, enable: bool) -> None:
        gconf = self._read_reg(GCONF)
        if enable:
            gconf |= (1 << 2)
        else:
            gconf &= ~(1 << 2)
        self._write_reg(GCONF, gconf)

    def set_stealthchop_threshold(self, tpwmthrs: int) -> None:
        self._write_reg(TPWMTHRS, tpwmthrs)

    def set_stallguard_threshold(self, sgthrs: int) -> None:
        self._write_reg(SGTHRS, sgthrs)

    def set_coolthrs(self, tcoolthrs: int) -> None:
        self._write_reg(TCOOLTHRS, tcoolthrs)

    def set_shaft(self, invert: bool) -> None:
        gconf = self._read_reg(GCONF)
        if invert:
            gconf |= (1 << 4)
        else:
            gconf &= ~(1 << 4)
        self._write_reg(GCONF, gconf)

    def set_chopper_config(self, toff: int = 5, hstrt: int = 4, hend: int = 0, tbl: int = 2) -> None:
        chopconf = self._read_reg(CHOPCONF)
        # Preserve MRES (bits 27-24); clear toff/hstrt/hend/tbl fields
        chopconf &= (0xF << 24)
        chopconf |= (tbl << 15) | ((hend & 0xF) << 7) | ((hstrt & 0x7) << 4) | (toff & 0xF)
        self._write_reg(CHOPCONF, chopconf)

    def read_gstat(self) -> dict:
        v = self._read_reg(GSTAT)
        return {
            "reset":  bool(v & 1),
            "drv_err": bool(v & 2),
            "uv_cp":  bool(v & 4),
        }

    def read_drv_status(self) -> dict:
        v = self._read_reg(DRV_STATUS)
        return {
            "otpw":      bool(v & (1 << 0)),
            "ot":        bool(v & (1 << 1)),
            "s2ga":      bool(v & (1 << 2)),
            "s2gb":      bool(v & (1 << 3)),
            "s2vsa":     bool(v & (1 << 4)),
            "s2vsb":     bool(v & (1 << 5)),
            "ola":       bool(v & (1 << 6)),
            "olb":       bool(v & (1 << 7)),
            "t120":      bool(v & (1 << 8)),
            "t143":      bool(v & (1 << 9)),
            "t150":      bool(v & (1 << 10)),
            "t157":      bool(v & (1 << 11)),
            "cs_actual": (v >> 16) & 0x1F,
            "stealth":   bool(v & (1 << 30)),
            "stst":      bool(v & (1 << 31)),
        }

    def read_mscnt(self) -> int:
        return self._read_reg(MSCNT) & 0x3FF

    def read_mscuract(self) -> dict:
        v = self._read_reg(MSCURACT)
        cur_a = v & 0x1FF
        if cur_a & 0x100:
            cur_a -= 0x200
        cur_b = (v >> 16) & 0x1FF
        if cur_b & 0x100:
            cur_b -= 0x200
        return {"cur_a": cur_a, "cur_b": cur_b}

    def read_tstep(self) -> int:
        return self._read_reg(TSTEP)

    def read_sg_result(self) -> int:
        return self._read_reg(SG_RESULT) & 0x1FF

    def read_ifcnt(self) -> int:
        return self._read_reg(IFCNT) & 0xFF

    def read_ioin(self) -> dict:
        v = self._read_reg(IOIN)
        return {
            "enn":     bool(v & (1 << 0)),
            "ms1":     bool(v & (1 << 2)),
            "ms2":     bool(v & (1 << 3)),
            "diag":    bool(v & (1 << 4)),
            "pdn_uart": bool(v & (1 << 6)),
            "step":    bool(v & (1 << 7)),
            "spread_en": bool(v & (1 << 8)),
            "dir":     bool(v & (1 << 9)),
            "version": (v >> 24) & 0xFF,
        }
