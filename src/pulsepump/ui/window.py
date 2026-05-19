from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from .document import Document
from .programme_editor import ProgrammeEditorWidget


class DocumentWindow(QMainWindow):
    """A top-level window hosting a single document."""

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize(1100, 700)

        self._document = document
        self._editor = ProgrammeEditorWidget(document, self)
        self.setCentralWidget(self._editor)
        self._editor.status_message.connect(self.statusBar().showMessage)

        self._remove_block_act: QAction  # assigned inside _build_menu
        self._build_menu()
        self._update_title()

        document.modified_changed.connect(lambda _: self._update_title())
        document.path_changed.connect(self._update_title)
        self._editor.remove_block_enabled.connect(self._remove_block_act.setEnabled)

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

        save_act = QAction("&Save", self)
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self.save)
        file_menu.addAction(save_act)

        save_as_act = QAction("Save &As…", self)
        save_as_act.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_act.triggered.connect(self.save_as)
        file_menu.addAction(save_as_act)

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

    def save(self) -> bool:
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
