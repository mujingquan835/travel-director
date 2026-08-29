"""Parser for one explicitly captured, currently visible catalog page."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from director.schema import (
    CatalogSearchResult,
    MusicCandidate,
    MusicSearchBrief,
    ProviderError,
)


PROVIDER_NAME = "quduoduo_browser"
BLOCKING_STATES = {"login_required", "captcha", "waf"}
ALLOWED_CARD_FIELDS = {
    "candidate_id",
    "title",
    "visible_tags",
    "bpm",
    "duration_seconds",
    "author",
    "label",
    "detail_url",
    "preview_url",
}


def _blocked(code: str, message: str) -> CatalogSearchResult:
    return CatalogSearchResult(
        provider=PROVIDER_NAME,
        status="blocked",
        capture_scope="current_visible_page",
        candidates=[],
        downloaded_audio_count=0,
        errors=[ProviderError(stage="catalog", code=code, message=message)],
    )


def parse_visible_results(
    payload: dict[str, Any], brief: MusicSearchBrief
) -> CatalogSearchResult:
    """Normalize allowed visible fields from exactly one user-triggered page."""

    del brief
    state = payload.get("page_state")
    if state in BLOCKING_STATES:
        return _blocked(str(state), f"catalog page is blocked by {state}")
    if state != "results":
        return _blocked("unsupported_structure", "page_state is not results")
    if payload.get("page_count", 1) != 1 or "pages" in payload:
        return _blocked("unsupported_structure", "capture must contain one visible page")
    if not isinstance(payload.get("page_url"), str) or not isinstance(
        payload.get("captured_at"), str
    ):
        return _blocked(
            "unsupported_structure", "page_url and captured_at are required"
        )
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return _blocked("unsupported_structure", "cards must be a list")

    candidates: list[MusicCandidate] = []
    try:
        for raw in cards[:5]:
            if not isinstance(raw, dict):
                raise ValueError("each visible card must be an object")
            normalized = {
                key: raw[key] for key in ALLOWED_CARD_FIELDS if key in raw
            }
            candidates.append(
                MusicCandidate(provider=PROVIDER_NAME, **normalized)
            )
    except (TypeError, ValueError, ValidationError) as exc:
        return _blocked("unsupported_structure", str(exc))

    return CatalogSearchResult(
        provider=PROVIDER_NAME,
        status="completed",
        capture_scope="current_visible_page",
        candidates=candidates,
        downloaded_audio_count=0,
    )
