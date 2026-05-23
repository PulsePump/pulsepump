from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pulsepump.core.programme import Block, OpenBFSource, Programme
from pulsepump.core.waveform import WaveformType

from .fg_form import FunctionGeneratorForm
from .openbf_form import OpenBFForm
from .programme_fields import ProgrammeFieldsBox


class _AdaptiveStack(QStackedWidget):
    """QStackedWidget that reports the current page's size hint rather than the max."""

    def sizeHint(self):  # type: ignore[override]
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):  # type: ignore[override]
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()


class InspectorPanel(QWidget):
    """Right-hand inspector. Composes programme/block/source-specific subforms."""

    programme_changed = Signal()
    block_changed = Signal()
    run_simulation_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._syncing = False
        self._block: Block | None = None

        fm = QFontMetrics(self.font())
        label_w = (
            max(
                fm.horizontalAdvance(t)
                for t in (
                    "Name",
                    "Sample rate",
                    "Pressure units",
                    "Repeat count",
                    "Source",
                    "Waveform",
                    "Amplitude",
                    "Offset",
                    "BPM",
                    "Duty",
                    "Symmetry",
                    "Phase",
                    "Model",
                    "Vessel",
                    "Position",
                )
            )
            + 4
        )

        self._placeholder = QLabel("No block selected")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: gray;")

        self._programme_box = ProgrammeFieldsBox(label_w)

        # Block-general controls
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Untitled block")
        self._repeat_spin = QSpinBox()
        self._repeat_spin.setMinimum(1)
        self._repeat_spin.setMaximum(99999)
        self._source_combo = QComboBox()
        self._source_combo.addItem("Function Generator")
        self._source_combo.addItem("openBF")

        general_grid = QGridLayout()
        general_grid.setContentsMargins(8, 8, 8, 8)
        general_grid.setHorizontalSpacing(12)
        general_grid.setVerticalSpacing(6)
        general_grid.setColumnMinimumWidth(0, label_w)
        general_grid.setColumnStretch(0, 0)
        general_grid.setColumnStretch(1, 1)
        _L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        _R = Qt.AlignmentFlag.AlignVCenter
        general_grid.addWidget(QLabel("Name"), 0, 0, alignment=_L)
        general_grid.addWidget(self._name_edit, 0, 1, alignment=_R)
        general_grid.addWidget(QLabel("Repeat count"), 1, 0, alignment=_L)
        general_grid.addWidget(self._repeat_spin, 1, 1, alignment=_R)
        general_grid.addWidget(QLabel("Source"), 2, 0, alignment=_L)
        general_grid.addWidget(self._source_combo, 2, 1, alignment=_R)
        self._general_box = QGroupBox("Block")
        self._general_box.setLayout(general_grid)

        self._fg_form = FunctionGeneratorForm(label_w)
        self._openbf_form = OpenBFForm(label_w)

        self._params_stack = _AdaptiveStack()
        self._params_stack.addWidget(self._fg_form)  # 0
        self._params_stack.addWidget(self._openbf_form)  # 1

        self._params_box = QGroupBox("Parameters")
        self._params_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        params_box_layout = QVBoxLayout()
        params_box_layout.setContentsMargins(0, 0, 0, 0)
        params_box_layout.setSpacing(0)
        params_box_layout.addWidget(self._params_stack)
        self._params_box.setLayout(params_box_layout)

        self._run_btn = self._openbf_form.run_button()
        self._run_btn.setVisible(False)

        form_container = QWidget()
        outer = QVBoxLayout(form_container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(self._programme_box)
        outer.addWidget(self._general_box)
        outer.addWidget(self._params_box)
        outer.addWidget(self._run_btn)
        outer.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(form_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._stack.addWidget(self._placeholder)  # 0
        self._stack.addWidget(scroll)  # 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._stack, 1)

        # Wire signals
        self._programme_box.changed.connect(self._on_programme_changed)
        self._name_edit.textEdited.connect(self._on_block_field_changed)
        self._repeat_spin.valueChanged.connect(self._on_block_field_changed)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        self._fg_form.changed.connect(self._on_block_field_changed)
        self._fg_form.layout_changed.connect(self._refresh_stack_geometry)
        self._openbf_form.changed.connect(self._on_block_field_changed)
        self._openbf_form.run_requested.connect(self.run_simulation_requested)

    # ---------- signal slots ----------

    def _on_programme_changed(self) -> None:
        if self._syncing:
            return
        self.programme_changed.emit()

    def _on_block_field_changed(self) -> None:
        if self._syncing:
            return
        self.block_changed.emit()

    def _on_source_changed(self) -> None:
        if self._syncing:
            return
        is_obf = self._source_combo.currentIndex() == 1
        if not is_obf and self._block is not None and isinstance(self._block.source, OpenBFSource):
            reply = QMessageBox.warning(
                self,
                "Switch source",
                "Switching to Function Generator will overwrite the simulation samples. Continue?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Ok:
                self._syncing = True
                self._source_combo.setCurrentIndex(1)
                self._syncing = False
                return
        self._params_stack.setCurrentIndex(1 if is_obf else 0)
        self._run_btn.setVisible(is_obf)
        self._refresh_stack_geometry()
        self._on_block_field_changed()

    def _refresh_stack_geometry(self) -> None:
        # Without these explicit calls the QGroupBox keeps the larger of its
        # two stacked pages even after the FG form hides several rows. Note:
        # we deliberately do NOT call adjustSize() on the inspector itself —
        # it lives inside a splitter and should keep the user's chosen width
        # and the full available height.
        self._params_stack.updateGeometry()
        box_layout = self._params_box.layout()
        if box_layout is not None:
            box_layout.activate()
        self._params_box.adjustSize()
        self._params_box.updateGeometry()

    # ---------- public API ----------

    def show_programme(self, programme: Programme) -> None:
        self._programme_box.set_from_programme(programme)
        self._fg_form.set_pressure_units(programme.pressure_units)

    def show_block(self, block: Block) -> None:
        self._block = block
        src = block.source
        self._syncing = True
        self._name_edit.setText(block.name)
        self._repeat_spin.setValue(block.repeat_count)

        if isinstance(src, OpenBFSource):
            self._source_combo.setCurrentIndex(1)
            self._params_stack.setCurrentIndex(1)
            self._run_btn.setVisible(True)
            self._openbf_form.set_values(src.model_key, src.vessel, src.x_fraction, src.bpm)
        else:
            self._source_combo.setCurrentIndex(0)
            self._params_stack.setCurrentIndex(0)
            self._run_btn.setVisible(False)
            self._fg_form.set_values(
                src.type,
                src.amplitude,
                src.offset,
                src.bpm,
                src.duty,
                src.symmetry,
                src.phase,
            )

        self._general_box.setVisible(True)
        self._params_box.setVisible(True)
        self._refresh_stack_geometry()
        self._syncing = False
        self._stack.setCurrentIndex(1)

    def show_programme_only(self, programme: Programme) -> None:
        """Show programme fields without a selected block."""
        self.show_programme(programme)
        self._general_box.setVisible(False)
        self._params_box.setVisible(False)
        self._run_btn.setVisible(False)
        self._stack.setCurrentIndex(1)

    def clear(self) -> None:
        self._block = None
        self._placeholder.setText("No block selected")
        self._stack.setCurrentIndex(0)

    def current_programme_values(self) -> tuple[str, float, str] | None:
        if self._stack.currentIndex() != 1:
            return None
        return self._programme_box.values()

    def set_simulation_running(self, running: bool) -> None:
        self._programme_box.set_editable(not running)
        for w in (self._name_edit, self._repeat_spin, self._source_combo):
            w.setEnabled(not running)
        self._fg_form.set_editable(not running)
        self._openbf_form.set_editable(not running)

    def current_openbf_values(self) -> tuple[str, int, str, str, float, float] | None:
        """Return (name, repeat_count, model_key, vessel, x_fraction, bpm) or None."""
        if self._params_stack.currentIndex() != 1:
            return None
        vals = self._openbf_form.values()
        if vals is None:
            return None
        model_key, vessel, x_fraction, bpm = vals
        return (
            self._name_edit.text(),
            self._repeat_spin.value(),
            model_key,
            vessel,
            x_fraction,
            bpm,
        )

    def current_block_values(
        self,
    ) -> tuple[str, int, WaveformType, float, float, float, float, float, float] | None:
        if self._params_stack.currentIndex() != 0:
            return None
        wt, amp, off, bpm, duty, sym, phase = self._fg_form.values()
        return (
            self._name_edit.text(),
            self._repeat_spin.value(),
            wt,
            amp,
            off,
            bpm,
            duty,
            sym,
            phase,
        )

    def source_is_openbf(self) -> bool:
        return self._source_combo.currentIndex() == 1
