"""Data contracts and schemas for subjective audiovisual listening and viewing review."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from director.shot_review_schema import ReviewModel


class SilentPictureReview(ReviewModel):
    """Review of picture rhythm, temporal continuity, and event clarity without audio."""

    temporal_flow: str = Field(min_length=5, max_length=500)
    event_clarity: str = Field(min_length=5, max_length=500)
    cut_connection_validity: str = Field(min_length=5, max_length=500)
    verdict: Literal["acceptable", "needs_revision"]
    notes: str = Field(min_length=10, max_length=1000)


class AudioOnlyReview(ReviewModel):
    """Blind review of audio tracks without visual cues."""

    ambient_continuity: str = Field(min_length=5, max_length=500)
    foley_anchor_sync: str = Field(min_length=5, max_length=500)
    dynamic_range_and_planes: str = Field(min_length=5, max_length=500)
    verdict: Literal["acceptable", "needs_revision"]
    notes: str = Field(min_length=10, max_length=1000)


class CombinedReview(ReviewModel):
    """Holistic review of picture and audio playing together."""

    foreground_competition: str = Field(min_length=5, max_length=500)
    rhythm_breathing: str = Field(min_length=5, max_length=500)
    verdict: Literal["acceptable", "needs_revision"]
    notes: str = Field(min_length=10, max_length=1000)


class VariantComparison(ReviewModel):
    """Evaluation entry for A/B/C/D sample comparison matrix."""

    variant_id: Literal["A_baseline", "B_picture_revised", "C_sound_revised", "D_music_swapped"]
    description: str = Field(min_length=5, max_length=500)
    findings: str = Field(min_length=5, max_length=1000)
    verdict: Literal["baseline", "improved", "degraded", "inconclusive"]


class AudiovisualReviewReport(ReviewModel):
    """Complete subjective audiovisual listening and viewing review report."""

    reviewer: str = Field(min_length=1, max_length=100)
    listening_environment: str = Field(min_length=2, max_length=100)
    reviewed_at: datetime
    silent_picture: SilentPictureReview
    audio_only: AudioOnlyReview
    combined: CombinedReview
    comparisons: list[VariantComparison] | None = None
    overall_verdict: Literal["accepted", "needs_revision"]
    revision_recommendations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_verdict_consistency(self) -> "AudiovisualReviewReport":
        if self.reviewed_at.tzinfo is None:
            raise ValueError("audiovisual review report requires a timezone-aware reviewed_at timestamp")

        sub_verdicts = [
            self.silent_picture.verdict,
            self.audio_only.verdict,
            self.combined.verdict,
        ]
        if self.overall_verdict == "accepted" and any(v == "needs_revision" for v in sub_verdicts):
            raise ValueError("cannot declare overall_verdict='accepted' when any sub-review needs revision")

        if self.overall_verdict == "needs_revision" and not self.revision_recommendations:
            raise ValueError("overall_verdict='needs_revision' requires at least one revision recommendation")

        return self
