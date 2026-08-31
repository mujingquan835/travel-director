from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from director.brief_interpreter import (
    DeterministicBriefInterpreter,
    render_brief_review,
    validate_brief_confirmation,
)
from director.cli import app
from director.schema import UserCreativeBrief
from director.visual_schema import BriefConfirmation, RawCreativeBrief


def complete_description() -> str:
    return (
        "在开封拍一条60秒竖屏城市漫游短片，"
        "风格明亮、纪实，情绪温暖，快节奏，纯音乐，偏好木吉他和钢琴。"
    )


def test_deterministic_normalizer_extracts_explicit_fields_with_sources() -> None:
    draft = DeterministicBriefInterpreter().normalize(
        RawCreativeBrief(raw_description=complete_description())
    )

    fields = draft.normalized_fields
    assert draft.status == "completed"
    assert fields.location == "开封"
    assert fields.travel_type == "城市漫游"
    assert fields.target_duration_seconds == 60
    assert fields.orientation == "portrait"
    assert fields.style == "明亮、纪实"
    assert fields.mood == "温暖"
    assert fields.rhythm == "high"
    assert fields.vocals == "instrumental_only"
    assert fields.instrument_preferences == ["木吉他", "钢琴"]
    assert draft.unknown_fields == []
    assert draft.review_required_fields == []
    assert all(
        complete_description()[span.start : span.end] == span.text
        for span in draft.source_spans
        if span.source_kind == "raw_description"
    )


def test_conflicting_orientation_abstains_and_requires_review() -> None:
    draft = DeterministicBriefInterpreter().normalize(
        RawCreativeBrief(
            raw_description=(
                "在开封拍一条60秒城市漫游短片，横屏和竖屏都可以，"
                "风格明亮，情绪温暖，快节奏。"
            )
        )
    )

    assert draft.normalized_fields.orientation is None
    assert "orientation" in draft.conflicting_fields
    assert "orientation" in draft.unknown_fields
    assert "orientation" in draft.review_required_fields
    assert draft.status == "partial"


def test_structured_hint_conflict_does_not_silently_override_text() -> None:
    draft = DeterministicBriefInterpreter().normalize(
        RawCreativeBrief(
            raw_description=complete_description(),
            optional_structured_hints={"orientation": "landscape"},
        )
    )

    assert draft.normalized_fields.orientation is None
    assert "orientation" in draft.conflicting_fields
    assert any(
        span.field == "orientation" and span.source_kind == "structured_hint"
        for span in draft.source_spans
    )


def test_whitespace_only_description_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RawCreativeBrief(raw_description="   ")


def test_legacy_v01_brief_migrates_without_model_call() -> None:
    legacy = UserCreativeBrief(
        location="开封",
        travel_type="城市漫游",
        target_duration_seconds=60,
        orientation="portrait",
        style="明亮",
        mood="探索",
        rhythm="medium",
    )

    draft = DeterministicBriefInterpreter().normalize_legacy(legacy)

    assert draft.status == "completed"
    assert draft.normalized_fields.location == "开封"
    assert draft.normalized_fields.vocals == "instrumental_preferred"
    assert all(
        span.source_kind == "legacy_structured_brief"
        for span in draft.source_spans
    )


def test_review_page_is_offline_and_confirmation_is_hash_bound(tmp_path: Path) -> None:
    draft = DeterministicBriefInterpreter().normalize(
        RawCreativeBrief(raw_description=complete_description())
    )
    draft_path = tmp_path / "intent_brief.json"
    draft_path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    draft_hash = hashlib.sha256(draft_path.read_bytes()).hexdigest()
    output = tmp_path / "brief-review.html"

    render_brief_review(draft, output, draft_sha256=draft_hash)

    html = output.read_text(encoding="utf-8")
    assert complete_description() in html
    assert "下载 brief_confirmation.json" in html
    assert draft_hash in html
    assert "https://" not in html

    confirmation = BriefConfirmation(
        status="completed",
        draft_sha256=draft_hash,
        normalized_fields=draft.normalized_fields,
        changed_fields=[],
        confirmed_at="2026-08-31T15:00:00+08:00",
    )
    validate_brief_confirmation(confirmation, draft, draft_hash)
    with pytest.raises(ValueError, match="hash"):
        validate_brief_confirmation(confirmation, draft, "f" * 64)

    revised = confirmation.model_copy(
        update={
            "normalized_fields": draft.normalized_fields.model_copy(
                update={"orientation": "landscape"}
            ),
            "changed_fields": ["orientation"],
        }
    )
    validate_brief_confirmation(revised, draft, draft_hash)
    with pytest.raises(ValueError, match="changed_fields"):
        validate_brief_confirmation(
            revised.model_copy(update={"changed_fields": []}),
            draft,
            draft_hash,
        )


def test_completed_confirmation_rejects_missing_critical_fields() -> None:
    with pytest.raises(ValidationError, match="missing"):
        BriefConfirmation(
            status="completed",
            draft_sha256="a" * 64,
            normalized_fields={"location": "开封"},
            changed_fields=[],
            confirmed_at="2026-08-31T15:00:00+08:00",
        )


def test_cli_normalize_render_and_confirm_round_trip(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(
        RawCreativeBrief(raw_description=complete_description()).model_dump_json(),
        encoding="utf-8",
    )
    draft_path = tmp_path / "draft.json"
    review_path = tmp_path / "review.html"
    confirmation_path = tmp_path / "confirmation.json"
    confirmed_path = tmp_path / "confirmed.json"
    runner = CliRunner()

    normalized = runner.invoke(
        app,
        ["normalize-brief", "--brief", str(raw_path), "--output", str(draft_path)],
    )
    rendered = runner.invoke(
        app,
        [
            "render-brief-review",
            "--draft",
            str(draft_path),
            "--output",
            str(review_path),
        ],
    )
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    confirmation = {
        "schema_version": "0.2.0",
        "status": "completed",
        "draft_sha256": hashlib.sha256(draft_path.read_bytes()).hexdigest(),
        "normalized_fields": draft["normalized_fields"],
        "changed_fields": [],
        "confirmed_at": "2026-08-31T15:00:00+08:00",
    }
    confirmation_path.write_text(
        json.dumps(confirmation, ensure_ascii=False), encoding="utf-8"
    )
    confirmed = runner.invoke(
        app,
        [
            "confirm-brief",
            "--draft",
            str(draft_path),
            "--confirmation",
            str(confirmation_path),
            "--output",
            str(confirmed_path),
        ],
    )

    assert normalized.exit_code == 0, normalized.output
    assert rendered.exit_code == 0, rendered.output
    assert confirmed.exit_code == 0, confirmed.output
    assert confirmed_path.exists()
