"""Run recorder — writes one parquet file per device plus a JSON manifest."""

from __future__ import annotations

import json
import platform
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from .config import BenchConfig
    from .signals import SignalDescriptor

# Row batching: flush when the per-device buffer hits this many rows.
_BATCH_ROWS = 64


def _np_to_arrow_type(dtype: str) -> pa.DataType:
    return {
        "f4": pa.float32(),
        "f8": pa.float64(),
        "u2": pa.uint16(),
        "u4": pa.uint32(),
        "i4": pa.int32(),
    }.get(dtype, pa.float32())


@dataclass
class _DeviceWriter:
    descriptors: list[SignalDescriptor]
    schema: pa.Schema
    path: Path
    writer: pq.ParquetWriter
    buf_t: list[float]
    buf_v: dict[str, list[float]]

    def append(self, t_s: float, values: dict[str, float]) -> None:
        self.buf_t.append(float(t_s))
        for d in self.descriptors:
            self.buf_v[d.name].append(float(values.get(d.name, float("nan"))))
        if len(self.buf_t) >= _BATCH_ROWS:
            self.flush()

    def flush(self) -> None:
        if not self.buf_t:
            return
        cols = [pa.array(self.buf_t, type=pa.float64())]
        for d in self.descriptors:
            cols.append(pa.array(self.buf_v[d.name], type=_np_to_arrow_type(d.dtype)))
        table = pa.Table.from_arrays(cols, schema=self.schema)
        self.writer.write_table(table)
        self.buf_t.clear()
        for lst in self.buf_v.values():
            lst.clear()

    def close(self) -> None:
        self.flush()
        self.writer.close()


class RunRecorder:
    """Owns the on-disk artefacts of a single run.

    Lifecycle: ``start(name, config) -> append(...) -> stop() -> manifest_path``.
    Concurrent calls are not supported; the BenchController serialises access.
    """

    def __init__(self, runs_root: Path) -> None:
        self._runs_root = Path(runs_root)
        self._writers: dict[str, _DeviceWriter] = {}
        self._run_dir: Path | None = None
        self._t_start_mono: float = 0.0
        self._t_start_wall: datetime | None = None
        self._config_snapshot: dict | None = None
        self._sample_counts: dict[str, int] = defaultdict(int)
        self._events: list[dict] = []
        self._run_name: str = ""

    @property
    def is_active(self) -> bool:
        return self._run_dir is not None

    @property
    def run_dir(self) -> Path | None:
        return self._run_dir

    # -- lifecycle ---------------------------------------------------------

    def start(
        self,
        name: str,
        config: BenchConfig,
        device_signals: dict[str, list[SignalDescriptor]],
    ) -> Path:
        if self.is_active:
            raise RuntimeError("recorder already active")
        self._run_name = name or "run"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self._run_name)
        self._run_dir = self._runs_root / f"{stamp}_{safe}"
        self._run_dir.mkdir(parents=True, exist_ok=True)

        for dev_id, descs in device_signals.items():
            self._open_device_writer(dev_id, descs)

        self._t_start_mono = time.monotonic()
        self._t_start_wall = datetime.now()
        self._config_snapshot = config.model_dump(mode="json")
        self._sample_counts.clear()
        self._events.clear()
        return self._run_dir

    def _open_device_writer(self, dev_id: str, descs: list[SignalDescriptor]) -> None:
        if not descs or self._run_dir is None:
            return
        fields = [pa.field("t_s", pa.float64())]
        fields.extend(pa.field(d.name, _np_to_arrow_type(d.dtype)) for d in descs)
        schema = pa.schema(fields)
        path = self._run_dir / f"{dev_id}.parquet"
        writer = pq.ParquetWriter(path, schema)
        self._writers[dev_id] = _DeviceWriter(
            descriptors=list(descs),
            schema=schema,
            path=path,
            writer=writer,
            buf_t=[],
            buf_v={d.name: [] for d in descs},
        )

    def add_device_mid_run(self, dev_id: str, descs: list[SignalDescriptor]) -> None:
        if not self.is_active or dev_id in self._writers:
            return
        self._open_device_writer(dev_id, descs)
        self._events.append(
            {
                "t_s": time.monotonic() - self._t_start_mono,
                "kind": "device_added",
                "id": dev_id,
            }
        )

    def remove_device_mid_run(self, dev_id: str) -> None:
        if not self.is_active or dev_id not in self._writers:
            return
        self._writers[dev_id].close()
        del self._writers[dev_id]
        self._events.append(
            {
                "t_s": time.monotonic() - self._t_start_mono,
                "kind": "device_removed",
                "id": dev_id,
            }
        )

    def append(self, dev_id: str, t_s: float, values: dict[str, float]) -> None:
        writer = self._writers.get(dev_id)
        if writer is None:
            return
        writer.append(t_s, values)
        self._sample_counts[dev_id] += 1

    def log_event(self, kind: str, **payload) -> None:
        if not self.is_active:
            return
        ev = {
            "t_s": time.monotonic() - self._t_start_mono,
            "kind": kind,
        }
        ev.update(payload)
        self._events.append(ev)

    def stop(self) -> Path | None:
        if not self.is_active or self._run_dir is None:
            return None
        for w in self._writers.values():
            w.close()
        manifest = {
            "run_name": self._run_name,
            "start_wall": self._t_start_wall.isoformat() if self._t_start_wall else None,
            "stop_wall": datetime.now().isoformat(),
            "duration_s": time.monotonic() - self._t_start_mono,
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "bench_config": self._config_snapshot,
            "sample_counts": dict(self._sample_counts),
            "parquet_files": {dev_id: w.path.name for dev_id, w in self._writers.items()},
            "events": self._events,
        }
        manifest_path = self._run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        result = self._run_dir
        self._writers.clear()
        self._run_dir = None
        self._t_start_wall = None
        self._config_snapshot = None
        return result
