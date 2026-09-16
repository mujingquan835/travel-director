"""Data contracts and schemas for evidence-backed sound event design."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from director.shot_review_schema import ReviewModel


class SoundListeningRecord(ReviewModel):
    listening_id: str = Field(min_length=1, max_length=80)
    source_path: Path
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    reviewer: str = Field(min_length=1, max_length=100)
    method: Literal["direct_listening", "context_mix_listening", "user_report"]
    note: str = Field(min_length=1, max_length=1000)
    reviewed_at: datetime

    @model_validator(mode="after")
    def validate_record(self) -> "SoundListeningRecord":
        if self.source_out <= self.source_in:
            raise ValueError("sound listening record requires a positive source range")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("sound listening record requires a timezone-aware reviewed_at date")
        if not self.source_path.is_absolute():
            raise ValueError("sound listening record requires an absolute source_path")
        return self


class GainPoint(ReviewModel):
    offset_seconds: float = Field(ge=0)
    gain: float = Field(ge=0, le=4)


class GainEnvelope(ReviewModel):
    fade_in_seconds: float = Field(default=0.0, ge=0)
    fade_out_seconds: float = Field(default=0.0, ge=0)
    base_gain: float = Field(default=1.0, ge=0, le=4)
    points: list[GainPoint] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_points(self) -> "GainEnvelope":
        offsets = [p.offset_seconds for p in self.points]
        if offsets != sorted(offsets):
            raise ValueError("gain envelope points must be in ascending offset order")
        return self


class SoundEventVisualAnchor(ReviewModel):
    event_time: float = Field(ge=0)
    anchor_type: Literal["shot_action", "cut_transition", "environment_presence"]
    description: str = Field(min_length=1, max_length=500)
    shot_id: str | None = Field(default=None, max_length=80)
    action_field: Literal["action_start", "action_accent", "action_end"] | None = None
    uncertainty_seconds: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_anchor(self) -> "SoundEventVisualAnchor":
        if self.anchor_type == "shot_action":
            if self.shot_id is None or self.action_field is None:
                raise ValueError("shot_action anchor requires shot_id and action_field")
        elif self.action_field is not None:
            raise ValueError("action_field can only be specified for shot_action anchors")
        return self


class SoundSourcePlacement(ReviewModel):
    source_path: Path | None = None
    sound_type: Literal["location_recorded", "library_sfx", "missing_gap"]
    source_anchor_time: float | None = Field(default=None, ge=0)
    pre_roll: float = Field(default=0.0, ge=0)
    source_in: float = Field(default=0.0, ge=0)
    duration: float = Field(default=0.0, ge=0)
    tail_policy: Literal["ring_out", "cut_at_boundary", "fade_out"] = "ring_out"

    @model_validator(mode="after")
    def validate_placement(self) -> "SoundSourcePlacement":
        if self.sound_type == "missing_gap":
            if self.source_path is not None:
                raise ValueError("missing_gap sound cue must not provide a source_path")
            if self.duration != 0.0:
                raise ValueError("missing_gap sound cue duration must be 0.0")
        else:
            if self.source_path is None or not self.source_path.is_absolute():
                raise ValueError("playable sound cue requires an absolute source_path")
            if self.duration <= 0:
                raise ValueError("playable sound cue requires a positive duration")
            if self.source_anchor_time is None:
                raise ValueError("playable sound cue requires source_anchor_time")
            if self.source_anchor_time < self.source_in - 1e-6:
                raise ValueError("source_anchor_time cannot precede source_in")
            if self.source_anchor_time > self.source_in + self.duration + 1e-6:
                raise ValueError("source_anchor_time cannot exceed source_in + duration")
            expected_pre_roll = self.source_anchor_time - self.source_in
            if abs(expected_pre_roll - self.pre_roll) > 1e-6:
                raise ValueError(
                    f"pre_roll mismatch: source_anchor_time ({self.source_anchor_time}) - "
                    f"source_in ({self.source_in}) != pre_roll ({self.pre_roll})"
                )
        return self


class SoundCue(ReviewModel):
    cue_id: str = Field(min_length=1, max_length=80)
    role: Literal["location_ambient", "action_foley", "transition_accent"]
    auditory_plane: Literal["foreground", "midground", "background"]
    music_relation: Literal["parallel", "music_ducked", "music_silent", "accent_sync"]
    visual_anchor: SoundEventVisualAnchor
    source: SoundSourcePlacement
    envelope: GainEnvelope = Field(default_factory=GainEnvelope)
    selection_reason: str = Field(min_length=1, max_length=500)
    listening_status: Literal["not_listened", "source_listened", "context_reviewed"] = "not_listened"
    listening_id: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_cue(self) -> "SoundCue":
        if self.source.sound_type == "missing_gap":
            if self.listening_status != "not_listened" or self.listening_id is not None:
                raise ValueError("missing_gap cue cannot claim listening status or listening_id")
        elif self.listening_status in ("source_listened", "context_reviewed"):
            if self.listening_id is None:
                raise ValueError("reviewed sound cue requires a valid listening_id")
        elif self.listening_id is not None:
            raise ValueError("not_listened sound cue must not attach a listening_id")
        return self


class SoundDesignPlan(ReviewModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    base_decision: Path
    revision_reason: str = Field(min_length=1, max_length=1000)
    cues: list[SoundCue] = Field(min_length=1, max_length=100)
    listening: list[SoundListeningRecord] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_plan(self) -> "SoundDesignPlan":
        if not self.base_decision.is_absolute():
            raise ValueError("base_decision must be an absolute path")
        cue_ids = [cue.cue_id for cue in self.cues]
        if len(cue_ids) != len(set(cue_ids)):
            raise ValueError("duplicate cue_id in sound design plan")
        listening_ids = [r.listening_id for r in self.listening]
        if len(listening_ids) != len(set(listening_ids)):
            raise ValueError("duplicate listening_id in sound design plan")
        return self


class SoundDesignBinding(ReviewModel):
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
