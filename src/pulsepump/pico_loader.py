"""Deploy and run the MicroPython firmware on a connected Pico via mpremote."""

from __future__ import annotations

import subprocess
import sys
from importlib import resources
from pathlib import Path

from serial.tools import list_ports

RPI_VID = 0x2E8A


class PicoNotFoundError(RuntimeError):
    pass


def find_pico_port() -> str:
    for p in list_ports.comports():
        if p.vid == RPI_VID:
            return p.device
    raise PicoNotFoundError("No Raspberry Pi Pico detected on USB.")


def _firmware_path() -> Path:
    ref = resources.files("pulsepump.firmware").joinpath("main.py")
    with resources.as_file(ref) as p:
        return Path(p)


class PicoLoader:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.port: str | None = None

    def start(self) -> subprocess.Popen[str]:
        self.port = find_pico_port()
        firmware = _firmware_path()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "mpremote", "connect", self.port, "run", str(firmware)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return self.proc

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
