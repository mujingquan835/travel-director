"""Developer-only command line interface."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

import typer

from scanner import __version__
from scanner.config import SamplingConfig
from scanner.cv_metrics import aggregate_quality, measure_motion
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
