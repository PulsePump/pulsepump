from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from pulsepump.openbf import (
    INSTALL_JULIA_URL,
    ModelBundle,
    OpenBFRunner,
    VesselPressureResult,
    check_julia,
    convert_pressure,
    interpolate_x,
    parse_vessel_pressure,
)


@dataclass(frozen=True)
class SimRequest:
    block_index: int
    model_key: str
    vessel: str
    x_fraction: float
    bpm: float
    sample_rate_hz: float
    pressure_units: str


@dataclass(frozen=True)
class SimResult:
    block_index: int
    model_key: str
    vessel: str
    x_fraction: float
    bpm: float
    samples: np.ndarray
    from_cache: bool


class SimulationController(QObject):
    """Owns the openBF run lifecycle: subprocess, temp dir, cache, result encoding.

    Emits ``started`` once a Julia subprocess actually starts, ``stdout`` /
    ``stderr`` for each line, ``finished`` (with the resulting :class:`SimResult`)
    when results are encoded, and ``failed`` on any error path.
    """

    started = Signal()
    stdout = Signal(str)
    stderr = Signal(str)
    finished = Signal(object)  # SimResult
    failed = Signal(str)

    def __init__(self, models: tuple[ModelBundle, ...], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._models = models
        self._runner = OpenBFRunner(self)
        self._runner.started.connect(self.started)
        self._runner.stdout.connect(self.stdout)
        self._runner.stderr.connect(self.stderr)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)

        self._julia_checked: bool = False
        self._current: SimRequest | None = None
        self._run_dir: tempfile.TemporaryDirectory | None = None  # type: ignore[type-arg]
        # Cache: (model_key, bpm_rounded) → {vessel: VesselPressureResult}
        self._cache: dict[tuple[str, float], dict[str, VesselPressureResult]] = {}

    # ---------- public API ----------

    def is_running(self) -> bool:
        return self._runner.is_running()

    def cancel(self) -> None:
        self._runner.kill()
        self._cleanup_run_dir()
        self._current = None

    def try_extract_cached(self, req: SimRequest) -> np.ndarray | None:
        """Return resampled pressure samples for ``req`` if cached, else ``None``."""
        return self._extract_from_cache(req)

    def run(self, req: SimRequest) -> bool:
        """Start a simulation. Returns False if Julia is unavailable or one is already running."""
        if self.is_running():
            return False
        if not self._julia_checked:
            self._julia_checked = True
            status = check_julia()
            if not status.julia_found:
                self.failed.emit(
                    f"Julia not found on PATH. Install from {INSTALL_JULIA_URL} "
                    f"({status.error or 'no error'})"
                )
                return False

        bundle = self._bundle_for(req.model_key)
        if bundle is None:
            self.failed.emit(f"openBF model not found: {req.model_key}")
            return False

        self._current = req
        self._run_dir = tempfile.TemporaryDirectory(prefix="pulsepump_obf_")
        run_dir = Path(self._run_dir.name)

        # Copy model YAML and inlet .dat
        model_pkg = files("pulsepump.openbf_models")
        for part in req.model_key.split("/"):
            model_pkg = model_pkg.joinpath(part)
        yaml_src = model_pkg.joinpath(bundle.yaml_name)
        inlet_src = model_pkg.joinpath(bundle.inlet_name)
        with as_file(yaml_src) as p:
            (run_dir / bundle.yaml_name).write_bytes(p.read_bytes())
        with as_file(inlet_src) as p:
            (run_dir / bundle.inlet_name).write_bytes(p.read_bytes())

        # Patch inlet period from BPM
        period_s = 60.0 / max(req.bpm, 1e-6)
        self._patch_inlet_period(run_dir / bundle.inlet_name, period_s)

        # Copy Julia script
        script_src = files("pulsepump.openbf_models").joinpath("run_openbf.jl")
        with as_file(script_src) as p:
            (run_dir / "run_openbf.jl").write_bytes(p.read_bytes())

        self.stdout.emit(
            f"Model: {bundle.label}  |  BPM: {req.bpm:.1f}  |  Period: {period_s:.3f}s"
            f"  |  Run dir: {run_dir}"
        )
        self._runner.run(str(run_dir), str(run_dir / "run_openbf.jl"), bundle.yaml_name)
        return True

    # ---------- internal ----------

    def _bundle_for(self, model_key: str) -> ModelBundle | None:
        return next((b for b in self._models if b.key == model_key), None)

    @staticmethod
    def _patch_inlet_period(inlet_path: Path, period_s: float) -> None:
        """Rewrite the first data column of the inlet .dat to span [0, period_s].

        NOTE: this rescales only the time axis and leaves the flow-rate column
        unchanged. That alters integrated stroke volume non-physically when
        BPM differs greatly from the source data's BPM — acceptable here as
        we use it only for shape; revisit if quantitative accuracy matters.
        """
        try:
            data = np.loadtxt(inlet_path)
            if data.ndim == 2 and data.shape[1] >= 2:
                n = data.shape[0]
                data[:, 0] = np.linspace(0.0, period_s, n, endpoint=True)
                np.savetxt(inlet_path, data, fmt="%.8e")
        except Exception:
            pass  # Leave inlet as-is if we can't parse it

    def _extract_from_cache(self, req: SimRequest) -> np.ndarray | None:
        cache_key = (req.model_key, round(req.bpm, 4))
        vessel_cache = self._cache.get(cache_key)
        if vessel_cache is None:
            return None
        result = vessel_cache.get(req.vessel)
        if not isinstance(result, VesselPressureResult):
            return None
        return self._resample_result(result, req)

    @staticmethod
    def _locate_results_dir(run_dir: Path, vessel: str) -> Path | None:
        """Find the directory holding ``{vessel}_P.last``.

        openBF writes results to ``{project_name}_results/`` by default but
        some configurations (or older versions) flush them straight to the
        working directory. Newer ones may nest by cycle index. Search wherever
        the file ended up rather than guessing.
        """
        target = f"{vessel}_P.last"
        # Cheapest matches first.
        direct = run_dir / target
        if direct.exists():
            return run_dir
        for d in run_dir.iterdir():
            if d.is_dir() and (d / target).exists():
                return d
        # Last resort: any depth.
        matches = list(run_dir.rglob(target))
        return matches[0].parent if matches else None

    @staticmethod
    def _resample_result(result: VesselPressureResult, req: SimRequest) -> np.ndarray:
        p_pa = interpolate_x(result, req.x_fraction)
        p_out = convert_pressure(p_pa, req.pressure_units)
        total_time = result.t[-1] - result.t[0]
        n_out = max(round(total_time * req.sample_rate_hz), 1)
        t_out = np.linspace(result.t[0], result.t[-1], n_out, endpoint=False)
        return np.interp(t_out, result.t, p_out)

    def _on_finished(self, exit_code: int) -> None:
        req = self._current
        run_dir_obj = self._run_dir
        self._current = None
        if req is None or run_dir_obj is None:
            self._cleanup_run_dir()
            return
        if exit_code != 0:
            self._cleanup_run_dir()
            self.failed.emit(f"Simulation failed (exit {exit_code})")
            return

        run_dir = Path(run_dir_obj.name)
        results_dir = self._locate_results_dir(run_dir, req.vessel)
        if results_dir is None:
            found = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*_P.last"))
            hint = ", ".join(found) or "no *_P.last files were written"
            self._cleanup_run_dir()
            self.failed.emit(
                f"Result parse error: {req.vessel}_P.last not found under {run_dir}. Found: {hint}"
            )
            return

        try:
            primary = parse_vessel_pressure(results_dir, req.vessel)
        except Exception as exc:
            self._cleanup_run_dir()
            self.failed.emit(f"Result parse error: {exc}")
            return

        # Cache every vessel available for this (model, bpm)
        bundle = self._bundle_for(req.model_key)
        vessel_cache: dict[str, VesselPressureResult] = {req.vessel: primary}
        if bundle is not None:
            for v in bundle.vessels:
                if v == req.vessel:
                    continue
                v_dir = self._locate_results_dir(run_dir, v)
                if v_dir is None:
                    continue
                with contextlib.suppress(Exception):
                    vessel_cache[v] = parse_vessel_pressure(v_dir, v)
        self._cache[(req.model_key, round(req.bpm, 4))] = vessel_cache

        samples = self._resample_result(primary, req)
        p_min, p_max = float(samples.min()), float(samples.max())
        self.stdout.emit(
            f"Results: {len(primary.t)} rows  |  P=[{p_min:.1f}, {p_max:.1f}] {req.pressure_units}"
        )
        self._cleanup_run_dir()
        self.finished.emit(
            SimResult(
                block_index=req.block_index,
                model_key=req.model_key,
                vessel=req.vessel,
                x_fraction=req.x_fraction,
                bpm=req.bpm,
                samples=samples,
                from_cache=False,
            )
        )

    def _on_failed(self, msg: str) -> None:
        self._cleanup_run_dir()
        self._current = None
        self.failed.emit(msg)

    def _cleanup_run_dir(self) -> None:
        if self._run_dir is not None:
            with contextlib.suppress(Exception):
                self._run_dir.cleanup()
            self._run_dir = None
