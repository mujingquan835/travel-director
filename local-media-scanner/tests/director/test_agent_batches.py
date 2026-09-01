from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from director.agent_batches import (
    AGENT_VISUAL_FIELDS,
    MaterialFrameMap,
    MaterialFrameSet,
    build_agent_batch_manifest,
    build_contact_sheet,
)
from director.scanner_bridge import (
    build_material_frame_map,
    build_scanner_observations_from_files,
)
from scanner.schema import ManifestEntry, TestManifest as ScannerManifest
from director.visual_schema import ClipObservation, ClipObservationBatch, MaterialRef, derive_material_id
from scanner.schema import (
    ContentAnalysis,
    FrameRecord,
    MotionMetrics,
    QualityMetrics,
    ScannerCard,
    ScannerResult,
    SourceRecord,
    TechnicalMetadata,
    TimingBreakdown,
)


def _material(path: str, seed: str) -> MaterialRef:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return MaterialRef(
        material_id=derive_material_id(digest), relative_path=path,
        source_sha256=digest, size_bytes=10, mtime_ns=1, duration_seconds=1.0,
        fps=25.0, orientation="landscape",
    )


@pytest.fixture
def frame_images(tmp_path: Path) -> list[Path]:
    frames = []
    for index, color in enumerate(("red", "green", "blue", "yellow", "purple", "orange")):
        path = tmp_path / f"frame-{index}.jpg"
        Image.new("RGB", (80 + index * 5, 40 + index * 3), color).save(path)
        frames.append(path)
    return frames


@pytest.fixture
def material_frame_map(frame_images: list[Path]) -> MaterialFrameMap:
    return MaterialFrameMap(items=[MaterialFrameSet(material=_material("clip-a.mov", "a"), frame_paths=[str(path) for path in frame_images[:3]])])


def test_contact_sheet_uses_three_to_five_frames(tmp_path: Path, frame_images: list[Path]) -> None:
    sheet = build_contact_sheet(frame_images[:5], tmp_path / "sheet.jpg", "clip-a")
    assert sheet.exists()
    assert Image.open(sheet).mode == "RGB"


def test_contact_sheet_rejects_more_than_five_input_frames(tmp_path: Path, frame_images: list[Path]) -> None:
    with pytest.raises(ValueError, match="three to five"):
        build_contact_sheet(frame_images, tmp_path / "sheet.jpg", "clip-a")


def test_batch_manifest_caps_every_batch_at_ten(material_frame_map: MaterialFrameMap, tmp_path: Path) -> None:
    frame_map = MaterialFrameMap(items=[
        MaterialFrameSet(material=_material(f"clip-{index:02d}.mov", str(index)), frame_paths=material_frame_map.items[0].frame_paths)
        for index in range(23)
    ])
    manifest = build_agent_batch_manifest(frame_map, tmp_path)
    assert [len(batch.items) for batch in manifest.batches] == [10, 10, 3]
    assert len({item.contact_sheet_path for item in manifest.items}) == 23


def test_missing_representative_frames_is_recorded_not_invented(material_frame_map: MaterialFrameMap, tmp_path: Path) -> None:
    frame_map = MaterialFrameMap(items=[MaterialFrameSet(material=_material("clip-a.mov", "a"), frame_paths=[])])
    manifest = build_agent_batch_manifest(frame_map, tmp_path)
    item = manifest.item_by_relative_path("clip-a.mov")
    assert item.status == "review_required"
    assert item.contact_sheet_path is None


def test_batch_manifest_orders_packets_by_relative_path_and_keeps_local_outputs(material_frame_map: MaterialFrameMap, tmp_path: Path) -> None:
    frame_map = MaterialFrameMap(items=[
        MaterialFrameSet(material=_material("z.mov", "z"), frame_paths=material_frame_map.items[0].frame_paths),
        MaterialFrameSet(material=_material("a.mov", "a"), frame_paths=material_frame_map.items[0].frame_paths),
    ])
    manifest = build_agent_batch_manifest(frame_map, tmp_path)
    assert [item.relative_path for item in manifest.items] == ["a.mov", "z.mov"]
    assert all(Path(item.contact_sheet_path).resolve().is_relative_to(tmp_path.resolve()) for item in manifest.items if item.contact_sheet_path)
    assert all(item.allowed_fields == list(AGENT_VISUAL_FIELDS) for item in manifest.items)


def test_empty_material_map_is_rejected() -> None:
    with pytest.raises(ValueError):
        MaterialFrameMap(items=[])


def _card(relative_path: str, frames: list[FrameRecord]) -> ScannerCard:
    return ScannerCard(
        file=Path(relative_path).name, source=SourceRecord(relative_path=relative_path, size_bytes=10, mtime_ns=1), analysis_status="complete",
        technical=TechnicalMetadata(duration=1.0, width=320, height=240, fps=25.0, orientation="landscape", codec="h264"),
        quality=QualityMetrics(), motion=MotionMetrics(), content=ContentAnalysis(),
        representative_frames=frames, timings_ms=TimingBreakdown(),
    )


def test_build_material_frame_map_resolves_saved_frames_and_preserves_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    saved = run_dir / "frames" / "a.jpg"
    saved.parent.mkdir(parents=True)
    Image.new("RGB", (20, 20), "red").save(saved)
    first, second = _material("a.mov", "a"), _material("b.mov", "b")
    result = ScannerResult(run_id="run", requested_device="cpu", actual_device="cpu", items=[
        _card("a.mov", [FrameRecord(timestamp=2.0, reasons=["temporal"], thumbnail_relpath="frames/a.jpg")]),
        _card("b.mov", []),
    ])
    observations = ClipObservationBatch(status="partial", mode="scanner_only", items=[
        ClipObservation(material=first, provider="scanner_only", observation_status="abstained"),
        ClipObservation(material=second, provider="scanner_only", observation_status="abstained"),
    ])
    frame_map = build_material_frame_map(result, observations, run_dir)
    assert frame_map.items[0].frame_paths == [str(saved.resolve())]
    assert frame_map.items[1].frame_paths == []


def test_build_material_frame_map_rejects_thumbnail_path_traversal(tmp_path: Path) -> None:
    material = _material("a.mov", "a")
    result = ScannerResult(run_id="run", requested_device="cpu", actual_device="cpu", items=[
        _card("a.mov", [FrameRecord(timestamp=0.0, reasons=["temporal"], thumbnail_relpath="../outside.jpg")])
    ])
    observations = ClipObservationBatch(status="partial", mode="scanner_only", items=[ClipObservation(material=material, provider="scanner_only", observation_status="abstained")])
    with pytest.raises(ValueError, match="escapes scanner run directory"):
        build_material_frame_map(result, observations, tmp_path / "run")


def test_scanner_observations_hash_sources_and_bind_saved_result(tmp_path: Path) -> None:
    source = tmp_path / "input" / "a.mov"
    source.parent.mkdir()
    source.write_bytes(b"immutable source")
    result = ScannerResult(run_id="run", requested_device="cpu", actual_device="cpu", items=[_card("a.mov", [])])
    result_path = tmp_path / "scanner_result.json"
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    manifest = ScannerManifest(
        input_root=str(source.parent),
        entries=[ManifestEntry(file="a.mov", source=SourceRecord(relative_path="a.mov", size_bytes=source.stat().st_size, mtime_ns=source.stat().st_mtime_ns), technical=result.items[0].technical)],
    )
    observations = build_scanner_observations_from_files(result, manifest, result_path)
    evidence = observations.items[0].assertions[0].evidence_refs[0]
    assert observations.items[0].material.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert evidence.sha256 == hashlib.sha256(result_path.read_bytes()).hexdigest()


def test_scanner_observations_reject_source_path_traversal(tmp_path: Path) -> None:
    result = ScannerResult(run_id="run", requested_device="cpu", actual_device="cpu", items=[_card("../a.mov", [])])
    result_path = tmp_path / "scanner_result.json"
    result_path.write_text(result.model_dump_json(), encoding="utf-8")
    manifest = ScannerManifest(input_root=str(tmp_path / "input"), entries=[ManifestEntry(file="a.mov", source=SourceRecord(relative_path="../a.mov", size_bytes=1, mtime_ns=1), technical=result.items[0].technical)])
    with pytest.raises(ValueError, match="escapes manifest input root"):
        build_scanner_observations_from_files(result, manifest, result_path)
