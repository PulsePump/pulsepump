"""BenchController — orchestrates devices, transport, recorder, and signals."""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal

from .config import MAX_PER_KIND, BenchConfig, DeviceConfig
from .devices import BenchDevice, device_for
from .recorder import RunRecorder
from .signals import SignalRegistry
from .transport import BenchTransport


def _default_runs_root() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(base) / "PulsePump" / "runs"


class BenchController(QObject):
    """Single source of truth for the bench session.

    Owns:
        * the device list (one :class:`BenchDevice` per :class:`DeviceConfig`)
        * the transport (set externally; may be ``FakeTransport`` or ``MpremoteTransport``)
        * the :class:`SignalRegistry` (live ring buffers for plotting)
        * the :class:`RunRecorder` (parquet + manifest)

    Emits Qt signals on every state change so the UI can stay declarative.
    """

    device_added = Signal(str)  # device id
    device_removed = Signal(str)  # device id
    config_changed = Signal()  # any structural change
    connection_changed = Signal(bool, str)
    run_state_changed = Signal(bool, str)  # active, run_dir (or "")
    error = Signal(str)
    status_message = Signal(str, int)  # text, timeout_ms (0 = persistent)

    def __init__(
        self,
        runs_root: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._transport: BenchTransport | None = None
        self._devices: dict[str, BenchDevice] = {}
        self._signals = SignalRegistry(parent=self)
        self._recorder = RunRecorder(runs_root or _default_runs_root())

    # -- accessors --------------------------------------------------------

    @property
    def signals(self) -> SignalRegistry:
        return self._signals

    @property
    def recorder(self) -> RunRecorder:
        return self._recorder

    @property
    def transport(self) -> BenchTransport | None:
        return self._transport

    def devices(self) -> list[BenchDevice]:
        return list(self._devices.values())

    def device(self, device_id: str) -> BenchDevice | None:
        return self._devices.get(device_id)

    def config(self) -> BenchConfig:
        return BenchConfig(devices=[d.config for d in self._devices.values()])

    def count_of(self, kind: str) -> int:
        return sum(1 for d in self._devices.values() if d.device_type == kind)

    def next_id_for(self, kind: str) -> str:
        used = {d.id for d in self._devices.values() if d.device_type == kind}
        for n in range(MAX_PER_KIND):
            candidate = f"{kind}{n}"
            if candidate not in used:
                return candidate
        return f"{kind}{MAX_PER_KIND}"  # caller checks MAX_PER_KIND first

    # -- transport --------------------------------------------------------

    def set_transport(self, transport: BenchTransport) -> None:
        if self._transport is not None:
            # Disconnect previous wiring; silently ignore not-connected errors.
            with contextlib.suppress(TypeError, RuntimeError):
                self._transport.frame_received.disconnect(self._on_frame)
            with contextlib.suppress(TypeError, RuntimeError):
                self._transport.connection_changed.disconnect(self._on_conn_changed)
            with contextlib.suppress(TypeError, RuntimeError):
                self._transport.error.disconnect(self.error)
            with contextlib.suppress(TypeError, RuntimeError):
                self._transport.log.disconnect(self._on_transport_log)
        self._transport = transport
        transport.frame_received.connect(self._on_frame)
        transport.connection_changed.connect(self._on_conn_changed)
        transport.error.connect(self.error)
        transport.log.connect(self._on_transport_log)
        for dev in self._devices.values():
            dev.attach_transport(transport)

    def _on_transport_log(self, line: str) -> None:
        """Forward a raw transport log line (e.g. firmware stderr) into the
        status bar so the user can see what the Pico printed."""
        self.status_message.emit(f"pico: {line}", 6000)

    def open(self) -> None:
        """Open the transport (renamed from ``connect`` to avoid LSP-style
        clash with :meth:`QObject.connect`)."""
        if self._transport is None:
            self.error.emit("no transport set")
            return
        self.status_message.emit("Opening transport…", 0)
        self._transport.open()

    def close(self) -> None:
        """Close the transport, stopping any active run first."""
        if self._transport is None:
            return
        if self._recorder.is_active:
            self.stop_run()
        self.status_message.emit("Closing transport…", 0)
        self._transport.close()

    # -- device list ------------------------------------------------------

    def add_device(self, config: DeviceConfig) -> BenchDevice:
        if self.count_of(config.type) >= MAX_PER_KIND:
            raise ValueError(f"max {MAX_PER_KIND} {config.type} devices already configured")
        if config.id in self._devices:
            raise ValueError(f"device id {config.id!r} already in use")
        device = device_for(config)
        if self._transport is not None:
            device.attach_transport(self._transport)
        device.status_message.connect(lambda m: self.status_message.emit(m, 3000))
        self._devices[device.id] = device
        self._register_signals(device)
        if self._recorder.is_active:
            self._recorder.add_device_mid_run(device.id, device.signals_for())
        self.device_added.emit(device.id)
        self.config_changed.emit()
        self._push_configure()
        self.status_message.emit(f"Added {device.device_type} {device.id}", 3000)
        return device

    def remove_device(self, device_id: str) -> None:
        device = self._devices.pop(device_id, None)
        if device is None:
            return
        self._signals.remove_device(device_id)
        if self._recorder.is_active:
            self._recorder.remove_device_mid_run(device_id)
        self.device_removed.emit(device_id)
        self.config_changed.emit()
        self._push_configure()
        self.status_message.emit(f"Removed {device_id}", 3000)

    def reconfigure_device(self, device_id: str, new_config: DeviceConfig) -> None:
        device = self._devices.get(device_id)
        if device is None:
            raise KeyError(device_id)
        if new_config.id != device_id:
            raise ValueError("cannot rename a device via reconfigure")
        if new_config.type != device.device_type:
            raise ValueError("cannot change device type via reconfigure")
        # Refresh signals: existing plots subscribed by id remain valid as long
        # as the signal names match; pressure-unit changes flow through anyway.
        self._signals.remove_device(device_id)
        device.update_config(new_config)
        self._register_signals(device)
        if self._recorder.is_active:
            self._recorder.log_event("device_reconfigured", id=device_id)
        self.config_changed.emit()
        self._push_configure()
        self.status_message.emit(f"Applied new config to {device_id}", 3000)

    def load_config(self, config: BenchConfig) -> None:
        """Replace the entire device set with the given config."""
        for dev_id in list(self._devices.keys()):
            self.remove_device(dev_id)
        for cfg in config.devices:
            try:
                self.add_device(cfg)
            except ValueError as exc:
                self.error.emit(str(exc))

    def _register_signals(self, device: BenchDevice) -> None:
        for desc in device.signals_for():
            self._signals.register(desc, device.sample_rate_hz)

    def _push_configure(self) -> None:
        if self._transport is None or not self._transport.connected:
            return
        payload = self.config().model_dump(mode="json")["devices"]
        self._transport.send({"cmd": "configure", "devices": payload})

    # -- run lifecycle ----------------------------------------------------

    def start_run(self, name: str) -> Path:
        """Start a recording run.

        Streaming is independent of recording: by the time start_run is
        called, sample frames are already flowing (since the moment the
        transport opened). This method only opens parquet writers + the
        manifest so the in-flight data starts being persisted to disk.
        """
        if self._recorder.is_active:
            raise RuntimeError("run already in progress")
        device_signals = {d.id: d.signals_for() for d in self._devices.values()}
        run_dir = self._recorder.start(name, self.config(), device_signals)
        # Defensive: ensure firmware is actually streaming. Cheap to repeat.
        if self._transport is not None and self._transport.connected:
            self._transport.send({"cmd": "start_streaming"})
        self.run_state_changed.emit(True, str(run_dir))
        return run_dir

    def stop_run(self) -> Path | None:
        """Stop the recording run. Streaming continues so plots keep updating."""
        if not self._recorder.is_active:
            return None
        path = self._recorder.stop()
        self.run_state_changed.emit(False, "")
        return path

    # -- transport callbacks ----------------------------------------------

    def _on_conn_changed(self, connected: bool, msg: str) -> None:
        self.connection_changed.emit(connected, msg)
        if connected:
            # Push current device set so firmware mirrors host state, then
            # start streaming immediately so live plots and readings work
            # without the user having to start a recording run.
            self._push_configure()
            if self._transport is not None:
                self._transport.send({"cmd": "start_streaming"})
                self.status_message.emit("Streaming started", 3000)

    def _on_frame(self, frame: dict) -> None:
        if "id" in frame and "data" in frame and "t" in frame:
            dev = self._devices.get(frame["id"])
            if dev is None:
                return
            t_s = float(frame["t"]) / 1_000_000.0
            decoded = dev.ingest(t_s, frame["data"])
            dev.sample.emit(t_s, decoded)
            self._recorder.append(dev.id, t_s, decoded)
            for name, val in decoded.items():
                self._signals.append(f"{dev.id}.{name}", t_s, val)
            return
        if "event" in frame:
            if frame["event"] == "error":
                self.error.emit(str(frame.get("msg", "unknown firmware error")))
            elif frame["event"] == "hello":
                # Could capture fw revision here; not needed for slice 1.
                pass
