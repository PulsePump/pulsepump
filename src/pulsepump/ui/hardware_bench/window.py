"""HardwareBenchWindow — main window for the bench."""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from ...hardware.bench.config import (
    MAX_PER_KIND,
    BenchConfig,
    PressureSensorConfig,
    ServoConfig,
    StepperConfig,
)
from ...hardware.bench.controller import BenchController
from ...hardware.bench.transport import FakeTransport
from .docks.connection import ConnectionDock
from .docks.device_panel import DevicePanel
from .docks.plot import PlotDock
from .docks.run import RunDock
from .docks.signals_dock import SignalsView


class HardwareBenchWindow(QMainWindow):
    """Dockable test bench for servos, steppers, and pressure sensors."""

    _settings_key_config = "HardwareBench/last_config_yaml"
    _settings_key_geometry = "HardwareBench/geometry"
    _settings_key_state = "HardwareBench/window_state"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hardware Bench")
        self.resize(1300, 820)
        self.setDockNestingEnabled(True)

        self._controller = BenchController(parent=self)
        self._device_panels: dict[str, DevicePanel] = {}
        self._plot_docks: list[PlotDock] = []
        self._first_plot: PlotDock | None = None
        self._current_config_path: Path | None = None

        # Central widget: the live signals view. Always visible — drag a
        # leaf onto a plot dock to add a trace.
        self._signals_view = SignalsView(self._controller, self)
        self.setCentralWidget(self._signals_view)

        self._connection_dock = ConnectionDock(self._controller, self)
        self._run_dock = RunDock(self._controller, self)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._connection_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._run_dock)

        self._build_menu()
        self._build_status_bar()

        self._controller.device_added.connect(self._on_device_added)
        self._controller.device_removed.connect(self._on_device_removed)
        self._controller.error.connect(self._on_error)

        self._connection_dock.request_use_fake.connect(self._on_use_fake)
        self._connection_dock.request_use_mpremote.connect(self._on_use_mpremote)
        self._connection_dock.request_refresh_ports.connect(self._on_refresh_ports)
        self._connection_dock.request_disconnect.connect(self._controller.close)

        self._restore_state()

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        new_act = QAction("&New Bench Config", self)
        new_act.setShortcut(QKeySequence.StandardKey.New)
        new_act.triggered.connect(self._on_new_config)
        file_menu.addAction(new_act)
        open_act = QAction("&Open Bench Config…", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self._on_open_config)
        file_menu.addAction(open_act)
        save_act = QAction("&Save Bench Config", self)
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self._on_save_config)
        file_menu.addAction(save_act)
        save_as_act = QAction("Save Bench Config &As…", self)
        save_as_act.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_act.triggered.connect(self._on_save_config_as)
        file_menu.addAction(save_as_act)
        file_menu.addSeparator()
        close_act = QAction("&Close", self)
        close_act.setShortcut(QKeySequence.StandardKey.Close)
        close_act.triggered.connect(self.close)
        file_menu.addAction(close_act)

        bench_menu = self.menuBar().addMenu("&Bench")
        self._add_servo_act = QAction("Add &Servo", self)
        self._add_servo_act.triggered.connect(lambda: self._add_kind("servo"))
        bench_menu.addAction(self._add_servo_act)
        self._add_stepper_act = QAction("Add S&tepper", self)
        self._add_stepper_act.triggered.connect(lambda: self._add_kind("stepper"))
        bench_menu.addAction(self._add_stepper_act)
        self._add_pressure_act = QAction("Add &Pressure Sensor", self)
        self._add_pressure_act.triggered.connect(lambda: self._add_kind("pressure"))
        bench_menu.addAction(self._add_pressure_act)
        bench_menu.aboutToShow.connect(self._update_add_actions)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self._connection_dock.toggleViewAction())
        view_menu.addAction(self._run_dock.toggleViewAction())
        view_menu.addSeparator()
        self._device_panels_menu = view_menu.addMenu("Device &Panels")
        self._device_panels_menu.aboutToShow.connect(self._refresh_device_panels_menu)
        view_menu.addSeparator()
        new_plot_act = QAction("&New Plot", self)
        new_plot_act.setShortcut(QKeySequence("Ctrl+P"))
        new_plot_act.triggered.connect(self._new_plot_dock)
        view_menu.addAction(new_plot_act)

    def _refresh_device_panels_menu(self) -> None:
        menu = self._device_panels_menu
        menu.clear()
        if not self._device_panels:
            empty = menu.addAction("(no devices configured)")
            empty.setEnabled(False)
            return
        for dev_id, panel in self._device_panels.items():
            action = panel.toggleViewAction()
            action.setText(dev_id)
            menu.addAction(action)

    def _build_status_bar(self) -> None:
        self._controller.connection_changed.connect(self._on_status_connection)
        self._controller.run_state_changed.connect(self._on_status_run)
        self._controller.error.connect(lambda m: self.statusBar().showMessage(f"Error: {m}", 5000))
        self._controller.status_message.connect(self.statusBar().showMessage)

    def _status(self, msg: str, timeout_ms: int = 3000) -> None:
        """Show a one-off status-bar message from inside the window."""
        self.statusBar().showMessage(msg, timeout_ms)

    def _on_status_connection(self, connected: bool, msg: str) -> None:
        self.statusBar().showMessage(
            f"Connected — {msg}" if connected else f"Disconnected ({msg})" if msg else "",
            3000,
        )

    def _on_status_run(self, active: bool, run_dir: str) -> None:
        if active:
            self.statusBar().showMessage(f"Recording to {run_dir}", 0)
        else:
            self.statusBar().showMessage("Run stopped", 3000)

    def _update_add_actions(self) -> None:
        self._add_servo_act.setEnabled(self._controller.count_of("servo") < MAX_PER_KIND)
        self._add_stepper_act.setEnabled(self._controller.count_of("stepper") < MAX_PER_KIND)
        self._add_pressure_act.setEnabled(self._controller.count_of("pressure") < MAX_PER_KIND)

    # ------------------------------------------------------------------
    # Add / remove devices
    # ------------------------------------------------------------------

    def _add_kind(self, kind: str) -> None:
        next_id = self._controller.next_id_for(kind)
        if kind == "servo":
            cfg = ServoConfig(id=next_id)
        elif kind == "stepper":
            cfg = StepperConfig(id=next_id)
        elif kind == "pressure":
            cfg = PressureSensorConfig(id=next_id)
        else:
            return
        try:
            self._controller.add_device(cfg)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot add device", str(exc))

    def _on_device_added(self, device_id: str) -> None:
        device = self._controller.device(device_id)
        if device is None:
            return
        panel = DevicePanel(self._controller, device, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
        # Tabify with any existing device panels for a tidy default layout.
        existing = [p for p in self._device_panels.values() if p is not panel]
        if existing:
            self.tabifyDockWidget(existing[-1], panel)
        self._device_panels[device_id] = panel
        panel.show()
        panel.raise_()

    def _on_device_removed(self, device_id: str) -> None:
        panel = self._device_panels.pop(device_id, None)
        if panel is not None:
            self.removeDockWidget(panel)
            panel.deleteLater()

    # ------------------------------------------------------------------
    # Plots
    # ------------------------------------------------------------------

    def _new_plot_dock(self) -> None:
        dock = PlotDock(self._controller.signals, self)
        dock.status_message.connect(self._status)
        self._plot_docks.append(dock)
        self._status(f"New plot #{len(self._plot_docks)}")
        if self._first_plot is None:
            self._first_plot = dock
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        else:
            # Stack vertically and link x-axis to the first plot.
            self.splitDockWidget(self._plot_docks[-2], dock, Qt.Orientation.Vertical)
            dock.link_x_to(self._first_plot)
        dock.destroyed.connect(lambda _=None, d=dock: self._on_plot_closed(d))

    def _on_plot_closed(self, dock: PlotDock) -> None:
        if dock in self._plot_docks:
            self._plot_docks.remove(dock)
        if dock is self._first_plot:
            self._first_plot = self._plot_docks[0] if self._plot_docks else None
            # Re-link survivors to the new first plot.
            if self._first_plot is not None:
                for d in self._plot_docks:
                    if d is not self._first_plot:
                        d.link_x_to(self._first_plot)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _on_use_fake(self) -> None:
        self._status("Switching to fake transport…")
        transport = FakeTransport(parent=self)
        self._controller.set_transport(transport)
        self._controller.open()

    def _on_use_mpremote(self, port: str) -> None:
        try:
            from ...hardware.bench.mpremote_transport import MpremoteTransport
        except ImportError as exc:
            QMessageBox.warning(self, "Pico transport unavailable", str(exc))
            return
        self._status(f"Connecting to Pico on {port}…")
        transport = MpremoteTransport(port=port, parent=self)
        self._controller.set_transport(transport)
        self._controller.open()

    def _on_refresh_ports(self) -> None:
        try:
            from ...hardware.bench.mpremote_transport import list_pico_ports
        except ImportError:
            return
        try:
            ports = list_pico_ports()
            self._connection_dock.set_ports(ports)
            self._status(f"Found {len(ports)} port(s)")
        except Exception as exc:
            self._on_error(str(exc))

    # ------------------------------------------------------------------
    # Config save / load
    # ------------------------------------------------------------------

    def _on_new_config(self) -> None:
        for dev_id in list(self._device_panels.keys()):
            self._controller.remove_device(dev_id)
        self._current_config_path = None
        self._update_title()
        self._status("New empty bench config")

    def _on_open_config(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open bench config",
            str(Path.home()),
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not path_str:
            return
        try:
            cfg = BenchConfig.from_yaml(Path(path_str).read_text())
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._controller.load_config(cfg)
        self._current_config_path = Path(path_str)
        self._update_title()
        self._status(f"Loaded {self._current_config_path.name}")

    def _on_save_config(self) -> None:
        if self._current_config_path is None:
            self._on_save_config_as()
            return
        self._write_config_to(self._current_config_path)

    def _on_save_config_as(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save bench config",
            str(self._current_config_path or Path.home() / "bench.yaml"),
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix == "":
            path = path.with_suffix(".yaml")
        self._write_config_to(path)
        self._current_config_path = path
        self._update_title()

    def _write_config_to(self, path: Path) -> None:
        try:
            path.write_text(self._controller.config().to_yaml())
            self.statusBar().showMessage(f"Saved {path.name}", 3000)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _update_title(self) -> None:
        if self._current_config_path is None:
            self.setWindowTitle("Hardware Bench")
        else:
            self.setWindowTitle(f"Hardware Bench — {self._current_config_path.name}")

    # ------------------------------------------------------------------
    # QSettings
    # ------------------------------------------------------------------

    def _restore_state(self) -> None:
        settings = QSettings()
        geom = settings.value(self._settings_key_geometry)
        if geom is not None:
            self.restoreGeometry(geom)
        state = settings.value(self._settings_key_state)
        if state is not None:
            self.restoreState(state)
        yaml_text = settings.value(self._settings_key_config, "", type=str)
        if isinstance(yaml_text, str) and yaml_text:
            try:
                cfg = BenchConfig.from_yaml(yaml_text)
            except Exception:
                return
            self._controller.load_config(cfg)
        # Always start with at least one plot dock so the layout makes sense.
        if not self._plot_docks:
            self._new_plot_dock()

    def _persist_state(self) -> None:
        settings = QSettings()
        settings.setValue(self._settings_key_geometry, self.saveGeometry())
        settings.setValue(self._settings_key_state, self.saveState())
        settings.setValue(self._settings_key_config, self._controller.config().to_yaml())

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"Error: {msg}", 6000)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._persist_state()
        with contextlib.suppress(Exception):
            self._controller.close()
        super().closeEvent(event)
