"""Bench transport: abstract base + a synthetic transport for headless tests.

The real :class:`MpremoteTransport` lives in :mod:`mpremote_transport` and is
only constructed when the user actually connects to a Pico. Tests and the UI
shell can wire up a :class:`FakeTransport` that synthesises sample frames
directly, so the entire host stack can be exercised without hardware.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal


class BenchTransport(QObject):
    """Abstract bidirectional JSON-frame transport.

    Inbound frames are emitted as :attr:`frame_received` (Python dict).
    Outbound frames go through :meth:`send`.
    """

    frame_received = Signal(dict)
    connection_changed = Signal(bool, str)  # connected, status text
    error = Signal(str)
    log = Signal(str)  # raw informational line (e.g. firmware stderr)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def send(self, frame: dict[str, Any]) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fake transport
# ---------------------------------------------------------------------------


class FakeTransport(BenchTransport):
    """Synthetic transport useful for tests and UI development.

    Honours ``configure`` and ``start_streaming`` / ``stop_streaming`` commands
    by spinning up a :class:`QTimer` per configured device that emits sample
    frames with deterministic-but-varying values (a sine for pressure, a
    smoothed step for servo, a ramp + jitter for stepper).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._t0 = time.monotonic()
        self._streaming = False
        self._timers: dict[str, QTimer] = {}
        self._configs: dict[str, dict] = {}
        self._servo_angles: dict[str, float] = {}
        self._stepper_step: dict[str, int] = {}

    # -- BenchTransport API -----------------------------------------------

    def open(self) -> None:
        self._connected = True
        self._t0 = time.monotonic()
        self.connection_changed.emit(True, "fake transport connected")
        self.frame_received.emit({"event": "hello", "fw": "fake-0.1", "caps": {}})

    def close(self) -> None:
        self._stop_streaming()
        self._connected = False
        self.connection_changed.emit(False, "disconnected")

    def send(self, frame: dict[str, Any]) -> None:
        if not self._connected:
            self.error.emit("send on disconnected transport")
            return
        # Round-trip via JSON to catch any non-serialisable values early.
        try:
            frame = json.loads(json.dumps(frame))
        except (TypeError, ValueError) as exc:
            self.error.emit(f"frame not JSON-serialisable: {exc}")
            return
        cmd = frame.get("cmd")
        if cmd == "configure":
            self._configure(frame.get("devices", []))
        elif cmd == "start_streaming":
            self._start_streaming()
        elif cmd == "stop_streaming":
            self._stop_streaming()
        elif cmd == "set":
            self._on_set(frame)
        elif cmd == "step":
            self._on_step(frame)
        elif cmd == "read_now":
            dev_id = frame.get("id")
            if dev_id and dev_id in self._configs:
                self._emit_sample(dev_id)

    # -- behaviour --------------------------------------------------------

    def _configure(self, devices: list[dict]) -> None:
        new_ids = {d["id"] for d in devices}
        for old_id in list(self._configs.keys()):
            if old_id not in new_ids:
                self._teardown_device(old_id)
        for d in devices:
            self._configs[d["id"]] = d
            self._servo_angles.setdefault(d["id"], 0.0)
            self._stepper_step.setdefault(d["id"], 0)
            self.frame_received.emit({"event": "configured", "id": d["id"], "ok": True})
        if self._streaming:
            self._start_streaming()  # rebuild timers for current set

    def _teardown_device(self, dev_id: str) -> None:
        timer = self._timers.pop(dev_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._configs.pop(dev_id, None)
        self._servo_angles.pop(dev_id, None)
        self._stepper_step.pop(dev_id, None)

    def _start_streaming(self) -> None:
        self._stop_streaming()
        self._streaming = True
        for dev_id, cfg in self._configs.items():
            rate = float(cfg.get("sample_rate_hz", 50.0))
            interval_ms = max(1, round(1000.0 / rate))
            timer = QTimer(self)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.timeout.connect(lambda d=dev_id: self._emit_sample(d))
            timer.start(interval_ms)
            self._timers[dev_id] = timer

    def _stop_streaming(self) -> None:
        self._streaming = False
        for timer in self._timers.values():
            timer.stop()
            timer.deleteLater()
        self._timers.clear()

    def _on_set(self, frame: dict) -> None:
        dev_id = frame.get("id")
        if dev_id and frame.get("field") == "angle_deg":
            self._servo_angles[dev_id] = float(frame.get("value", 0.0))

    def _on_step(self, frame: dict) -> None:
        dev_id = frame.get("id")
        if dev_id is None:
            return
        steps = int(frame.get("steps", 0))
        direction = int(frame.get("dir", 1))
        self._stepper_step[dev_id] = self._stepper_step.get(dev_id, 0) + (
            steps if direction else -steps
        )

    def _emit_sample(self, dev_id: str) -> None:
        cfg = self._configs.get(dev_id)
        if cfg is None:
            return
        t_us = int((time.monotonic() - self._t0) * 1_000_000)
        t_s = t_us / 1_000_000.0
        kind = cfg.get("type")
        if kind == "pressure":
            # Pulsatile-ish synthetic signal in raw counts (16-bit).
            base = 32768.0
            counts = base + 6000.0 * math.sin(2.0 * math.pi * 1.2 * t_s)
            counts += 2000.0 * math.sin(2.0 * math.pi * 2.4 * t_s + 0.7)
            data = {"counts": float(int(counts))}
        elif kind == "servo":
            data = {"commanded_angle_deg": float(self._servo_angles.get(dev_id, 0.0))}
        elif kind == "stepper":
            step = self._stepper_step.get(dev_id, 0)
            tstep = 1_000_000 // max(1, int(200 + 50 * math.sin(t_s)))
            data = {
                "commanded_step": float(step),
                "tstep": float(tstep),
                "sg_result": float(120 + 30 * math.sin(t_s * 0.7)),
                "ifcnt": float(int(t_s) & 0xFF),
                "cs_actual": 16.0,
                "ot": 0.0,
                "otpw": 0.0,
                "stealth": 1.0,
                "stst": float(1 if step == 0 else 0),
            }
        else:
            return
        self.frame_received.emit({"t": t_us, "id": dev_id, "data": data})
