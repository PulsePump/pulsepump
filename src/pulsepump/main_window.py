"""Main application window."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QScrollArea

from .panels import (
    ConfigPanel,
    FunctionGeneratorPanel,
    PressureSensorsPanel,
    SamplingPanel,
)
from .pico_loader import PicoLoader
from .plot_view import PlotView
from .serial_reader import SerialReader

_SETTINGS_ORG = "pulsepump"
_SETTINGS_APP = "pulsepump"


class MainWindow(QMainWindow):
    def __init__(self, loader: PicoLoader) -> None:
        super().__init__()
        self.setWindowTitle("pulsepump — live ADC")
        self.resize(1400, 800)

        self.loader = loader
        self.plot = PlotView()
        self.setCentralWidget(self.plot)
        self.status = self.statusBar()
        try:
            pkg_version = version("pulsepump")
        except PackageNotFoundError:
            pkg_version = "dev"
        self.status.addPermanentWidget(QLabel(f"v{pkg_version}"))
        self.reader: SerialReader | None = None

        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )

        self._docks: dict[str, QDockWidget] = {}

        self._add_dock(FunctionGeneratorPanel(), Qt.DockWidgetArea.LeftDockWidgetArea)
        self.sampling = SamplingPanel()
        self.sampling.sampleRateChanged.connect(self.loader.set_sample_rate)
        self.sampling.pinChanged.connect(self.loader.set_pin)
        self.sampling.pinChanged.connect(self.plot.set_channel_pin)
        self.plot.set_channel_pin(1, self.sampling.current_pin(1))
        self.plot.set_channel_pin(2, self.sampling.current_pin(2))
        sampling_dock = self._add_dock(self.sampling, Qt.DockWidgetArea.RightDockWidgetArea)
        self.pressure_sensors = PressureSensorsPanel()
        self.pressure_sensors.paramsChanged.connect(self.plot.refresh_units)
        pressure_dock = self._add_dock(self.pressure_sensors, Qt.DockWidgetArea.RightDockWidgetArea)
        self.splitDockWidget(sampling_dock, pressure_dock, Qt.Orientation.Vertical)

        self._build_view_menu()
        self._restore_layout()

    def _add_dock(self, panel: ConfigPanel, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(panel.title, self)
        dock.setObjectName(f"Dock_{type(panel).__name__}")
        dock.setMinimumWidth(panel.min_width)
        scroll = QScrollArea(dock)
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        dock.setWidget(scroll)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(area, dock)
        self._docks[dock.objectName()] = dock
        return dock

    def _build_view_menu(self) -> None:
        view_menu = self.menuBar().addMenu("&View")
        panels_menu = view_menu.addMenu("Panels")
        for dock in self._docks.values():
            panels_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        reset = view_menu.addAction("Reset layout")
        reset.triggered.connect(self._reset_layout)

    def _restore_layout(self) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        geom = s.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = s.value("windowState")
        if state:
            self.restoreState(state)

    def _reset_layout(self) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.remove("windowState")
        s.remove("geometry")
        self.status.showMessage("Layout reset — restart to apply defaults", 4000)

    def attach_reader(self) -> None:
        assert self.loader.proc is not None
        self.status.showMessage(f"Connected to Pico on {self.loader.port}")
        self.reader = SerialReader(self.loader.proc, parent=self)
        self.reader.sample.connect(self.plot.append)
        self.reader.warning.connect(lambda msg: self.status.showMessage(msg, 2000))
        self.reader.start()
        self.loader.set_sample_rate(self.sampling.current_rate())
        self.loader.set_pin(1, self.sampling.current_pin(1))
        self.loader.set_pin(2, self.sampling.current_pin(2))

    def show_disconnected(self, message: str) -> None:
        self.status.showMessage(message)

    def closeEvent(self, event) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        if self.reader is not None:
            self.reader.requestInterruption()
        self.loader.stop()
        if self.reader is not None:
            self.reader.wait(2000)
        super().closeEvent(event)
