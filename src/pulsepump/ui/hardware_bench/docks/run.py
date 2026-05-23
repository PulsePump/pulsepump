"""RunDock — Start/Stop run + elapsed + folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ....hardware.bench.controller import BenchController


class RunDock(QDockWidget):
    """Controls run lifecycle and shows where data is being written."""

    def __init__(self, controller: BenchController, parent: QWidget | None = None) -> None:
        super().__init__("Run", parent)
        self.setObjectName("HardwareBench.RunDock")
        self._controller = controller
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(250)
        self._elapsed_timer.timeout.connect(self._tick)
        self._t_start = 0.0
        self._last_dir: Path | None = None

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit("run")
        name_row.addWidget(self._name_edit, 1)
        layout.addLayout(name_row)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start Run")
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = QPushButton("Stop Run")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        self._open_btn = QPushButton("Open Folder…")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._open_btn)
        layout.addLayout(btn_row)

        self._elapsed_lbl = QLabel("idle")
        self._elapsed_lbl.setStyleSheet("color: #888;")
        layout.addWidget(self._elapsed_lbl)
        self._folder_lbl = QLabel("")
        self._folder_lbl.setWordWrap(True)
        self._folder_lbl.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self._folder_lbl)
        layout.addStretch()
        self.setWidget(body)

        controller.run_state_changed.connect(self._on_run_state)
        controller.error.connect(self._on_error)

    def _on_start(self) -> None:
        try:
            self._controller.start_run(self._name_edit.text() or "run")
        except RuntimeError as exc:
            QMessageBox.warning(self, "Cannot start run", str(exc))

    def _on_stop(self) -> None:
        self._controller.stop_run()

    def _on_open_folder(self) -> None:
        if self._last_dir is None:
            return
        QFileDialog.getOpenFileName(self, "Run folder", str(self._last_dir))

    def _on_run_state(self, active: bool, run_dir: str) -> None:
        self._start_btn.setEnabled(not active)
        self._stop_btn.setEnabled(active)
        self._name_edit.setEnabled(not active)
        if active:
            from time import monotonic

            self._t_start = monotonic()
            self._elapsed_timer.start()
            self._folder_lbl.setText(run_dir)
            self._last_dir = Path(run_dir)
            self._open_btn.setEnabled(True)
        else:
            self._elapsed_timer.stop()
            self._elapsed_lbl.setText("stopped" if self._last_dir else "idle")

    def _tick(self) -> None:
        from time import monotonic

        secs = monotonic() - self._t_start
        self._elapsed_lbl.setText(f"recording — {secs:6.1f} s elapsed")

    def _on_error(self, msg: str) -> None:
        self._elapsed_lbl.setText(f"error: {msg}")
