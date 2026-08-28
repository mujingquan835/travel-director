from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from director.catalog.base import MusicCatalogProvider
from director.catalog.fixture import FixtureCatalogProvider
from director.cli import app
from director.music_directions import rank_directions
from director.schema import MusicSearchBrief, MusicSearchEvidence


FIXTURE = Path(__file__).parents[2] / "prototype" / "fixtures" / "catalog-visible-results.json"


def search_brief() -> MusicSearchBrief:
    return MusicSearchBrief(
        keywords=["开封", "城市漫游", "探索", "明亮"],
        genres=["轻电子", "流行器乐"],
        moods=["探索", "明亮"],
        bpm_min=105,
        bpm_max=125,
        instrument_preferences=["木吉他", "电子鼓"],
        vocals="instrumental_preferred",
        target_duration_seconds=60,
        evidence=MusicSearchEvidence(source_scanner_run_id="scanner-3", rules=[]),
    )


def test_fixture_provider_implements_catalog_protocol_and_caps_results() -> None:
    provider: MusicCatalogProvider = FixtureCatalogProvider(FIXTURE)

    result = provider.search(search_brief())

    assert result.status == "completed"
    assert result.capture_scope == "fixture"
    assert len(result.candidates) == 5
    assert result.downloaded_audio_count == 0
    assert all(candidate.provider_payload is None for candidate in result.candidates)


def test_ranker_returns_three_explainable_directions() -> None:
    result = FixtureCatalogProvider(FIXTURE).search(search_brief())

    directions = rank_directions(result, search_brief(), limit=3)

    assert len(directions) == 3
    assert directions[0].candidate_id == "fixture-01"
    assert all(direction.preview_url.startswith("https://example.invalid/") for direction in directions)
    assert all(
        set(direction.reasons) == {"bpm_fit", "duration_fit", "tag_overlap", "instrument_overlap"}
        for direction in directions
    )


def test_catalog_fixture_cli_writes_only_local_json(tmp_path: Path) -> None:
    brief_path = tmp_path / "search-brief.json"
    brief_path.write_text(search_brief().model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "directions.json"

    result = CliRunner().invoke(
        app,
        [
            "catalog-fixture",
            "--brief",
            str(brief_path),
            "--fixture",
            str(FIXTURE),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload) == 3
    assert payload[0]["candidate_id"] == "fixture-01"
