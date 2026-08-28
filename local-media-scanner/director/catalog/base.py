"""Replaceable music catalog provider boundary."""

from typing import Protocol

from director.schema import CatalogSearchResult, MusicSearchBrief


class MusicCatalogProvider(Protocol):
    provider_name: str

    def search(self, brief: MusicSearchBrief) -> CatalogSearchResult:
        """Return normalized metadata without downloading preview audio."""


__all__ = ["MusicCatalogProvider"]
