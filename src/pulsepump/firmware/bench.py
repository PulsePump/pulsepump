"""MicroPython bench firmware for the Hardware Bench window.

One unified loop that:
  * reads newline-JSON commands from sys.stdin (non-blocking)
  * runs a cooperative scheduler over a configurable set of devices
  * emits newline-JSON sample frames on sys.stdout

Wire format is documented in pulsepump.hardware.bench.__init__.

This file is uploaded to the Pico as ``:bench.py`` and run via ``mpremote run``.
It is MicroPython-only — no host imports.
"""

import sys
import select
import time
import ujson
from machine import ADC, PWM, Pin, UART


def _now_us():
    return time.ticks_us()


# ---------------------------------------------------------------------------
# Device drivers
# ---------------------------------------------------------------------------


class PressureDevice:
    type = "pressure"

    def __init__(self, cfg):
        self.id = cfg["id"]
        self.adc_pin = int(cfg.get("adc_pin", 26))
        self._adc = ADC(self.adc_pin)
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", 200))

    def reconfigure(self, cfg):
        new_pin = int(cfg.get("adc_pin", self.adc_pin))
        if new_pin != self.adc_pin:
            self.adc_pin = new_pin
            self._adc = ADC(new_pin)
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", self.sample_rate_hz))

    def sample(self):
        return {"counts": self._adc.read_u16()}

    def set_field(self, field, value):
        pass

    def advance_steps(self):
        pass

    def teardown(self):
        pass


def _angle_to_duty_u16(angle_deg, max_angle, min_us, max_us, freq):
    span = max_us - min_us
    pulse_us = min_us + (angle_deg / max_angle) * span
    period_us = 1_000_000 // freq
    return int(pulse_us / period_us * 65535), int(pulse_us)


class ServoDevice:
    type = "servo"

    def __init__(self, cfg):
        self.id = cfg["id"]
        self.pwm_pin = int(cfg.get("pwm_pin", 15))
        self.pwm_freq_hz = int(cfg.get("pwm_freq_hz", 50))
        self.min_us = int(cfg.get("min_us", 1000))
        self.max_us = int(cfg.get("max_us", 2000))
        self.max_angle = float(cfg.get("max_angle_deg", 180.0))
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", 50))
        self._pwm = PWM(Pin(self.pwm_pin))
        self._pwm.freq(self.pwm_freq_hz)
        self.commanded_angle = 0.0
        self._duty = 0
        self._pulse_us = 0
        self._apply_angle(self.commanded_angle)

    def reconfigure(self, cfg):
        new_pin = int(cfg.get("pwm_pin", self.pwm_pin))
        if new_pin != self.pwm_pin:
            self._pwm.deinit()
            self.pwm_pin = new_pin
            self._pwm = PWM(Pin(self.pwm_pin))
        self.pwm_freq_hz = int(cfg.get("pwm_freq_hz", self.pwm_freq_hz))
        self._pwm.freq(self.pwm_freq_hz)
        self.min_us = int(cfg.get("min_us", self.min_us))
        self.max_us = int(cfg.get("max_us", self.max_us))
        self.max_angle = float(cfg.get("max_angle_deg", self.max_angle))
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", self.sample_rate_hz))
        self._apply_angle(self.commanded_angle)

    def _apply_angle(self, deg):
        if deg < 0:
            deg = 0.0
        elif deg > self.max_angle:
            deg = self.max_angle
        self.commanded_angle = deg
        self._duty, self._pulse_us = _angle_to_duty_u16(
            deg, self.max_angle, self.min_us, self.max_us, self.pwm_freq_hz
        )
        self._pwm.duty_u16(self._duty)

    def set_field(self, field, value):
        if field == "angle_deg":
            self._apply_angle(float(value))

    def advance_steps(self):
        pass

    def sample(self):
        return {
            "commanded_angle_deg": self.commanded_angle,
            "pulse_us": self._pulse_us,
            "duty_u16": self._duty,
            "pwm_freq_hz": self.pwm_freq_hz,
        }

    def teardown(self):
        try:
            self._pwm.deinit()
        except Exception:
            pass


# ---- TMC2209 minimal driver --------------------------------------------------
# Inlined here so the bench firmware is one self-contained file. Uses single
# wire UART for register reads/writes plus STEP/DIR/EN pins for motion.


_GCONF      = 0x00
_IFCNT      = 0x02
_IOIN       = 0x06
_IHOLD_IRUN = 0x10
_TSTEP      = 0x12
_MSCNT      = 0x6A
_MSCURACT   = 0x6B
_CHOPCONF   = 0x6C
_DRV_STATUS = 0x6F
_SG_RESULT  = 0x41
_SYNC       = 0x05
_WRITE      = 0x80

# CHOPCONF MRES field [27:24]: 0=256, 1=128, 2=64, ..., 8=1 (full step)
_MRES_ENC = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}


def _crc8(data):
    crc = 0
    for byte in data:
        b = byte
        for _ in range(8):
            if (crc >> 7) ^ (b & 1):
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
            b >>= 1
    return crc


class StepperDevice:
    type = "stepper"

    def __init__(self, cfg):
        self.id = cfg["id"]
        self.uart_id = int(cfg.get("uart_id", 0))
        self.tx_pin = int(cfg.get("tx_pin", 0))
        self.rx_pin = int(cfg.get("rx_pin", 1))
        self.step_pin_n = int(cfg.get("step_pin", 2))
        self.dir_pin_n = int(cfg.get("dir_pin", 4))
        self.en_pin_n = int(cfg.get("en_pin", 3))
        self.slave_addr = int(cfg.get("slave_addr", 0))
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", 20))
        self.run_current = int(cfg.get("run_current", 16))
        self.hold_current = int(cfg.get("hold_current", 8))
        self.microsteps = int(cfg.get("microsteps", 16))

        self._uart = UART(self.uart_id, baudrate=115200,
                          tx=Pin(self.tx_pin), rx=Pin(self.rx_pin),
                          bits=8, parity=None, stop=1)
        self._step_pin = Pin(self.step_pin_n, Pin.OUT, value=0)
        self._dir_pin = Pin(self.dir_pin_n, Pin.OUT, value=0)
        self._en_pin = Pin(self.en_pin_n, Pin.OUT, value=1)  # disabled by default
        time.sleep_ms(10)
        self.commanded_step = 0
        self.step_rate_hz = 0.0
        self.direction = 0
        self.enabled = False

        # Non-blocking step state
        self._steps_remaining = 0
        self._step_phase = 0      # 0=idle, 1=pin-high pending, 2=pin-low pending
        self._step_dir = 1
        self._half_us = 500
        self._next_edge_us = 0

        try:
            gconf = self._read_reg(_GCONF)
            self._write_reg(_GCONF, gconf | (1 << 6) | (1 << 7))
            self._apply_current()
            self._apply_microsteps()
        except OSError:
            pass

    def _apply_current(self):
        val = (self.hold_current & 0x1F) | ((self.run_current & 0x1F) << 8) | (6 << 16)
        self._write_reg(_IHOLD_IRUN, val)

    def _apply_microsteps(self):
        mres = _MRES_ENC.get(self.microsteps, 4)
        chopconf = self._read_reg(_CHOPCONF)
        chopconf = (chopconf & 0xF0FFFFFF) | (mres << 24)
        self._write_reg(_CHOPCONF, chopconf)

    def reconfigure(self, cfg):
        changed = (
            int(cfg.get("uart_id", self.uart_id)) != self.uart_id
            or int(cfg.get("tx_pin", self.tx_pin)) != self.tx_pin
            or int(cfg.get("rx_pin", self.rx_pin)) != self.rx_pin
        )
        if changed:
            self.uart_id = int(cfg.get("uart_id", self.uart_id))
            self.tx_pin = int(cfg.get("tx_pin", self.tx_pin))
            self.rx_pin = int(cfg.get("rx_pin", self.rx_pin))
            self._uart = UART(self.uart_id, baudrate=115200,
                              tx=Pin(self.tx_pin), rx=Pin(self.rx_pin),
                              bits=8, parity=None, stop=1)
        for attr, key in (
            ("step_pin_n", "step_pin"),
            ("dir_pin_n", "dir_pin"),
            ("en_pin_n", "en_pin"),
        ):
            new = int(cfg.get(key, getattr(self, attr)))
            setattr(self, attr, new)
        self._step_pin = Pin(self.step_pin_n, Pin.OUT, value=0)
        self._dir_pin = Pin(self.dir_pin_n, Pin.OUT, value=self.direction)
        self._en_pin = Pin(self.en_pin_n, Pin.OUT, value=0 if self.enabled else 1)
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", self.sample_rate_hz))

        new_run = int(cfg.get("run_current", self.run_current))
        new_hold = int(cfg.get("hold_current", self.hold_current))
        if new_run != self.run_current or new_hold != self.hold_current:
            self.run_current = new_run
            self.hold_current = new_hold
            try:
                self._apply_current()
            except OSError:
                pass
        else:
            self.run_current = new_run
            self.hold_current = new_hold

        new_ms = int(cfg.get("microsteps", self.microsteps))
        if new_ms != self.microsteps:
            self.microsteps = new_ms
            try:
                self._apply_microsteps()
            except OSError:
                pass
        else:
            self.microsteps = new_ms

    def _write_reg(self, reg, value):
        data = bytes([_SYNC, self.slave_addr, reg | _WRITE,
                      (value >> 24) & 0xFF, (value >> 16) & 0xFF,
                      (value >> 8) & 0xFF, value & 0xFF])
        dgram = data + bytes([_crc8(data)])
        self._uart.write(dgram)
        time.sleep_ms(2)
        self._uart.read(8)

    def _read_reg(self, reg):
        req = bytes([_SYNC, self.slave_addr, reg])
        req = req + bytes([_crc8(req)])
        self._uart.write(req)
        time.sleep_ms(2)
        self._uart.read(4)
        time.sleep_ms(3)
        resp = self._uart.read(8)
        if resp is None or len(resp) != 8:
            raise OSError("tmc read timeout")
        if resp[7] != _crc8(resp[:7]):
            raise OSError("tmc crc")
        return (resp[3] << 24) | (resp[4] << 16) | (resp[5] << 8) | resp[6]

    def set_field(self, field, value):
        if field == "enabled":
            self.enabled = bool(value)
            self._en_pin.value(0 if self.enabled else 1)

    def step(self, steps, rate_hz, direction):
        self._step_pin.value(0)  # ensure pin is low before starting
        self.direction = 1 if direction else 0
        self._dir_pin.value(self.direction)
        self.step_rate_hz = float(rate_hz)
        self._step_dir = 1 if self.direction else -1
        self._half_us = 1_000_000 // max(1, int(rate_hz) * 2)
        self._steps_remaining = int(steps)
        self._step_phase = 1
        self._next_edge_us = time.ticks_us()

    def advance_steps(self):
        """Emit as many pending step edges as are due without blocking."""
        if self._steps_remaining <= 0:
            return
        now = time.ticks_us()
        while self._steps_remaining > 0:
            if time.ticks_diff(now, self._next_edge_us) < 0:
                break
            if self._step_phase == 1:
                self._step_pin.value(1)
                self._step_phase = 2
                self._next_edge_us = time.ticks_add(self._next_edge_us, self._half_us)
            else:
                self._step_pin.value(0)
                self._steps_remaining -= 1
                self.commanded_step += self._step_dir
                if self._steps_remaining > 0:
                    self._step_phase = 1
                    self._next_edge_us = time.ticks_add(self._next_edge_us, self._half_us)
                else:
                    self._step_phase = 0
            now = time.ticks_us()

    def sample(self):
        out = {
            "commanded_step": self.commanded_step,
            "step_rate_hz": self.step_rate_hz,
            "dir": self.direction,
            "enabled": 1 if self.enabled else 0,
        }
        if self._steps_remaining > 0:
            # Skip UART reads during active stepping to keep the main loop fast.
            return out
        try:
            out["tstep"] = self._read_reg(_TSTEP) & 0xFFFFF
            out["sg_result"] = self._read_reg(_SG_RESULT) & 0x1FF
            out["mscnt"] = self._read_reg(_MSCNT) & 0x3FF
            mcur = self._read_reg(_MSCURACT)
            cur_a = mcur & 0x1FF
            if cur_a & 0x100:
                cur_a -= 0x200
            cur_b = (mcur >> 16) & 0x1FF
            if cur_b & 0x100:
                cur_b -= 0x200
            out["cur_a"] = cur_a
            out["cur_b"] = cur_b
            drv = self._read_reg(_DRV_STATUS)
            out["cs_actual"] = (drv >> 16) & 0x1F
            for i, name in enumerate((
                "otpw", "ot", "s2ga", "s2gb", "s2vsa", "s2vsb", "ola", "olb",
                "t120", "t143", "t150", "t157")):
                out[name] = (drv >> i) & 1
            out["stealth"] = (drv >> 30) & 1
            out["stst"] = (drv >> 31) & 1
            out["ifcnt"] = self._read_reg(_IFCNT) & 0xFF
            ioin = self._read_reg(_IOIN)
            for i, name in enumerate((
                "enn", "_p1", "ms1", "ms2", "diag", "_p5", "pdn_uart",
                "step_pin", "spread_en", "dir_pin")):
                if not name.startswith("_"):
                    out["ioin_" + name] = (ioin >> i) & 1
        except OSError:
            # Driver disconnected / wiring issue — surface as NaNs by omission.
            pass
        return out

    def teardown(self):
        self._steps_remaining = 0
        self._step_phase = 0
        self._step_pin.value(0)
        try:
            self._en_pin.value(1)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Manager + scheduler
# ---------------------------------------------------------------------------


_DEVICE_CLASSES = {
    "pressure": PressureDevice,
    "servo": ServoDevice,
    "stepper": StepperDevice,
}


def _emit(obj):
    sys.stdout.write(ujson.dumps(obj))
    sys.stdout.write("\n")


class Bench:
    def __init__(self):
        self.devices = {}     # id -> device
        self.next_us = {}     # id -> next scheduled sample time
        self.streaming = False

    def configure(self, dev_cfgs):
        new_ids = set()
        for cfg in dev_cfgs:
            dev_id = cfg["id"]
            new_ids.add(dev_id)
            if dev_id in self.devices:
                dev = self.devices[dev_id]
                if dev.type != cfg.get("type"):
                    # Type changed — tear down and rebuild.
                    dev.teardown()
                    self.devices.pop(dev_id, None)
                    self.next_us.pop(dev_id, None)
                else:
                    try:
                        dev.reconfigure(cfg)
                        _emit({"event": "configured", "id": dev_id, "ok": True})
                    except Exception as e:
                        _emit({"event": "error", "id": dev_id, "msg": str(e)})
                    continue
            kind = cfg.get("type")
            cls = _DEVICE_CLASSES.get(kind)
            if cls is None:
                _emit({"event": "error", "id": dev_id, "msg": "unknown type " + str(kind)})
                continue
            try:
                self.devices[dev_id] = cls(cfg)
                self.next_us[dev_id] = _now_us()
                _emit({"event": "configured", "id": dev_id, "ok": True})
            except Exception as e:
                _emit({"event": "error", "id": dev_id, "msg": str(e)})
        # Remove devices not in the new set.
        for old_id in list(self.devices.keys()):
            if old_id not in new_ids:
                try:
                    self.devices[old_id].teardown()
                except Exception:
                    pass
                del self.devices[old_id]
                self.next_us.pop(old_id, None)

    def start(self):
        self.streaming = True
        t = _now_us()
        for dev_id in self.devices:
            self.next_us[dev_id] = t

    def stop(self):
        self.streaming = False

    def tick(self):
        # Advance pending stepper moves — non-blocking, must run every loop iteration.
        for dev in self.devices.values():
            dev.advance_steps()

        if not self.streaming:
            return
        now = _now_us()
        for dev_id, dev in self.devices.items():
            target = self.next_us.get(dev_id, now)
            if time.ticks_diff(now, target) >= 0:
                period_us = int(1_000_000 / max(0.1, dev.sample_rate_hz))
                self.next_us[dev_id] = time.ticks_add(target, period_us)
                try:
                    data = dev.sample()
                except Exception as e:
                    _emit({"event": "error", "id": dev_id, "msg": "sample: " + str(e)})
                    continue
                _emit({"t": now, "id": dev_id, "data": data})

    def handle(self, cmd):
        name = cmd.get("cmd")
        if name == "configure":
            self.configure(cmd.get("devices", []))
        elif name == "start_streaming":
            self.start()
        elif name == "stop_streaming":
            self.stop()
        elif name == "set":
            dev = self.devices.get(cmd.get("id"))
            if dev is not None:
                dev.set_field(cmd.get("field"), cmd.get("value"))
        elif name == "step":
            dev = self.devices.get(cmd.get("id"))
            if dev is not None:
                dev.step(int(cmd.get("steps", 0)),
                         int(cmd.get("rate_hz", 1000)),
                         int(cmd.get("dir", 1)))
        elif name == "read_now":
            dev = self.devices.get(cmd.get("id"))
            if dev is not None:
                try:
                    _emit({"t": _now_us(), "id": dev.id, "data": dev.sample()})
                except Exception as e:
                    _emit({"event": "error", "id": dev.id, "msg": str(e)})
        else:
            _emit({"event": "error", "id": None, "msg": "unknown cmd " + str(name)})


def main():
    bench = Bench()
    _emit({"event": "hello", "fw": "bench-0.1", "caps": {"max_per_kind": 2}})
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    line_buf = ""
    while True:
        bench.tick()
        if poll.poll(0):
            ch = sys.stdin.read(1)
            if ch:
                if ch == "\n":
                    line = line_buf.strip()
                    line_buf = ""
                    if line:
                        try:
                            bench.handle(ujson.loads(line))
                        except Exception as e:
                            _emit({"event": "error", "id": None, "msg": "parse: " + str(e)})
                else:
                    line_buf += ch


main()
