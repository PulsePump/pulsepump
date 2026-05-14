"""QThread that reads CSV samples from the mpremote subprocess stdout."""

from __future__ import annotations

import subprocess

from PySide6.QtCore import QThread, Signal


class SerialReader(QThread):
    sample = Signal(int, int, int)
    warning = Signal(str)
    finished_reading = Signal()

    def __init__(self, proc: subprocess.Popen[str], parent=None) -> None:
        super().__init__(parent)
        self.proc = proc

    def run(self) -> None:
        assert self.proc.stdout is not None
        stdout = self.proc.stdout
        while not self.isInterruptionRequested():
            line = stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    break
                continue
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) != 3:
                self.warning.emit(f"skip: {line!r}")
                continue
            try:
                t, v0, v1 = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                self.warning.emit(f"parse: {line!r}")
                continue
            self.sample.emit(t, v0, v1)
        self.finished_reading.emit()
