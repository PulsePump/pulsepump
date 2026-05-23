"""Real Pico transport for the Hardware Bench.

Uses mpremote's Python API (SerialTransport) to enter raw REPL mode and start
bench.py on the Pico, then pumps newline-JSON frames over the serial port
directly via a background QThread.

The old subprocess approach (``mpremote run bench.py``) had a fundamental
flaw: ``mpremote run`` uses ``follow()`` which only reads Pico stdout waiting
for a ``\\x04`` EOF marker and never forwards host stdin to the serial port,
so configure/start_streaming commands written to the subprocess's stdin pipe
were silently ignored.
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from serial.tools import list_ports

from .transport import BenchTransport

RPI_VID = 0x2E8A


def _mpremote_bin() -> str:
    return str(Path(sys.executable).parent / "mpremote")


def _firmware_file() -> Path:
    ref = resources.files("pulsepump.firmware").joinpath("bench.py")
    with resources.as_file(ref) as p:
        return Path(p)


def list_pico_ports() -> list[str]:
    """Return serial-port device strings that look like a Raspberry Pi Pico."""
    out: list[str] = []
    for p in list_ports.comports():
        if p.vid == RPI_VID:
            out.append(p.device)
    if out:
        return out
    # Fallback: ask mpremote for whatever it sees.
    try:
        result = subprocess.run(
            [_mpremote_bin(), "connect", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError, subprocess.TimeoutExpired:
        return []
    for line in result.stdout.splitlines():
        m = re.match(r"^(\S+)\s", line.strip())
        if m:
            out.append(m.group(1))
    return out


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------


class _OpenThread(QThread):
    """Enters raw REPL mode and starts bench.py on the Pico.

    Runs on a worker thread because ``enter_raw_repl`` involves a soft reset
    that takes ~1 s. On success, stores the live ``serial.Serial`` object in
    ``result_serial`` and emits ``succeeded``; on failure emits ``failed``.
    """

    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, port: str, firmware_bytes: bytes, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = port
        self._firmware = firmware_bytes
        self.result_serial: Any = None

    def run(self) -> None:
        port = self._port
        if port == "auto":
            ports = list_pico_ports()
            if not ports:
                self.failed.emit("no Pico found — plug in your Pico and try again")
                return
            port = ports[0]

        try:
            from mpremote.transport_serial import SerialTransport
        except ImportError as exc:
            self.failed.emit(f"mpremote not available: {exc}")
            return

        try:
            st = SerialTransport(port, baudrate=115200)
            st.enter_raw_repl(soft_reset=True)
            st.exec_raw_no_follow(self._firmware)
            # Short timeout so the reader thread can check for interruption ~10/s.
            serial: Any = st.serial
            serial.timeout = 0.1
            self.result_serial = serial
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class _SerialReaderThread(QThread):
    """Reads newline-JSON frames from a pyserial serial port."""

    frame = Signal(dict)
    warn = Signal(str)
    closed = Signal()

    def __init__(self, serial_port: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._serial = serial_port

    def run(self) -> None:
        buf = b""
        while not self.isInterruptionRequested():
            try:
                chunk = self._serial.read(self._serial.in_waiting or 1)
            except OSError:
                break
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                    self.frame.emit(obj)
                except json.JSONDecodeError, ValueError:
                    self.warn.emit(f"non-JSON from Pico: {text!r}")
        self.closed.emit()


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class MpremoteTransport(BenchTransport):
    """Bench transport that communicates directly with the Pico via serial."""

    def __init__(self, port: str = "auto", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = port
        self._serial: Any = None
        self._opener: _OpenThread | None = None
        self._reader: _SerialReaderThread | None = None

    @property
    def port(self) -> str:
        return self._port

    def open(self) -> None:
        if self._connected:
            return
        self._saw_hello = False
        fw = _firmware_file().read_bytes()
        self._opener = _OpenThread(self._port, fw, parent=self)
        self._opener.succeeded.connect(self._on_opened)
        self._opener.failed.connect(self._on_open_failed)
        self._opener.start()
        # Mark connected immediately so UI buttons lock; we'll update the
        # message once firmware is alive.
        self._connected = True
        self.connection_changed.emit(True, f"{self._port} (connecting…)")

    def _on_opened(self) -> None:
        assert self._opener is not None
        self._serial = self._opener.result_serial
        self._reader = _SerialReaderThread(self._serial, parent=self)
        self._reader.frame.connect(self.frame_received)
        self._reader.frame.connect(self._note_first_frame)
        self._reader.warn.connect(self.log)
        self._reader.closed.connect(self._on_reader_closed)
        self._reader.start()

        from PySide6.QtCore import QTimer

        QTimer.singleShot(4000, self._check_for_hello)

    def _on_open_failed(self, msg: str) -> None:
        self._connected = False
        self._opener = None
        self.error.emit(f"failed to start firmware: {msg}")
        self.connection_changed.emit(False, "")

    def _note_first_frame(self, _frame: dict) -> None:
        if not self._saw_hello:
            self._saw_hello = True
            self.connection_changed.emit(True, f"{self._port} (firmware alive)")

    def _check_for_hello(self) -> None:
        if not self._connected:
            return
        if not self._saw_hello:
            self.error.emit(
                "no frames from firmware after 4 s — "
                "try running bench.py manually via mpremote and check for errors"
            )

    def close(self) -> None:
        if not self._connected:
            return
        self._connected = False
        if self._opener is not None:
            self._opener.requestInterruption()
        if self._reader is not None:
            self._reader.requestInterruption()
        if self._serial is not None:
            with contextlib.suppress(OSError):
                self._serial.write(b"\r\x03")  # Ctrl-C: interrupt running script
            with contextlib.suppress(OSError):
                self._serial.close()
        if self._reader is not None:
            self._reader.wait(2000)
            self._reader = None
        self._opener = None
        self._serial = None
        self.connection_changed.emit(False, "")

    def send(self, frame: dict[str, Any]) -> None:
        if not self._connected:
            self.error.emit("send on disconnected transport")
            return
        if self._serial is None:
            # Still in the connecting window; the controller will resend when
            # _note_first_frame fires connection_changed(True) again.
            return
        try:
            self._serial.write((json.dumps(frame) + "\n").encode())
        except OSError as exc:
            self.error.emit(f"write failed: {exc}")

    def _on_reader_closed(self) -> None:
        if self._connected:
            self._connected = False
            self.connection_changed.emit(False, "serial port closed")
