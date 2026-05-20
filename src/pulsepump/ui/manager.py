from __future__ import annotations

import contextlib
from pathlib import Path

import yaml
from PySide6.QtWidgets import QApplication

from pulsepump.core.programme import (
    Block,
    FunctionGeneratorSource,
    Programme,
    encode_samples,
)
from pulsepump.core.waveform import (
    Interpolation,
    WaveformType,
    default_fg_config,
    sample_one_cycle,
)

from .document import Document
from .window import DocumentWindow


def _default_programme_yaml() -> str:
    """Build the YAML for a one-block default programme.

    Single sine block oscillating 80-120 mmHg at 60 BPM, 100 Hz sample rate.
    Picked so new documents open with a populated, physiologically reasonable
    waveform instead of an empty editor.
    """
    cfg = default_fg_config(WaveformType.SINE, sample_rate_hz=100.0)
    src = FunctionGeneratorSource(
        kind="function_generator",
        type=cfg.type,
        bpm=cfg.bpm,
        amplitude=cfg.amplitude,
        offset=cfg.offset,
        duty=cfg.duty,
        symmetry=cfg.symmetry,
        phase=cfg.phase,
        sample_rate_hz=cfg.sample_rate_hz,
        interpolation=Interpolation.FIRST_ORDER_HOLD,
    )
    _, y = sample_one_cycle(cfg)
    block = Block(
        name="Untitled block 1",
        repeat_count=1,
        samples_f32_b64=encode_samples(y),
        source=src,
    )
    programme = Programme(
        name="Untitled",
        sampling_rate_hz=100.0,
        pressure_units="mmHg",
        blocks=[block],
    )
    return yaml.dump(programme.model_dump(mode="json"), allow_unicode=True, sort_keys=False)


class DocumentManager:
    """Singleton tracking all open DocumentWindows."""

    _instance: DocumentManager | None = None

    @classmethod
    def instance(cls) -> DocumentManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._windows: list[DocumentWindow] = []

    def new_window(self) -> DocumentWindow:
        """Open a new window pre-populated with a default sine programme."""

        doc = Document()
        doc.content = _default_programme_yaml()
        # A freshly-created file with default content is not "unsaved user
        # work" — clear the dirty flag so the title bar stays clean.
        doc.clear_modified()
        window = DocumentWindow(doc)
        self._windows.append(window)
        window.show()
        return window

    def open_file(self, path: Path) -> DocumentWindow:
        """Open a file in a new window, or focus it if already open."""

        for window in self._windows:
            if window.document.path == path:
                window.activateWindow()
                window.raise_()
                return window
        doc = Document()
        with contextlib.suppress(OSError):
            doc.read_from(path)
        window = DocumentWindow(doc)
        self._windows.append(window)
        window.show()
        return window

    def on_window_closed(self, window: DocumentWindow) -> None:
        """Remove window from the tracked set and quit when none remain."""

        if window in self._windows:
            self._windows.remove(window)
        if not self._windows:
            QApplication.quit()
