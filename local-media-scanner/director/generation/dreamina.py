"""Dreamina capability parser and fail-closed generation gate."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from director.generation.base import GenerationAuthorization
from director.schema import GeneratedMusicAsset, MusicBlueprint, ProviderError


GenerationRunner = Callable[
    [MusicBlueprint, str, GenerationAuthorization], GeneratedMusicAsset
]


@dataclass(frozen=True)
class DreaminaCapabilities:
    music_generation: bool
    music_command: str | None = None

    @classmethod
    def from_help(cls, text: str) -> "DreaminaCapabilities":
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().lower().split())
            match = re.search(r"\b(music|audio)\s+(generate|create)\b", line)
            if match:
                return cls(
                    music_generation=True,
                    music_command=f"{match.group(1)} {match.group(2)}",
                )
        return cls(music_generation=False)


class DreaminaMusicProvider:
    provider_name = "dreamina"

    def __init__(
        self,
        *,
        capabilities: DreaminaCapabilities,
        runner: GenerationRunner,
    ) -> None:
        self.capabilities = capabilities
        self.runner = runner

    def generate(
        self,
        blueprint: MusicBlueprint,
        authorization: GenerationAuthorization,
    ) -> GeneratedMusicAsset:
        blueprint_hash = hashlib.sha256(
            blueprint.model_dump_json().encode("utf-8")
        ).hexdigest()

        if (
            not authorization.approved_by_user
            or authorization.provider != self.provider_name
            or authorization.max_calls != 1
        ):
            return self._blocked(
                blueprint_hash,
                code="not_authorized",
                message="Dreamina music generation requires explicit one-call authorization.",
            )

        if not self.capabilities.music_generation or not self.capabilities.music_command:
            return self._blocked(
                blueprint_hash,
                code="unsupported_capability",
                message="Installed Dreamina help does not expose a music generation command.",
            )

        return self.runner(
            blueprint,
            self.capabilities.music_command,
            authorization,
        )

    def _blocked(
        self,
        blueprint_hash: str,
        *,
        code: str,
        message: str,
    ) -> GeneratedMusicAsset:
        return GeneratedMusicAsset(
            status="blocked",
            provider=self.provider_name,
            blueprint_hash=blueprint_hash,
            errors=[
                ProviderError(
                    stage="music_generation",
                    code=code,
                    message=message,
                )
            ],
        )
