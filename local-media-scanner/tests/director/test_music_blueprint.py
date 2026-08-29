from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from director.cli import app
from director.music_blueprint import build_blueprint, build_generation_prompt
from director.schema import MusicDirection, UserCreativeBrief


def direction() -> MusicDirection:
    return MusicDirection(
        candidate_id="fixture-01",
        title="明亮城市脉冲",
        author="Fixture Studio",
        plain_description="116 BPM，轻电子、明亮、探索。",
        fit_reason="本地fixture方向",
        preview_url="https://example.invalid/preview/fixture-01",
        bpm=116,
        genres=["轻电子"],
        moods=["明亮", "探索"],
        instruments=["木吉他", "电子鼓"],
        score=0.875,
        reasons={
            "bpm_fit": 1.0,
            "duration_fit": 1.0,
            "tag_overlap": 0.5,
            "instrument_overlap": 1.0,
        },
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


def test_blueprint_sections_are_contiguous_and_cover_duration() -> None:
    blueprint = build_blueprint(direction(), brief())

    assert blueprint.sections[0].start == 0
    assert blueprint.sections[-1].end == 60
    assert all(
        previous.end == current.start
        for previous, current in zip(blueprint.sections, blueprint.sections[1:])
    )
    assert [section.role for section in blueprint.sections] == [
        "intro",
        "rise",
        "breath",
        "climax",
        "outro",
    ]


def test_prompt_excludes_reference_identity_and_copying_language() -> None:
    prompt = build_generation_prompt(build_blueprint(direction(), brief()))

    assert direction().title not in prompt
    assert direction().author not in prompt
    assert "复制旋律" not in prompt
    assert "116 BPM" in prompt
    assert "原创配乐" in prompt
    assert "不得复刻任何现有旋律、歌词或具体编曲" in prompt


def test_blueprint_cli_writes_reference_safe_envelope(tmp_path: Path) -> None:
    directions = tmp_path / "directions.json"
    directions.write_text(
        json.dumps([direction().model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(brief().model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "blueprint.json"

    result = CliRunner().invoke(
        app,
        [
            "blueprint",
            "--directions",
            str(directions),
            "--choice",
            "1",
            "--brief",
            str(brief_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["blueprint"]["duration_seconds"] == 60
    assert "明亮城市脉冲" not in payload["generation_prompt"]
    assert "Fixture Studio" not in payload["generation_prompt"]
