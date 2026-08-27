"""Developer-only command line interface."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import cv2
import psutil
import typer
from PIL import Image

from scanner import __version__
from scanner.config import SamplingConfig
from scanner.cv_metrics import aggregate_quality, measure_motion
from scanner.detector import TorchvisionSSDLiteDetector, summarize_detections
from scanner.metadata import build_manifest, discover_videos
from scanner.sampling import decode_probe_frames, extract_representative_thumbnails, select_representatives
from scanner.schema import GroundTruthDataset, TestManifest
from scanner.selection import propose_stratified_set, render_contact_sheet


app = typer.Typer(no_args_is_help=True, help="Local-first travel media scanner experiments.")


@app.callback()
def main() -> None:
    """Run a local media scanner experiment command."""


@app.command()
def version() -> None:
    """Print the scanner package version."""

    typer.echo(__version__)


@app.command()
def inspect(input: Path = typer.Option(..., "--input", exists=True, file_okay=False)) -> None:
    """Print read-only ffprobe metadata for a video directory."""

    manifest = build_manifest(input, discover_videos(input))
    typer.echo(manifest.model_dump_json(indent=2))


@app.command()
def sample(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    profile: Literal["temporal3", "adaptive5"] = typer.Option("adaptive5", "--profile"),
    hwaccel: Literal["none", "videotoolbox"] = typer.Option("none", "--hwaccel"),
    output: Path = typer.Option(..., "--output", file_okay=False),
) -> None:
    """Extract bounded probe frames and sparse representative thumbnails."""

    parsed = TestManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
    config = SamplingConfig(profile=profile, hardware_acceleration=hwaccel)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for index, entry in enumerate(parsed.entries):
        started = time.perf_counter()
        source = Path(parsed.input_root) / entry.source.relative_path
        item_dir = output / "frames" / f"{index:04d}-{Path(entry.file).stem}"
        probe_frames = decode_probe_frames(source, entry.technical, item_dir / "probe", config)
        candidates = select_representatives(probe_frames, entry.technical.duration, profile)
        records = extract_representative_thumbnails(source, candidates, item_dir / "representative")
        rows.append(
            {
                "file": entry.file,
                "profile": profile,
                "hardware_acceleration": hwaccel,
                "probe_frame_count": len(probe_frames),
                "representative_frames": [record.model_dump() for record in records],
                "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            }
        )
    result_path = output / "sampling_result.json"
    result_path.write_text(json.dumps({"items": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(str(result_path))


@app.command("cv-profile")
def cv_profile(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", file_okay=False),
    hwaccel: Literal["none", "videotoolbox"] = typer.Option("none", "--hwaccel"),
) -> None:
    """Measure uncalibrated CV quality and motion values for a manifest."""

    parsed = TestManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
    config = SamplingConfig(hardware_acceleration=hwaccel)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for index, entry in enumerate(parsed.entries):
        started = time.perf_counter()
        source = Path(parsed.input_root) / entry.source.relative_path
        probe_frames = decode_probe_frames(source, entry.technical, output / "probe" / f"{index:04d}", config)
        rows.append(
            {
                "file": entry.file,
                "probe_frame_count": len(probe_frames),
                "hardware_acceleration": hwaccel,
                "quality": aggregate_quality(probe_frames).model_dump(),
                "motion": measure_motion(probe_frames).model_dump(),
                "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            }
        )
    result_path = output / "cv_profile.json"
    result_path.write_text(json.dumps({"items": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(str(result_path))


@app.command("select-testset")
def select_testset(
    input: Path = typer.Option(..., "--input", exists=True, file_okay=False),
    count: int = typer.Option(30, "--count", min=1),
    seed: int = typer.Option(20260827, "--seed"),
    manifest: Path = typer.Option(..., "--manifest", dir_okay=False),
    contact_sheet: Path = typer.Option(..., "--contact-sheet", dir_okay=False),
    hwaccel: Literal["none", "videotoolbox"] = typer.Option("none", "--hwaccel"),
) -> None:
    """Propose a deterministic, model-free Ground Truth test set."""

    inventory = build_manifest(input, discover_videos(input))
    selected = propose_stratified_set(inventory, [], count=count, seed=seed)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(selected.model_dump_json(indent=2), encoding="utf-8")
    render_contact_sheet(selected, contact_sheet, hardware_acceleration=hwaccel)
    typer.echo(str(manifest))


@app.command("validate-ground-truth")
def validate_ground_truth(
    input: Path = typer.Option(..., "--input", exists=True, dir_okay=False),
) -> None:
    """Validate a frozen human Ground Truth JSON file."""

    dataset = GroundTruthDataset.model_validate_json(input.read_text(encoding="utf-8"))
    suffix = "item" if len(dataset.items) == 1 else "items"
    typer.echo(f"valid: {len(dataset.items)} {suffix}")


@app.command("detector-smoke")
def detector_smoke(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    limit: int = typer.Option(5, "--limit", min=1),
    output: Path = typer.Option(..., "--output", file_okay=False),
    device: Literal["cpu", "mps", "cuda"] = typer.Option("cpu", "--device"),
    threshold: float = typer.Option(0.5, "--threshold", min=0.0, max=1.0),
    hwaccel: Literal["none", "videotoolbox"] = typer.Option("none", "--hwaccel"),
    cache_dir: Path = typer.Option(Path(".cache/models/torchvision"), "--cache-dir", file_okay=False),
) -> None:
    """Run local SSDLite evidence on a bounded manifest prefix."""

    parsed = TestManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    total_started = time.perf_counter()

    load_started = time.perf_counter()
    detector = TorchvisionSSDLiteDetector.load(
        cache_dir=cache_dir,
        score_threshold=threshold,
        device=device,
    )
    load_ms = (time.perf_counter() - load_started) * 1000.0
    peak_rss = max(peak_rss, process.memory_info().rss)

    config = SamplingConfig(profile="adaptive5", hardware_acceleration=hwaccel)
    items: list[dict] = []
    for index, entry in enumerate(parsed.entries[:limit]):
        item_started = time.perf_counter()
        source = Path(parsed.input_root) / entry.source.relative_path
        probe_frames = decode_probe_frames(
            source,
            entry.technical,
            output / "probe" / f"{index:04d}",
            config,
        )
        candidates = select_representatives(probe_frames, entry.technical.duration, "adaptive5")
        images = [
            Image.fromarray(cv2.cvtColor(candidate.image, cv2.COLOR_BGR2RGB))
            for candidate in candidates
        ]
        inference_started = time.perf_counter()
        per_frame = detector.detect(images)
        inference_ms = (time.perf_counter() - inference_started) * 1000.0
        summary = summarize_detections(per_frame)
        frames = [
            {
                "timestamp": candidate.timestamp,
                "reasons": candidate.reasons,
                "detections": [asdict(detection) for detection in detections],
            }
            for candidate, detections in zip(candidates, per_frame, strict=True)
        ]
        peak_rss = max(peak_rss, process.memory_info().rss)
        items.append(
            {
                "file": entry.file,
                "probe_frame_count": len(probe_frames),
                "representative_frame_count": len(candidates),
                "frames": frames,
                "summary": summary.model_dump(),
                "inference_ms": inference_ms,
                "elapsed_ms": (time.perf_counter() - item_started) * 1000.0,
            }
        )

    try:
        import torch
        import torchvision

        dependency_versions = {"torch": torch.__version__, "torchvision": torchvision.__version__}
    except ImportError:
        dependency_versions = {}
    result = {
        "model_id": detector.model_id,
        "weights_id": detector.weights_id,
        "device": detector.device,
        "score_threshold": detector.score_threshold,
        "hardware_acceleration": hwaccel,
        "cache_dir": str(cache_dir.resolve()),
        "dependency_versions": dependency_versions,
        "load_ms": load_ms,
        "peak_rss_bytes_observed": peak_rss,
        "total_ms": (time.perf_counter() - total_started) * 1000.0,
        "items": items,
    }
    result_path = output / "detector_result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(str(result_path))
