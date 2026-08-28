"""Offline fixture catalog provider used by tests and local demos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from director.schema import CatalogSearchResult, MusicCandidate, MusicSearchBrief


class FixtureCatalogProvider:
    provider_name = "fixture"

    def __init__(self, source: Path | dict[str, Any]) -> None:
        self.source = source

    def _payload(self) -> dict[str, Any]:
        if isinstance(self.source, Path):
            return json.loads(self.source.read_text(encoding="utf-8"))
        return self.source

    def search(self, brief: MusicSearchBrief) -> CatalogSearchResult:
        del brief
        payload = self._payload()
        provider = str(payload.get("provider", self.provider_name))
        candidates = [
            MusicCandidate(provider=provider, **row)
            for row in payload.get("candidates", [])[:5]
        ]
        return CatalogSearchResult(
            provider=provider,
            status="completed",
            capture_scope="fixture",
            candidates=candidates,
            downloaded_audio_count=0,
        )
