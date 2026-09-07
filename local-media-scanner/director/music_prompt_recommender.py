"""Compatibility entry point for the retired fixed-template prompt generator."""

from __future__ import annotations

from director.visual_schema import (
    BriefConfirmation,
    DirectorTreatment,
    MusicGenerationPromptRecommendationBatch,
    ProjectCoverage,
)

CREATIVE_DIRECTION_REQUIRED = (
    "Fixed-template music recommendations have been retired. "
    "Use travel-director run to obtain needs_creative_direction; "
    "select reference evidence and plan audiovisual sections in the current session, "
    "then submit exactly three music prompts with run --creative-response."
)


def recommend_music_prompts(
    treatment: DirectorTreatment,
    brief: BriefConfirmation,
    coverage: ProjectCoverage,
) -> MusicGenerationPromptRecommendationBatch:
    """Reject legacy generation; historical recommendation artifacts remain readable."""
    raise ValueError(CREATIVE_DIRECTION_REQUIRED)
