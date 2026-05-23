from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pulsepump.openbf import ModelBundle, list_models


class OpenBFForm(QWidget):
    """openBF-specific parameter controls plus the Run button."""

    changed = Signal()
    run_requested = Signal()

    def __init__(self, label_min_width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._syncing = False

        self._model_combo = QComboBox()
        self._vessel_combo = QComboBox()

        self._x_combo = QComboBox()
        for _label, _xval in (
            ("Inlet (0%)", 0.0),
            ("25%", 0.25),
            ("50%", 0.5),
            ("75%", 0.75),
            ("Outlet (100%)", 1.0),
        ):
            self._x_combo.addItem(_label, userData=_xval)

        self._bpm_spin = QDoubleSpinBox()
        self._bpm_spin.setMinimum(1.0)
        self._bpm_spin.setMaximum(300.0)
        self._bpm_spin.setDecimals(2)
        self._bpm_spin.setSingleStep(1.0)
        self._bpm_spin.setValue(60.0)

        self._run_btn = QPushButton("Run simulation")
        self._run_btn.clicked.connect(self.run_requested)

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnMinimumWidth(0, label_min_width)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        _L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        _R = Qt.AlignmentFlag.AlignVCenter

        r = 0
        grid.addWidget(QLabel("Model"), r, 0, alignment=_L)
        grid.addWidget(self._model_combo, r, 1, alignment=_R)
        r += 1
        grid.addWidget(QLabel("Vessel"), r, 0, alignment=_L)
        grid.addWidget(self._vessel_combo, r, 1, alignment=_R)
        r += 1
        grid.addWidget(QLabel("Position"), r, 0, alignment=_L)
        grid.addWidget(self._x_combo, r, 1, alignment=_R)
        r += 1
        grid.addWidget(QLabel("BPM"), r, 0, alignment=_L)
        grid.addWidget(self._bpm_spin, r, 1, alignment=_R)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        params_container = QWidget()
        params_container.setLayout(grid)
        outer.addWidget(params_container)

        self._models: tuple[ModelBundle, ...] = list_models()
        for bundle in self._models:
            self._model_combo.addItem(bundle.label, userData=bundle)

        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._vessel_combo.currentIndexChanged.connect(self._emit_changed)
        self._x_combo.currentIndexChanged.connect(self._emit_changed)
        self._bpm_spin.valueChanged.connect(self._emit_changed)

        # Populate vessels for the initial model: addItem above ran *before*
        # the signal was connected, so currentIndexChanged never fired for the
        # default selection. Seed the vessel list directly.
        initial = self._model_combo.currentData()
        if isinstance(initial, ModelBundle):
            self._syncing = True
            for vessel in initial.vessels:
                self._vessel_combo.addItem(vessel)
            self._syncing = False

    def _emit_changed(self) -> None:
        if not self._syncing:
            self.changed.emit()

    def _on_model_changed(self) -> None:
        bundle: ModelBundle | None = self._model_combo.currentData()
        self._syncing = True
        self._vessel_combo.clear()
        if bundle is not None:
            for vessel in bundle.vessels:
                self._vessel_combo.addItem(vessel)
        self._syncing = False
        self._emit_changed()

    def run_button(self) -> QPushButton:
        return self._run_btn

    def models(self) -> tuple[ModelBundle, ...]:
        return self._models

    def set_values(self, model_key: str, vessel: str, x_fraction: float, bpm: float) -> None:
        self._syncing = True
        model_idx = next((i for i, b in enumerate(self._models) if b.key == model_key), 0)
        self._model_combo.setCurrentIndex(model_idx)
        # Refresh vessel list to match the (possibly newly-selected) model
        bundle: ModelBundle | None = self._model_combo.currentData()
        self._vessel_combo.clear()
        if bundle is not None:
            for v in bundle.vessels:
                self._vessel_combo.addItem(v)
            if vessel:
                idx = self._vessel_combo.findText(vessel)
                if idx >= 0:
                    self._vessel_combo.setCurrentIndex(idx)
        if self._x_combo.count() > 0:
            best = min(
                range(self._x_combo.count()),
                key=lambda i: abs(self._x_combo.itemData(i) - x_fraction),
            )
            self._x_combo.setCurrentIndex(best)
        self._bpm_spin.setValue(bpm)
        self._syncing = False

    def values(self) -> tuple[str, str, float, float] | None:
        bundle: ModelBundle | None = self._model_combo.currentData()
        if bundle is None:
            return None
        x_fraction: float = self._x_combo.currentData() or 0.0
        return (
            bundle.key,
            self._vessel_combo.currentText(),
            x_fraction,
            self._bpm_spin.value(),
        )

    def set_editable(self, editable: bool) -> None:
        for w in (
            self._model_combo,
            self._vessel_combo,
            self._x_combo,
            self._bpm_spin,
            self._run_btn,
        ):
            w.setEnabled(editable)
