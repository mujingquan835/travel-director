"""Developer-only command line interface."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Literal

import cv2
import psutil
import typer
from PIL import Image

from scanner import __version__
from scanner.cache import create_run_dir
from scanner.config import SamplingConfig, ScanConfig
from scanner.cv_metrics import aggregate_quality, measure_motion
from scanner.detector import TorchvisionSSDLiteDetector, summarize_detections
from scanner.evaluation import evaluate_ablation, evaluate_detector, evaluate_run
from scanner.metadata import build_manifest, discover_videos
from scanner.pipeline import ScanContext, scan_manifest
from scanner.report import publish_run, rebase_thumbnail_paths, render_validation_report
from scanner.sampling import decode_probe_frames, extract_representative_thumbnails, select_representatives
from scanner.schema import (
    EvaluationSummary,
    GroundTruthDataset,
    PeopleValidationDataset,
    ScannerResult,
    TestManifest,
)
from scanner.selection import propose_independent_set, propose_stratified_set, render_contact_sheet
from scanner.telemetry import ResourceMonitor, accelerator_memory
from scanner.vision import (
    ACTION_PROMPTS,
    DEFAULT_SIGLIP2_MODEL_ID,
    DEFAULT_SIGLIP2_REVISION,
    OBJECT_PROMPTS,
    PEOPLE_TYPE_PROMPTS,
    PROMPT_SET_VERSION,
    SCENE_PROMPTS,
    SHOT_SCALE_PROMPTS,
    SiglipEvidenceEncoder,
)


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


@app.command("select-people-validation")
def select_people_validation(
    input: Path = typer.Option(..., "--input", exists=True, file_okay=False),
    exclude_manifest: Path = typer.Option(
        ..., "--exclude-manifest", exists=True, dir_okay=False
    ),
    count: int = typer.Option(30, "--count", min=1),
    seed: int = typer.Option(20260828, "--seed"),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Freeze a metadata-only people-validation set excluding prior Ground Truth."""

    inventory = build_manifest(input, discover_videos(input))
    excluded = TestManifest.model_validate_json(exclude_manifest.read_text(encoding="utf-8"))
    selected = propose_independent_set(inventory, excluded, count=count, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(selected.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("validate-ground-truth")
def validate_ground_truth(
    input: Path = typer.Option(..., "--input", exists=True, dir_okay=False),
) -> None:
    """Validate a frozen human Ground Truth JSON file."""

    dataset = GroundTruthDataset.model_validate_json(input.read_text(encoding="utf-8"))
    suffix = "item" if len(dataset.items) == 1 else "items"
    typer.echo(f"valid: {len(dataset.items)} {suffix}")


@app.command("validate-people-ground-truth")
def validate_people_ground_truth(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    input: Path = typer.Option(..., "--input", exists=True, dir_okay=False),
) -> None:
    """Validate independent people labels against the exact frozen manifest."""

    manifest_bytes = manifest.read_bytes()
    parsed_manifest = TestManifest.model_validate_json(manifest_bytes)
    dataset = PeopleValidationDataset.model_validate_json(input.read_text(encoding="utf-8"))
    expected_hash = sha256(manifest_bytes).hexdigest()
    if dataset.manifest_sha256 != expected_hash:
        raise typer.BadParameter("people Ground Truth manifest_sha256 does not match manifest")
    manifest_files = {entry.file for entry in parsed_manifest.entries}
    if len(manifest_files) != len(parsed_manifest.entries):
        raise typer.BadParameter("people validation manifest contains ambiguous duplicate filenames")
    label_files = {item.file for item in dataset.items}
    if label_files != manifest_files:
        missing = sorted(manifest_files - label_files)
        extra = sorted(label_files - manifest_files)
        raise typer.BadParameter(
            f"people Ground Truth membership mismatch: missing={missing}, extra={extra}"
        )
    typer.echo(f"valid: {len(dataset.items)} people validation items")


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


@app.command("vision-smoke")
def vision_smoke(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    limit: int = typer.Option(5, "--limit", min=1),
    output: Path = typer.Option(..., "--output", file_okay=False),
    device: Literal["auto", "cpu", "mps", "cuda"] = typer.Option("auto", "--device"),
    hwaccel: Literal["none", "videotoolbox"] = typer.Option("none", "--hwaccel"),
    model_id: str = typer.Option(DEFAULT_SIGLIP2_MODEL_ID, "--model-id"),
    revision: str = typer.Option(DEFAULT_SIGLIP2_REVISION, "--revision"),
    cache_dir: Path = typer.Option(Path(".cache/models/huggingface"), "--cache-dir", file_okay=False),
    local_files_only: bool = typer.Option(False, "--local-files-only/--allow-download"),
) -> None:
    """Run pinned local SigLIP2 prompt evidence on a bounded manifest prefix."""

    parsed = TestManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    total_started = time.perf_counter()

    load_started = time.perf_counter()
    encoder = SiglipEvidenceEncoder.load(
        model_id=model_id,
        cache_dir=cache_dir,
        requested_device=device,
        revision=revision,
        local_files_only=local_files_only,
    )
    load_ms = (time.perf_counter() - load_started) * 1000.0
    peak_rss = max(peak_rss, process.memory_info().rss)

    field_groups = {
        "scene": SCENE_PROMPTS,
        "shot_scale": SHOT_SCALE_PROMPTS,
        "people_type": PEOPLE_TYPE_PROMPTS,
        "action": ACTION_PROMPTS,
        "objects": OBJECT_PROMPTS,
    }
    config = SamplingConfig(profile="adaptive5", hardware_acceleration=hwaccel)
    items: list[dict] = []
    inference_total_ms = 0.0
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
        predictions_by_field = encoder.classify_many(images, field_groups)
        inference_ms = (time.perf_counter() - inference_started) * 1000.0
        inference_total_ms += inference_ms
        frames: list[dict] = []
        for frame_index, candidate in enumerate(candidates):
            frames.append(
                {
                    "timestamp": candidate.timestamp,
                    "reasons": candidate.reasons,
                    "predictions": {
                        field: asdict(predictions[frame_index])
                        for field, predictions in predictions_by_field.items()
                    },
                }
            )
        peak_rss = max(peak_rss, process.memory_info().rss)
        items.append(
            {
                "file": entry.file,
                "probe_frame_count": len(probe_frames),
                "representative_frame_count": len(candidates),
                "frames": frames,
                "inference_ms": inference_ms,
                "elapsed_ms": (time.perf_counter() - item_started) * 1000.0,
            }
        )

    import torch
    import transformers

    mps_allocated = None
    if encoder.device.actual == "mps" and hasattr(torch.mps, "current_allocated_memory"):
        mps_allocated = torch.mps.current_allocated_memory()
    result = {
        "model_id": encoder.model_id,
        "requested_revision": revision,
        "resolved_revision": encoder.resolved_revision,
        "prompt_set_version": PROMPT_SET_VERSION,
        "requested_device": encoder.device.requested,
        "actual_device": encoder.device.actual,
        "fallback_reason": encoder.device.fallback_reason,
        "hardware_acceleration": hwaccel,
        "cache_dir": str(cache_dir.resolve()),
        "local_files_only": local_files_only,
        "dependency_versions": {"torch": torch.__version__, "transformers": transformers.__version__},
        "load_ms": load_ms,
        "inference_total_ms": inference_total_ms,
        "peak_rss_bytes_observed": peak_rss,
        "mps_allocated_bytes_after_run": mps_allocated,
        "total_ms": (time.perf_counter() - total_started) * 1000.0,
        "items": items,
    }
    result_path = output / "vision_result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(str(result_path))


@app.command("evaluate-detector")
def evaluate_detector_command(
    ground_truth: Path = typer.Option(..., "--ground-truth", exists=True, dir_okay=False),
    detector_result: Path = typer.Option(..., "--detector-result", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Compare detector evidence with the frozen human labels."""

    truth = GroundTruthDataset.model_validate_json(ground_truth.read_text(encoding="utf-8"))
    payload = json.loads(detector_result.read_text(encoding="utf-8"))
    result = evaluate_detector(truth, payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(str(output))


@app.command("evaluate")
def evaluate_command(
    ground_truth: Path = typer.Option(..., "--ground-truth", exists=True, dir_okay=False),
    result: Path = typer.Option(..., "--result", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Evaluate every overlapping Scanner field without an overall accuracy."""

    truth = GroundTruthDataset.model_validate_json(ground_truth.read_text(encoding="utf-8"))
    scanner_result = ScannerResult.model_validate_json(result.read_text(encoding="utf-8"))
    summary = evaluate_run(truth, scanner_result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("ablate")
def ablate_command(
    ground_truth: Path = typer.Option(..., "--ground-truth", exists=True, dir_okay=False),
    evidence_dir: Path = typer.Option(..., "--evidence-dir", exists=True, file_okay=False),
    fields: str = typer.Option("people_count_estimate,shot_scale", "--fields"),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Compare only the supported saved-evidence ablation methods."""

    truth = GroundTruthDataset.model_validate_json(ground_truth.read_text(encoding="utf-8"))
    summary = evaluate_ablation(
        truth,
        evidence_dir,
        [field.strip() for field in fields.split(",") if field.strip()],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("report")
def report_command(
    ground_truth: Path = typer.Option(..., "--ground-truth", exists=True, dir_okay=False),
    run: Path = typer.Option(..., "--run", exists=True, file_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Render a local static validation report from saved run artifacts."""

    result = ScannerResult.model_validate_json((run / "scanner_result.json").read_text(encoding="utf-8"))
    evaluation = EvaluationSummary.model_validate_json((run / "evaluation.json").read_text(encoding="utf-8"))
    truth = GroundTruthDataset.model_validate_json(ground_truth.read_text(encoding="utf-8"))
    environment = json.loads((run / "environment.json").read_text(encoding="utf-8"))
    rebased = rebase_thumbnail_paths(result, run, output.parent)
    render_validation_report(rebased, evaluation, environment, output, truth)
    typer.echo(str(output))


@app.command("publish")
def publish_command(
    ground_truth: Path = typer.Option(..., "--ground-truth", exists=True, dir_okay=False),
    run: Path = typer.Option(..., "--run", exists=True, file_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir", file_okay=False),
) -> None:
    """Publish shareable JSON/HTML pointers without copying private frames."""

    result_path, report_path = publish_run(run, ground_truth, output_dir)
    typer.echo(str(result_path))
    typer.echo(str(report_path))


@app.command("scan")
def scan_command(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    run_id: str = typer.Option(..., "--run-id"),
    runs_dir: Path = typer.Option(Path("benchmark/runs"), "--runs-dir", file_okay=False),
    limit: int | None = typer.Option(None, "--limit", min=1),
    sampling_profile: Literal["temporal3", "adaptive5"] = typer.Option(
        "adaptive5", "--sampling-profile"
    ),
    device: Literal["auto", "cpu", "mps", "cuda"] = typer.Option("auto", "--device"),
    hwaccel: Literal["none", "videotoolbox"] = typer.Option("none", "--hwaccel"),
    models: bool = typer.Option(True, "--models/--no-models"),
    resume: bool = typer.Option(False, "--resume"),
) -> None:
    """Run one immutable, local-only Scanner pipeline."""

    parsed = TestManifest.model_validate_json(manifest.read_text(encoding="utf-8"))
    if limit is not None:
        parsed = parsed.model_copy(update={"entries": parsed.entries[:limit]})
    config = ScanConfig(
        device=device,
        sampling=SamplingConfig(profile=sampling_profile, hardware_acceleration=hwaccel),
    )
    paths = create_run_dir(runs_dir, run_id, config, resume=resume)
    monitor = ResourceMonitor().start()
    detector = None
    vision_encoder = None
    model_revisions: dict[str, str] = {}
    actual_device = "none"
    model_load_ms = 0.0
    scan_ms = 0.0
    result = None
    status = "failed"
    failure: str | None = None
    try:
        load_started = time.perf_counter()
        if models:
            detector = TorchvisionSSDLiteDetector.load(
                cache_dir=config.models.model_cache_dir / "torchvision",
                score_threshold=config.models.detector_score_threshold,
                device="cpu",
            )
            vision_encoder = SiglipEvidenceEncoder.load(
                model_id=config.models.vision_model_id,
                cache_dir=config.models.model_cache_dir / "huggingface",
                requested_device=device,
                revision=DEFAULT_SIGLIP2_REVISION,
                local_files_only=True,
            )
            model_revisions = {
                "detector": detector.weights_id,
                "siglip": vision_encoder.resolved_revision or DEFAULT_SIGLIP2_REVISION,
            }
            actual_device = vision_encoder.device.actual
        model_load_ms = (time.perf_counter() - load_started) * 1000.0
        context = ScanContext(
            input_root=Path(parsed.input_root),
            run_dir=paths.root,
            config=config,
            detector=detector,
            vision_encoder=vision_encoder,
            model_revisions=model_revisions,
            actual_device=actual_device,
        )
        scan_started = time.perf_counter()
        result = scan_manifest(parsed, context)
        scan_ms = (time.perf_counter() - scan_started) * 1000.0
        output = paths.root / "scanner_result.json"
        output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        status = "completed"
    except Exception as exc:
        failure = type(exc).__name__
        raise
    finally:
        resources = monitor.stop()
        cards = result.items if result is not None else []
        telemetry = {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "status": status,
            "failure": failure,
            "phases_ms": {
                "model_load": model_load_ms,
                "scan": scan_ms,
                "total": resources.wall_ms,
            },
            "resource": resources.to_dict(),
            "accelerator": {
                "requested_device": device,
                **accelerator_memory(actual_device),
            },
            "workload": {
                "cards_total": len(cards),
                "cards_complete": sum(card.analysis_status == "complete" for card in cards),
                "cards_partial": sum(card.analysis_status == "partial" for card in cards),
                "cards_failed": sum(card.analysis_status == "failed" for card in cards),
                "representative_frames": sum(len(card.representative_frames) for card in cards),
            },
        }
        (paths.root / "telemetry.json").write_text(
            json.dumps(telemetry, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    typer.echo(str(output))
