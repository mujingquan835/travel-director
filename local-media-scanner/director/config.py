"""Versioned local Director configuration."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DirectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_internal_candidates: int = Field(default=5, ge=1, le=5)
    displayed_directions: int = Field(default=3, ge=1, le=3)
    min_clip_seconds: float = Field(default=0.8, gt=0.0)
    max_clip_seconds: float = Field(default=6.0, gt=0.0)

    @model_validator(mode="after")
    def clip_bounds_are_ordered(self) -> "DirectorConfig":
        if self.min_clip_seconds > self.max_clip_seconds:
            raise ValueError("min_clip_seconds must not exceed max_clip_seconds")
        if self.displayed_directions > self.max_internal_candidates:
            raise ValueError("displayed_directions must not exceed max_internal_candidates")
        return self
