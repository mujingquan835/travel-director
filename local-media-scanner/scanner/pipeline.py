"""Stage-isolated local scanning orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import time
from typing import Any

import cv2
from PIL import Image

from scanner.config import ScanConfig
from scanner.cache import cache_key
from scanner.cv_metrics import aggregate_quality, measure_motion
from scanner.detector import summarize_detections
from scanner.fusion import FusedField, fuse_people, fuse_shot_scale, fuse_single_label
from scanner.roles import infer_material_roles
from scanner.sampling import SamplingError, decode_probe_frames, select_representatives
from scanner.schema import (
    ConfidenceScore,
    ContentAnalysis,
    ErrorRecord,
    FrameRecord,
    ManifestEntry,
    MotionMetrics,
    QualityMetrics,
    ScannerCard,
    ScannerResult,
    TestManifest,
    TimingBreakdown,
)
from scanner.vision import (
    ACTION_PROMPTS,
    OBJECT_PROMPTS,
    PEOPLE_TYPE_PROMPTS,
    SCENE_PROMPTS,
    SHOT_SCALE_PROMPTS,
)


@dataclass
class ScanContext:
    input_root: Path
    run_dir: Path
    config: ScanConfig
    detector: Any | None = None
    vision_encoder: Any | None = None
    model_revisions: dict[str, str] = field(default_factory=dict)
    actual_device: str = "none"


def _write_candidate_frames(entry: ManifestEntry, candidates, context: ScanContext) -> list[FrameRecord]:
    output_dir = context.run_dir / "frames" / entry.file.replace("/", "_")
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[FrameRecord] = []
    max_edge = context.config.sampling.thumbnail_max_edge
    for index, candidate in enumerate(candidates):
        image = candidate.image
        height, width = image.shape[:2]
        scale = min(1.0, max_edge / max(height, width))
        if scale < 1.0:
            image = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        relative = Path("frames") / entry.file.replace("/", "_") / f"{index:02d}.jpg"
        output = context.run_dir / relative
        if not cv2.imwrite(str(output), image):
            raise SamplingError("thumbnail_failed", f"Could not write {output}")
        records.append(
            FrameRecord(
                timestamp=candidate.timestamp,
                reasons=candidate.reasons,
                thumbnail_relpath=relative.as_posix(),
            )
        )
    return records


def _failed_card(entry: ManifestEntry, error: ErrorRecord, total_ms: float) -> ScannerCard:
    return ScannerCard(
        file=entry.file,
        source=entry.source,
        analysis_status="failed",
        technical=entry.technical,
        quality=QualityMetrics(),
        motion=MotionMetrics(),
        content=ContentAnalysis(),
        field_status={},
        timings_ms=TimingBreakdown(total=total_ms),
        errors=[error],
    )


def _confidence_from_fusion(field: FusedField[str], source: str) -> ConfidenceScore | None:
    if field.value is None or field.agreement is None or field.margin is None:
        return None
    margin_score = min(max(field.margin / 0.08, 0.0), 1.0)
    return ConfidenceScore(
        score=round(field.agreement * margin_score, 6),
        source=source,
        margin=field.margin,
    )


def scan_one(entry: ManifestEntry, context: ScanContext) -> ScannerCard:
    started = time.perf_counter()
    source = context.input_root / entry.source.relative_path
    sampling_started = time.perf_counter()
    try:
        probe_frames = decode_probe_frames(
            source,
            entry.technical,
            context.run_dir / "probe" / entry.file.replace("/", "_"),
            context.config.sampling,
        )
        candidates = select_representatives(
            probe_frames,
            entry.technical.duration,
            context.config.sampling.profile,
        )
        frame_records = _write_candidate_frames(entry, candidates, context)
    except SamplingError as exc:
        return _failed_card(
            entry,
            ErrorRecord(stage="sampling", code=exc.code, message=str(exc)),
            (time.perf_counter() - started) * 1000.0,
        )

    frame_scan_ms = (time.perf_counter() - sampling_started) * 1000.0
    cv_started = time.perf_counter()
    errors: list[ErrorRecord] = []
    try:
        quality = aggregate_quality(probe_frames)
        motion = measure_motion(probe_frames)
    except Exception as exc:
        quality = QualityMetrics()
        motion = MotionMetrics()
        errors.append(ErrorRecord(stage="cv", code="cv_failed", message=str(exc)))
    cv_ms = (time.perf_counter() - cv_started) * 1000.0
    images = [Image.fromarray(cv2.cvtColor(candidate.image, cv2.COLOR_BGR2RGB)) for candidate in candidates]
    field_status: dict[str, str] = {}
    confidence: dict[str, ConfidenceScore] = {}
    content = ContentAnalysis()
    shot_scale = None
    detector_rows = [[] for _ in images]
    detector_ms = None
    vision_ms = None
    vision_predictions: dict[str, list[Any]] = {}

    if context.detector is not None:
        stage_started = time.perf_counter()
        try:
            detector_rows = context.detector.detect(images)
            summary = summarize_detections(detector_rows)
            people = fuse_people(summary)
            content.people_present = people.present.value
            content.people_count_estimate = people.count.value
            content.main_objects = summary.main_objects
            field_status["content.people_present"] = "candidate"
            field_status["content.people_count_estimate"] = "candidate"
            field_status["content.main_objects"] = "candidate"
            person_score = summary.object_max_scores.get("person")
            if person_score is not None:
                confidence["content.people_present"] = ConfidenceScore(
                    score=person_score,
                    source="detector",
                )
        except Exception as exc:  # model adapters define their own runtime errors
            errors.append(ErrorRecord(stage="detector", code="detector_failed", message=str(exc)))
            field_status["content.people_present"] = "unavailable"
        detector_ms = (time.perf_counter() - stage_started) * 1000.0
    else:
        field_status["content.people_present"] = "unavailable"

    if context.vision_encoder is not None:
        stage_started = time.perf_counter()
        try:
            predictions = context.vision_encoder.classify_many(
                images,
                {
                    "scene": SCENE_PROMPTS,
                    "shot_scale": SHOT_SCALE_PROMPTS,
                    "people_type": PEOPLE_TYPE_PROMPTS,
                    "action": ACTION_PROMPTS,
                    "objects": OBJECT_PROMPTS,
                },
            )
            vision_predictions = predictions
            scene = fuse_single_label(predictions["scene"], min_margin=0.08, min_agreement=0.6)
            action = fuse_single_label(predictions["action"], min_margin=0.08, min_agreement=0.6)
            people_type = fuse_single_label(predictions["people_type"], min_margin=0.08, min_agreement=0.6)
            objects = fuse_single_label(predictions["objects"], min_margin=0.08, min_agreement=0.6)
            image_sizes = [(candidate.image.shape[0], candidate.image.shape[1]) for candidate in candidates]
            shot = fuse_shot_scale(predictions["shot_scale"], detector_rows, image_sizes)

            content.scene_type = scene.value
            content.simple_action = action.value
            if content.people_present is True and people_type.value in {"child", "adult"}:
                content.people_type = [people_type.value]
            if objects.value is not None and objects.value not in content.main_objects:
                content.main_objects.append(objects.value)
            shot_scale = shot.value
            for key, fused in (
                ("content.scene_type", scene),
                ("content.simple_action", action),
                ("content.people_type", people_type),
                ("content.main_objects", objects),
                ("shot_scale", shot),
            ):
                field_status[key] = fused.status
                score = _confidence_from_fusion(fused, fused.evidence_source)
                if score is not None:
                    confidence[key] = score
        except Exception as exc:
            errors.append(ErrorRecord(stage="vision_model", code="vision_failed", message=str(exc)))
            for key in ("content.scene_type", "content.simple_action", "content.people_type", "shot_scale"):
                field_status[key] = "unavailable"
        vision_ms = (time.perf_counter() - stage_started) * 1000.0
    else:
        for key in ("content.scene_type", "content.simple_action", "content.people_type", "shot_scale"):
            field_status[key] = "unavailable"

    evidence_path = context.run_dir / "evidence" / f"{entry.file.replace('/', '_')}.json"
    cache_link_path = context.run_dir / "cache-links" / f"{entry.file.replace('/', '_')}.json"
    try:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        cache_link_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(
                {
                    "file": entry.file,
                    "representative_frames": [record.model_dump(mode="json") for record in frame_records],
                    "detector": [[asdict(row) for row in frame] for frame in detector_rows],
                    "vision": {
                        key: [
                            {
                                "field": prediction.field,
                                "scores": [asdict(score) for score in prediction.scores],
                                "top_margin": prediction.top_margin,
                                "source": prediction.source,
                            }
                            for prediction in rows
                        ]
                        for key, rows in vision_predictions.items()
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cache_link_path.write_text(
            json.dumps(
                {
                    "cache_key": cache_key(entry, context.config, context.model_revisions),
                    "evidence_relpath": evidence_path.relative_to(context.run_dir).as_posix(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        errors.append(ErrorRecord(stage="evidence", code="evidence_write_failed", message=str(exc)))

    fusion_started = time.perf_counter()
    card = ScannerCard(
        file=entry.file,
        source=entry.source,
        analysis_status="partial" if errors else "complete",
        technical=entry.technical,
        quality=quality,
        motion=motion,
        content=content,
        shot_scale=shot_scale,
        representative_frames=frame_records,
        confidence=confidence,
        field_status=field_status,
        timings_ms=TimingBreakdown(
            frame_scan=frame_scan_ms,
            cv=cv_ms,
            detector=detector_ms,
            vision_model=vision_ms,
        ),
        errors=errors,
    )
    roles, role_evidence = infer_material_roles(card)
    card.material_role_candidates = roles
    card.material_role_evidence = role_evidence
    card.timings_ms.fusion = (time.perf_counter() - fusion_started) * 1000.0
    card.timings_ms.total = (time.perf_counter() - started) * 1000.0
    return card


def scan_manifest(manifest: TestManifest, context: ScanContext) -> ScannerResult:
    context.run_dir.mkdir(parents=True, exist_ok=True)
    items = [scan_one(entry, context) for entry in manifest.entries]
    return ScannerResult(
        run_id=context.run_dir.name,
        requested_device=context.config.device,
        actual_device=context.actual_device,
        model_revisions=context.model_revisions,
        items=items,
    )
