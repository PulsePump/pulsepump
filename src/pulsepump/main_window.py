"""Main application window."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

from .pico_loader import PicoLoader
from .plot_view import PlotView
from .serial_reader import SerialReader


class MainWindow(QMainWindow):
    def __init__(self, loader: PicoLoader) -> None:
        super().__init__()
        self.setWindowTitle("pulsepump — live ADC")
        self.resize(1000, 600)

        self.loader = loader
        self.plot = PlotView()
        self.setCentralWidget(self.plot)
        self.status = self.statusBar()
        self.reader: SerialReader | None = None

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
        if self.reader is not None:
            self.reader.requestInterruption()
        self.loader.stop()
        if self.reader is not None:
            self.reader.wait(2000)
        super().closeEvent(event)
