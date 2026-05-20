from __future__ import annotations

from typing import Any, cast

import numpy as np
import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from pulsepump.core.programme import (
    Block,
    FunctionGeneratorSource,
    OpenBFSource,
    PressureUnits,
    Programme,
    decode_samples,
    encode_samples,
)
from pulsepump.core.units import convert as convert_pressure_value
from pulsepump.core.waveform import (
    Interpolation,
    WaveformType,
    default_fg_config,
    sample_one_cycle,
)

from ..document import Document
from .block_list import BlockListPanel
from .inspector import InspectorPanel
from .julia_console import JuliaConsoleWindow
from .simulation import SimRequest, SimResult, SimulationController
from .waveform_view import WaveformView


def _make_default_block(
    sampling_rate_hz: float,
    name: str = "",
    waveform_type: WaveformType = WaveformType.SINE,
) -> Block:
    cfg = default_fg_config(waveform_type, sampling_rate_hz)
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
        interpolation=cfg.interpolation,
    )
    _, y = sample_one_cycle(cfg)
    return Block(name=name, repeat_count=1, samples_f32_b64=encode_samples(y), source=src)


def _obf_signature(src: OpenBFSource) -> tuple[str, str, float, float]:
    return (src.model_key, src.vessel, round(src.x_fraction, 6), round(src.bpm, 4))


def _migrate_kpa_to_mmhg(raw: object) -> bool:
    """In-place migrate a parsed YAML dict from ``pressure_units: kPa`` to mmHg.

    kPa was dropped as a supported unit; existing files that used it would
    otherwise fail Pydantic validation. Convert numeric values (FG amp/offset
    and per-block samples) so the displayed waveform is unchanged.
    Returns True iff a migration was applied.
    """
    if not isinstance(raw, dict):
        return False
    d = cast(dict[str, Any], raw)
    if d.get("pressure_units") != "kPa":
        return False
    d["pressure_units"] = "mmHg"
    # kPa is no longer a supported unit, so we can't ask `convert`; use the
    # closed-form factor: 1 kPa = 1000 Pa = 1000 / 133.322387415 mmHg.
    factor = 1_000.0 / 133.322387415  # ≈ 7.500617
    for block in d.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        src = block.get("source")
        if isinstance(src, dict) and src.get("kind") == "function_generator":
            for key in ("amplitude", "offset"):
                v = src.get(key)
                if isinstance(v, int | float):
                    src[key] = float(v) * factor
        b64 = block.get("samples_f32_b64")
        if isinstance(b64, str) and b64:
            samples = decode_samples(b64)
            block["samples_f32_b64"] = encode_samples(samples * factor)
    return True


class ProgrammeEditorWidget(QWidget):
    status_message = Signal(str, int)  # message, timeout_ms (0 = persistent)
    remove_block_enabled = Signal(bool)
    simulation_running_changed = Signal(bool)
    save_enabled_changed = Signal(bool)  # True iff no unsimulated openBF blocks and no sim running

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self._programme: Programme | None = None
        self._selected_index: int | None = None
        self._syncing = False
        self._simulating = False
        # Per-block signature of the last simulation whose samples currently sit
        # in the block. ``None`` means "no simulation has produced these samples".
        # Length stays in lockstep with ``programme.blocks``.
        self._simulated_sig: list[tuple[str, str, float, float] | None] = []

        self._block_list = BlockListPanel()
        self._waveform = WaveformView()
        self._inspector = InspectorPanel()
        self._sim = SimulationController(self._inspector._openbf_form.models(), self)
        self._console: JuliaConsoleWindow | None = None

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._block_list)
        splitter.addWidget(self._waveform)
        splitter.addWidget(self._inspector)
        splitter.setSizes([200, 500, 260])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self._block_list.block_selected.connect(self._on_block_selected)
        self._block_list.add_block_requested.connect(self.add_block)
        self._block_list.remove_block_requested.connect(self.remove_block)
        self._inspector.programme_changed.connect(self._on_programme_inspector_changed)
        self._inspector.block_changed.connect(self._on_block_inspector_changed)
        self._inspector.run_simulation_requested.connect(self._on_run_simulation)
        document.content_changed.connect(self._on_document_content_changed)

        self._sim.started.connect(self._on_sim_started)
        self._sim.stdout.connect(self._on_sim_stdout)
        self._sim.stderr.connect(self._on_sim_stderr)
        self._sim.finished.connect(self._on_sim_finished)
        self._sim.failed.connect(self._on_sim_failed)

        self._parse_programme()
        self._rebuild_all()

    # ---------- save / unsimulated tracking ----------

    def _unsimulated_indices(self) -> set[int]:
        if self._programme is None:
            return set()
        out: set[int] = set()
        for i, block in enumerate(self._programme.blocks):
            if not isinstance(block.source, OpenBFSource):
                continue
            sig = self._simulated_sig[i] if i < len(self._simulated_sig) else None
            if sig != _obf_signature(block.source):
                out.add(i)
        return out

    def _emit_save_enabled(self) -> None:
        enabled = not self._simulating and not self._unsimulated_indices()
        self.save_enabled_changed.emit(enabled)

    def can_save(self) -> bool:
        return not self._simulating and not self._unsimulated_indices()

    def has_unsimulated_openbf_blocks(self) -> bool:
        return bool(self._unsimulated_indices())

    # ---------- document sync ----------

    def _parse_programme(self) -> None:
        content = self._document.content
        if not content.strip():
            self._programme = None
            self._simulated_sig = []
            return
        try:
            raw = yaml.safe_load(content)
            migrated = _migrate_kpa_to_mmhg(raw)
            self._programme = Programme.model_validate(raw)
            n = len(self._programme.blocks)
            # On load, trust persisted samples: any OpenBFSource block is
            # considered already simulated for its recorded params.
            self._simulated_sig = [
                _obf_signature(b.source) if isinstance(b.source, OpenBFSource) else None
                for b in self._programme.blocks
            ]
            normalised = self._normalise_sample_rates()
            self.status_message.emit(f"Loaded {n} block{'s' if n != 1 else ''}", 3000)
            if normalised or migrated:
                # Push the corrected programme back into the document so the
                # next save persists the fix.
                self._serialize_programme()
        except Exception as exc:
            self._programme = None
            self._simulated_sig = []
            self.status_message.emit(f"Parse error: {exc}", 0)

    def _normalise_sample_rates(self) -> bool:
        """Realign every FG block's source ``sample_rate_hz`` with the programme rate.

        Returns ``True`` if any block was changed. Hand-edited YAML files can
        end up with mismatched rates; this regenerates samples at the correct
        rate so the preview and downstream consumers stay consistent.
        """
        if self._programme is None:
            return False
        rate = self._programme.sampling_rate_hz
        changed = False
        for i, block in enumerate(self._programme.blocks):
            src = block.source
            if not isinstance(src, FunctionGeneratorSource):
                continue
            if src.sample_rate_hz == rate:
                continue
            new_src = src.model_copy(update={"sample_rate_hz": rate})
            _, y = sample_one_cycle(new_src.to_waveform_config())
            self._programme.blocks[i] = block.model_copy(
                update={"samples_f32_b64": encode_samples(y), "source": new_src}
            )
            changed = True
        return changed

    def _serialize_programme(self) -> None:
        if self._programme is None:
            return
        self._syncing = True
        self._document.content = yaml.dump(
            self._programme.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        )
        self._syncing = False
        self._emit_save_enabled()

    def _on_document_content_changed(self) -> None:
        if self._syncing:
            return
        self._parse_programme()
        self._rebuild_all()
        self._emit_save_enabled()

    # ---------- rebuilds ----------

    def _rebuild_all(self) -> None:
        self._selected_index = None
        self._block_list.clear_selection()
        if self._programme is None:
            self._block_list.set_blocks([])
            self._waveform.clear()
            self._inspector.clear()
            self._emit_save_enabled()
            return
        self._block_list.set_blocks(self._programme.blocks)
        self._waveform.set_programme(self._programme, self._unsimulated_indices())
        self._inspector.show_programme_only(self._programme)
        self._emit_save_enabled()

    def _rebuild_waveform(self) -> None:
        if self._programme is not None:
            self._waveform.set_programme(self._programme, self._unsimulated_indices())
            if self._selected_index is not None:
                self._waveform.pan_to_block(self._selected_index, self._programme)
        self._emit_save_enabled()

    def _update_block_list_labels(self) -> None:
        if self._programme is not None:
            self._block_list.set_blocks(self._programme.blocks)

    # ---------- block selection ----------

    def _on_block_selected(self, index: int) -> None:
        self._selected_index = index
        if self._programme is None:
            return
        self._waveform.pan_to_block(index, self._programme)
        self._inspector.show_programme(self._programme)
        self._inspector.show_block(self._programme.blocks[index])
        self._emit_remove_enabled()

    # ---------- inspector edits ----------

    def _on_programme_inspector_changed(self) -> None:
        if self._programme is None:
            return
        pvals = self._inspector.current_programme_values()
        if pvals is None:
            return
        prog_name, sample_rate, pressure_units = pvals
        sample_rate_changed = sample_rate != self._programme.sampling_rate_hz
        old_units = self._programme.pressure_units
        units_changed = pressure_units != old_units
        self._programme.name = prog_name
        self._programme.pressure_units = cast(PressureUnits, pressure_units)
        self._programme.sampling_rate_hz = sample_rate
        if units_changed:
            self._convert_block_values(old_units, pressure_units)
        if sample_rate_changed:
            # Re-resample every block at the new rate so durations stay consistent.
            for i, block in enumerate(self._programme.blocks):
                src = block.source
                if isinstance(src, FunctionGeneratorSource):
                    new_src = src.model_copy(update={"sample_rate_hz": sample_rate})
                    cfg = new_src.to_waveform_config()
                    _, y = sample_one_cycle(cfg)
                    self._programme.blocks[i] = block.model_copy(
                        update={"samples_f32_b64": encode_samples(y), "source": new_src}
                    )
                elif isinstance(src, OpenBFSource):
                    req = SimRequest(
                        block_index=i,
                        model_key=src.model_key,
                        vessel=src.vessel,
                        x_fraction=src.x_fraction,
                        bpm=src.bpm,
                        sample_rate_hz=sample_rate,
                        pressure_units=self._programme.pressure_units,
                    )
                    cached = self._sim.try_extract_cached(req)
                    if cached is not None:
                        self._programme.blocks[i] = block.model_copy(
                            update={"samples_f32_b64": encode_samples(cached)}
                        )
                        # Cache hit means samples still match the recorded source.
                        self._simulated_sig[i] = _obf_signature(src)
            if self._selected_index is not None:
                self._inspector.show_block(self._programme.blocks[self._selected_index])
        elif units_changed and self._selected_index is not None:
            # Even without a sample-rate change, the inspector needs to refresh
            # so the new amp/offset values appear in the spinboxes.
            self._inspector.show_block(self._programme.blocks[self._selected_index])
        self._rebuild_waveform()
        self._serialize_programme()
        self.status_message.emit("Modified", 2000)

    def _convert_block_values(self, old_units: str, new_units: str) -> None:
        """Convert every block's samples (and FG amp/offset) between units.

        Samples (FG or openBF) are stored as raw numbers in the programme's
        pressure unit; changing units requires multiplying them. The cached
        openBF simulation results stay in Pa, so they are untouched — only
        the resampled output stored in the block is converted.
        """
        if self._programme is None or old_units == new_units:
            return
        factor = convert_pressure_value(1.0, old_units, new_units)
        for i, block in enumerate(self._programme.blocks):
            src = block.source
            samples = decode_samples(block.samples_f32_b64) * np.float32(factor)
            updates: dict[str, object] = {"samples_f32_b64": encode_samples(samples)}
            if isinstance(src, FunctionGeneratorSource):
                updates["source"] = src.model_copy(
                    update={
                        "amplitude": src.amplitude * factor,
                        "offset": src.offset * factor,
                    }
                )
            self._programme.blocks[i] = block.model_copy(update=updates)

    def _on_block_inspector_changed(self) -> None:
        if self._programme is None or self._selected_index is None:
            return
        old_block = self._programme.blocks[self._selected_index]
        src = old_block.source
        i = self._selected_index

        if self._inspector.source_is_openbf():
            obf_vals = self._inspector.current_openbf_values()
            if obf_vals is None:
                return
            name, repeat_count, model_key, vessel, x_fraction, bpm = obf_vals
            new_src = OpenBFSource(
                kind="openbf",
                model_key=model_key,
                vessel=vessel,
                x_fraction=x_fraction,
                bpm=bpm,
            )
            req = SimRequest(
                block_index=i,
                model_key=model_key,
                vessel=vessel,
                x_fraction=x_fraction,
                bpm=bpm,
                sample_rate_hz=self._programme.sampling_rate_hz,
                pressure_units=self._programme.pressure_units,
            )
            cached_samples = self._sim.try_extract_cached(req)
            if cached_samples is not None:
                new_block = old_block.model_copy(
                    update={
                        "name": name,
                        "repeat_count": repeat_count,
                        "source": new_src,
                        "samples_f32_b64": encode_samples(cached_samples),
                    }
                )
                self._simulated_sig[i] = _obf_signature(new_src)
            else:
                new_block = old_block.model_copy(
                    update={"name": name, "repeat_count": repeat_count, "source": new_src}
                )
                # Source changed without fresh samples → mark unsimulated.
                self._simulated_sig[i] = None
                if (
                    not isinstance(src, OpenBFSource)
                    or src.model_key != model_key
                    or round(src.bpm, 4) != round(bpm, 4)
                ):
                    self.status_message.emit("Run simulation to update waveform", 0)
            self._programme.blocks[i] = new_block
            self._update_block_list_labels()
            self._block_list.select_block(i)
            self._rebuild_waveform()
            self._serialize_programme()
            self.status_message.emit("Modified", 2000)
            return

        # Function Generator branch
        values = self._inspector.current_block_values()
        if values is None:
            return
        name, repeat_count, waveform_type, amplitude, offset, bpm, duty, symmetry, phase = values
        if isinstance(src, FunctionGeneratorSource):
            new_src_fg = src.model_copy(
                update={
                    "type": waveform_type,
                    "amplitude": amplitude,
                    "offset": offset,
                    "bpm": bpm,
                    "duty": duty,
                    "symmetry": symmetry,
                    "phase": phase,
                }
            )
        else:
            new_src_fg = FunctionGeneratorSource(
                kind="function_generator",
                type=waveform_type,
                bpm=bpm,
                amplitude=amplitude,
                offset=offset,
                duty=duty,
                symmetry=symmetry,
                phase=phase,
                sample_rate_hz=self._programme.sampling_rate_hz,
                interpolation=Interpolation.FIRST_ORDER_HOLD,
            )
        cfg = new_src_fg.to_waveform_config()
        _, y = sample_one_cycle(cfg)
        new_block = old_block.model_copy(
            update={
                "name": name,
                "repeat_count": repeat_count,
                "samples_f32_b64": encode_samples(y),
                "source": new_src_fg,
            }
        )
        self._programme.blocks[i] = new_block
        self._simulated_sig[i] = (
            None  # FG blocks are never "simulated"; this clears any stale flag.
        )
        self._update_block_list_labels()
        self._block_list.select_block(i)
        self._rebuild_waveform()
        self._serialize_programme()
        self.status_message.emit("Modified", 2000)

    # ---------- simulation ----------

    def _on_run_simulation(self) -> None:
        if self._programme is None or self._selected_index is None or self._simulating:
            return
        obf_vals = self._inspector.current_openbf_values()
        if obf_vals is None:
            return
        _name, _repeat, model_key, vessel, x_fraction, bpm = obf_vals
        i = self._selected_index
        req = SimRequest(
            block_index=i,
            model_key=model_key,
            vessel=vessel,
            x_fraction=x_fraction,
            bpm=bpm,
            sample_rate_hz=self._programme.sampling_rate_hz,
            pressure_units=self._programme.pressure_units,
        )

        cached = self._sim.try_extract_cached(req)
        if cached is not None:
            self._apply_sim_samples(req, cached)
            self.status_message.emit("Simulation complete (cached)", 3000)
            return

        if self._console is None:
            self._console = JuliaConsoleWindow(self)
            self._console.kill_requested.connect(self._on_kill_simulation)
        self._console.clear()
        self._console.show()
        self._console.raise_()
        if not self._sim.run(req):
            self.status_message.emit("Simulation could not start", 0)

    def _apply_sim_samples(self, req: SimRequest, samples) -> None:
        if self._programme is None:
            return
        new_src = OpenBFSource(
            kind="openbf",
            model_key=req.model_key,
            vessel=req.vessel,
            x_fraction=req.x_fraction,
            bpm=req.bpm,
        )
        block = self._programme.blocks[req.block_index]
        new_block = block.model_copy(
            update={"samples_f32_b64": encode_samples(samples), "source": new_src}
        )
        self._programme.blocks[req.block_index] = new_block
        self._simulated_sig[req.block_index] = _obf_signature(new_src)
        self._rebuild_waveform()
        self._serialize_programme()

    def _set_simulating(self, running: bool) -> None:
        self._simulating = running
        self._inspector.set_simulation_running(running)
        self._block_list.setEnabled(not running)
        if self._console is not None:
            self._console.set_running(running)
        self.simulation_running_changed.emit(running)
        self._emit_save_enabled()

    def _on_sim_started(self) -> None:
        self._set_simulating(True)
        self.status_message.emit("Simulation running…", 0)

    def _on_sim_stdout(self, line: str) -> None:
        if self._console is not None:
            self._console.append_stdout(line)

    def _on_sim_stderr(self, line: str) -> None:
        if self._console is not None:
            self._console.append_stderr(line)

    def _on_sim_finished(self, result: SimResult) -> None:
        req = SimRequest(
            block_index=result.block_index,
            model_key=result.model_key,
            vessel=result.vessel,
            x_fraction=result.x_fraction,
            bpm=result.bpm,
            sample_rate_hz=self._programme.sampling_rate_hz if self._programme else 0.0,
            pressure_units=self._programme.pressure_units if self._programme else "Pa",
        )
        self._apply_sim_samples(req, result.samples)
        self._set_simulating(False)
        self.status_message.emit("Simulation complete", 3000)

    def _on_sim_failed(self, msg: str) -> None:
        self._set_simulating(False)
        self.status_message.emit(f"Simulation error: {msg}", 0)

    def _on_kill_simulation(self) -> None:
        self._sim.cancel()
        self._set_simulating(False)
        self.status_message.emit("Simulation killed", 3000)

    # ---------- public actions ----------

    def add_block(self) -> None:
        if self._programme is None:
            block_name = "Untitled block 1"
            self._programme = Programme(
                name="Untitled",
                sampling_rate_hz=100.0,
                pressure_units="Pa",
                blocks=[_make_default_block(100.0, name=block_name)],
            )
            self._simulated_sig = [None]
        else:
            n = len(self._programme.blocks) + 1
            block_name = f"Untitled block {n}"
            new_block = _make_default_block(self._programme.sampling_rate_hz, name=block_name)
            self._programme.blocks.append(new_block)
            self._simulated_sig.append(None)
        new_index = len(self._programme.blocks) - 1
        self._rebuild_all()
        self._block_list.select_block(new_index)
        self._inspector.show_programme(self._programme)
        self._inspector.show_block(self._programme.blocks[new_index])
        self._selected_index = new_index
        self._waveform.pan_to_block(new_index, self._programme)
        self._serialize_programme()
        self.status_message.emit("Block added", 2000)
        self._emit_remove_enabled()

    def remove_block(self, index: int | None = None) -> None:
        if self._programme is None or len(self._programme.blocks) <= 1:
            return
        i = index if index is not None else self._selected_index
        if i is None:
            return
        del self._programme.blocks[i]
        if 0 <= i < len(self._simulated_sig):
            del self._simulated_sig[i]
        self._selected_index = None
        self._rebuild_all()
        self._serialize_programme()
        self.status_message.emit("Block removed", 2000)
        self._emit_remove_enabled()

    def zoom_to_fit(self) -> None:
        self._waveform.zoom_to_fit()

    def _emit_remove_enabled(self) -> None:
        can_remove = (
            self._programme is not None
            and len(self._programme.blocks) > 1
            and self._selected_index is not None
        )
        self.remove_block_enabled.emit(can_remove)
