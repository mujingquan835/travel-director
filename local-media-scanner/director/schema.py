"""Strict, versioned contracts shared across Director stages."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scanner.schema import ErrorRecord, FrameRecord, SourceRecord, TechnicalMetadata


SchemaVersion = Literal["0.1.0"]
StageStatus = Literal["pending", "completed", "failed", "blocked", "partial"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderError(StrictModel):
    stage: str
    code: str
    message: str


class ExternalCallRecord(StrictModel):
    provider: str
    operation: str
    authorized_at: str
    call_count: int = Field(ge=0)
    expected_cost: str = "unknown"
    actual_cost: str = "unknown"
    output_status: Literal["not_started", "succeeded", "failed"]
    artifact_relpath: str | None = None


class ArtifactStatus(StrictModel):
    status: StageStatus
    errors: list[ProviderError] = Field(default_factory=list)


class ScalarEvidence(StrictModel):
    value: float | None = None
    source: str
    status: Literal["measured", "candidate", "unavailable"]


class QualityEvidence(StrictModel):
    laplacian_variance_raw: float | None = None
    brightness_score: float | None = None
    dark_pixel_ratio: float | None = None
    bright_pixel_ratio: float | None = None
    exposure_candidate: str | None = None


class MotionEvidence(StrictModel):
    motion_intensity_raw: float | None = None
    directional_motion_ratio: float | None = None
    luma_change_p90: float | None = None
    motion_level_candidate: str | None = None


class PeopleEvidence(StrictModel):
    present_candidate: bool | None = None
    count_lower_bound: int | None = Field(default=None, ge=0)
    source: str = "scanner_candidate"


class AudioValueCandidate(StrictModel):
    status: Literal["candidate", "unavailable"]
    rms: float | None = Field(default=None, ge=0.0)
    clipping_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    spectral_flatness: float | None = Field(default=None, ge=0.0, le=1.0)
    onset_density: float | None = Field(default=None, ge=0.0)
    reason: str


class RecommendedRange(StrictModel):
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    reasons: list[str]

    @model_validator(mode="after")
    def end_follows_start(self) -> "RecommendedRange":
        if self.end <= self.start:
            raise ValueError("range end must follow start")
        return self


class SfxCandidate(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    file: str
    label: str
    source_time_seconds: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_source: str


class MaterialScanResult(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    file: str
    source: SourceRecord
    technical: TechnicalMetadata
    analysis_status: Literal["complete", "partial", "failed"]
    quality_evidence: QualityEvidence
    motion_evidence: MotionEvidence
    scene_candidates: list[str] = Field(default_factory=list)
    confirmed_scene: str | None = None
    object_candidates: list[str] = Field(default_factory=list)
    people_evidence: PeopleEvidence
    story_priority: float | None = None
    representative_frames: list[FrameRecord] = Field(default_factory=list)
    duplicate_group_id: str | None = None
    visual_impact_score: float | None = Field(default=None, ge=0.0, le=1.0)
    original_audio_value_candidate: AudioValueCandidate | None = None
    sfx_candidates: list[SfxCandidate] = Field(default_factory=list)
    recommended_ranges: list[RecommendedRange] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)


class MaterialLibraryProfile(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    source_scanner_run_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    materials: list[MaterialScanResult]
    total_source_duration_seconds: float = Field(ge=0.0)
    usable_material_count: int = Field(ge=0)
    scene_distribution: dict[str, int] = Field(default_factory=dict)
    motion_distribution: dict[str, int] = Field(default_factory=dict)
    orientation_distribution: dict[str, int] = Field(default_factory=dict)
    processing_time_estimate_seconds: float | None = Field(default=None, ge=0.0)


class UserCreativeBrief(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    location: str = Field(min_length=1)
    travel_type: str = Field(min_length=1)
    target_duration_seconds: int = Field(ge=30, le=180)
    orientation: Literal["landscape", "portrait"]
    style: str = Field(min_length=1)
    mood: str = Field(min_length=1)
    rhythm: Literal["low", "medium", "high"]
    vocals: Literal["instrumental_only", "instrumental_preferred", "allowed"] = (
        "instrumental_preferred"
    )
    instrument_preferences: list[str] = Field(default_factory=list)


class MusicSearchEvidence(StrictModel):
    source_scanner_run_id: str
    rules: list[str]


class MusicSearchBrief(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    keywords: list[str]
    genres: list[str]
    moods: list[str]
    bpm_min: int = Field(ge=40, le=240)
    bpm_max: int = Field(ge=40, le=240)
    instrument_preferences: list[str] = Field(default_factory=list)
    vocals: Literal["instrumental_only", "instrumental_preferred", "allowed"]
    target_duration_seconds: int = Field(ge=30, le=180)
    evidence: MusicSearchEvidence

    @model_validator(mode="after")
    def bpm_range_is_ordered(self) -> "MusicSearchBrief":
        if self.bpm_min >= self.bpm_max:
            raise ValueError("bpm_min must be lower than bpm_max")
        return self


class MusicCandidate(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    provider: str
    candidate_id: str
    title: str
    visible_tags: list[str] = Field(default_factory=list)
    bpm: int | None = Field(default=None, ge=40, le=240)
    duration_seconds: float | None = Field(default=None, gt=0.0)
    author: str | None = None
    label: str | None = None
    detail_url: str | None = None
    preview_url: str | None = None
    provider_payload: None = None


class CatalogSearchResult(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    provider: str
    status: StageStatus
    capture_scope: Literal["fixture", "current_visible_page"]
    candidates: list[MusicCandidate] = Field(max_length=5)
    downloaded_audio_count: Literal[0] = 0
    errors: list[ProviderError] = Field(default_factory=list)


class MusicDirection(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    candidate_id: str
    title: str
    author: str | None = None
    plain_description: str
    fit_reason: str
    preview_url: str | None = None
    bpm: int | None = None
    genres: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)
    instruments: list[str] = Field(default_factory=list)
    score: float
    reasons: dict[str, float]


class MusicBlueprintSection(StrictModel):
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    role: Literal["intro", "rise", "breath", "climax", "outro", "unknown"]
    energy: float = Field(ge=0.0, le=1.0)


class MusicBlueprint(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    duration_seconds: int = Field(ge=30, le=180)
    bpm: int = Field(ge=40, le=240)
    meter: str
    genre: str
    instrumentation: list[str]
    vocals: Literal["none", "allowed"]
    sections: list[MusicBlueprintSection] = Field(min_length=1)
    ending: str

    @model_validator(mode="after")
    def sections_are_contiguous(self) -> "MusicBlueprint":
        tolerance = 1e-6
        if abs(self.sections[0].start) > tolerance:
            raise ValueError("sections must be contiguous from zero")
        for previous, current in zip(self.sections, self.sections[1:]):
            if abs(previous.end - current.start) > tolerance:
                raise ValueError("sections must be contiguous")
        if abs(self.sections[-1].end - self.duration_seconds) > tolerance:
            raise ValueError("sections must be contiguous through duration")
        return self


class GeneratedMusicAsset(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    status: StageStatus
    provider: str
    blueprint_hash: str
    local_path: str | None = None
    sha256: str | None = None
    duration_seconds: float | None = Field(default=None, gt=0.0)
    mime_type: str | None = None
    external_call: ExternalCallRecord | None = None
    errors: list[ProviderError] = Field(default_factory=list)


class EnergyPoint(StrictModel):
    time_seconds: float = Field(ge=0.0)
    value: float = Field(ge=0.0, le=1.0)


class MusicStructureSection(StrictModel):
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    role: Literal["intro", "rise", "breath", "climax", "outro", "unknown"]
    energy: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class MusicEnding(StrictModel):
    last_onset_seconds: float | None = Field(default=None, ge=0.0)
    behavior: Literal["hard_stop", "decay", "fade", "unknown"]


class OnsetEvent(StrictModel):
    id: str = Field(min_length=1)
    t: float = Field(ge=0.0)
    strength: float = Field(ge=0.0, le=1.0)


class BeatGap(StrictModel):
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)


class BeatGridInfo(StrictModel):
    period_s: float = Field(gt=0.0)
    coverage: float = Field(ge=0.0, le=1.0)
    gaps: list[BeatGap] = Field(default_factory=list)


class BeatEvent(StrictModel):
    i: int = Field(ge=0)
    t: float = Field(ge=0.0)
    bar: int = Field(ge=0)
    beat_in_bar: int = Field(ge=0, le=16)
    is_downbeat: bool
    is_phrase_start: bool = False
    onset_strength: float = Field(ge=0.0, le=1.0)
    energy: float = Field(ge=0.0, le=1.0)
    accent: bool = False


class PhraseSpan(StrictModel):
    id: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    bars: int = Field(ge=1)
    source: Literal["bar_grid_4", "energy_step", "allin1"]
    confidence: float = Field(ge=0.0, le=1.0)


DownbeatDetectorName = Literal[
    "every_fourth_beat",
    "onset_phase_heuristic",
    "beat_this",
    "allin1",
    "unknown",
]


class MusicStructure(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    source_sha256: str
    duration_seconds: float = Field(gt=0.0)
    bpm: float | None = Field(default=None, gt=0.0)
    beats_seconds: list[float] = Field(default_factory=list)
    downbeats_seconds: list[float] = Field(default_factory=list)
    downbeat_cluster_times: list[float] = Field(default_factory=list)
    energy_curve: list[EnergyPoint] = Field(default_factory=list)
    sections: list[MusicStructureSection] = Field(default_factory=list)
    ending: MusicEnding
    confidence: float = Field(ge=0.0, le=1.0)
    errors: list[ProviderError] = Field(default_factory=list)
    # Rhythm detail is optional. Older files load with the defaults.
    beat_backend: str = ""
    beat_backend_note: str = ""
    onsets: list[OnsetEvent] = Field(default_factory=list)
    beat_events: list[BeatEvent] = Field(default_factory=list)
    beat_grid: BeatGridInfo | None = None
    phrases: list[PhraseSpan] = Field(default_factory=list)
    downbeat_detector: DownbeatDetectorName = "every_fourth_beat"
    downbeat_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    meter_assumed: int | None = None
    analysis_warnings: list[str] = Field(default_factory=list)
    plp_beat_count: int | None = Field(default=None, ge=0)


class TimelineSlot(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    slot_id: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    section_role: str
    energy: float = Field(ge=0.0, le=1.0)
    content_need: str
    desired_motion: str
    beat_start: int | None = Field(default=None, ge=0)
    beat_end: int | None = Field(default=None, ge=0)

    @property
    def duration(self) -> float:
        return self.end - self.start


class ClipPlacement(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    slot_id: str
    file: str
    source_in: float = Field(ge=0.0)
    source_out: float = Field(gt=0.0)
    source_duration: float = Field(gt=0.0)
    section_role: str
    duplicate_group_id: str | None = None
    score_components: dict[str, float] = Field(default_factory=dict)
    relaxed_constraints: list[str] = Field(default_factory=list)


class SfxPlanItem(StrictModel):
    file: str
    timeline_time_seconds: float = Field(ge=0.0)
    decision: Literal["keep_original", "enhance_original", "generate_sfx", "silence"]
    label: str | None = None
    reason: str


class SfxPlan(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    status: StageStatus
    items: list[SfxPlanItem] = Field(default_factory=list)
    errors: list[ProviderError] = Field(default_factory=list)


class ProjectState(StrictModel):
    schema_version: SchemaVersion = "0.1.0"
    project_id: str
    status: StageStatus
    current_stage: str
    artifact_paths: dict[str, str]
    completed_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    errors: list[ProviderError] = Field(default_factory=list)
