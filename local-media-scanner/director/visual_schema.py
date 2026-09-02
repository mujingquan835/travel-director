"""Strict V0.2 contracts for visual understanding and director decisions."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from director.schema import StageStatus


VisualSchemaVersion = Literal["0.2.0"]
DirectorArtifactSchemaVersion = Literal["0.2.0", "0.3.0"]
Sha256 = str
MaterialId = str
CompletionMode = Literal["unresolved", "automatic", "assisted"]
AssertionStatus = Literal["measured", "candidate", "confirmed", "abstained", "unavailable"]
EvidenceSourceKind = Literal[
    "scanner",
    "visual_provider",
    "user_brief",
    "user_confirmation",
    "director_rule",
]
Bucket = Literal["core", "candidate", "redundant", "reject_suggestion", "review_required"]
DirectorFunction = Literal[
    "opening",
    "context",
    "progression",
    "emotion",
    "contrast",
    "breathing",
    "climax",
    "ending",
]
MaterialCapability = Literal[
    "environment_establishing",
    "directional_entry",
    "movement_progression",
    "human_emotion",
    "event_energy",
    "sensory_detail",
    "spatial_transition",
    "quiet_breathing",
    "closure_resonance",
]


class VisualStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_sha256(value: str, field: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return value


def derive_material_id(source_sha256: str) -> str:
    """Create a path-independent material identity from immutable source bytes."""

    return f"sha256:{_validate_sha256(source_sha256, 'source_sha256')}"


class MaterialRef(VisualStrictModel):
    material_id: MaterialId = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    relative_path: str = Field(min_length=1)
    source_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    duration_seconds: float = Field(ge=0.0)
    fps: float = Field(ge=0.0)
    orientation: Literal["landscape", "portrait", "square", "unknown"]
    rotation: int | None = None

    @model_validator(mode="after")
    def identity_matches_source(self) -> "MaterialRef":
        if self.material_id != derive_material_id(self.source_sha256):
            raise ValueError("material_id must be derived from source_sha256")
        return self


class EvidenceRef(VisualStrictModel):
    material_id: MaterialId | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    artifact_path: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    frame_timestamp: float | None = Field(default=None, ge=0.0)
    source_kind: EvidenceSourceKind
    status: AssertionStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ProviderIssue(VisualStrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field: str | None = None


class ObservationAssertion(VisualStrictModel):
    field: str = Field(min_length=1)
    value: Any = None
    status: AssertionStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def supported_values_have_evidence(self) -> "ObservationAssertion":
        if self.status in {"measured", "candidate", "confirmed"} and not self.evidence_refs:
            raise ValueError("supported assertion requires evidence_refs")
        if self.status == "candidate" and self.confidence is None:
            raise ValueError("candidate assertion requires confidence")
        if self.status in {"abstained", "unavailable"} and self.value is not None:
            raise ValueError("abstained or unavailable assertion must not carry a value")
        return self


class ClipObservation(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    material: MaterialRef
    provider: str = Field(min_length=1)
    observation_status: Literal["automatic", "assisted", "abstained", "unavailable"]
    assertions: list[ObservationAssertion] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    review_required_fields: list[str] = Field(default_factory=list)
    errors: list[ProviderIssue] = Field(default_factory=list)


class ClipObservationBatch(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    status: StageStatus
    mode: Literal["automatic", "assisted", "scanner_only"]
    items: list[ClipObservation] = Field(default_factory=list)


class RawCreativeBrief(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    raw_description: str = Field(min_length=1)
    optional_structured_hints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw_description")
    @classmethod
    def description_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("raw_description cannot be blank")
        return stripped


BriefFieldName = Literal[
    "location",
    "travel_type",
    "target_duration_seconds",
    "orientation",
    "style",
    "mood",
    "rhythm",
    "vocals",
    "instrument_preferences",
]
BRIEF_FIELD_NAMES = (
    "location",
    "travel_type",
    "target_duration_seconds",
    "orientation",
    "style",
    "mood",
    "rhythm",
    "vocals",
    "instrument_preferences",
)
REQUIRED_BRIEF_FIELDS = (
    "location",
    "travel_type",
    "target_duration_seconds",
    "orientation",
    "style",
    "mood",
    "rhythm",
)


class NormalizedBriefFields(VisualStrictModel):
    location: str | None = Field(default=None, min_length=1)
    travel_type: str | None = Field(default=None, min_length=1)
    target_duration_seconds: int | None = Field(default=None, ge=30, le=180)
    orientation: Literal["landscape", "portrait"] | None = None
    style: str | None = Field(default=None, min_length=1)
    mood: str | None = Field(default=None, min_length=1)
    rhythm: Literal["low", "medium", "high"] | None = None
    vocals: Literal[
        "instrumental_only", "instrumental_preferred", "allowed"
    ] | None = None
    instrument_preferences: list[str] = Field(default_factory=list)

    @field_validator("instrument_preferences")
    @classmethod
    def instruments_are_unique_and_nonblank(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("instrument preferences cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("instrument preferences must be unique")
        return cleaned


class SourceSpan(VisualStrictModel):
    field: BriefFieldName
    source_kind: Literal[
        "raw_description", "structured_hint", "legacy_structured_brief", "invoking_agent"
    ] = "raw_description"
    text: str = Field(min_length=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def end_follows_start(self) -> "SourceSpan":
        if self.source_kind == "raw_description":
            if self.start is None or self.end is None or self.end <= self.start:
                raise ValueError("raw source span must have ordered offsets")
        elif self.start is not None or self.end is not None:
            raise ValueError("non-raw source evidence cannot carry raw offsets")
        return self


class NormalizedIntentDraft(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    status: StageStatus
    raw_description: str = Field(min_length=1)
    provider: str = Field(default="deterministic", min_length=1)
    normalized_fields: NormalizedBriefFields
    source_spans: list[SourceSpan] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    review_required_fields: list[str] = Field(default_factory=list)
    issues: list[ProviderIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def completion_and_sources_are_consistent(self) -> "NormalizedIntentDraft":
        supported = set(BRIEF_FIELD_NAMES)
        unknown = set(self.unknown_fields)
        conflicts = set(self.conflicting_fields)
        review = set(self.review_required_fields)
        if not unknown.issubset(supported):
            raise ValueError("unknown_fields contains unsupported fields")
        if not conflicts.issubset(supported):
            raise ValueError("conflicting_fields contains unsupported fields")
        if not review.issubset(supported):
            raise ValueError("review_required_fields contains unsupported fields")
        if not conflicts.issubset(unknown & review):
            raise ValueError("conflicting fields must be unknown and review required")
        required_missing = {
            field
            for field in REQUIRED_BRIEF_FIELDS
            if getattr(self.normalized_fields, field) is None
        }
        if not required_missing.issubset(unknown & review):
            raise ValueError("missing required brief fields must require review")
        if self.status == "completed" and review:
            raise ValueError("completed intent draft cannot require review")
        for source in self.source_spans:
            if source.source_kind != "raw_description":
                continue
            assert source.start is not None and source.end is not None
            if self.raw_description[source.start : source.end] != source.text:
                raise ValueError("source span does not match raw_description")
        return self


class BriefConfirmation(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    status: StageStatus
    draft_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_fields: NormalizedBriefFields
    changed_fields: list[str] = Field(default_factory=list)
    confirmed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def completed_confirmation_has_required_fields(self) -> "BriefConfirmation":
        unsupported = set(self.changed_fields) - set(BRIEF_FIELD_NAMES)
        if unsupported:
            raise ValueError("changed_fields contains unsupported fields")
        if self.status == "completed":
            missing = [
                field
                for field in REQUIRED_BRIEF_FIELDS
                if getattr(self.normalized_fields, field) is None
            ]
            if missing:
                raise ValueError(
                    "completed brief confirmation is missing: " + ", ".join(missing)
                )
        return self


class IntentConditionedDecision(VisualStrictModel):
    material_id: MaterialId = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bucket: Bucket
    relevance_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    candidate_capabilities: list[MaterialCapability] = Field(default_factory=list)
    capability_reasons: list[str] = Field(default_factory=list)
    director_function_candidates: list[DirectorFunction] = Field(default_factory=list)
    reasons: list[str] = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    user_confirmation_required: bool

    @model_validator(mode="after")
    def capabilities_are_unique_and_explained(self) -> "IntentConditionedDecision":
        if len(self.candidate_capabilities) != len(set(self.candidate_capabilities)):
            raise ValueError("candidate capabilities must be unique")
        if self.candidate_capabilities and not self.capability_reasons:
            raise ValueError("candidate capabilities require reasons")
        if len(self.director_function_candidates) != len(
            set(self.director_function_candidates)
        ):
            raise ValueError("assigned director functions must be unique")
        return self


class ProjectRoleAssignment(VisualStrictModel):
    director_function: DirectorFunction
    material_ids: list[MaterialId] = Field(min_length=1)
    assignment_score: float = Field(ge=0.0, le=1.0)
    selection_reason: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def assignment_is_project_grounded(self) -> "ProjectRoleAssignment":
        if len(self.material_ids) != len(set(self.material_ids)):
            raise ValueError("project role assignment materials must be unique")
        if self.director_function == "contrast" and len(self.material_ids) < 2:
            raise ValueError("contrast assignment requires at least two materials")
        if self.director_function in {"opening", "climax", "ending"} and len(
            self.material_ids
        ) != 1:
            raise ValueError(
                f"{self.director_function} assignment requires exactly one material"
            )
        if not any(ref.source_kind == "user_brief" for ref in self.evidence_refs):
            raise ValueError("project role assignment requires brief evidence")
        for material_id in self.material_ids:
            if not any(ref.material_id == material_id for ref in self.evidence_refs):
                raise ValueError(
                    "project role assignment requires evidence for every material"
                )
        return self


class IntentDecisionBatch(VisualStrictModel):
    schema_version: DirectorArtifactSchemaVersion = "0.2.0"
    status: StageStatus
    items: list[IntentConditionedDecision] = Field(default_factory=list)
    role_assignments: list[ProjectRoleAssignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def materials_are_unique(self) -> "IntentDecisionBatch":
        material_ids = [item.material_id for item in self.items]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("intent decisions contain duplicate materials")
        if self.schema_version == "0.3.0":
            functions = [row.director_function for row in self.role_assignments]
            if len(functions) != len(set(functions)):
                raise ValueError("project role functions must be unique")
            known = set(material_ids)
            for row in self.role_assignments:
                if not set(row.material_ids).issubset(known):
                    raise ValueError("project role references unknown material")
            if any(item.director_function_candidates for item in self.items):
                raise ValueError(
                    "V0.3 final director functions belong only to project assignments"
                )
        return self


class ProjectCoverage(VisualStrictModel):
    schema_version: DirectorArtifactSchemaVersion = "0.2.0"
    status: StageStatus
    content_distribution: dict[str, int] = Field(default_factory=dict)
    lighting_distribution: dict[str, int] = Field(default_factory=dict)
    people_distribution: dict[str, int] = Field(default_factory=dict)
    motion_distribution: dict[str, int] = Field(default_factory=dict)
    duplicate_groups: dict[str, list[MaterialId]] = Field(default_factory=dict)
    available_director_functions: list[DirectorFunction] = Field(default_factory=list)
    missing_director_functions: list[DirectorFunction] = Field(default_factory=list)
    uncertainty_summary: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class EvidenceBackedStatement(VisualStrictModel):
    text: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)


class TreatmentChapter(VisualStrictModel):
    chapter_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    director_functions: list[DirectorFunction] = Field(min_length=1)
    material_ids: list[MaterialId] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)


class DirectorTreatment(VisualStrictModel):
    schema_version: DirectorArtifactSchemaVersion = "0.2.0"
    status: StageStatus
    mode: Literal["automatic", "assisted", "deterministic"]
    logline: str = Field(min_length=1)
    narrative_spine: str = Field(min_length=1)
    chapters: list[TreatmentChapter] = Field(min_length=1)
    emotional_arc: list[EvidenceBackedStatement] = Field(min_length=1)
    pacing_strategy: str = Field(min_length=1)
    pacing_evidence_refs: list[EvidenceRef] = Field(min_length=1)
    core_materials: list[MaterialId] = Field(default_factory=list)
    candidate_materials: list[MaterialId] = Field(default_factory=list)
    redundant_materials: list[MaterialId] = Field(default_factory=list)
    reject_suggestions: list[MaterialId] = Field(default_factory=list)
    review_required: list[MaterialId] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    role_assignments: list[ProjectRoleAssignment] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    unsupported_inferences: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def memberships_are_disjoint_and_chapters_are_grounded(self) -> "DirectorTreatment":
        groups = (
            self.core_materials,
            self.candidate_materials,
            self.redundant_materials,
            self.reject_suggestions,
            self.review_required,
        )
        flattened = [material_id for group in groups for material_id in group]
        if len(flattened) != len(set(flattened)):
            raise ValueError("director treatment bucket memberships must be disjoint")
        known = set(flattened)
        chapter_materials = {
            material_id
            for chapter in self.chapters
            for material_id in chapter.material_ids
        }
        if not chapter_materials.issubset(known):
            raise ValueError("chapter references material outside treatment buckets")
        if self.schema_version == "0.3.0":
            assigned_materials = {
                material_id
                for assignment in self.role_assignments
                for material_id in assignment.material_ids
            }
            if not assigned_materials.issubset(known):
                raise ValueError("project role references material outside treatment buckets")
            functions = [row.director_function for row in self.role_assignments]
            if len(functions) != len(set(functions)):
                raise ValueError("director treatment role functions must be unique")
            for chapter in self.chapters:
                expected = {
                    material_id
                    for assignment in self.role_assignments
                    if assignment.director_function in chapter.director_functions
                    for material_id in assignment.material_ids
                }
                if set(chapter.material_ids) != expected:
                    raise ValueError(
                        "V0.3 chapter materials must come from project role assignments"
                    )
        return self


class EditorialOverride(VisualStrictModel):
    material_id: MaterialId = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    original_bucket: Bucket
    bucket_override: Bucket | None = None
    director_function_overrides: list[DirectorFunction] = Field(default_factory=list)
    force_include: bool = False
    force_exclude: bool = False
    user_note: str | None = None
    changed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def include_and_exclude_are_exclusive(self) -> "EditorialOverride":
        if self.force_include and self.force_exclude:
            raise ValueError("force_include and force_exclude cannot both be true")
        return self


class DirectorReview(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    treatment_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    status: StageStatus
    mode: Literal["automatic", "assisted"]
    overrides: list[EditorialOverride] = Field(default_factory=list)
    confirmed_at: str | None = None


MusicDifferenceAxis = Literal[
    "genre",
    "mood",
    "rhythm",
    "instrumentation",
    "drum_density",
    "energy_structure",
]


class MusicPromptParameters(VisualStrictModel):
    duration_seconds: int = Field(ge=30, le=180)
    genre: str = Field(min_length=1)
    mood: str = Field(min_length=1)
    bpm: int = Field(ge=40, le=240)
    instruments: list[str] = Field(min_length=1, max_length=4)
    drum_density: Literal["low", "medium", "high"]
    vocals: Literal["instrumental_only", "instrumental_preferred", "allowed"]
    energy_structure: str = Field(min_length=1)

    @field_validator("instruments")
    @classmethod
    def instruments_are_unique(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("prompt instruments must be unique and nonblank")
        return cleaned


class MusicGenerationPromptRecommendation(VisualStrictModel):
    direction_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    generation_prompt: str = Field(min_length=1, max_length=200)
    parameters: MusicPromptParameters
    difference_axes: list[MusicDifferenceAxis] = Field(min_length=2)
    fit_reason: str = Field(min_length=1)
    director_evidence_refs: list[EvidenceRef] = Field(min_length=1)

    @field_validator("difference_axes")
    @classmethod
    def axes_are_unique(cls, value: list[MusicDifferenceAxis]) -> list[MusicDifferenceAxis]:
        if len(value) != len(set(value)):
            raise ValueError("difference_axes must be unique")
        return value

    @model_validator(mode="after")
    def prompt_is_self_contained(self) -> "MusicGenerationPromptRecommendation":
        parameters = self.parameters
        required = [
            f"{parameters.duration_seconds}秒",
            f"{parameters.bpm} BPM",
            parameters.genre,
            parameters.mood,
            *parameters.instruments,
            parameters.energy_structure,
            {"low": "低密度鼓点", "medium": "中密度鼓点", "high": "高密度鼓点"}[
                parameters.drum_density
            ],
            {
                "instrumental_only": "纯器乐，无人声",
                "instrumental_preferred": "器乐为主，无清晰歌词",
                "allowed": "可用轻量无语义哼唱",
            }[parameters.vocals],
            "不模仿具体歌曲或艺人",
        ]
        missing = [token for token in required if token not in self.generation_prompt]
        if missing:
            raise ValueError("generation_prompt is missing required parameters")
        return self


class MusicGenerationPromptRecommendationBatch(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    status: StageStatus
    items: list[MusicGenerationPromptRecommendation] = Field(
        min_length=3, max_length=3
    )
    external_call_count: Literal[0] = 0

    @model_validator(mode="after")
    def directions_are_unique_and_materially_different(
        self,
    ) -> "MusicGenerationPromptRecommendationBatch":
        if len({item.direction_id for item in self.items}) != 3:
            raise ValueError("music prompt direction_ids must be unique")
        if len({item.generation_prompt for item in self.items}) != 3:
            raise ValueError("music generation prompts must be unique")
        axis_getters = {
            "genre": lambda item: item.parameters.genre,
            "mood": lambda item: item.parameters.mood,
            "rhythm": lambda item: item.parameters.bpm,
            "instrumentation": lambda item: tuple(item.parameters.instruments),
            "drum_density": lambda item: item.parameters.drum_density,
            "energy_structure": lambda item: item.parameters.energy_structure,
        }
        for index, left in enumerate(self.items):
            actual_axes = {
                axis
                for axis, getter in axis_getters.items()
                if any(getter(left) != getter(right) for right in self.items if right is not left)
            }
            if set(left.difference_axes) != actual_axes:
                raise ValueError("difference_axes do not match prompt parameters")
            for right in self.items[index + 1 :]:
                pairwise = sum(
                    getter(left) != getter(right) for getter in axis_getters.values()
                )
                if pairwise < 2:
                    raise ValueError("music prompts must differ on at least two axes")
        return self


class VisualReviewArtifact(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    status: StageStatus
    report_path: str = Field(min_length=1)
    source_artifact_hashes: dict[str, Sha256]
    external_call_count: Literal[0] = 0


class VisualProjectState(VisualStrictModel):
    schema_version: VisualSchemaVersion = "0.2.0"
    project_id: str
    status: StageStatus
    completion_mode: CompletionMode = "unresolved"
    current_stage: str
    artifact_paths: dict[str, str]
    completed_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    errors: list[ProviderIssue] = Field(default_factory=list)


class ProviderCapabilities(VisualStrictModel):
    provider_name: str = Field(min_length=1)
    local_only: bool
    supports_abstention: bool
    requires_model_weights: bool
    output_schema_version: VisualSchemaVersion = "0.2.0"


VISUAL_STAGE_MODELS: dict[str, type[VisualStrictModel]] = {
    "clip_observations": ClipObservationBatch,
    "intent_brief": NormalizedIntentDraft,
    "brief_confirmation": BriefConfirmation,
    "intent_decisions": IntentDecisionBatch,
    "project_coverage": ProjectCoverage,
    "director_treatment": DirectorTreatment,
    "director_review": DirectorReview,
    "music_style_recommendations": MusicGenerationPromptRecommendationBatch,
    "visual_review": VisualReviewArtifact,
}


def validate_visual_stage_artifact(stage: str, value: Any) -> dict[str, Any]:
    """Validate and normalize one V0.2 stage artifact."""

    try:
        model = VISUAL_STAGE_MODELS[stage]
    except KeyError as exc:
        raise ValueError(f"unknown visual stage: {stage}") from exc
    return model.model_validate(value).model_dump(mode="json")
