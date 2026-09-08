"""Evidence-bound audiovisual direction authored in the current conversation."""
from __future__ import annotations

import hashlib
import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from director.visual_schema import BriefConfirmation, DirectorTreatment, ProjectCoverage

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Vocals = Literal["instrumental_only", "instrumental_preferred", "allowed", "unspecified"]
IntentSource = Literal["not_recorded", "creative_proposal", "user_explicit"]


class CreativeStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CreativeAudioIntent(CreativeStrictModel):
    """Explicit global audio intent; missing fields must remain unknown/default."""

    source: IntentSource = "not_recorded"
    hook_policy: Literal["conditional", "disabled"] | None = None
    added_sfx_policy: Literal["conditional", "disabled"] | None = None
    original_sound_priority: Literal["normal", "preserve", "foreground"] | None = None
    silence_priority: Literal["normal", "preserve", "required"] | None = None
    reason: Text | None = None

    @model_validator(mode="after")
    def intent_has_provenance(self) -> "CreativeAudioIntent":
        decisions = (
            self.hook_policy,
            self.added_sfx_policy,
            self.original_sound_priority,
            self.silence_priority,
        )
        if self.source == "not_recorded" and any(value is not None for value in decisions):
            raise ValueError("audio intent decisions require explicit provenance")
        if self.source != "not_recorded" and (not any(value is not None for value in decisions) or self.reason is None):
            raise ValueError("recorded audio intent requires a decision and reason")
        if self.silence_priority == "required" and self.original_sound_priority in {"preserve", "foreground"}:
            raise ValueError("required silence conflicts with preserved original sound")
        return self


class SectionAudioIntent(CreativeStrictModel):
    """Section-specific intent. Explicit user choices outrank creative proposals."""

    source: IntentSource = "not_recorded"
    added_sfx_policy: Literal["conditional", "disabled"] | None = None
    original_sound_priority: Literal["normal", "preserve", "foreground"] | None = None
    silence_priority: Literal["normal", "preserve", "required"] | None = None
    reason: Text | None = None

    @model_validator(mode="after")
    def intent_has_provenance(self) -> "SectionAudioIntent":
        decisions = (
            self.added_sfx_policy,
            self.original_sound_priority,
            self.silence_priority,
        )
        if self.source == "not_recorded" and any(value is not None for value in decisions):
            raise ValueError("section audio intent decisions require explicit provenance")
        if self.source != "not_recorded" and (not any(value is not None for value in decisions) or self.reason is None):
            raise ValueError("recorded section audio intent requires a decision and reason")
        if self.silence_priority == "required" and self.original_sound_priority in {"preserve", "foreground"}:
            raise ValueError("required silence conflicts with preserved original sound")
        return self


class ReferenceObservation(CreativeStrictModel):
    observation_id: Text
    time: float = Field(ge=0)
    description: Text
    evidence_path: Text


class ReferenceEntry(CreativeStrictModel):
    reference_id: Text
    title: Text
    url: Text
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    visual_verified: Literal[True]
    audio_listened: bool
    audio_notes: Text
    applicability: Text
    observations: list[ReferenceObservation] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_in_range(self):
        if self.end <= self.start:
            raise ValueError("reference end must follow start")
        ids = [o.observation_id for o in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("reference observation IDs must be unique")
        if any(not self.start <= o.time <= self.end for o in self.observations):
            raise ValueError("observation outside reference range")
        return self


class ReferenceLibrary(CreativeStrictModel):
    schema_version: Literal["1.0.0"]
    references: list[ReferenceEntry]


class SelectedReference(CreativeStrictModel):
    reference_id: Text
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    observation_ids: list[Text] = Field(min_length=1)
    fit_reason: Text


class CreativeSection(CreativeStrictModel):
    section_id: Text
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    narrative_task: Text
    material_ids: list[Text]
    material_gaps: list[Text]
    visual_plan: Text
    music_change: Text
    sfx_plan: list[Text]
    packaging: list[Text]
    reference_ids: list[Text]
    climax: bool = False
    audio_intent: SectionAudioIntent = Field(default_factory=SectionAudioIntent)


class CreativeMusicPrompt(CreativeStrictModel):
    direction_id: Text
    title: Text
    generation_prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    fit_reason: Text
    variation: Text
    section_ids: list[Text] = Field(min_length=1)


class CreativeDirection(CreativeStrictModel):
    schema_version: Literal["1.0.0"]
    kind: Literal["creative_direction"]
    source_hashes: dict[Text, Hash]
    target_duration_seconds: float = Field(gt=0)
    location: Text
    orientation: Literal["landscape", "portrait"]
    user_preferences: list[Text]
    audio_intent: CreativeAudioIntent = Field(default_factory=CreativeAudioIntent)
    reference_policy: Literal["default_library", "custom", "brief_only"]
    custom_references: list[ReferenceEntry] = Field(default_factory=list)
    selected_references: list[SelectedReference]
    sections: list[CreativeSection] = Field(min_length=1)
    music_brief: Text
    vocals: Vocals
    music_prompts: list[CreativeMusicPrompt] = Field(min_length=3, max_length=3)


def _library_bytes() -> bytes:
    return files("director").joinpath("references/defaults.json").read_bytes()


def resolve_reference_evidence(evidence_path: str) -> Path:
    """Resolve an evidence path to a concrete filesystem Path.

    Supports explicit environment variables (TRAVEL_DIRECTOR_REFERENCE_ROOT,
    TRAVEL_DIRECTOR_WORKSPACE), package-internal resources, and absolute paths.
    """
    raw = Path(evidence_path)
    if raw.is_absolute() and raw.exists():
        return raw

    custom_root = os.environ.get("TRAVEL_DIRECTOR_REFERENCE_ROOT")
    if custom_root:
        candidate = Path(custom_root) / evidence_path
        if candidate.exists():
            return candidate.resolve()

    workspace = os.environ.get("TRAVEL_DIRECTOR_WORKSPACE")
    if workspace:
        ws_path = Path(workspace)
        for candidate in (
            ws_path / "director" / "references" / evidence_path,
            ws_path / "local-media-scanner" / "director" / "references" / evidence_path,
            ws_path / evidence_path,
        ):
            if candidate.exists():
                return candidate.resolve()

    try:
        pkg_ref = files("director").joinpath("references").joinpath(evidence_path)
        pkg_path = Path(str(pkg_ref))
        if pkg_path.exists():
            return pkg_path.resolve()
    except (TypeError, FileNotFoundError):
        pass

    file_ref = Path(__file__).resolve().parent / "references" / evidence_path
    if file_ref.exists():
        return file_ref.resolve()

    return file_ref


def load_reference_library(*, resolve_paths: bool = False) -> dict:
    """Load fresh validated package data, independent of the process directory.

    When resolve_paths is True, observation evidence paths are resolved to absolute
    paths on the local filesystem.
    """
    data = ReferenceLibrary.model_validate(json.loads(_library_bytes())).model_dump(mode="json")
    if resolve_paths:
        for ref in data.get("references", []):
            for obs in ref.get("observations", []):
                obs["evidence_path"] = str(resolve_reference_evidence(obs["evidence_path"]))
    return data


def reference_library_sha256() -> str:
    return hashlib.sha256(_library_bytes()).hexdigest()


def validate_creative_direction(payload: dict, *, source_hashes: dict[str, str],
                                brief: BriefConfirmation, treatment: DirectorTreatment,
                                coverage: ProjectCoverage, material_ids: set[str]) -> CreativeDirection:
    direction = CreativeDirection.model_validate(payload)
    fields = brief.normalized_fields
    if brief.status != "completed":
        raise ValueError("creative direction requires confirmed brief")
    if treatment.status != "completed" or coverage.status != "completed":
        raise ValueError("creative direction requires completed treatment and coverage")
    if treatment.unsupported_inferences:
        raise ValueError("creative direction cannot inherit unsupported treatment inferences")
    if direction.source_hashes != source_hashes or "reference_library" not in source_hashes:
        raise ValueError("source hashes must exactly match current inputs including reference_library")
    if (direction.target_duration_seconds != fields.target_duration_seconds
            or direction.location != fields.location or direction.orientation != fields.orientation):
        raise ValueError("creative direction must retain confirmed duration, location and orientation")
    if fields.vocals is not None and direction.vocals != fields.vocals:
        raise ValueError("creative direction must retain confirmed vocals")
    library = {r["reference_id"]: ReferenceEntry.model_validate(r)
               for r in load_reference_library()["references"]}
    custom_ids = set()
    for reference in direction.custom_references:
        if reference.reference_id in library:
            raise ValueError("custom reference cannot overwrite an existing reference ID")
        for original in library.values():
            if urlsplit(reference.url).path.rstrip('/') == urlsplit(original.url).path.rstrip('/'):
                if reference.start < original.start or reference.end > original.end:
                    raise ValueError("custom alias cannot expand a default reference range")
        custom_ids.add(reference.reference_id)
        library[reference.reference_id] = reference
    selected_ids = set()
    for selection in direction.selected_references:
        reference = library.get(selection.reference_id)
        if reference is None:
            raise ValueError("selected reference is unknown")
        if not reference.start <= selection.start < selection.end <= reference.end:
            raise ValueError("selection outside reference bounds")
        observations = {o.observation_id: o for o in reference.observations}
        for observation_id in selection.observation_ids:
            observation = observations.get(observation_id)
            if observation is None or not selection.start <= observation.time <= selection.end:
                raise ValueError("selected observation must belong to reference and selected range")
        selected_ids.add(selection.reference_id)
    if direction.reference_policy == "custom" and not selected_ids & custom_ids:
        raise ValueError("custom policy requires a custom reference selection")
    if direction.reference_policy == "default_library" and not selected_ids:
        raise ValueError("default library policy requires reference selections")
    if direction.reference_policy == "brief_only" and not direction.user_preferences:
        raise ValueError("brief_only requires user preferences explaining the choice")
    treatment_ids = set(treatment.core_materials + treatment.candidate_materials
                        + treatment.redundant_materials + treatment.review_required)
    allowed_ids = (material_ids & treatment_ids) - set(treatment.reject_suggestions)
    section_ids = set()
    previous_end = 0.0
    for section in direction.sections:
        if section.section_id in section_ids:
            raise ValueError("section IDs must be unique")
        section_ids.add(section.section_id)
        if section.end <= section.start or abs(section.start - previous_end) > 1e-6:
            raise ValueError("sections must be contiguous and nonoverlapping from zero")
        previous_end = section.end
        if not set(section.material_ids).issubset(allowed_ids):
            raise ValueError("section contains unknown or rejected treatment material")
        if not section.material_ids and not section.material_gaps:
            raise ValueError("section without material requires explicit material gaps")
        if section.climax and "climax" in coverage.missing_director_functions and not section.material_gaps:
            raise ValueError("missing climax coverage requires explicit section gap")
        if not set(section.reference_ids).issubset(selected_ids):
            raise ValueError("section uses unselected reference")
    if abs(previous_end - direction.target_duration_seconds) > 1e-6:
        raise ValueError("sections must cover full target duration")
    for attribute in ("direction_id", "generation_prompt"):
        values = [getattr(prompt, attribute) for prompt in direction.music_prompts]
        if len(values) != len(set(values)):
            raise ValueError("music prompt IDs and text must be unique")
    for prompt in direction.music_prompts:
        if not set(prompt.section_ids).issubset(section_ids):
            raise ValueError("music prompt references unknown section")
    return direction
