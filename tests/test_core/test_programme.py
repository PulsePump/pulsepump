"""Tests for pulsepump.programme — schema validation, I/O, and decompression."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from pydantic import ValidationError

from pulsepump.core.programme import (
    Block,
    FunctionGeneratorSource,
    OpenBFSource,
    Programme,
    SamplesMissingError,
    decode_samples,
    decompress,
    encode_samples,
    load,
    save,
)
from pulsepump.core.waveform import Interpolation, WaveformType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sine_cycle(n: int = 83, amplitude: float = 40.0, offset: float = 80.0) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    return (amplitude * np.sin(2 * np.pi * t) + offset).astype(np.float32)


def _fg_source() -> FunctionGeneratorSource:
    return FunctionGeneratorSource(
        kind="function_generator",
        type=WaveformType.SINE,
        bpm=72.0,
        amplitude=40.0,
        offset=80.0,
        duty=0.5,
        symmetry=0.5,
        phase=0.0,
        sample_rate_hz=100.0,
        interpolation=Interpolation.FIRST_ORDER_HOLD,
    )


def _openbf_source() -> OpenBFSource:
    return OpenBFSource(
        kind="openbf",
        model_key="boileau2015/cca",
        vessel="common_carotid_artery",
        x_fraction=0.5,
        bpm=72.0,
    )


def _make_programme(
    blocks: list[Block] | None = None,
    sampling_rate_hz: float = 100.0,
) -> Programme:
    if blocks is None:
        cycle = _sine_cycle()
        blocks = [
            Block(
                repeat_count=10,
                samples_f32_b64=encode_samples(cycle),
                source=_fg_source(),
            )
        ]
    return Programme(
        name="test programme",
        sampling_rate_hz=sampling_rate_hz,
        pressure_units="mmHg",
        blocks=blocks,
    )


# ---------------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------------


def test_encode_decode_roundtrip():
    arr = np.array([1.0, 2.5, -3.14, 0.0], dtype=np.float32)
    assert np.array_equal(arr, decode_samples(encode_samples(arr)))


def test_encode_forces_float32():
    arr = np.array([1.0, 2.0], dtype=np.float64)
    result = decode_samples(encode_samples(arr))
    assert result.dtype == np.float32


def test_encode_decode_large_array():
    arr = np.random.default_rng(0).random(10_000).astype(np.float32)
    assert np.array_equal(arr, decode_samples(encode_samples(arr)))


# ---------------------------------------------------------------------------
# FunctionGeneratorSource validation
# ---------------------------------------------------------------------------


def test_fg_source_valid():
    src = _fg_source()
    assert src.bpm == 72.0


def test_fg_source_bad_bpm():
    with pytest.raises(ValidationError) as exc_info:
        FunctionGeneratorSource(
            kind="function_generator",
            type=WaveformType.SINE,
            bpm=-1.0,
            amplitude=40.0,
            offset=80.0,
            duty=0.5,
            symmetry=0.5,
            phase=0.0,
            sample_rate_hz=100.0,
            interpolation=Interpolation.FIRST_ORDER_HOLD,
        )
    assert "bpm" in str(exc_info.value)


def test_fg_source_duty_too_high():
    with pytest.raises(ValidationError) as exc_info:
        FunctionGeneratorSource(
            kind="function_generator",
            type=WaveformType.SINE,
            bpm=72.0,
            amplitude=40.0,
            offset=80.0,
            duty=1.3,
            symmetry=0.5,
            phase=0.0,
            sample_rate_hz=100.0,
            interpolation=Interpolation.FIRST_ORDER_HOLD,
        )
    assert "duty" in str(exc_info.value)


def test_fg_source_phase_at_one():
    with pytest.raises(ValidationError) as exc_info:
        FunctionGeneratorSource(
            kind="function_generator",
            type=WaveformType.SINE,
            bpm=72.0,
            amplitude=40.0,
            offset=80.0,
            duty=0.5,
            symmetry=0.5,
            phase=1.0,
            sample_rate_hz=100.0,
            interpolation=Interpolation.FIRST_ORDER_HOLD,
        )
    assert "phase" in str(exc_info.value)


def test_fg_source_to_waveform_config():
    cfg = _fg_source().to_waveform_config()
    assert cfg.bpm == 72.0
    assert cfg.type == WaveformType.SINE


# ---------------------------------------------------------------------------
# OpenBFSource validation
# ---------------------------------------------------------------------------


def test_openbf_source_valid():
    src = _openbf_source()
    assert src.model_key == "boileau2015/cca"


def test_openbf_source_x_fraction_out_of_range():
    with pytest.raises(ValidationError) as exc_info:
        OpenBFSource(
            kind="openbf",
            model_key="boileau2015/cca",
            vessel="common_carotid_artery",
            x_fraction=1.5,
            bpm=72.0,
        )
    assert "x_fraction" in str(exc_info.value)


def test_openbf_source_bpm_zero():
    with pytest.raises(ValidationError) as exc_info:
        OpenBFSource(
            kind="openbf",
            model_key="boileau2015/cca",
            vessel="common_carotid_artery",
            x_fraction=0.5,
            bpm=0.0,
        )
    assert "bpm" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Discriminator / kind field
# ---------------------------------------------------------------------------


def test_unknown_kind_raises():
    with pytest.raises(ValidationError) as exc_info:
        Block(
            repeat_count=1,
            samples_f32_b64=encode_samples(_sine_cycle()),
            source=cast(Any, {"kind": "unknown_model", "bpm": 72.0}),
        )
    error_text = str(exc_info.value)
    # Pydantic v2 reports tag mismatch as union_tag_invalid; "source" identifies the field
    assert "source" in error_text and ("union_tag_invalid" in error_text or "kind" in error_text)


# ---------------------------------------------------------------------------
# Programme validation
# ---------------------------------------------------------------------------


def test_programme_valid():
    p = _make_programme()
    assert p.name == "test programme"
    assert p.version == "1.0"


def test_programme_unknown_pressure_units():
    with pytest.raises(ValidationError) as exc_info:
        Programme(
            name="bad",
            sampling_rate_hz=100.0,
            pressure_units=cast(Any, "atm"),
            blocks=[
                Block(
                    repeat_count=1,
                    samples_f32_b64=encode_samples(_sine_cycle()),
                    source=_fg_source(),
                )
            ],
        )
    assert "pressure_units" in str(exc_info.value)


def test_programme_empty_phases():
    with pytest.raises(ValidationError):
        Programme(
            name="empty",
            sampling_rate_hz=100.0,
            pressure_units="mmHg",
            blocks=[],
        )


def test_programme_total_duration():
    cycle = _sine_cycle(n=83)
    p = _make_programme(
        blocks=[
            Block(
                repeat_count=10,
                samples_f32_b64=encode_samples(cycle),
                source=_fg_source(),
            )
        ],
        sampling_rate_hz=100.0,
    )
    expected = 83 / 100.0 * 10
    assert math.isclose(p.total_duration_s, expected)


def test_programme_total_cycles():
    cycle = _sine_cycle()
    p = _make_programme(
        blocks=[
            Block(repeat_count=5, samples_f32_b64=encode_samples(cycle), source=_fg_source()),
            Block(repeat_count=3, samples_f32_b64=encode_samples(cycle), source=_openbf_source()),
        ]
    )
    assert p.total_cycles == 8


# ---------------------------------------------------------------------------
# Decompression
# ---------------------------------------------------------------------------


def test_decompress_sample_count():
    cycle = _sine_cycle(n=83)
    p = _make_programme(
        blocks=[Block(repeat_count=10, samples_f32_b64=encode_samples(cycle), source=_fg_source())]
    )
    result = decompress(p)
    assert result.shape == (830,)
    assert result.dtype == np.float32


def test_decompress_tile_semantics():
    cycle = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    p = _make_programme(
        blocks=[Block(repeat_count=3, samples_f32_b64=encode_samples(cycle), source=_fg_source())]
    )
    result = decompress(p)
    expected = np.tile(cycle, 3)
    assert np.array_equal(result, expected)


def test_decompress_multi_phase_count():
    c1 = _sine_cycle(n=83)
    c2 = _sine_cycle(n=50)
    p = _make_programme(
        blocks=[
            Block(repeat_count=6, samples_f32_b64=encode_samples(c1), source=_fg_source()),
            Block(repeat_count=4, samples_f32_b64=encode_samples(c2), source=_openbf_source()),
        ]
    )
    result = decompress(p)
    assert result.shape == (83 * 6 + 50 * 4,)


def test_decompress_total_duration_consistent():
    cycle = _sine_cycle(n=83)
    p = _make_programme(
        blocks=[Block(repeat_count=10, samples_f32_b64=encode_samples(cycle), source=_fg_source())],
        sampling_rate_hz=100.0,
    )
    result = decompress(p)
    assert math.isclose(len(result) / p.sampling_rate_hz, p.total_duration_s)


def test_decompress_raises_on_empty_samples():
    # Use model_construct to bypass pydantic validation so we can pass corrupt
    # data directly to decompress() and test its own error handling.
    corrupt_b64 = encode_samples(np.array([], dtype=np.float32))
    phase = Block.model_construct(
        repeat_count=1,
        samples_f32_b64=corrupt_b64,
        source=_fg_source(),
    )
    p = Programme.model_construct(
        name="corrupt",
        sampling_rate_hz=100.0,
        pressure_units="mmHg",
        blocks=[phase],
        version="1.0",
    )
    with pytest.raises(SamplesMissingError):
        decompress(p)


# ---------------------------------------------------------------------------
# File I/O round-trip
# ---------------------------------------------------------------------------


def test_save_load_roundtrip():
    cycle = _sine_cycle()
    p = _make_programme(
        blocks=[
            Block(repeat_count=5, samples_f32_b64=encode_samples(cycle), source=_fg_source()),
            Block(repeat_count=2, samples_f32_b64=encode_samples(cycle), source=_openbf_source()),
        ]
    )
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = Path(f.name)
    try:
        save(p, path)
        p2 = load(path)
        assert p2.name == p.name
        assert p2.pressure_units == p.pressure_units
        assert p2.sampling_rate_hz == p.sampling_rate_hz
        assert len(p2.blocks) == len(p.blocks)
        assert p2.blocks[0].repeat_count == p.blocks[0].repeat_count
        assert np.array_equal(
            decode_samples(p2.blocks[0].samples_f32_b64),
            decode_samples(p.blocks[0].samples_f32_b64),
        )
    finally:
        path.unlink(missing_ok=True)


def test_load_bad_yaml_raises_validation_error(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: '1.0'\nname: broken\nsampling_rate_hz: -10\npressure_units: mmHg\nphases: []\n"
    )
    with pytest.raises(ValidationError):
        load(bad)
