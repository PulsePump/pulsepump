"""ConnectionDock — port picker + Connect/Disconnect + status."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ....hardware.bench.controller import BenchController


class ConnectionDock(QDockWidget):
    """Lets the user pick a transport (Fake / Pico port) and (dis)connect."""

    request_use_fake = Signal()
    request_use_mpremote = Signal(str)  # port string
    request_refresh_ports = Signal()
    request_disconnect = Signal()

    def __init__(self, controller: BenchController, parent: QWidget | None = None) -> None:
        super().__init__("Connection", parent)
        self.setObjectName("HardwareBench.ConnectionDock")
        self._controller = controller

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._port_combo.addItem("auto")
        port_row.addWidget(self._port_combo, 1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.request_refresh_ports)
        port_row.addWidget(self._refresh_btn)
        outer.addLayout(port_row)

        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect Pico")
        self._connect_btn.clicked.connect(self._on_connect)
        self._fake_btn = QPushButton("Use Fake")
        self._fake_btn.setToolTip("Synthesise samples in-process — no hardware needed")
        self._fake_btn.clicked.connect(self.request_use_fake)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self.request_disconnect)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._fake_btn)
        btn_row.addWidget(self._disconnect_btn)
        outer.addLayout(btn_row)

        self._status = QLabel("Not connected")
        self._status.setStyleSheet("color: #888;")
        outer.addWidget(self._status)
        outer.addStretch()
        self.setWidget(body)

        controller.connection_changed.connect(self._on_connection_changed)

    def _on_connect(self) -> None:
        port = self._port_combo.currentText().strip() or "auto"
        self.request_use_mpremote.emit(port)

    def set_ports(self, ports: list[str]) -> None:
        current = self._port_combo.currentText()
        self._port_combo.clear()
        self._port_combo.addItem("auto")
        for p in ports:
            self._port_combo.addItem(p)
        if current in ["auto", *ports]:
            self._port_combo.setCurrentText(current)

    def _on_connection_changed(self, connected: bool, msg: str) -> None:
        if connected:
            self._status.setText(f"Connected — {msg}")
            self._status.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self._status.setText(f"Disconnected ({msg})" if msg else "Disconnected")
            self._status.setStyleSheet("color: #888;")
        self._disconnect_btn.setEnabled(connected)
        self._connect_btn.setEnabled(not connected)
        self._fake_btn.setEnabled(not connected)
