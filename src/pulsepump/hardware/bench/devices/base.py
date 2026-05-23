"""Abstract base class for host-side bench device drivers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from ..signals import SignalDescriptor

if TYPE_CHECKING:
    from ..config import DeviceConfig
    from ..transport import BenchTransport


class BenchDevice[ConfigT: "DeviceConfig"](QObject):
    """Host-side mirror of one firmware device.

    Subclasses declare their signal list via :meth:`signals_for`, decode
    inbound sample-frame ``data`` dicts via :meth:`ingest`, and may add
    command methods that send outbound frames via :attr:`transport`.

    The device is transport-agnostic: a :class:`BenchController` injects a
    transport before any command method is called.

    The class is generic over its config type so subclasses get a narrowly
    typed :attr:`config` without needing per-subclass overrides.
    """

    sample = Signal(float, dict)  # t_seconds, {signal_name: value}
    input_changed = Signal(str, float)  # signal_name, value — host-commanded inputs
    status_message = Signal(str)

    device_type: str = ""  # overridden by subclasses

    def __init__(self, config: ConfigT, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config: ConfigT = config
        self._transport: BenchTransport | None = None

    # -- identity / config -------------------------------------------------

    @property
    def id(self) -> str:
        return self._config.id

    @property
    def sample_rate_hz(self) -> float:
        return float(self._config.sample_rate_hz)

    @property
    def config(self) -> ConfigT:
        return self._config

    def update_config(self, new_config: ConfigT) -> None:
        """Replace the local config (signal list may change). Caller is
        responsible for re-registering signals in the registry."""
        self._config = new_config

    def attach_transport(self, transport: BenchTransport) -> None:
        self._transport = transport

    def _send(self, frame: dict) -> None:
        if self._transport is None:
            self.status_message.emit("no transport — drop")
            return
        self._transport.send(frame)

    # -- subclass contract -------------------------------------------------

    def signals_for(self) -> list[SignalDescriptor]:
        """Return the descriptor list this device produces. Pure function of
        the current config."""
        raise NotImplementedError

    def ingest(self, t_s: float, data: dict) -> dict[str, float]:
        """Decode an inbound ``data`` dict from a firmware sample frame into
        a flat ``{signal_name: value}`` map. Default: pass through anything
        that is already a Python number; non-numeric values are dropped."""
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float, bool))}
