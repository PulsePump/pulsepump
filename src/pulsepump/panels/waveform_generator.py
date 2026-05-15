from __future__ import annotations

import shutil
from datetime import datetime
from importlib.resources import as_file, files
from pathlib import Path
from uuid import uuid4

import numpy as np
import pyqtgraph as pg
import yaml
from PySide6.QtCore import (
    QRunnable,
    QSettings,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pulsepump import pressure
from pulsepump.openbf.detect import (
    INSTALL_JULIA_URL,
    INSTALL_OPENBF_CMD,
    JuliaStatus,
    check_openbf,
)
from pulsepump.openbf.models import ModelBundle, list_models
from pulsepump.openbf.results import (
    VesselPressureResult,
    convert_pressure,
    interpolate_x,
    parse_vessel_pressure,
)
from pulsepump.openbf.runner import OpenBFRunner
from pulsepump.waveform import Interpolation, WaveformConfig, WaveformType, sample_one_cycle

from .base import FIELD_WIDTH, ConfigPanel, apply_field_width

_SETTINGS_ORG = "pulsepump"
_SETTINGS_APP = "pulsepump"

# funcgen keys (unchanged so existing QSettings persist)
_TYPE_KEY = "funcgen/type"
_BPM_KEY = "funcgen/bpm"
_AMP_KEY = "funcgen/amplitude"
_OFFSET_KEY = "funcgen/offset"
_DUTY_KEY = "funcgen/duty"
_SYMMETRY_KEY = "funcgen/symmetry"
_PHASE_KEY = "funcgen/phase"
_SAMPLE_RATE_KEY = "funcgen/sampleRateHz"
_INTERP_KEY = "funcgen/interpolation"

# waveform generator keys
_MODE_KEY = "waveform/mode"
_BF_MODEL_KEY = "waveform/bf_model"
_BF_VESSEL_KEY = "waveform/bf_vessel"
_BF_X_KEY = "waveform/bf_x"
_BF_BPM_KEY = "waveform/bf_bpm"
_BF_SAMPLE_RATE_KEY = "waveform/bf_sample_rate"

_DEBOUNCE_MS = 250

_DEFAULT_TYPE = WaveformType.SINE
_DEFAULT_BPM = 60.0
_DEFAULT_AMPLITUDE = 20.0
_DEFAULT_OFFSET = 80.0
_DEFAULT_DUTY = 0.5
_DEFAULT_SYMMETRY = 0.5
_DEFAULT_PHASE = 0.0
_DEFAULT_SAMPLE_RATE = 1000.0
_DEFAULT_INTERPOLATION = Interpolation.ZERO_ORDER_HOLD
_DEFAULT_BF_BPM = 60.0
_DEFAULT_BF_SAMPLE_RATE = 1000.0
_MAX_PREVIEW_SAMPLES = 5000

_INTERPOLATION_LABELS: dict[Interpolation, str] = {
    Interpolation.ZERO_ORDER_HOLD: "Zero-order hold",
    Interpolation.FIRST_ORDER_HOLD: "First-order hold",
}

_WAVEFORM_ORDER: tuple[WaveformType, ...] = (
    WaveformType.SINE,
    WaveformType.SQUARE,
    WaveformType.TRIANGLE,
    WaveformType.SAWTOOTH,
    WaveformType.PULSE,
    WaveformType.CONSTANT,
)

_WAVEFORM_LABELS: dict[WaveformType, str] = {
    WaveformType.SINE: "Sine",
    WaveformType.SQUARE: "Square",
    WaveformType.TRIANGLE: "Triangle",
    WaveformType.SAWTOOTH: "Sawtooth",
    WaveformType.PULSE: "Pulse",
    WaveformType.CONSTANT: "Constant (DC)",
}

_MODE_FUNCTION = "Function"
_MODE_OPENBF = "openBF"

# (label, x_frac) for the five fixed output positions openBF writes
_SAMPLE_POINTS: tuple[tuple[str, float], ...] = (
    ("0% — inlet", 0.0),
    ("25%", 0.25),
    ("50% — midpoint", 0.5),
    ("75%", 0.75),
    ("100% — outlet", 1.0),
)


def _load_float(settings: QSettings, key: str, default: float) -> float:
    raw = settings.value(key, default)
    try:
        return float(str(raw))
    except TypeError, ValueError:
        return default


def _load_str(settings: QSettings, key: str, default: str) -> str:
    raw = settings.value(key, default)
    return default if raw is None else str(raw)


def _load_type(settings: QSettings) -> WaveformType:
    raw = _load_str(settings, _TYPE_KEY, _DEFAULT_TYPE.value)
    try:
        return WaveformType(raw)
    except ValueError:
        return _DEFAULT_TYPE


def _load_interpolation(settings: QSettings) -> Interpolation:
    raw = _load_str(settings, _INTERP_KEY, _DEFAULT_INTERPOLATION.value)
    try:
        return Interpolation(raw)
    except ValueError:
        return _DEFAULT_INTERPOLATION


class WaveformGeneratorPanel(ConfigPanel):
    title = "Waveform generator"

    waveformChanged = Signal(object)  # WaveformConfig (Function mode)
    samplesReady = Signal(object, object)  # (t_array, y_array) in active pressure units
    processOutput = Signal(str, str)  # (stream, line) from Julia runner
    modeChanged = Signal(str)  # "Function" or "openBF"
    statusMessage = Signal(str)  # messages for the main window status bar
    simulationStarted = Signal()  # emitted just before Julia process is launched

    # Internal signal — marshals detection result back to the main thread safely
    _detect_finished = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)

        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._models: tuple[ModelBundle, ...] = ()
        self._last_result: VesselPressureResult | None = None
        self._last_results_dir: Path | None = None
        self._last_run_key: tuple[str, float, float] | None = None
        self._run_dirs: list[Path] = []
        self._runner = OpenBFRunner(self)
        self._pending_run_dir: Path = Path()
        self._pending_vessel: str = ""
        self._pending_bundle: ModelBundle | None = None

        saved_mode = _load_str(self._settings, _MODE_KEY, _MODE_FUNCTION)
        self._preview_mode: str = saved_mode

        self._runner.stdout.connect(lambda line: self.processOutput.emit("stdout", line))
        self._runner.stderr.connect(lambda line: self.processOutput.emit("stderr", line))
        self._runner.finished.connect(self._on_run_finished)
        self._runner.failed.connect(self._on_run_failed)
        self._detect_finished.connect(self._on_detection_done)

        # ── Splitter: preview (top) + controls (bottom) ───────────────────────
        self._splitter = QSplitter(Qt.Orientation.Vertical, self)

        self._plot = pg.PlotWidget(self._splitter)
        self._plot.setBackground("w")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("bottom", "t", units="s")
        self._plot.setLabel("left", "Pressure", units=pressure.units())
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMenuEnabled(False)
        self._plot.hideButtons()
        self._pen = pg.mkPen("#1f77b4", width=2)
        self._curve = self._plot.plot(pen=self._pen)
        self._markers = self._plot.plot(
            pen=None,
            symbol="o",
            symbolSize=4,
            symbolBrush="#1f77b4",
            symbolPen=None,
        )

        self._ctl = QWidget(self._splitter)
        _ctl_layout = QVBoxLayout(self._ctl)
        _ctl_layout.setContentsMargins(8, 8, 8, 8)
        _ctl_layout.setSpacing(6)

        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self.body.addWidget(self._splitter)

        # ── Source group ──────────────────────────────────────────────────────
        source_group = QGroupBox(self)
        source_form = QFormLayout(source_group)
        source_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.mode_combo = QComboBox(source_group)
        self.mode_combo.addItem(_MODE_FUNCTION)
        self.mode_combo.addItem(_MODE_OPENBF)
        apply_field_width(self.mode_combo)
        mode_idx = self.mode_combo.findText(saved_mode)
        if mode_idx >= 0:
            self.mode_combo.setCurrentIndex(mode_idx)
        source_form.addRow("Source", self.mode_combo)
        _ctl_layout.addWidget(source_group)

        # ── Stacked pages ─────────────────────────────────────────────────────
        self._stack = QStackedWidget(self)
        _ctl_layout.addWidget(self._stack)

        self._func_page = QWidget()
        func_layout = QVBoxLayout(self._func_page)
        func_layout.setContentsMargins(0, 0, 0, 0)
        func_layout.setSpacing(6)
        self._build_function_page(func_layout)
        self._stack.addWidget(self._func_page)

        self._openbf_page = QWidget()
        openbf_layout = QVBoxLayout(self._openbf_page)
        openbf_layout.setContentsMargins(0, 0, 0, 0)
        openbf_layout.setSpacing(6)
        self._build_openbf_page(openbf_layout)
        self._stack.addWidget(self._openbf_page)

        _ctl_layout.addStretch(1)

        initial_idx = 0 if saved_mode == _MODE_FUNCTION else 1
        self._stack.setCurrentIndex(initial_idx)
        self._on_stack_page_changed(initial_idx)
        self._stack.currentChanged.connect(self._on_stack_page_changed)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)

        self.refresh_units()

        self.waveformChanged.connect(self._update_function_preview)
        self.samplesReady.connect(self._update_openbf_preview)

        if saved_mode == _MODE_OPENBF:
            self._start_detection()

    # ── Function page ─────────────────────────────────────────────────────────

    def _build_function_page(self, layout: QVBoxLayout) -> None:
        wtype = _load_type(self._settings)
        bpm = _load_float(self._settings, _BPM_KEY, _DEFAULT_BPM)
        amplitude = _load_float(self._settings, _AMP_KEY, _DEFAULT_AMPLITUDE)
        offset = _load_float(self._settings, _OFFSET_KEY, _DEFAULT_OFFSET)
        duty = _load_float(self._settings, _DUTY_KEY, _DEFAULT_DUTY)
        symmetry = _load_float(self._settings, _SYMMETRY_KEY, _DEFAULT_SYMMETRY)
        phase = _load_float(self._settings, _PHASE_KEY, _DEFAULT_PHASE)
        sample_rate = _load_float(self._settings, _SAMPLE_RATE_KEY, _DEFAULT_SAMPLE_RATE)
        interpolation = _load_interpolation(self._settings)

        params_group = QGroupBox("Parameters", self._func_page)
        self._params_form = QFormLayout(params_group)
        self._params_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.type_combo = QComboBox(params_group)
        for w in _WAVEFORM_ORDER:
            self.type_combo.addItem(_WAVEFORM_LABELS[w], w.value)
        idx = self.type_combo.findData(wtype.value)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        apply_field_width(self.type_combo)
        self._params_form.addRow("Waveform", self.type_combo)

        self.bpm_spin = self._spin(
            parent=self._func_page,
            value=bpm,
            minimum=1.0,
            maximum=600.0,
            step=1.0,
            decimals=1,
            suffix=" BPM",
        )
        self.period_label = QLabel("", params_group)
        self.sample_rate_spin = self._spin(
            parent=self._func_page,
            value=sample_rate,
            minimum=10.0,
            maximum=20_000.0,
            step=100.0,
            decimals=0,
            suffix=" Hz",
        )
        self.sample_rate_spin.setToolTip(
            "Setpoint update rate the fluid sim will consume (samples per second)."
        )
        self.amp_spin = self._spin(
            parent=self._func_page,
            value=amplitude,
            minimum=0.0,
            maximum=10_000.0,
            step=1.0,
            decimals=2,
        )
        self.offset_spin = self._spin(
            parent=self._func_page,
            value=offset,
            minimum=-10_000.0,
            maximum=10_000.0,
            step=1.0,
            decimals=2,
        )
        self.phase_spin = self._spin(
            parent=self._func_page,
            value=phase,
            minimum=0.0,
            maximum=1.0,
            step=0.05,
            decimals=3,
            suffix=" cyc",
        )
        self.phase_spin.setWrapping(True)
        self.duty_spin = self._spin(
            parent=self._func_page,
            value=duty,
            minimum=0.01,
            maximum=0.99,
            step=0.05,
            decimals=2,
        )
        self.duty_spin.setToolTip("Fraction of the cycle where the output is high.")
        self.symmetry_spin = self._spin(
            parent=self._func_page,
            value=symmetry,
            minimum=0.0,
            maximum=1.0,
            step=0.05,
            decimals=2,
        )
        self.symmetry_spin.setToolTip(
            "Triangle: 0.5 is symmetric, 1.0 a rising ramp, 0.0 a falling ramp. "
            "Sawtooth: > 0.5 rises, ≤ 0.5 falls."
        )

        self._params_form.addRow("Rate", self.bpm_spin)
        self._params_form.addRow("Period", self.period_label)
        self._params_form.addRow("Sample rate", self.sample_rate_spin)
        self._params_form.addRow("Amplitude", self.amp_spin)
        self._params_form.addRow("Offset", self.offset_spin)
        self._params_form.addRow("Phase", self.phase_spin)
        self._params_form.addRow("Duty cycle", self.duty_spin)
        self._params_form.addRow("Symmetry", self.symmetry_spin)
        layout.addWidget(params_group)

        preview_group = QGroupBox("Preview", self._func_page)
        preview_form = QFormLayout(preview_group)
        preview_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.interp_combo = QComboBox(preview_group)
        for interp in (Interpolation.ZERO_ORDER_HOLD, Interpolation.FIRST_ORDER_HOLD):
            self.interp_combo.addItem(_INTERPOLATION_LABELS[interp], interp.value)
        idx = self.interp_combo.findData(interpolation.value)
        if idx >= 0:
            self.interp_combo.setCurrentIndex(idx)
        apply_field_width(self.interp_combo)
        preview_form.addRow("Interpolation", self.interp_combo)
        layout.addWidget(preview_group)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._commit)

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.bpm_spin.valueChanged.connect(self._on_bpm_changed)
        self.sample_rate_spin.valueChanged.connect(self._schedule_commit)
        self.amp_spin.valueChanged.connect(self._schedule_commit)
        self.offset_spin.valueChanged.connect(self._schedule_commit)
        self.phase_spin.valueChanged.connect(self._schedule_commit)
        self.duty_spin.valueChanged.connect(self._schedule_commit)
        self.symmetry_spin.valueChanged.connect(self._schedule_commit)
        self.interp_combo.currentIndexChanged.connect(self._schedule_commit)

        self._refresh_period_label()
        self._refresh_shape_visibility()

    # ── openBF page ───────────────────────────────────────────────────────────

    def _build_openbf_page(self, layout: QVBoxLayout) -> None:
        # Re-check row — visible only when detection has failed
        recheck_row = QHBoxLayout()
        self._recheck_btn = QPushButton("Re-check Julia / openBF", self._openbf_page)
        self._recheck_btn.setFixedWidth(FIELD_WIDTH + 60)
        self._recheck_btn.clicked.connect(self._start_detection)
        self._recheck_btn.hide()
        recheck_row.addStretch()
        recheck_row.addWidget(self._recheck_btn)
        layout.addLayout(recheck_row)

        self._sim_group = QGroupBox("Parameters", self._openbf_page)
        self._sim_group.setEnabled(False)
        sim_form = QFormLayout(self._sim_group)
        sim_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # Model and vessel use minimum width so they expand to fill the panel
        self.model_combo = QComboBox(self._sim_group)
        self.model_combo.setMinimumWidth(FIELD_WIDTH)
        self.model_combo.view().setMinimumWidth(260)
        sim_form.addRow("Model", self.model_combo)

        self.vessel_combo = QComboBox(self._sim_group)
        self.vessel_combo.setMinimumWidth(FIELD_WIDTH)
        self.vessel_combo.view().setMinimumWidth(260)
        sim_form.addRow("Vessel", self.vessel_combo)

        self.x_combo = QComboBox(self._sim_group)
        for label, xf in _SAMPLE_POINTS:
            self.x_combo.addItem(label, xf)
        saved_x = _load_float(self._settings, _BF_X_KEY, 0.0)
        x_idx = next((i for i, (_, xf) in enumerate(_SAMPLE_POINTS) if abs(xf - saved_x) < 0.01), 0)
        self.x_combo.setCurrentIndex(x_idx)
        apply_field_width(self.x_combo)
        sim_form.addRow("Sample point", self.x_combo)

        saved_bpm = _load_float(self._settings, _BF_BPM_KEY, _DEFAULT_BF_BPM)
        self.bf_bpm_spin = self._spin(
            parent=self._sim_group,
            value=saved_bpm,
            minimum=10.0,
            maximum=300.0,
            step=5.0,
            decimals=0,
            suffix=" BPM",
        )
        self.bf_period_label = QLabel("", self._sim_group)
        sim_form.addRow("Heart rate", self.bf_bpm_spin)
        sim_form.addRow("Period", self.bf_period_label)

        saved_sr = _load_float(self._settings, _BF_SAMPLE_RATE_KEY, _DEFAULT_BF_SAMPLE_RATE)
        self.bf_sample_rate_spin = self._spin(
            parent=self._sim_group,
            value=saved_sr,
            minimum=10.0,
            maximum=20_000.0,
            step=100.0,
            decimals=0,
            suffix=" Hz",
        )
        sim_form.addRow("Sample rate", self.bf_sample_rate_spin)

        layout.addWidget(self._sim_group)

        self.run_btn = QPushButton("Run simulation", self._openbf_page)
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run_simulation)
        _run_btn_row = QHBoxLayout()
        _run_btn_row.addStretch()
        _run_btn_row.addWidget(self.run_btn)
        layout.addLayout(_run_btn_row)

        layout.addStretch(1)

        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.vessel_combo.currentIndexChanged.connect(self._on_vessel_changed)
        self.x_combo.currentIndexChanged.connect(self._on_x_changed)
        self.bf_bpm_spin.valueChanged.connect(self._on_bf_bpm_changed)
        self.bf_sample_rate_spin.valueChanged.connect(self._on_bf_sample_rate_changed)

        self._models = list_models()
        saved_model = _load_str(self._settings, _BF_MODEL_KEY, "")
        for bundle in self._models:
            self.model_combo.addItem(bundle.label, bundle.key)
        restore_idx = self.model_combo.findData(saved_model)
        if restore_idx >= 0:
            self.model_combo.setCurrentIndex(restore_idx)
        self._populate_vessels()
        self._refresh_bf_period_label()

    # ── Detection ─────────────────────────────────────────────────────────────

    def _start_detection(self) -> None:
        self._recheck_btn.hide()
        self._sim_group.setEnabled(False)
        self._update_run_btn()
        self.statusMessage.emit("Checking Julia and openBF…")

        panel = self

        class _Worker(QRunnable):
            def __init__(self) -> None:
                super().__init__()
                self.setAutoDelete(True)

            def run(self) -> None:
                panel._detect_finished.emit(check_openbf())

        QThreadPool.globalInstance().start(_Worker())

    @Slot(object)
    def _on_detection_done(self, status: JuliaStatus) -> None:
        if not status.julia_found:
            self.statusMessage.emit("Julia not found on PATH.")
            self._recheck_btn.show()
            QMessageBox.warning(
                self,
                "Julia not found",
                f"Julia was not found on PATH.\n\nInstall from: {INSTALL_JULIA_URL}",
            )
        elif not status.openbf_found:
            self.statusMessage.emit(
                f"Julia found ({status.julia_version}) but openBF is not installed."
            )
            self._recheck_btn.show()
            QMessageBox.warning(
                self,
                "openBF not installed",
                f"openBF is not installed.\n\nIn the Julia REPL, run:\n{INSTALL_OPENBF_CMD}",
            )
        else:
            self.statusMessage.emit(f"openBF ready ({status.julia_version})")
            self._recheck_btn.hide()
            self._sim_group.setEnabled(True)
            self._update_run_btn()

    # ── Model / vessel helpers ─────────────────────────────────────────────────

    def _current_bundle(self) -> ModelBundle | None:
        key = self.model_combo.currentData()
        for b in self._models:
            if b.key == key:
                return b
        return None

    def _populate_vessels(self) -> None:
        bundle = self._current_bundle()
        self.vessel_combo.blockSignals(True)
        self.vessel_combo.clear()
        if bundle:
            for v in bundle.vessels:
                self.vessel_combo.addItem(v)
            saved = _load_str(self._settings, _BF_VESSEL_KEY, "")
            idx = self.vessel_combo.findText(saved)
            if idx >= 0:
                self.vessel_combo.setCurrentIndex(idx)
        self.vessel_combo.blockSignals(False)

    def _run_key(self) -> tuple[str, float, float]:
        return (
            str(self.model_combo.currentData() or ""),
            self.bf_bpm_spin.value(),
            self.bf_sample_rate_spin.value(),
        )

    def _update_run_btn(self) -> None:
        if not self._sim_group.isEnabled():
            self.run_btn.setEnabled(False)
            return
        needs_run = self._last_results_dir is None or self._run_key() != self._last_run_key
        self.run_btn.setEnabled(needs_run)

    def _clear_samples(self) -> None:
        self._last_result = None
        self.samplesReady.emit(np.array([]), np.array([]))

    def _on_model_changed(self, _idx: int) -> None:
        self._last_results_dir = None
        self._settings.setValue(_BF_MODEL_KEY, self.model_combo.currentData())
        self._clear_samples()
        self._populate_vessels()
        self._update_run_btn()

    def _on_vessel_changed(self, _idx: int) -> None:
        vessel = self.vessel_combo.currentText()
        self._settings.setValue(_BF_VESSEL_KEY, vessel)
        if self._last_results_dir is not None and vessel:
            try:
                self._last_result = parse_vessel_pressure(self._last_results_dir, vessel)
                self._reinterpolate()
                return
            except Exception:
                pass
        self._clear_samples()

    def _on_x_changed(self, _idx: int) -> None:
        xf = self.x_combo.currentData()
        self._settings.setValue(_BF_X_KEY, float(xf) if xf is not None else 0.0)
        self._reinterpolate()

    def _on_bf_bpm_changed(self, _value: float) -> None:
        self._settings.setValue(_BF_BPM_KEY, self.bf_bpm_spin.value())
        self._refresh_bf_period_label()
        self._last_results_dir = None
        self._clear_samples()
        self._update_run_btn()

    def _on_bf_sample_rate_changed(self, _value: float) -> None:
        self._settings.setValue(_BF_SAMPLE_RATE_KEY, self.bf_sample_rate_spin.value())
        self._last_results_dir = None
        self._clear_samples()
        self._update_run_btn()

    def _refresh_bf_period_label(self) -> None:
        period = 60.0 / max(self.bf_bpm_spin.value(), 1e-6)
        self.bf_period_label.setText(f"{period:.3f} s")

    def _reinterpolate(self) -> None:
        if self._last_result is None:
            return
        xf = self.x_combo.currentData()
        x_frac = float(xf) if xf is not None else 0.0
        p_pa = interpolate_x(self._last_result, x_frac)
        y = convert_pressure(p_pa, pressure.units())
        t = self._last_result.t - self._last_result.t[0]
        self.samplesReady.emit(t, y)

    # ── Run simulation ────────────────────────────────────────────────────────

    def _scale_inlet(self, src: Path, dst: Path, bpm: float) -> None:
        data = np.loadtxt(src)
        t_max = float(data[-1, 0])
        if t_max > 0:
            scale = (60.0 / max(bpm, 1.0)) / t_max
            data[:, 0] = data[:, 0] * scale
        np.savetxt(dst, data, fmt="%.18e")

    def _run_simulation(self) -> None:
        if self._runner.is_running():
            return
        bundle = self._current_bundle()
        vessel = self.vessel_combo.currentText()
        if bundle is None or not vessel:
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        )
        run_dir = data_dir / "openbf_runs" / f"{ts}_{uuid4().hex[:8]}"
        run_dir.mkdir(parents=True, exist_ok=True)
        self._run_dirs.append(run_dir)

        pkg = files("pulsepump.openbf_models")
        model_pkg = pkg
        for part in bundle.key.split("/"):
            model_pkg = model_pkg.joinpath(part)

        bpm = self.bf_bpm_spin.value()
        period = 60.0 / max(bpm, 1.0)
        jump = max(2, int(self.bf_sample_rate_spin.value() * period))
        with as_file(model_pkg.joinpath(bundle.yaml_name)) as yaml_src:
            with open(yaml_src) as fh:
                sim_config = yaml.safe_load(fh)
            sim_config["solver"]["jump"] = jump
            with open(run_dir / bundle.yaml_name, "w") as fh:
                yaml.safe_dump(sim_config, fh)
        with as_file(model_pkg.joinpath(bundle.inlet_name)) as dat_src:
            self._scale_inlet(Path(dat_src), run_dir / bundle.inlet_name, bpm)
        with as_file(pkg.joinpath("run_openbf.jl")) as jl_src:
            run_script = run_dir / "run_openbf.jl"
            shutil.copy(jl_src, run_script)

        self._pending_run_dir = run_dir
        self._pending_vessel = vessel
        self._pending_bundle = bundle

        self.run_btn.setEnabled(False)
        self.simulationStarted.emit()
        self.statusMessage.emit(f"Running simulation: {bundle.label} / {vessel}…")
        self._runner.run(str(run_dir), str(run_script), bundle.yaml_name)

    def _on_run_finished(self, exit_code: int) -> None:
        self.run_btn.setEnabled(True)
        if exit_code != 0:
            msg = f"Simulation failed (exit {exit_code})"
            self.statusMessage.emit(msg)
            QMessageBox.critical(self, "Simulation error", msg)
            return
        bundle = self._pending_bundle
        assert bundle is not None
        results_dir = self._pending_run_dir / f"{bundle.project_name}_results"
        try:
            result = parse_vessel_pressure(results_dir, self._pending_vessel)
        except Exception as exc:
            msg = f"Could not parse results: {exc}"
            self.statusMessage.emit(msg)
            QMessageBox.critical(self, "Simulation error", msg)
            return
        self._last_results_dir = results_dir
        self._last_run_key = self._run_key()
        self._last_result = result
        self.statusMessage.emit(f"Simulation complete: {bundle.label} / {self._pending_vessel}")
        self._update_run_btn()
        self._reinterpolate()

    def _on_run_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.statusMessage.emit(f"Simulation error: {message}")
        QMessageBox.critical(self, "Simulation error", message)

    # ── Embedded preview ──────────────────────────────────────────────────────

    def _clear_preview(self) -> None:
        self._curve.setData(x=[], y=[])
        self._markers.setData(x=[], y=[])

    def _update_function_preview(self, config: WaveformConfig) -> None:
        if self._preview_mode != _MODE_FUNCTION:
            return
        n = min(config.samples_per_cycle, _MAX_PREVIEW_SAMPLES)
        t, y = sample_one_cycle(config, n=n)
        step_mode = "right" if config.interpolation == Interpolation.ZERO_ORDER_HOLD else None
        self._curve.setData(t, y, stepMode=step_mode, pen=self._pen)
        if n <= 200:
            self._markers.setData(t, y)
        else:
            self._markers.setData(x=[], y=[])
        self._plot.getPlotItem().setXRange(0.0, config.period_s, padding=0.02)

    def _update_openbf_preview(self, t: np.ndarray, y: np.ndarray) -> None:
        if self._preview_mode != _MODE_OPENBF:
            return
        if len(t) == 0:
            self._curve.setData(x=[], y=[])
            self._markers.setData(x=[], y=[])
            return
        self._curve.setData(t, y, stepMode=None, pen=self._pen)
        self._markers.setData(x=[], y=[])
        if len(t) >= 2:
            self._plot.getPlotItem().setXRange(float(t[0]), float(t[-1]), padding=0.02)

    # ── Mode switching ────────────────────────────────────────────────────────

    def _on_stack_page_changed(self, idx: int) -> None:
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
            if w is not None:
                policy = QSizePolicy.Policy.Preferred if i == idx else QSizePolicy.Policy.Ignored
                w.setSizePolicy(policy, policy)
        self._stack.adjustSize()

    def _on_mode_changed(self, mode: str) -> None:
        self._settings.setValue(_MODE_KEY, mode)
        self._stack.setCurrentIndex(0 if mode == _MODE_FUNCTION else 1)
        if mode == _MODE_OPENBF and not self._sim_group.isEnabled():
            self._start_detection()
        self._preview_mode = mode
        self._clear_preview()
        self.modeChanged.emit(mode)
        self.replay()

    def replay(self) -> None:
        mode = self.mode_combo.currentText()
        if mode == _MODE_FUNCTION:
            self.waveformChanged.emit(self.current_config())
        elif self._last_result is not None:
            self._reinterpolate()

    # ── Function-mode helpers ─────────────────────────────────────────────────

    def _spin(
        self,
        *,
        parent: QWidget,
        value: float,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(parent)
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        if suffix:
            spin.setSuffix(suffix)
        spin.setAccelerated(True)
        spin.setKeyboardTracking(False)
        spin.setFixedWidth(FIELD_WIDTH)
        spin.setValue(value)
        return spin

    def current_type(self) -> WaveformType:
        data = self.type_combo.currentData()
        try:
            return WaveformType(data)
        except ValueError:
            return _DEFAULT_TYPE

    def current_interpolation(self) -> Interpolation:
        data = self.interp_combo.currentData()
        try:
            return Interpolation(data)
        except ValueError:
            return _DEFAULT_INTERPOLATION

    def current_config(self) -> WaveformConfig:
        return WaveformConfig(
            type=self.current_type(),
            bpm=self.bpm_spin.value(),
            amplitude=self.amp_spin.value(),
            offset=self.offset_spin.value(),
            duty=self.duty_spin.value(),
            symmetry=self.symmetry_spin.value(),
            phase=self.phase_spin.value(),
            sample_rate_hz=self.sample_rate_spin.value(),
            interpolation=self.current_interpolation(),
        )

    @Slot()
    def refresh_units(self) -> None:
        suffix = f" {pressure.units()}"
        self.amp_spin.setSuffix(suffix)
        self.offset_spin.setSuffix(suffix)
        self._plot.setLabel("left", "Pressure", units=pressure.units())
        if self.mode_combo.currentText() == _MODE_OPENBF and self._last_result is not None:
            self._reinterpolate()

    def _on_type_changed(self, _idx: int) -> None:
        self._refresh_shape_visibility()
        self._schedule_commit()

    def _on_bpm_changed(self, _value: float) -> None:
        self._refresh_period_label()
        self._schedule_commit()

    def _schedule_commit(self, *_args: object) -> None:
        self._debounce.start()

    def _refresh_period_label(self) -> None:
        period = 60.0 / max(self.bpm_spin.value(), 1e-6)
        self.period_label.setText(f"{period:.3f} s")

    def _refresh_shape_visibility(self) -> None:
        wtype = self.current_type()
        show_duty = wtype in (WaveformType.SQUARE, WaveformType.PULSE)
        show_symmetry = wtype in (WaveformType.TRIANGLE, WaveformType.SAWTOOTH)
        self._params_form.setRowVisible(self.duty_spin, show_duty)
        self._params_form.setRowVisible(self.symmetry_spin, show_symmetry)

    def _commit(self) -> None:
        config = self.current_config()
        self._settings.setValue(_TYPE_KEY, config.type.value)
        self._settings.setValue(_BPM_KEY, config.bpm)
        self._settings.setValue(_AMP_KEY, config.amplitude)
        self._settings.setValue(_OFFSET_KEY, config.offset)
        self._settings.setValue(_DUTY_KEY, config.duty)
        self._settings.setValue(_SYMMETRY_KEY, config.symmetry)
        self._settings.setValue(_PHASE_KEY, config.phase)
        self._settings.setValue(_SAMPLE_RATE_KEY, config.sample_rate_hz)
        self._settings.setValue(_INTERP_KEY, config.interpolation.value)
        if self.mode_combo.currentText() == _MODE_FUNCTION:
            self.waveformChanged.emit(config)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._runner.kill()
        for d in self._run_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._run_dirs.clear()
