"""Signal descriptors and live registry for the Hardware Bench.

A :class:`SignalDescriptor` describes a single time-series variable produced
by a device (e.g. ``stepper0.sg_result``, ``pressure0.pressure_mmhg``). The
:class:`SignalRegistry` is the canonical map from fully-qualified signal id
to its descriptor plus a fixed-size ring buffer used by live plotting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from PySide6.QtCore import QObject, Signal

SignalKind = Literal["input", "reading", "status"]
"""input  = host-commanded values (servo angle, stepper target)
reading = measured/derived signals (ADC counts, TSTEP, SG_RESULT)
status  = boolean/categorical health flags
"""


@dataclass(frozen=True)
class SignalDescriptor:
    """Metadata for one logged variable produced by a device."""

    device_id: str
    name: str
    units: str
    kind: SignalKind
    dtype: str = "f4"  # numpy dtype string for parquet schema
    description: str = ""

    @property
    def id(self) -> str:
        """Fully-qualified id, e.g. ``stepper0.sg_result``."""
        return f"{self.device_id}.{self.name}"


@dataclass
class _Ring:
    """Fixed-size ring buffer of (timestamp_s, value) pairs."""

    capacity: int
    t: np.ndarray = field(init=False)
    v: np.ndarray = field(init=False)
    head: int = 0
    filled: int = 0

    def __post_init__(self) -> None:
        self.t = np.zeros(self.capacity, dtype="f8")
        self.v = np.zeros(self.capacity, dtype="f4")

    def push(self, t_s: float, value: float) -> None:
        self.t[self.head] = t_s
        self.v[self.head] = value
        self.head = (self.head + 1) % self.capacity
        if self.filled < self.capacity:
            self.filled += 1

    def snapshot(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (t, v) in chronological order. Allocates a copy."""
        if self.filled < self.capacity:
            return self.t[: self.filled].copy(), self.v[: self.filled].copy()
        idx = np.arange(self.head, self.head + self.capacity) % self.capacity
        return self.t[idx], self.v[idx]


class SignalRegistry(QObject):
    """Live store of every signal the bench is currently producing.

    Plot widgets subscribe here, not directly to devices, so plots stay alive
    across device re-configuration as long as the signal id is still produced.
    """

    signal_added = Signal(str)  # signal id
    signal_removed = Signal(str)  # signal id
    samples_appended = Signal(str)  # signal id — emitted on every ingest

    def __init__(self, buffer_seconds: float = 60.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._buffer_seconds = buffer_seconds
        self._descriptors: dict[str, SignalDescriptor] = {}
        self._rings: dict[str, _Ring] = {}
        self._rates: dict[str, float] = {}  # for ring sizing
        self._latest: dict[str, float] = {}

    # -- mutation ----------------------------------------------------------

    def register(self, desc: SignalDescriptor, sample_rate_hz: float) -> None:
        if desc.id in self._descriptors:
            return
        capacity = max(64, int(self._buffer_seconds * sample_rate_hz) + 1)
        self._descriptors[desc.id] = desc
        self._rings[desc.id] = _Ring(capacity=capacity)
        self._rates[desc.id] = sample_rate_hz
        self.signal_added.emit(desc.id)

    def unregister(self, signal_id: str) -> None:
        if signal_id not in self._descriptors:
            return
        del self._descriptors[signal_id]
        del self._rings[signal_id]
        del self._rates[signal_id]
        self._latest.pop(signal_id, None)
        self.signal_removed.emit(signal_id)

    def remove_device(self, device_id: str) -> None:
        for sid in [k for k in self._descriptors if k.startswith(f"{device_id}.")]:
            self.unregister(sid)

    def append(self, signal_id: str, t_s: float, value: float) -> None:
        ring = self._rings.get(signal_id)
        if ring is None:
            return
        ring.push(t_s, value)
        self._latest[signal_id] = value
        self.samples_appended.emit(signal_id)

    # -- introspection -----------------------------------------------------

    def ids(self) -> list[str]:
        return list(self._descriptors.keys())

    def descriptors(self) -> dict[str, SignalDescriptor]:
        return dict(self._descriptors)

    def descriptor(self, signal_id: str) -> SignalDescriptor | None:
        return self._descriptors.get(signal_id)

    def latest(self, signal_id: str) -> float | None:
        return self._latest.get(signal_id)

    def snapshot(self, signal_id: str) -> tuple[np.ndarray, np.ndarray] | None:
        ring = self._rings.get(signal_id)
        return None if ring is None else ring.snapshot()

    def ids_for_device(self, device_id: str) -> list[str]:
        return [k for k in self._descriptors if k.startswith(f"{device_id}.")]
