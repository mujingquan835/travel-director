"""Pydantic contracts shared across scanner stages."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Orientation = Literal["landscape", "portrait", "square", "unknown"]
ExposureStatus = Literal["underexposed", "normal", "overexposed", "mixed", "unknown"]
MotionLevel = Literal["low", "medium", "high", "unknown"]
StaticDynamic = Literal["static", "dynamic", "unknown"]
SceneType = Literal[
    "nature",
    "city",
    "building",
    "indoor",
    "theme_park",
    "food_dining",
    "transportation",
    "night_scene",
    "other",
]
ShotScale = Literal["wide", "medium", "close", "close_up", "aerial"]
MaterialRole = Literal[
    "human_story",
    "environment",
    "experience",
    "detail",
    "transition",
    "atmosphere",
]
FieldStatus = Literal["predicted", "candidate", "abstained", "unavailable"]
AnalysisStatus = Literal["complete", "partial", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRecord(StrictModel):
    relative_path: str
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)


class TechnicalMetadata(StrictModel):
    duration: float = Field(ge=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(ge=0.0)
    orientation: Orientation
    codec: str
    creation_time: str | None = None
    rotation: int | None = None


class QualityMetrics(StrictModel):
    laplacian_variance_raw: float | None = Field(default=None, ge=0.0)
    blur_score: float | None = Field(default=None, ge=0.0, le=1.0)
    brightness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    dark_pixel_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    bright_pixel_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    exposure_status: ExposureStatus = "unknown"
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)


class MotionMetrics(StrictModel):
    motion_intensity_raw: float | None = Field(default=None, ge=0.0)
    motion_intensity: float | None = Field(default=None, ge=0.0, le=1.0)
    motion_level: MotionLevel = "unknown"
    static_or_dynamic: StaticDynamic = "unknown"
    directional_motion_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    luma_change_p90: float | None = Field(default=None, ge=0.0, le=1.0)


class LabelCandidate(StrictModel):
    label: str
    score: float


class ContentAnalysis(StrictModel):
    people_present: bool | None = None
    people_count_estimate: int | None = Field(default=None, ge=0)
    people_type: list[Literal["child", "adult"]] = Field(default_factory=list)
    scene_type: SceneType | None = None
    scene_type_candidates: list[LabelCandidate] = Field(default_factory=list)
    main_objects: list[str] = Field(default_factory=list)
    simple_action: str | None = None


class FrameRecord(StrictModel):
    timestamp: float = Field(ge=0.0)
    reasons: list[Literal["temporal", "motion", "scene_change"]]
    thumbnail_relpath: str


class ConfidenceScore(StrictModel):
    score: float
    source: str
    margin: float | None = None


class RoleEvidence(StrictModel):
    score: float = Field(ge=0.0, le=1.0)
    rules: list[str]
    inputs: list[str]


class ErrorRecord(StrictModel):
    stage: str
    code: str
    message: str


class TimingBreakdown(StrictModel):
    metadata: float | None = Field(default=None, ge=0.0)
    frame_scan: float | None = Field(default=None, ge=0.0)
    cv: float | None = Field(default=None, ge=0.0)
    detector: float | None = Field(default=None, ge=0.0)
    vision_model: float | None = Field(default=None, ge=0.0)
    fusion: float | None = Field(default=None, ge=0.0)
    report: float | None = Field(default=None, ge=0.0)
    total: float | None = Field(default=None, ge=0.0)


class ScannerCard(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    file: str
    source: SourceRecord
    analysis_status: AnalysisStatus
    technical: TechnicalMetadata
    quality: QualityMetrics
    motion: MotionMetrics
    content: ContentAnalysis
    shot_scale: ShotScale | None = None
    material_role_candidates: list[MaterialRole] = Field(default_factory=list)
    material_role_evidence: dict[MaterialRole, RoleEvidence] = Field(default_factory=dict)
    representative_frames: list[FrameRecord] = Field(default_factory=list)
    confidence: dict[str, ConfidenceScore] = Field(default_factory=dict)
    field_status: dict[str, FieldStatus] = Field(default_factory=dict)
    timings_ms: TimingBreakdown = Field(default_factory=TimingBreakdown)
    errors: list[ErrorRecord] = Field(default_factory=list)


class ManifestEntry(StrictModel):
    file: str
    source: SourceRecord
    technical: TechnicalMetadata


class TestManifest(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    input_root: str
    entries: list[ManifestEntry]
    total_duration_seconds: float = Field(default=0.0, ge=0.0)
    total_size_bytes: int = Field(default=0, ge=0)


class GroundTruthItem(StrictModel):
    file: str
    people_present: bool | None = None
    people_count_estimate: int | None = Field(default=None, ge=0)
    people_type: list[Literal["child", "adult"]] = Field(default_factory=list)
    scene_type: SceneType | None = None
    shot_scale: ShotScale | None = None
    motion_level: MotionLevel
    exposure_status: ExposureStatus
    quality_label: Literal["usable", "marginal", "unusable"]
    main_objects: list[str] = Field(default_factory=list)
    simple_action: str | None = None
    material_role_candidates: list[MaterialRole] = Field(default_factory=list)
    annotation_confidence: float = Field(ge=0.0, le=1.0)
    notes: str | None = None


class GroundTruthDataset(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    items: list[GroundTruthItem]

    @model_validator(mode="after")
    def unique_files(self) -> "GroundTruthDataset":
        files = [item.file for item in self.items]
        if len(files) != len(set(files)):
            raise ValueError("duplicate Ground Truth files are not allowed")
        return self


class ScannerResult(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    run_id: str
    requested_device: str
    actual_device: str
    model_revisions: dict[str, str] = Field(default_factory=dict)
    items: list[ScannerCard]


ReliabilityStatus = Literal[
    "reliable",
    "candidate",
    "not_reliable_for_v0_1",
    "insufficient_coverage",
]


class FieldMetrics(StrictModel):
    total_ground_truth: int = Field(ge=0)
    evaluated: int = Field(ge=0)
    abstentions: int = Field(ge=0)
    scored_coverage: float = Field(ge=0.0, le=1.0)
    end_to_end_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    f1: float | None = Field(default=None, ge=0.0, le=1.0)
    macro_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    micro_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    exact_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    within_one_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    mae: float | None = Field(default=None, ge=0.0)
    mean_jaccard: float | None = Field(default=None, ge=0.0, le=1.0)
    rank_correlation: float | None = Field(default=None, ge=-1.0, le=1.0)
    min_class_support: int = Field(default=0, ge=0)
    class_support: dict[str, int] = Field(default_factory=dict)
    confusion: dict[str, Any] = Field(default_factory=dict)


class ReliabilityDecision(StrictModel):
    status: ReliabilityStatus
    score_used: float | None = None
    min_class_support: int = Field(ge=0)
    systematic_failure: bool = False
    reason: str


class FieldEvaluation(StrictModel):
    metrics: FieldMetrics
    reliability: ReliabilityDecision


class EvaluationSummary(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    run_id: str
    ground_truth_items: int = Field(ge=0)
    overlapping_items: int = Field(ge=0)
    overlap_files: list[str]
    fields: dict[str, FieldEvaluation]


class AblationSummary(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    run_id: str
    fields: dict[str, dict[str, FieldEvaluation]]
