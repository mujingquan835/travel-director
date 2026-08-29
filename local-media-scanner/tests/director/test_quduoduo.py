from __future__ import annotations

import json
from pathlib import Path

import pytest

from director.catalog.quduoduo import parse_visible_results
from director.schema import MusicSearchBrief, MusicSearchEvidence


FIXTURE = Path(__file__).parent / "fixtures" / "quduoduo-visible-page.json"


@pytest.fixture
def brief() -> MusicSearchBrief:
    return MusicSearchBrief(
        keywords=["开封", "城市漫游", "明亮"],
        genres=["轻电子", "流行器乐"],
        moods=["探索"],
        bpm_min=105,
        bpm_max=125,
        instrument_preferences=["木吉他"],
        vocals="instrumental_preferred",
        target_duration_seconds=60,
        evidence=MusicSearchEvidence(source_scanner_run_id="scanner-3", rules=[]),
    )


def test_visible_page_parser_keeps_only_allowed_fields(brief: MusicSearchBrief) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    result = parse_visible_results(payload, brief)

    assert result.status == "completed"
    assert result.capture_scope == "current_visible_page"
    assert len(result.candidates) == 5
    assert result.downloaded_audio_count == 0
    assert all(candidate.provider_payload is None for candidate in result.candidates)
    assert result.candidates[0].model_dump() == {
        "schema_version": "0.1.0",
        "provider": "quduoduo_browser",
        "candidate_id": "visible-01",
        "title": "可见候选一",
        "visible_tags": ["轻电子", "明亮"],
        "bpm": 116,
        "duration_seconds": 60.0,
        "author": "页面可见作者",
        "label": "页面可见厂牌",
        "detail_url": "https://example.invalid/detail/visible-01",
        "preview_url": "https://example.invalid/preview/visible-01",
        "provider_payload": None,
    }


@pytest.mark.parametrize("state", ["login_required", "captcha", "waf"])
def test_access_challenge_blocks_without_fake_candidates(
    brief: MusicSearchBrief, state: str
) -> None:
    result = parse_visible_results(
        {
            "page_url": "https://example.invalid/search",
            "captured_at": "2026-08-30T09:00:00+08:00",
            "page_state": state,
            "cards": [],
        },
        brief,
    )

    assert result.status == "blocked"
    assert result.candidates == []
    assert result.errors[0].code == state


def test_unsupported_structure_blocks_instead_of_guessing(
    brief: MusicSearchBrief,
) -> None:
    result = parse_visible_results(
        {
            "page_url": "https://example.invalid/search",
            "captured_at": "2026-08-30T09:00:00+08:00",
            "page_state": "results",
            "cards": "not-a-list",
        },
        brief,
    )

    assert result.status == "blocked"
    assert result.candidates == []
    assert result.errors[0].code == "unsupported_structure"
