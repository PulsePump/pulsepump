from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from .document import Document
from .editor import EditorWidget
from .programme_editor import ProgrammeEditorWidget
from .tmc2209_window import Tmc2209Window


class DocumentWindow(QMainWindow):
    """A top-level window hosting a single document."""

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize(1100, 700)

        self._document = document
        self._editor = ProgrammeEditorWidget(document, self)
        self._yaml_view = EditorWidget(document, self)
        self._yaml_view.setReadOnly(True)
        self._view_stack = QStackedWidget(self)
        self._view_stack.addWidget(self._editor)  # 0
        self._view_stack.addWidget(self._yaml_view)  # 1
        self.setCentralWidget(self._view_stack)
        self._editor.status_message.connect(self.statusBar().showMessage)

        self._remove_block_act: QAction  # assigned inside _build_menu
        self._save_act: QAction
        self._save_as_act: QAction
        self._tmc2209_window: Tmc2209Window | None = None
        self._build_menu()
        self._update_title()

        document.modified_changed.connect(lambda _: self._update_title())
        document.path_changed.connect(self._update_title)
        self._editor.remove_block_enabled.connect(self._remove_block_act.setEnabled)
        self._editor.simulation_running_changed.connect(self._on_simulation_running_changed)
        self._editor.save_enabled_changed.connect(self._on_save_enabled_changed)
        # Sync initial state.
        self._apply_save_enabled(self._editor.can_save())

    @property
    def document(self) -> Document:
        return self._document

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_act = QAction("&New", self)
        new_act.setShortcut(QKeySequence.StandardKey.New)
        new_act.triggered.connect(self._new_document)
        file_menu.addAction(new_act)

        open_act = QAction("&Open…", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self._open_document)
        file_menu.addAction(open_act)

        file_menu.addSeparator()

        self._save_act = QAction("&Save", self)
        self._save_act.setShortcut(QKeySequence.StandardKey.Save)
        self._save_act.triggered.connect(self.save)
        file_menu.addAction(self._save_act)

        self._save_as_act = QAction("Save &As…", self)
        self._save_as_act.setShortcut(QKeySequence.StandardKey.SaveAs)
        self._save_as_act.triggered.connect(self.save_as)
        file_menu.addAction(self._save_as_act)

        file_menu.addSeparator()

        close_act = QAction("&Close", self)
        close_act.setShortcut(QKeySequence.StandardKey.Close)
        close_act.triggered.connect(self.close)
        file_menu.addAction(close_act)

        programme_menu = self.menuBar().addMenu("&Programme")

        add_block_act = QAction("&Add Block", self)
        add_block_act.setShortcut(QKeySequence("Ctrl+Shift+N"))
        add_block_act.triggered.connect(self._editor.add_block)
        programme_menu.addAction(add_block_act)

        self._remove_block_act = QAction("&Remove Block", self)
        self._remove_block_act.setShortcut(QKeySequence("Ctrl+Shift+Backspace"))
        self._remove_block_act.setEnabled(False)
        self._remove_block_act.triggered.connect(self._editor.remove_block)
        programme_menu.addAction(self._remove_block_act)

        programme_menu.addSeparator()

        zoom_fit_act = QAction("&Zoom to Fit", self)
        zoom_fit_act.setShortcut(QKeySequence("Ctrl+0"))
        zoom_fit_act.triggered.connect(self._editor.zoom_to_fit)
        programme_menu.addAction(zoom_fit_act)

        hardware_menu = self.menuBar().addMenu("&Hardware")
        tmc_act = QAction("TMC2209 Motor Controller…", self)
        tmc_act.triggered.connect(self._on_show_tmc2209)
        hardware_menu.addAction(tmc_act)

        view_menu = self.menuBar().addMenu("&View")
        self._yaml_view_act = QAction("Show &YAML Source", self)
        self._yaml_view_act.setShortcut(QKeySequence("Ctrl+Shift+Y"))
        self._yaml_view_act.setCheckable(True)
        self._yaml_view_act.toggled.connect(self._on_toggle_yaml_view)
        view_menu.addAction(self._yaml_view_act)

    def _on_show_tmc2209(self) -> None:
        if self._tmc2209_window is None:
            self._tmc2209_window = Tmc2209Window(parent=self)
        self._tmc2209_window.show()
        self._tmc2209_window.raise_()
        self._tmc2209_window.activateWindow()

    def _on_toggle_yaml_view(self, checked: bool) -> None:
        self._view_stack.setCurrentIndex(1 if checked else 0)
        if checked:
            self.statusBar().showMessage("YAML source (read-only)", 0)
        else:
            self.statusBar().clearMessage()

    def _new_document(self) -> None:
        from .manager import DocumentManager

        DocumentManager.instance().new_window()

    def _open_document(self) -> None:
        from .manager import DocumentManager

        docs_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open",
            docs_dir,
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        for path_str in paths:
            DocumentManager.instance().open_file(Path(path_str))

    def _on_simulation_running_changed(self, running: bool) -> None:
        if running:
            self.statusBar().showMessage("Simulation running — saving disabled", 0)
        # Actual enable/disable is handled by save_enabled_changed which folds
        # in both the simulation-running and unsimulated-openbf conditions.

    def _on_save_enabled_changed(self, enabled: bool) -> None:
        self._apply_save_enabled(enabled)
        if not enabled and not self._editor._simulating:
            self.statusBar().showMessage("Simulation not run — saving disabled", 0)

    def _apply_save_enabled(self, enabled: bool) -> None:
        self._save_act.setEnabled(enabled)
        self._save_as_act.setEnabled(enabled)

    def save(self) -> bool:
        if not self._editor.can_save():
            return False
        if self._document.path is None:
            return self.save_as()
        self.statusBar().showMessage("Saving…")
        try:
            self._document.write_to(self._document.path)
        except OSError as exc:
            self.statusBar().showMessage(f"Save failed: {exc}")
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self.statusBar().showMessage("Saved", 3000)
        return True

    def save_as(self) -> bool:
        docs_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        default = str(self._document.path or Path(docs_dir) / "Untitled.yaml")
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            default,
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not path_str:
            return False
        self.statusBar().showMessage("Saving…")
        try:
            self._document.write_to(Path(path_str))
        except OSError as exc:
            self.statusBar().showMessage(f"Save failed: {exc}")
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self.statusBar().showMessage("Saved", 3000)
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        event.accept()
        from .manager import DocumentManager

        DocumentManager.instance().on_window_closed(self)

    def _confirm_discard(self) -> bool:
        if not self._document.modified:
            return True
        if not self._editor.can_save():
            # Save is not a valid option (simulation pending or running); only offer Discard/Cancel.
            reply = QMessageBox.question(
                self,
                "Unsaved changes",
                f'"{self._document.display_name}" has unsaved changes that cannot be saved '
                f"because an openBF simulation is pending. Discard them?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            return reply == QMessageBox.StandardButton.Discard
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            f'"{self._document.display_name}" has unsaved changes. Save before closing?',
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self.save()
        return reply == QMessageBox.StandardButton.Discard

    def _update_title(self) -> None:
        name = self._document.display_name
        modifier = " •" if self._document.modified else ""
        self.setWindowTitle(f"{name}{modifier}")
