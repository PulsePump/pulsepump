"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow, QScrollArea

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
        sampling_dock = self._add_dock(SamplingPanel(), Qt.DockWidgetArea.RightDockWidgetArea)
        pressure_dock = self._add_dock(
            PressureSensorsPanel(), Qt.DockWidgetArea.RightDockWidgetArea
        )
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
