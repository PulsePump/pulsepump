from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
)

from pulsepump.core.programme import Programme


class ProgrammeFieldsBox(QGroupBox):
    """Programme-level fields: name, sample rate, pressure units."""

    changed = Signal()

    def __init__(self, label_min_width: int) -> None:
        super().__init__("Programme")
        self._syncing = False

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Untitled")

        self._sample_rate_spin = QDoubleSpinBox()
        self._sample_rate_spin.setMinimum(1.0)
        self._sample_rate_spin.setMaximum(100000.0)
        self._sample_rate_spin.setDecimals(1)
        self._sample_rate_spin.setSingleStep(10.0)
        self._sample_rate_spin.setSuffix(" Hz")

        self._pressure_units_combo = QComboBox()
        for u in ("Pa", "mmHg", "psi", "bar"):
            self._pressure_units_combo.addItem(u)

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnMinimumWidth(0, label_min_width)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        _L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        _R = Qt.AlignmentFlag.AlignVCenter

        grid.addWidget(QLabel("Name"), 0, 0, alignment=_L)
        grid.addWidget(self._name_edit, 0, 1, alignment=_R)
        grid.addWidget(QLabel("Sample rate"), 1, 0, alignment=_L)
        grid.addWidget(self._sample_rate_spin, 1, 1, alignment=_R)
        grid.addWidget(QLabel("Pressure units"), 2, 0, alignment=_L)
        grid.addWidget(self._pressure_units_combo, 2, 1, alignment=_R)
        self.setLayout(grid)

        self._name_edit.textEdited.connect(self._emit_changed)
        self._sample_rate_spin.valueChanged.connect(self._emit_changed)
        self._pressure_units_combo.currentTextChanged.connect(self._emit_changed)

    def _emit_changed(self) -> None:
        if not self._syncing:
            self.changed.emit()

    def set_from_programme(self, programme: Programme) -> None:
        self._syncing = True
        self._name_edit.setText(programme.name)
        self._sample_rate_spin.setValue(programme.sampling_rate_hz)
        idx = self._pressure_units_combo.findText(programme.pressure_units)
        if idx >= 0:
            self._pressure_units_combo.setCurrentIndex(idx)
        self._syncing = False

    def values(self) -> tuple[str, float, str]:
        return (
            self._name_edit.text(),
            self._sample_rate_spin.value(),
            self._pressure_units_combo.currentText(),
        )

    def set_editable(self, editable: bool) -> None:
        for w in (self._name_edit, self._sample_rate_spin, self._pressure_units_combo):
            w.setEnabled(editable)
