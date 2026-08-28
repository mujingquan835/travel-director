from __future__ import annotations

import math
from pathlib import Path
import wave

import numpy as np
from PIL import Image

from director.material_enrichment import enrich_materials
from director.schema import (
    MaterialScanResult,
    MotionEvidence,
    PeopleEvidence,
    QualityEvidence,
)
from scanner.schema import FrameRecord, SourceRecord, TechnicalMetadata


def write_tone(path: Path, frequency: float) -> None:
    sample_rate = 16_000
    times = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    samples = (0.25 * np.sin(2 * math.pi * frequency * times) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())


def material(file: str, frames: list[FrameRecord]) -> MaterialScanResult:
    return MaterialScanResult(
        file=file,
        source=SourceRecord(relative_path=file, size_bytes=64_044, mtime_ns=1),
        technical=TechnicalMetadata(
            duration=2.0,
            width=320,
            height=240,
            fps=24.0,
            orientation="landscape",
            codec="pcm_s16le",
        ),
        analysis_status="complete",
        quality_evidence=QualityEvidence(laplacian_variance_raw=100.0),
        motion_evidence=MotionEvidence(
            motion_intensity_raw=1.0,
            directional_motion_ratio=0.5,
            luma_change_p90=0.2,
            motion_level_candidate="medium",
        ),
        people_evidence=PeopleEvidence(),
        representative_frames=frames,
    )


def test_near_duplicate_frames_share_group_without_deleting_materials(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    run_dir = tmp_path / "run"
    input_root.mkdir()
    (run_dir / "frames").mkdir(parents=True)
    write_tone(input_root / "a.wav", 440.0)
    write_tone(input_root / "b.wav", 442.0)
    for name in ("a0.jpg", "a1.jpg", "b0.jpg", "b1.jpg"):
        Image.new("RGB", (32, 32), (30, 120, 200)).save(run_dir / "frames" / name)
    first = material(
        "a.wav",
        [
            FrameRecord(timestamp=0.5, reasons=["temporal"], thumbnail_relpath="frames/a0.jpg"),
            FrameRecord(timestamp=1.5, reasons=["temporal"], thumbnail_relpath="frames/a1.jpg"),
        ],
    )
    second = material(
        "b.wav",
        [
            FrameRecord(timestamp=0.5, reasons=["temporal"], thumbnail_relpath="frames/b0.jpg"),
            FrameRecord(timestamp=1.5, reasons=["temporal"], thumbnail_relpath="frames/b1.jpg"),
        ],
    )

    enriched = enrich_materials([first, second], input_root, run_dir)

    assert len(enriched) == 2
    assert enriched[0].duplicate_group_id is not None
    assert enriched[0].duplicate_group_id == enriched[1].duplicate_group_id


def test_sparse_audio_evidence_remains_candidate(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    run_dir = tmp_path / "run"
    input_root.mkdir()
    run_dir.mkdir()
    write_tone(input_root / "tone.wav", 440.0)
    item = material("tone.wav", [])

    enriched = enrich_materials([item], input_root, run_dir)[0]

    assert enriched.original_audio_value_candidate is not None
    assert enriched.original_audio_value_candidate.status == "candidate"
    assert 0.17 < enriched.original_audio_value_candidate.rms < 0.18


def test_missing_source_marks_audio_unavailable_and_keeps_ranges_bounded(tmp_path: Path) -> None:
    item = material(
        "missing.mov",
        [FrameRecord(timestamp=1.8, reasons=["motion"], thumbnail_relpath="missing.jpg")],
    )

    enriched = enrich_materials([item], tmp_path / "input", tmp_path / "run")[0]

    assert enriched.original_audio_value_candidate is not None
    assert enriched.original_audio_value_candidate.status == "unavailable"
    assert [(row.start, row.end) for row in enriched.recommended_ranges] == [(0.0, 2.0)]


def test_grounded_visible_object_creates_only_an_sfx_candidate(tmp_path: Path) -> None:
    item = material(
        "missing.mov",
        [FrameRecord(timestamp=0.5, reasons=["temporal"], thumbnail_relpath="missing.jpg")],
    )
    item.object_candidates = ["water"]

    enriched = enrich_materials([item], tmp_path / "input", tmp_path / "run")[0]

    assert [(row.label, row.source_time_seconds) for row in enriched.sfx_candidates] == [
        ("water", 0.5)
    ]
    assert enriched.sfx_candidates[0].evidence_source == "scanner_object_candidate"
