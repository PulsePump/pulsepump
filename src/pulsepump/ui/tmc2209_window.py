"""TMC2209 stepper motor debug/control window."""

from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..hardware.tmc2209_bridge import Tmc2209Bridge, _mpremote_bin
from ..hardware.tmc2209_registers import MICROSTEP_OPTIONS, irun_to_amps

# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


class CommandThread(QThread):
    """Runs a single mpremote command off the main thread."""

    result = Signal(dict)
    error = Signal(str)

    def __init__(self, bridge: Tmc2209Bridge, cmd: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._cmd = cmd

    def run(self) -> None:
        try:
            response = self._bridge.run_command(self._cmd)
            self.result.emit(response)
        except Exception as exc:
            self.error.emit(str(exc))


class _SubprocessThread(QThread):
    """Runs an arbitrary mpremote exec command string off the main thread."""

    done = Signal()
    error = Signal(str)

    def __init__(self, cmd: list[str], timeout: float = 30.0) -> None:
        super().__init__()
        self._cmd = cmd
        self._timeout = timeout

    def run(self) -> None:
        try:
            r = subprocess.run(self._cmd, capture_output=True, text=True, timeout=self._timeout)
            if r.returncode != 0:
                self.error.emit(r.stderr or r.stdout)
            else:
                self.done.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class _UploadThread(QThread):
    done = Signal()
    error = Signal(str)

    def __init__(self, bridge: Tmc2209Bridge) -> None:
        super().__init__()
        self._bridge = bridge

    def run(self) -> None:
        try:
            self._bridge.upload_firmware()
            self.done.emit()
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------


def _flag_label(parent: QWidget | None = None) -> QLabel:
    lbl = QLabel(parent)
    lbl.setFixedSize(12, 12)
    lbl.setStyleSheet("background: #888; border-radius: 3px;")
    return lbl


def _set_flag(lbl: QLabel, active: bool, fault: bool = True) -> None:
    if active and fault:
        lbl.setStyleSheet("background: #c0392b; border-radius: 3px;")
    elif active and not fault:
        lbl.setStyleSheet("background: #27ae60; border-radius: 3px;")
    else:
        lbl.setStyleSheet("background: #555; border-radius: 3px;")


def _linked_slider_spinbox(lo: int, hi: int, value: int) -> tuple[QHBoxLayout, QSlider, QSpinBox]:
    """A horizontal slider and spinbox kept in sync."""
    row = QHBoxLayout()
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(lo, hi)
    slider.setValue(value)
    spin = QSpinBox()
    spin.setRange(lo, hi)
    spin.setValue(value)
    spin.setFixedWidth(52)
    slider.valueChanged.connect(spin.setValue)
    spin.valueChanged.connect(slider.setValue)
    row.addWidget(slider, 1)
    row.addWidget(spin)
    return row, slider, spin


def _value_label(text: str = "--") -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class Tmc2209Window(QMainWindow):
    """Floating TMC2209 stepper motor debug window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TMC2209 Motor Controller")
        self.resize(440, 580)
        self.setMinimumWidth(380)

        self._bridge: Tmc2209Bridge | None = None
        self._connected = False
        self._polling = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_status)
        self._active_threads: list[QThread] = []

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 4)
        root_layout.setSpacing(6)

        # Permanent top: connection + motor enable (always visible)
        root_layout.addWidget(self._build_connection_group())
        root_layout.addWidget(self._build_enable_strip())

        # Tabbed area below
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_configure_tab(), "Configure")
        self._tabs.addTab(self._build_status_tab(), "Status")
        self._tabs.addTab(self._build_move_tab(), "Move")
        root_layout.addWidget(self._tabs, 1)

        self.setCentralWidget(root)

    # ------------------------------------------------------------------
    # Top section (permanent)
    # ------------------------------------------------------------------

    def _build_connection_group(self) -> QGroupBox:
        box = QGroupBox("Connection")
        layout = QVBoxLayout(box)
        layout.setSpacing(4)

        port_row = QHBoxLayout()
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._port_combo.addItem("auto")
        self._port_combo.setCurrentText("auto")
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(72)
        self._refresh_btn.clicked.connect(self._on_refresh_ports)
        port_row.addWidget(QLabel("Port:"))
        port_row.addWidget(self._port_combo, 1)
        port_row.addWidget(self._refresh_btn)
        layout.addLayout(port_row)

        btn_row = QHBoxLayout()
        self._upload_btn = QPushButton("Upload Firmware")
        self._upload_btn.clicked.connect(self._on_upload_firmware)
        self._connect_btn = QPushButton("Connect / Init")
        self._connect_btn.clicked.connect(self._on_connect_init)
        self._conn_status_lbl = QLabel("Not connected")
        self._conn_status_lbl.setStyleSheet("color: #888;")
        btn_row.addWidget(self._upload_btn)
        btn_row.addWidget(self._connect_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._conn_status_lbl)
        layout.addLayout(btn_row)

        return box

    def _build_enable_strip(self) -> QWidget:
        strip = QWidget()
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)

        self._enable_btn = QPushButton("Enable Motor")
        self._enable_btn.clicked.connect(self._on_enable)
        self._disable_btn = QPushButton("Disable Motor")
        self._disable_btn.clicked.connect(self._on_disable)
        self._shaft_chk = QCheckBox("Invert direction")
        self._shaft_chk.toggled.connect(self._on_shaft_toggled)

        layout.addWidget(self._enable_btn)
        layout.addWidget(self._disable_btn)
        layout.addStretch()
        layout.addWidget(self._shaft_chk)
        return strip

    # ------------------------------------------------------------------
    # Configure tab
    # ------------------------------------------------------------------

    def _build_configure_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)
        layout.addWidget(self._build_pins_group())
        layout.addWidget(self._build_current_group())
        layout.addWidget(self._build_chopper_group())
        layout.addWidget(self._build_stallguard_group())
        layout.addStretch()
        return tab

    def _build_pins_group(self) -> QGroupBox:
        box = QGroupBox("Pin Assignment")
        grid = QGridLayout(box)
        grid.setSpacing(5)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        def _pin_spin(default: int) -> QSpinBox:
            s = QSpinBox()
            s.setRange(0, 29)
            s.setValue(default)
            s.setPrefix("GP")
            return s

        self._uart_id_combo = QComboBox()
        self._uart_id_combo.addItem("UART0", 0)
        self._uart_id_combo.addItem("UART1", 1)

        self._tx_pin_spin = _pin_spin(0)
        self._rx_pin_spin = _pin_spin(1)
        self._step_pin_spin = _pin_spin(2)
        self._enn_pin_spin = _pin_spin(3)
        self._dir_pin_spin = _pin_spin(4)

        for row, (l1, w1, l2, w2) in enumerate(
            [
                ("UART", self._uart_id_combo, "TX", self._tx_pin_spin),
                ("RX", self._rx_pin_spin, "STEP", self._step_pin_spin),
                ("ENN", self._enn_pin_spin, "DIR", self._dir_pin_spin),
            ]
        ):
            grid.addWidget(QLabel(l1), row, 0)
            grid.addWidget(w1, row, 1)
            grid.addWidget(QLabel(l2), row, 2)
            grid.addWidget(w2, row, 3)

        return box

    def _build_current_group(self) -> QGroupBox:
        box = QGroupBox("Current")
        form = QFormLayout(box)
        form.setSpacing(5)

        irun_row, self._irun_slider, self._irun_spin = _linked_slider_spinbox(0, 31, 16)
        self._irun_amps_lbl = QLabel()
        self._irun_amps_lbl.setFixedWidth(56)
        irun_row.addWidget(self._irun_amps_lbl)
        self._irun_slider.valueChanged.connect(self._update_irun_label)
        form.addRow("IRUN:", irun_row)

        ihold_row, self._ihold_slider, self._ihold_spin = _linked_slider_spinbox(0, 31, 8)
        form.addRow("IHOLD:", ihold_row)

        ihd_row, self._iholddelay_slider, self._iholddelay_spin = _linked_slider_spinbox(0, 15, 6)
        form.addRow("IHOLD delay:", ihd_row)

        rsense_row = QHBoxLayout()
        self._rsense_spin = QDoubleSpinBox()
        self._rsense_spin.setRange(0.01, 1.0)
        self._rsense_spin.setSingleStep(0.01)
        self._rsense_spin.setDecimals(3)
        self._rsense_spin.setValue(0.11)
        self._rsense_spin.setSuffix(" Ohm")
        self._rsense_spin.setFixedWidth(100)
        self._rsense_spin.valueChanged.connect(self._update_irun_label)
        self._vsense_chk = QCheckBox("vsense")
        self._vsense_chk.toggled.connect(self._update_irun_label)
        rsense_row.addWidget(self._rsense_spin)
        rsense_row.addWidget(self._vsense_chk)
        rsense_row.addStretch()
        form.addRow("R_SENSE:", rsense_row)

        apply_btn = QPushButton("Apply Current")
        apply_btn.clicked.connect(self._on_apply_current)
        form.addRow("", apply_btn)

        self._update_irun_label()
        return box

    def _build_chopper_group(self) -> QGroupBox:
        box = QGroupBox("Microstep & Chopper")
        form = QFormLayout(box)
        form.setSpacing(5)

        ms_mode_row = QHBoxLayout()
        self._ms_combo = QComboBox()
        for ms in MICROSTEP_OPTIONS:
            self._ms_combo.addItem(str(ms), ms)
        self._ms_combo.setCurrentIndex(MICROSTEP_OPTIONS.index(16))
        self._ms_combo.setFixedWidth(72)
        self._stealthchop_radio = QRadioButton("StealthChop")
        self._stealthchop_radio.setChecked(True)
        self._spreadcycle_radio = QRadioButton("SpreadCycle")
        ms_mode_row.addWidget(self._ms_combo)
        ms_mode_row.addSpacing(12)
        ms_mode_row.addWidget(self._stealthchop_radio)
        ms_mode_row.addWidget(self._spreadcycle_radio)
        ms_mode_row.addStretch()
        form.addRow("Microsteps / Mode:", ms_mode_row)

        self._tpwmthrs_spin = QSpinBox()
        self._tpwmthrs_spin.setRange(0, 1048575)
        self._tpwmthrs_spin.setValue(500)
        form.addRow("TPWMTHRS:", self._tpwmthrs_spin)

        # TOFF, HSTRT, HEND, TBL in a single compact row
        chopper_row = QHBoxLayout()
        self._toff_spin = QSpinBox()
        self._toff_spin.setRange(1, 15)
        self._toff_spin.setValue(5)
        self._toff_spin.setFixedWidth(52)
        self._hstrt_spin = QSpinBox()
        self._hstrt_spin.setRange(0, 7)
        self._hstrt_spin.setValue(4)
        self._hstrt_spin.setFixedWidth(52)
        self._hend_spin = QSpinBox()
        self._hend_spin.setRange(0, 15)
        self._hend_spin.setValue(0)
        self._hend_spin.setFixedWidth(52)
        self._tbl_spin = QSpinBox()
        self._tbl_spin.setRange(0, 3)
        self._tbl_spin.setValue(2)
        self._tbl_spin.setFixedWidth(52)
        for label, spin in [
            ("TOFF", self._toff_spin),
            ("HSTRT", self._hstrt_spin),
            ("HEND", self._hend_spin),
            ("TBL", self._tbl_spin),
        ]:
            chopper_row.addWidget(QLabel(label))
            chopper_row.addWidget(spin)
        chopper_row.addStretch()
        form.addRow("Advanced:", chopper_row)

        apply_btn = QPushButton("Apply Chopper")
        apply_btn.clicked.connect(self._on_apply_chopper)
        form.addRow("", apply_btn)

        return box

    def _build_stallguard_group(self) -> QGroupBox:
        box = QGroupBox("StallGuard4 / CoolStep")
        form = QFormLayout(box)
        form.setSpacing(5)

        sg_row, self._sgthrs_slider, self._sgthrs_spin = _linked_slider_spinbox(0, 255, 50)
        form.addRow("SGTHRS:", sg_row)

        self._tcoolthrs_spin = QSpinBox()
        self._tcoolthrs_spin.setRange(0, 1048575)
        self._tcoolthrs_spin.setValue(200)
        form.addRow("TCOOLTHRS:", self._tcoolthrs_spin)

        apply_btn = QPushButton("Apply StallGuard")
        apply_btn.clicked.connect(self._on_apply_stallguard)
        form.addRow("", apply_btn)

        return box

    # ------------------------------------------------------------------
    # Status tab
    # ------------------------------------------------------------------

    def _build_status_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        # Polling control
        poll_row = QHBoxLayout()
        self._poll_btn = QPushButton("Start Polling")
        self._poll_btn.setCheckable(True)
        self._poll_btn.toggled.connect(self._on_poll_toggled)
        poll_row.addWidget(self._poll_btn)
        poll_row.addStretch()
        layout.addLayout(poll_row)

        # Progress bars
        bars_box = QGroupBox("Position & Load")
        bars_form = QFormLayout(bars_box)
        bars_form.setSpacing(4)

        mscnt_row = QHBoxLayout()
        self._mscnt_bar = QProgressBar()
        self._mscnt_bar.setRange(0, 1023)
        self._mscnt_bar.setValue(0)
        self._mscnt_bar.setFormat("%v")
        self._mscnt_angle_lbl = QLabel("0.0 deg")
        self._mscnt_angle_lbl.setFixedWidth(60)
        self._mscnt_angle_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        mscnt_row.addWidget(self._mscnt_bar, 1)
        mscnt_row.addWidget(self._mscnt_angle_lbl)
        bars_form.addRow("MSCNT:", mscnt_row)

        self._sg_bar = QProgressBar()
        self._sg_bar.setRange(0, 510)
        self._sg_bar.setValue(0)
        self._sg_bar.setFormat("%v")
        bars_form.addRow("SG_RESULT:", self._sg_bar)
        layout.addWidget(bars_box)

        # Numeric readouts in a 2-column grid
        readings_box = QGroupBox("Readings")
        grid = QGridLayout(readings_box)
        grid.setSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self._cura_lbl = _value_label()
        self._curb_lbl = _value_label()
        self._tstep_lbl = _value_label()
        self._cs_actual_lbl = _value_label()

        for row, (l1, v1, l2, v2) in enumerate(
            [
                ("CUR_A", self._cura_lbl, "CUR_B", self._curb_lbl),
                ("TSTEP", self._tstep_lbl, "CS_ACTUAL", self._cs_actual_lbl),
            ]
        ):
            grid.addWidget(QLabel(l1), row, 0)
            grid.addWidget(v1, row, 1)
            grid.addWidget(QLabel(l2), row, 2)
            grid.addWidget(v2, row, 3)
        layout.addWidget(readings_box)

        # Fault flags
        flags_box = QGroupBox("Fault Flags")
        flags_layout = QVBoxLayout(flags_box)
        flags_layout.setSpacing(4)

        # GSTAT row
        gstat_row = QHBoxLayout()
        self._gstat_reset_ind = _flag_label()
        self._gstat_drverr_ind = _flag_label()
        self._gstat_uvcp_ind = _flag_label()
        for name, ind in [
            ("reset", self._gstat_reset_ind),
            ("drv_err", self._gstat_drverr_ind),
            ("uv_cp", self._gstat_uvcp_ind),
        ]:
            gstat_row.addWidget(ind)
            gstat_row.addWidget(QLabel(name))
            gstat_row.addSpacing(8)
        gstat_row.addStretch()
        gstat_header = QHBoxLayout()
        gstat_header.addWidget(QLabel("GSTAT:"))
        gstat_header.addLayout(gstat_row)
        flags_layout.addLayout(gstat_header)

        # DRV_STATUS in a 2-column grid of (indicator + name) pairs
        drv_flags = [
            ("otpw", True),
            ("ot", True),
            ("s2ga", True),
            ("s2gb", True),
            ("ola", True),
            ("olb", True),
            ("stealth", False),
            ("stst", False),
        ]
        self._drv_flag_inds: dict[str, tuple[QLabel, bool]] = {}
        drv_grid = QGridLayout()
        drv_grid.setSpacing(4)
        drv_label = QLabel("DRV_STATUS:")
        flags_layout.addWidget(drv_label)
        for i, (flag_name, is_fault) in enumerate(drv_flags):
            ind = _flag_label()
            self._drv_flag_inds[flag_name] = (ind, is_fault)
            col = (i % 2) * 3
            grid_row = i // 2
            drv_grid.addWidget(ind, grid_row, col)
            drv_grid.addWidget(QLabel(flag_name), grid_row, col + 1)
            if i % 2 == 0:
                spacer = QWidget()
                spacer.setFixedWidth(16)
                spacer.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
                drv_grid.addWidget(spacer, grid_row, col + 2)
        flags_layout.addLayout(drv_grid)
        layout.addWidget(flags_box)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Move tab
    # ------------------------------------------------------------------

    def _build_move_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        move_box = QGroupBox("Step Control")
        form = QFormLayout(move_box)
        form.setSpacing(6)

        params_row = QHBoxLayout()
        self._steps_spin = QSpinBox()
        self._steps_spin.setRange(1, 100000)
        self._steps_spin.setValue(200)
        self._freq_spin = QSpinBox()
        self._freq_spin.setRange(1, 100000)
        self._freq_spin.setValue(1000)
        self._freq_spin.setSuffix(" Hz")
        params_row.addWidget(QLabel("Steps"))
        params_row.addWidget(self._steps_spin)
        params_row.addSpacing(12)
        params_row.addWidget(QLabel("Freq"))
        params_row.addWidget(self._freq_spin)
        params_row.addStretch()
        form.addRow("", params_row)

        dir_row = QHBoxLayout()
        self._cw_radio = QRadioButton("CW")
        self._cw_radio.setChecked(True)
        self._ccw_radio = QRadioButton("CCW")
        dir_row.addWidget(self._cw_radio)
        dir_row.addWidget(self._ccw_radio)
        dir_row.addStretch()
        form.addRow("Direction:", dir_row)

        btn_row = QHBoxLayout()
        self._move_btn = QPushButton("Move")
        self._move_btn.clicked.connect(self._on_move)
        self._stop_btn = QPushButton("Stop (ENN high)")
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._move_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)

        layout.addWidget(move_box)
        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_bridge(self) -> Tmc2209Bridge:
        port = self._port_combo.currentText().strip() or "auto"
        if self._bridge is None or self._bridge.port != port:
            self._bridge = Tmc2209Bridge(port=port)
        return self._bridge

    def _run_async(
        self,
        cmd: dict,
        on_result: object = None,
        on_error: object = None,
    ) -> CommandThread:
        bridge = self._get_bridge()
        thread = CommandThread(bridge, cmd, parent=self)
        if on_result:
            thread.result.connect(on_result)
        thread.error.connect(self._show_error)
        if on_error:
            thread.error.connect(on_error)
        thread.finished.connect(lambda: self._active_threads.remove(thread))
        self._active_threads.append(thread)
        thread.start()
        return thread

    def _start_thread(self, thread: QThread) -> None:
        thread.finished.connect(lambda: self._active_threads.remove(thread))
        self._active_threads.append(thread)
        thread.start()

    def _show_error(self, msg: str) -> None:
        self._status_bar.showMessage(f"Error: {msg}", 5000)

    def _update_irun_label(self) -> None:
        irun = self._irun_spin.value()
        rsense = self._rsense_spin.value()
        vsense = self._vsense_chk.isChecked()
        amps = irun_to_amps(irun, rsense_ohm=rsense, vsense=vsense)
        self._irun_amps_lbl.setText(f"{amps:.3f} A")

    # ------------------------------------------------------------------
    # Slots -- Connection
    # ------------------------------------------------------------------

    @Slot()
    def _on_refresh_ports(self) -> None:
        self._status_bar.showMessage("Scanning ports...")
        bridge = self._get_bridge()
        try:
            ports = bridge.list_ports()
        except Exception as exc:
            self._show_error(str(exc))
            return
        current = self._port_combo.currentText()
        self._port_combo.clear()
        self._port_combo.addItem("auto")
        for p in ports:
            self._port_combo.addItem(p)
        self._port_combo.setCurrentText(current if current in ["auto", *ports] else "auto")
        self._status_bar.showMessage(f"Found {len(ports)} port(s)", 3000)

    @Slot()
    def _on_upload_firmware(self) -> None:
        self._status_bar.showMessage("Uploading firmware...", 0)
        self._upload_btn.setEnabled(False)
        t = _UploadThread(self._get_bridge())
        t.done.connect(self._on_upload_done)
        t.error.connect(self._on_upload_error)
        self._start_thread(t)

    @Slot()
    def _on_upload_done(self) -> None:
        self._upload_btn.setEnabled(True)
        self._status_bar.showMessage("Firmware uploaded successfully", 4000)

    @Slot(str)
    def _on_upload_error(self, msg: str) -> None:
        self._upload_btn.setEnabled(True)
        self._show_error(msg)

    @Slot()
    def _on_connect_init(self) -> None:
        self._status_bar.showMessage("Connecting...", 0)
        self._run_async(
            {
                "cmd": "init",
                "uart_id": self._uart_id_combo.currentData(),
                "tx_pin": self._tx_pin_spin.value(),
                "rx_pin": self._rx_pin_spin.value(),
            },
            on_result=self._on_init_result,
        )

    @Slot(dict)
    def _on_init_result(self, _response: dict) -> None:
        self._connected = True
        self._conn_status_lbl.setText("Connected")
        self._conn_status_lbl.setStyleSheet("color: #27ae60; font-weight: bold;")
        self._status_bar.showMessage("Initialised -- GCONF pdn_disable=1", 4000)

    # ------------------------------------------------------------------
    # Slots -- Motor Enable
    # ------------------------------------------------------------------

    @Slot()
    def _on_enable(self) -> None:
        self._run_async({"cmd": "enable"})
        self._status_bar.showMessage("Motor enabled", 2000)

    @Slot()
    def _on_disable(self) -> None:
        self._run_async({"cmd": "disable"})
        self._status_bar.showMessage("Motor disabled", 2000)

    @Slot(bool)
    def _on_shaft_toggled(self, checked: bool) -> None:
        self._run_async({"cmd": "set_shaft", "invert": checked})

    # ------------------------------------------------------------------
    # Slots -- Current
    # ------------------------------------------------------------------

    @Slot()
    def _on_apply_current(self) -> None:
        self._run_async(
            {
                "cmd": "set_current",
                "irun": self._irun_spin.value(),
                "ihold": self._ihold_spin.value(),
                "iholddelay": self._iholddelay_spin.value(),
            }
        )
        self._status_bar.showMessage("Current applied", 2000)

    # ------------------------------------------------------------------
    # Slots -- Chopper
    # ------------------------------------------------------------------

    @Slot()
    def _on_apply_chopper(self) -> None:
        ms = self._ms_combo.currentData()
        self._run_async({"cmd": "set_microsteps", "ms": ms})
        spread = self._spreadcycle_radio.isChecked()
        self._run_async({"cmd": "set_spreadcycle", "enable": spread})
        self._run_async(
            {
                "cmd": "set_stealthchop_threshold",
                "tpwmthrs": self._tpwmthrs_spin.value(),
            }
        )
        self._run_async(
            {
                "cmd": "set_chopper",
                "toff": self._toff_spin.value(),
                "hstrt": self._hstrt_spin.value(),
                "hend": self._hend_spin.value(),
                "tbl": self._tbl_spin.value(),
            }
        )
        self._status_bar.showMessage("Chopper settings applied", 2000)

    # ------------------------------------------------------------------
    # Slots -- StallGuard
    # ------------------------------------------------------------------

    @Slot()
    def _on_apply_stallguard(self) -> None:
        self._run_async({"cmd": "set_stallguard_threshold", "sgthrs": self._sgthrs_spin.value()})
        self._run_async({"cmd": "set_coolthrs", "tcoolthrs": self._tcoolthrs_spin.value()})
        self._status_bar.showMessage("StallGuard settings applied", 2000)

    # ------------------------------------------------------------------
    # Slots -- Live Status / Polling
    # ------------------------------------------------------------------

    @Slot(bool)
    def _on_poll_toggled(self, checked: bool) -> None:
        self._polling = checked
        self._poll_btn.setText("Stop Polling" if checked else "Start Polling")
        if checked:
            self._poll_status()
        else:
            self._poll_timer.stop()

    def _poll_status(self) -> None:
        if not self._polling:
            return
        thread = CommandThread(self._get_bridge(), {"cmd": "read_status"}, parent=self)
        thread.result.connect(self._on_status_result)
        thread.error.connect(self._on_poll_error)
        thread.finished.connect(lambda: self._rearm_poll(thread))
        self._active_threads.append(thread)
        thread.start()

    def _rearm_poll(self, thread: CommandThread) -> None:
        if thread in self._active_threads:
            self._active_threads.remove(thread)
        if self._polling:
            QTimer.singleShot(500, self._poll_status)

    @Slot(dict)
    def _on_status_result(self, response: dict) -> None:
        data = response.get("data", {})

        mscnt = data.get("mscnt", 0)
        self._mscnt_bar.setValue(mscnt)
        angle = (mscnt / 1024.0) * 360.0
        self._mscnt_angle_lbl.setText(f"{angle:.1f} deg")

        mscuract = data.get("mscuract", {})
        self._cura_lbl.setText(str(mscuract.get("cur_a", "--")))
        self._curb_lbl.setText(str(mscuract.get("cur_b", "--")))

        self._sg_bar.setValue(data.get("sg_result", 0))
        self._tstep_lbl.setText(str(data.get("tstep", "--")))

        drv = data.get("drv_status", {})
        self._cs_actual_lbl.setText(str(drv.get("cs_actual", "--")))

        gstat = data.get("gstat", {})
        _set_flag(self._gstat_reset_ind, gstat.get("reset", False), fault=True)
        _set_flag(self._gstat_drverr_ind, gstat.get("drv_err", False), fault=True)
        _set_flag(self._gstat_uvcp_ind, gstat.get("uv_cp", False), fault=True)

        for flag_name, (ind, _is_fault) in self._drv_flag_inds.items():
            val = drv.get(flag_name, False)
            is_status = flag_name in ("stealth", "stst")
            _set_flag(ind, val, fault=not is_status)

    @Slot(str)
    def _on_poll_error(self, msg: str) -> None:
        self._status_bar.showMessage(f"Poll error: {msg}", 3000)

    # ------------------------------------------------------------------
    # Slots -- Step Control
    # ------------------------------------------------------------------

    @Slot()
    def _on_move(self) -> None:
        steps = self._steps_spin.value()
        freq = self._freq_spin.value()
        direction = 0 if self._cw_radio.isChecked() else 1
        step_pin = self._step_pin_spin.value()
        enn_pin = self._enn_pin_spin.value()
        dir_pin = self._dir_pin_spin.value()
        step_code = (
            f"from machine import Pin; import time; "
            f"Pin({dir_pin}, Pin.OUT).value({direction}); "
            f"Pin({enn_pin}, Pin.OUT).value(0); "
            f"step = Pin({step_pin}, Pin.OUT); "
            f"half = 1_000_000 // ({freq} * 2); "
            f"[step.toggle() or time.sleep_us(half) for _ in range({steps} * 2)]"
        )
        bridge = self._get_bridge()
        cmd_list = [_mpremote_bin(), *bridge._port_args(), "exec", step_code]
        t = _SubprocessThread(cmd_list, timeout=60.0)
        t.error.connect(self._show_error)
        t.done.connect(lambda: self._status_bar.showMessage("Move complete", 2000))
        self._start_thread(t)
        self._status_bar.showMessage(f"Moving {steps} steps at {freq} Hz...", 0)

    @Slot()
    def _on_stop(self) -> None:
        enn_pin = self._enn_pin_spin.value()
        stop_code = f"from machine import Pin; Pin({enn_pin}, Pin.OUT).value(1)"
        bridge = self._get_bridge()
        cmd_list = [_mpremote_bin(), *bridge._port_args(), "exec", stop_code]
        t = _SubprocessThread(cmd_list, timeout=5.0)
        t.error.connect(self._show_error)
        self._start_thread(t)
        self._status_bar.showMessage("Stop signal sent (ENN high)", 2000)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self._polling = False
        self._poll_timer.stop()
        for t in list(self._active_threads):
            t.requestInterruption()
            t.wait(500)
        super().closeEvent(event)
