"""Tests for evidence-backed sound event design."""

from __future__ import annotations

import json
import wave
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from director.cli import app
from director.fcpxml_delivery import (
    FcpxmlCanvasDecision,
    FcpxmlClipDecision,
    FcpxmlEditDecision,
    export_fcpxml_decision,
)
from director.sound_design import (
    build_sound_design,
    inspect_sound_design,
    validate_sound_design_export,
)
from director.sound_design_schema import (
    GainEnvelope,
    GainPoint,
    SoundCue,
    SoundDesignPlan,
    SoundEventVisualAnchor,
    SoundListeningRecord,
    SoundSourcePlacement,
)
from tests.director.test_shot_group import reviewed, project, plan as group_plan


def _write_mock_wav(path: Path, duration_seconds: float = 2.0, sample_rate: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    num_frames = int(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * num_frames)
    return path


def _base_decision(
    tmp_path: Path,
    duration: float = 6.0,
    video_path: Path | None = None,
    music_path: Path | None = None,
) -> Path:
    if video_path is None:
        video_path = tmp_path / "footage" / "clip.mov"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"dummy video data")
    clips = [
        FcpxmlClipDecision(
            kind="video",
            source_path=video_path,
            track="main",
            timeline_in=0.0,
            source_in=0.0,
            duration=duration,
            gain=1.0,
        )
    ]
    if music_path is not None:
        clips.append(
            FcpxmlClipDecision(
                kind="music",
                source_path=music_path,
                track="music",
                timeline_in=0.0,
                source_in=0.0,
                duration=duration,
                gain=0.8,
            )
        )
    decision = FcpxmlEditDecision(
        project_name="sound-design-test",
        canvas=FcpxmlCanvasDecision(width=1920, height=1080, fps=30, duration_seconds=duration),
        clips=clips,
    )
    path = tmp_path / "base_decision.json"
    path.write_text(decision.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_sound_design_aligns_anchor_and_pre_roll(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "impact.wav", duration_seconds=3.0)

    # Accent in audio file is at 0.4s. source_in=0.1s -> pre_roll=0.3s.
    # Visual event at timeline 1.5s -> timeline_in = 1.5 - 0.3 = 1.2s.
    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Align foley impact with picture event",
        cues=[
            SoundCue(
                cue_id="cue-1",
                role="action_foley",
                auditory_plane="foreground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=1.5,
                    anchor_type="environment_presence",
                    description="Box hits the floor",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.4,
                    pre_roll=0.3,
                    source_in=0.1,
                    duration=1.0,
                ),
                selection_reason="Solid thud matches heavy box",
            )
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    out_dir = tmp_path / "v1"
    res = build_sound_design(plan_path, out_dir)

    assert res["status"] == "sound_design_validated"
    assert res["playable_segments"] == 1
    assert res["missing_gaps"] == 0

    manifest = json.loads((out_dir / "sound_design.json").read_text(encoding="utf-8"))
    cue_data = manifest["cues"][0]
    assert cue_data["timeline_in"] == pytest.approx(1.2)
    assert cue_data["source_in"] == pytest.approx(0.1)
    assert cue_data["duration"] == pytest.approx(1.0)
    assert cue_data["pre_roll"] == pytest.approx(0.3)

    decision_data = json.loads((out_dir / "edit_decision.json").read_text(encoding="utf-8"))
    sfx_clip = [c for c in decision_data["clips"] if c["kind"] == "sfx"][0]
    assert sfx_clip["timeline_in"] == pytest.approx(1.2)
    assert sfx_clip["source_in"] == pytest.approx(0.1)
    assert sfx_clip["duration"] == pytest.approx(1.0)


def test_sound_design_rejects_pre_roll_before_timeline_zero(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "riser.wav", duration_seconds=3.0)

    # Event at 0.1s, but pre-roll is 0.5s -> timeline_in = -0.4s
    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Try riser at start",
        cues=[
            SoundCue(
                cue_id="cue-fail",
                role="transition_accent",
                auditory_plane="foreground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=0.1,
                    anchor_type="environment_presence",
                    description="Opening flash",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.5,
                    pre_roll=0.5,
                    source_in=0.0,
                    duration=1.5,
                ),
                selection_reason="Riser build",
            )
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="precede project start"):
        build_sound_design(plan_path, tmp_path / "v1")


def test_sound_design_rejects_duration_exceeding_project_canvas(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=3.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "long_amb.wav", duration_seconds=5.0)

    # Event at 1.0s, duration 2.5s -> ends at 3.5s > 3.0s project duration
    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Oversized ambient",
        cues=[
            SoundCue(
                cue_id="cue-oversize",
                role="location_ambient",
                auditory_plane="background",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=1.0,
                    anchor_type="environment_presence",
                    description="Street sound",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.0,
                    pre_roll=0.0,
                    source_in=0.0,
                    duration=2.5,
                ),
                selection_reason="Street bed",
            )
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="exceeds project duration"):
        build_sound_design(plan_path, tmp_path / "v1")


def test_sound_design_rejects_source_range_exceeding_audio_file(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "short.wav", duration_seconds=1.0)

    # Source duration 1.0s, but source_in=0.5s + duration=1.0s = 1.5s > 1.0s
    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Out of bounds source range",
        cues=[
            SoundCue(
                cue_id="cue-range",
                role="action_foley",
                auditory_plane="midground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=2.0,
                    anchor_type="environment_presence",
                    description="Click",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.6,
                    pre_roll=0.1,
                    source_in=0.5,
                    duration=1.0,
                ),
                selection_reason="Click sound",
            )
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="exceeds audio duration"):
        build_sound_design(plan_path, tmp_path / "v1")


def test_sound_design_rejects_library_sfx_claimed_as_location_recorded(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "音效及音乐" / "风声" / "whoosh.wav", duration_seconds=2.0)

    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="False claim of location sound",
        cues=[
            SoundCue(
                cue_id="cue-false-claim",
                role="action_foley",
                auditory_plane="foreground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=1.0,
                    anchor_type="environment_presence",
                    description="Passing object",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="location_recorded",  # False claim
                    source_anchor_time=0.2,
                    pre_roll=0.2,
                    source_in=0.0,
                    duration=0.8,
                ),
                selection_reason="Pretend this is location sound",
            )
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="library SFX file cannot be claimed as location_recorded"):
        build_sound_design(plan_path, tmp_path / "v1")


def test_sound_design_supports_missing_gap_without_materializing_clip(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)

    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Declare missing on-location sound gap",
        cues=[
            SoundCue(
                cue_id="gap-1",
                role="location_ambient",
                auditory_plane="background",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=2.0,
                    anchor_type="environment_presence",
                    description="River sound recorded too distantly to use",
                ),
                source=SoundSourcePlacement(
                    sound_type="missing_gap",
                    duration=0.0,
                ),
                selection_reason="On-site river audio has severe wind noise; mark as missing gap instead of faking",
            )
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    out_dir = tmp_path / "v1"
    res = build_sound_design(plan_path, out_dir)

    assert res["playable_segments"] == 0
    assert res["missing_gaps"] == 1

    decision_data = json.loads((out_dir / "edit_decision.json").read_text(encoding="utf-8"))
    assert not any(c["kind"] == "sfx" for c in decision_data["clips"])


def test_sound_design_enforces_attributable_listening_record(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "door.wav", duration_seconds=2.0)

    # 1. Claim listened without listening_id fails schema
    with pytest.raises(ValueError, match="reviewed sound cue requires a valid listening_id"):
        SoundCue(
            cue_id="cue-audit",
            role="action_foley",
            auditory_plane="midground",
            music_relation="parallel",
            visual_anchor=SoundEventVisualAnchor(
                event_time=1.0,
                anchor_type="environment_presence",
                description="Door slam",
            ),
            source=SoundSourcePlacement(
                source_path=audio,
                sound_type="library_sfx",
                source_anchor_time=0.3,
                pre_roll=0.1,
                source_in=0.2,
                duration=0.5,
            ),
            selection_reason="Solid slam",
            listening_status="source_listened",
            listening_id=None,
        )

    # 2. Listening record covers source range -> succeeds
    rec = SoundListeningRecord(
        listening_id="listen-door",
        source_path=audio,
        source_in=0.0,
        source_out=1.0,
        reviewer="Test Reviewer",
        method="direct_listening",
        note="Auditioned door sound; clean transient at 0.3s",
        reviewed_at=datetime.now(timezone.utc),
    )
    cue = SoundCue(
        cue_id="cue-audit",
        role="action_foley",
        auditory_plane="midground",
        music_relation="parallel",
        visual_anchor=SoundEventVisualAnchor(
            event_time=1.0,
            anchor_type="environment_presence",
            description="Door slam",
        ),
        source=SoundSourcePlacement(
            source_path=audio,
            sound_type="library_sfx",
            source_anchor_time=0.3,
            pre_roll=0.1,
            source_in=0.2,
            duration=0.5,
        ),
        selection_reason="Solid slam",
        listening_status="source_listened",
        listening_id="listen-door",
    )
    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="With valid listening record",
        cues=[cue],
        listening=[rec],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    out_dir = tmp_path / "v1"
    res = build_sound_design(plan_path, out_dir)
    assert res["listening_status"] == "source_ranges_reviewed"
    assert res["mix_listening_status"] == "not_reviewed"


def test_sound_design_immutable_parent_revision_and_diff(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "whoosh.wav", duration_seconds=2.0)

    cue_v1 = SoundCue(
        cue_id="cue-trans",
        role="transition_accent",
        auditory_plane="foreground",
        music_relation="parallel",
        visual_anchor=SoundEventVisualAnchor(
            event_time=0.0,
            anchor_type="cut_transition",
            description="Opening transition",
        ),
        source=SoundSourcePlacement(
            source_path=audio,
            sound_type="library_sfx",
            source_anchor_time=0.0,
            pre_roll=0.0,
            source_in=0.0,
            duration=0.5,
        ),
        envelope=GainEnvelope(base_gain=0.6),
        selection_reason="Soft whoosh into opening",
    )
    plan_v1 = SoundDesignPlan(
        base_decision=base,
        revision_reason="Initial sound design v1",
        cues=[cue_v1],
    )
    p1_path = tmp_path / "plan_v1.json"
    p1_path.write_text(plan_v1.model_dump_json(indent=2), encoding="utf-8")
    v1_dir = tmp_path / "v1"
    res_v1 = build_sound_design(p1_path, v1_dir)
    assert res_v1["changes"] == []

    # v2: extend duration to 0.8s and change gain to 0.4
    cue_v2 = SoundCue(
        cue_id="cue-trans",
        role="transition_accent",
        auditory_plane="foreground",
        music_relation="parallel",
        visual_anchor=SoundEventVisualAnchor(
            event_time=0.0,
            anchor_type="cut_transition",
            description="Opening transition",
        ),
        source=SoundSourcePlacement(
            source_path=audio,
            sound_type="library_sfx",
            source_anchor_time=0.0,
            pre_roll=0.0,
            source_in=0.0,
            duration=0.8,
        ),
        envelope=GainEnvelope(base_gain=0.4),
        selection_reason="Extend tail and reduce gain to let music breathe",
    )
    plan_v2 = SoundDesignPlan(
        base_decision=base,
        revision_reason="Extend tail and reduce gain",
        cues=[cue_v2],
    )
    p2_path = tmp_path / "plan_v2.json"
    p2_path.write_text(plan_v2.model_dump_json(indent=2), encoding="utf-8")
    v2_dir = tmp_path / "v2"
    res_v2 = build_sound_design(p2_path, v2_dir, parent_path=v1_dir / "sound_design.json")

    assert len(res_v2["changes"]) > 0
    paths_changed = [c["path"] for c in res_v2["changes"]]
    assert any("duration" in p for p in paths_changed)
    assert any("base_gain" in p for p in paths_changed)

    # Refuse overwrite v2
    with pytest.raises(FileExistsError):
        build_sound_design(p2_path, v2_dir)


def test_inspect_sound_design_revalidates(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "click.wav", duration_seconds=1.5)

    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Inspect test",
        cues=[
            SoundCue(
                cue_id="c1",
                role="action_foley",
                auditory_plane="foreground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=1.0,
                    anchor_type="environment_presence",
                    description="Click event",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.1,
                    pre_roll=0.1,
                    source_in=0.0,
                    duration=0.5,
                ),
                selection_reason="Click",
            )
        ],
    )
    p_path = tmp_path / "plan.json"
    p_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    v1_dir = tmp_path / "v1"
    build_sound_design(p_path, v1_dir)

    inspected = inspect_sound_design(v1_dir / "sound_design.json")
    assert inspected["status"] == "sound_design_inspected"
    assert inspected["playable_segments"] == 1


def _generate_test_video(path: Path, duration: float = 6.0) -> Path:
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={duration}:r=30",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
        ],
        check=True,
    )
    return path


def test_export_fcpxml_with_sound_design_binding(tmp_path: Path) -> None:
    video_file = _generate_test_video(tmp_path / "footage" / "v.mov", duration=6.0)
    base = _base_decision(tmp_path, duration=6.0, video_path=video_file)
    audio = _write_mock_wav(tmp_path / "sfx" / "bell.wav", duration_seconds=2.0)

    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Test FCPXML export integration",
        cues=[
            SoundCue(
                cue_id="bell-1",
                role="action_foley",
                auditory_plane="foreground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=2.0,
                    anchor_type="environment_presence",
                    description="Bell rings",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.2,
                    pre_roll=0.1,
                    source_in=0.1,
                    duration=0.8,
                ),
                selection_reason="Clear bell chime",
            )
        ],
    )
    p_path = tmp_path / "plan.json"
    p_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    v1_dir = tmp_path / "v1"
    build_sound_design(p_path, v1_dir)

    pkg_dir = tmp_path / "fcpxml_package"
    export_result = export_fcpxml_decision(v1_dir / "edit_decision.json", pkg_dir)

    assert export_result.status == "fcpxml_generated"
    assert (pkg_dir / "sound_design.json").is_file()
    assert (pkg_dir / "project.fcpxml").is_file()

    receipt = json.loads(export_result.receipt_path.read_text(encoding="utf-8"))
    assert "sound_design" in receipt
    assert receipt["sound_design"]["status"] == "sound_design_validated"
    assert receipt["validation"]["sound_design_evidence_validated"] is True
    assert len(receipt["sound_design"]["cues"]) == 1


def test_export_fcpxml_rejects_tampered_sound_design_binding(tmp_path: Path) -> None:
    video_file = _generate_test_video(tmp_path / "footage" / "v.mov", duration=6.0)
    base = _base_decision(tmp_path, duration=6.0, video_path=video_file)
    audio = _write_mock_wav(tmp_path / "sfx" / "tone.wav", duration_seconds=2.0)

    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="Tamper test",
        cues=[
            SoundCue(
                cue_id="tone-1",
                role="transition_accent",
                auditory_plane="midground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=0.0,
                    anchor_type="cut_transition",
                    description="Opening tone",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.0,
                    pre_roll=0.0,
                    source_in=0.0,
                    duration=0.5,
                ),
                selection_reason="Tone",
            )
        ],
    )
    p_path = tmp_path / "plan.json"
    p_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    v1_dir = tmp_path / "v1"
    build_sound_design(p_path, v1_dir)

    # Tamper with the sound_design.json
    sd_file = v1_dir / "sound_design.json"
    sd_data = json.loads(sd_file.read_text(encoding="utf-8"))
    sd_data["cues"][0]["selection_reason"] = "Tampered reason"
    sd_file.write_text(json.dumps(sd_data), encoding="utf-8")

    pkg_dir = tmp_path / "fcpxml_package"
    with pytest.raises(ValueError, match="sha256 mismatch"):
        export_fcpxml_decision(v1_dir / "edit_decision.json", pkg_dir)


def test_cli_build_and_inspect_sound_design(tmp_path: Path) -> None:
    base = _base_decision(tmp_path, duration=6.0)
    audio = _write_mock_wav(tmp_path / "sfx" / "cli_test.wav", duration_seconds=2.0)

    plan = SoundDesignPlan(
        base_decision=base,
        revision_reason="CLI build test",
        cues=[
            SoundCue(
                cue_id="cli-cue",
                role="action_foley",
                auditory_plane="foreground",
                music_relation="parallel",
                visual_anchor=SoundEventVisualAnchor(
                    event_time=1.0,
                    anchor_type="environment_presence",
                    description="CLI test cue",
                ),
                source=SoundSourcePlacement(
                    source_path=audio,
                    sound_type="library_sfx",
                    source_anchor_time=0.1,
                    pre_roll=0.1,
                    source_in=0.0,
                    duration=0.5,
                ),
                selection_reason="CLI test",
            )
        ],
    )
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    out_dir = tmp_path / "cli_v1"

    runner = CliRunner()
    res_build = runner.invoke(
        app,
        ["build-sound-design", "--plan", str(plan_file), "--output", str(out_dir)],
    )
    assert res_build.exit_code == 0, res_build.output
    build_data = json.loads(res_build.output)
    assert build_data["status"] == "sound_design_validated"

    res_inspect = runner.invoke(
        app,
        ["inspect-sound-design", "--sound-design", str(out_dir / "sound_design.json")],
    )
    assert res_inspect.exit_code == 0, res_inspect.output
    inspect_data = json.loads(res_inspect.output)
    assert inspect_data["status"] == "sound_design_inspected"


def test_sound_design_envelope_validation() -> None:
    # Keyframe points out of order raises ValueError
    with pytest.raises(ValueError, match="ascending offset order"):
        GainEnvelope(
            points=[
                GainPoint(offset_seconds=0.5, gain=0.8),
                GainPoint(offset_seconds=0.2, gain=0.4),
            ]
        )
    # Correct order succeeds
    env = GainEnvelope(
        fade_in_seconds=0.1,
        fade_out_seconds=0.2,
        base_gain=0.7,
        points=[
            GainPoint(offset_seconds=0.1, gain=0.5),
            GainPoint(offset_seconds=0.4, gain=0.9),
        ],
    )
    assert len(env.points) == 2


def test_export_fcpxml_with_all_three_bindings_simultaneously(tmp_path: Path, click_track: Path, reviewed: Any) -> None:
    from director.project import create_visual_project
    from director.visual_schema import RawCreativeBrief
    from director.audio_import import freeze_and_analyze_music
    from director.shot_group import build_shot_group
    from director.music_adaptation import build_music_adaptation
    from tests.director.test_shot_group import plan as group_plan
    from tests.director.test_shot_review import write

    # 1. Create music project and freeze click_track
    music_proj = create_visual_project(tmp_path / "music_p", "test_music", RawCreativeBrief(raw_description="Test music"))
    freeze_and_analyze_music(music_proj, click_track)

    # 2. Build shot group
    gp_file = tmp_path / "gp.json"
    write(gp_file, group_plan(reviewed))
    group_res = build_shot_group(gp_file, tmp_path / "shot_group_dir")
    base_edl = Path(group_res["decision_path"])
    base_data = json.loads(base_edl.read_text(encoding="utf-8"))
    duration = base_data["canvas"]["duration_seconds"]

    # 3. Build music adaptation with pause
    ma_plan_data = {
        "schema_version": "1.0.0",
        "music_project": str(music_proj.root),
        "base_decision": str(base_edl),
        "revision_reason": "Test adaptation",
        "listening": [],
        "phrases": [
            {
                "phrase_id": "p1",
                "source_in": 10.0,
                "source_out": 12.0,
                "label": "Phrase 1",
                "status": "candidate",
                "basis": "editorial_proposal",
                "listening_id": None,
                "reason": "Proposal",
            }
        ],
        "mapping": [
            {
                "segment_id": "s1",
                "kind": "music",
                "source_in": 10.0,
                "source_out": 10.4,
                "project_in": 0.0,
                "project_out": 0.4,
                "phrase_id": "p1",
                "gain": 0.5,
                "reason": "Head",
            },
            {
                "segment_id": "pause",
                "kind": "silence",
                "source_in": None,
                "source_out": None,
                "project_in": 0.4,
                "project_out": 0.8,
                "phrase_id": None,
                "gain": 0.0,
                "reason": "Pause",
            },
            {
                "segment_id": "s2",
                "kind": "music",
                "source_in": 10.4,
                "source_out": 10.4 + duration - 0.8,
                "project_in": 0.8,
                "project_out": duration,
                "phrase_id": "p1",
                "gain": 0.5,
                "reason": "Tail",
            },
        ],
        "events": [
            {
                "event_id": "ev-resume",
                "kind": "resume",
                "project_time": 0.8,
                "segment_id": "s2",
                "source_time": 10.4,
                "status": "proposed",
                "listening_id": None,
                "reason": "Resume",
            }
        ],
        "ending": {"treatment": "cut", "reason": "Cut", "listening_id": None},
        "pacing": [
            {
                "mode": "hold",
                "shot_ids": ["a"],
                "event_id": None,
                "action_field": None,
                "reason": "Hold",
            }
        ],
    }
    ma_plan_file = tmp_path / "ma_plan.json"
    write(ma_plan_file, ma_plan_data)
    ma_res = build_music_adaptation(ma_plan_file, tmp_path / "ma_dir")
    ma_edl = Path(ma_res["decision_path"])

    # 4. Now build sound design over this EDL which has both shot_group and music_adaptation!
    audio_sfx = _write_mock_wav(tmp_path / "sfx" / "swish.wav", duration_seconds=2.0)
    sd_plan = SoundDesignPlan(
        base_decision=ma_edl,
        revision_reason="Sound design over shot group and music adaptation",
        cues=[
            SoundCue(
                cue_id="foley-1",
                role="action_foley",
                auditory_plane="foreground",
                music_relation="music_silent",  # 0.5s is inside 0.4 - 0.8s silence!
                visual_anchor=SoundEventVisualAnchor(
                    event_time=0.5,
                    anchor_type="environment_presence",
                    description="Presence during silence",
                ),
                source=SoundSourcePlacement(
                    source_path=audio_sfx,
                    sound_type="library_sfx",
                    source_anchor_time=0.1,
                    pre_roll=0.1,
                    source_in=0.0,
                    duration=0.3,
                ),
                selection_reason="Foley during music silence",
            )
        ],
    )
    sd_plan_file = tmp_path / "sd_plan.json"
    sd_plan_file.write_text(sd_plan.model_dump_json(indent=2), encoding="utf-8")

    sd_res = build_sound_design(sd_plan_file, tmp_path / "sd_dir")
    assert sd_res["status"] == "sound_design_validated"

    # 5. Export FCPXML package and verify all 3 bindings in receipt
    pkg_dir = tmp_path / "full_package"
    export_result = export_fcpxml_decision(Path(sd_res["decision_path"]), pkg_dir)
    assert export_result.status == "fcpxml_generated"

    assert (pkg_dir / "shot_group.json").is_file()
    assert (pkg_dir / "music_adaptation.json").is_file()
    assert (pkg_dir / "sound_design.json").is_file()

    receipt = json.loads(export_result.receipt_path.read_text(encoding="utf-8"))
    assert "shot_group" in receipt
    assert "music_adaptation" in receipt
    assert "sound_design" in receipt
    assert receipt["validation"]["shot_group_evidence_validated"] is True
    assert receipt["validation"]["music_adaptation_evidence_validated"] is True
    assert receipt["validation"]["sound_design_evidence_validated"] is True

