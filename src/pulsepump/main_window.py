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
        self.status.showMessage(f"Connected to Pico on {loader.port}")

        assert loader.proc is not None
        self.reader = SerialReader(loader.proc, parent=self)
        self.reader.sample.connect(self.plot.append)
        self.reader.warning.connect(lambda msg: self.status.showMessage(msg, 2000))
        self.reader.start()

    def closeEvent(self, event) -> None:
        self.reader.requestInterruption()
        self.loader.stop()
        self.reader.wait(2000)
        super().closeEvent(event)
