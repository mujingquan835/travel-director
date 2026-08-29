"""Provider-neutral authorization contract for external music generation."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from director.schema import GeneratedMusicAsset, MusicBlueprint, StrictModel


class GenerationAuthorization(StrictModel):
    provider: str = Field(min_length=1)
    max_calls: int = Field(ge=0)
    approved_by_user: bool

    @classmethod
    def denied(cls, provider: str) -> "GenerationAuthorization":
        return cls(provider=provider, max_calls=0, approved_by_user=False)


class MusicGenerationProvider(Protocol):
    def generate(
        self,
        blueprint: MusicBlueprint,
        authorization: GenerationAuthorization,
    ) -> GeneratedMusicAsset: ...
