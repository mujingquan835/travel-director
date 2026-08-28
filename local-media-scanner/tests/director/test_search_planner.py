from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from director.cli import app
from director.schema import MaterialLibraryProfile, UserCreativeBrief
from director.search_planner import build_music_search_brief
from scanner.schema import ScannerResult, TestManifest as ScannerManifest


def profile() -> MaterialLibraryProfile:
    return MaterialLibraryProfile(
        source_scanner_run_id="scanner-30",
        manifest_sha256="a" * 64,
        materials=[],
        total_source_duration_seconds=476.33,
        usable_material_count=30,
        scene_distribution={"theme_park": 12, "city": 8, "other": 10},
        motion_distribution={"high": 8, "medium": 14, "low": 8},
        orientation_distribution={"portrait": 24, "landscape": 6},
        processing_time_estimate_seconds=None,
    )


def brief() -> UserCreativeBrief:
    return UserCreativeBrief(
        location="开封",
        travel_type="城市漫游",
        target_duration_seconds=60,
        orientation="portrait",
        style="明亮",
        mood="探索",
        rhythm="medium",
        instrument_preferences=["木吉他", "电子鼓"],
    )


def test_search_brief_combines_user_and_material_evidence() -> None:
    result = build_music_search_brief(profile(), brief())

    assert result.target_duration_seconds == 60
    assert (result.bpm_min, result.bpm_max) == (105, 125)
    assert "开封" in result.keywords
    assert "游乐" in result.keywords
    assert result.instrument_preferences == ["木吉他", "电子鼓"]
    assert result.evidence.source_scanner_run_id == "scanner-30"
    assert len(result.keywords) <= 8


def test_search_brief_does_not_claim_unmeasured_catalog_filters() -> None:
    result = build_music_search_brief(profile(), brief())

    assert all("曲多多" not in rule for rule in result.evidence.rules)
    assert result.vocals == "instrumental_preferred"


def test_plan_search_cli_serializes_local_result(tmp_path: Path) -> None:
    scanner_result = tmp_path / "scanner-result.json"
    scanner_result.write_text(
        ScannerResult(
            run_id="empty-local-run",
            requested_device="none",
            actual_device="none",
            items=[],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        ScannerManifest(
            input_root=str(tmp_path),
            entries=[],
            total_duration_seconds=0,
            total_size_bytes=0,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(brief().model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "search-brief.json"

    result = CliRunner().invoke(
        app,
        [
            "plan-search",
            "--scanner-result",
            str(scanner_result),
            "--scanner-manifest",
            str(manifest),
            "--brief",
            str(brief_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["evidence"]["source_scanner_run_id"] == "empty-local-run"
    assert payload["target_duration_seconds"] == 60
