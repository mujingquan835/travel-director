from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from scanner.cli import app
from scanner.config import SamplingConfig
from scanner.metadata import build_manifest, probe_video
from scanner.sampling import (
    ProbeFrame,
    decode_probe_frames,
    perceptual_hash,
    select_representatives,
    target_probe_times,
)


def _checkerboard(width: int = 160, height: int = 120) -> np.ndarray:
    yy, xx = np.indices((height, width))
    gray = (((xx // 10) + (yy // 10)) % 2 * 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _frames_at(times: list[float]) -> list[ProbeFrame]:
    image = _checkerboard()
    return [ProbeFrame(timestamp=time, image=image.copy()) for time in times]


def test_probe_count_is_bounded() -> None:
    config = SamplingConfig()

    assert len(target_probe_times(0.5, config)) <= 2
    assert len(target_probe_times(10.0, config)) == 20
    assert len(target_probe_times(120.0, config)) == 24


def test_temporal_baseline_returns_20_50_80_percent() -> None:
    frames = _frames_at(list(np.linspace(0.0, 10.0, 21)))

    selected = select_representatives(frames, 10.0, "temporal3")

    assert [item.timestamp for item in selected] == pytest.approx([2.0, 5.0, 8.0], abs=0.3)
    assert all(item.reasons == ["temporal"] for item in selected)


def test_adaptive_sampling_adds_motion_and_scene_candidates() -> None:
    base = _checkerboard()
    frames: list[ProbeFrame] = []
    for index, timestamp in enumerate(np.linspace(0.0, 10.0, 21)):
        if index < 10:
            image = base.copy()
        elif index == 10:
            image = np.full_like(base, 240)
        else:
            shift = (index - 10) * 8
            image = np.roll(base, shift, axis=1)
        frames.append(ProbeFrame(timestamp=float(timestamp), image=image))

    selected = select_representatives(frames, 10.0, "adaptive5")

    assert 3 <= len(selected) <= 5
    assert any("motion" in item.reasons for item in selected)
    assert any("scene_change" in item.reasons for item in selected)


def test_adaptive_sampling_deduplicates_identical_frames() -> None:
    selected = select_representatives(_frames_at(list(np.linspace(0.0, 10.0, 21))), 10.0, "adaptive5")

    assert len({perceptual_hash(item.image) for item in selected}) == len(selected)


def test_decode_probe_frames_respects_bounds_and_resolution(sample_video: Path, tmp_path: Path) -> None:
    metadata = probe_video(sample_video)

    frames = decode_probe_frames(sample_video, metadata, tmp_path / "probe", SamplingConfig())

    assert 1 <= len(frames) <= 3
    assert max(frames[0].image.shape[:2]) <= 320
    assert all(0.0 <= frame.timestamp <= metadata.duration for frame in frames)


def test_sample_command_writes_auditable_result(sample_video: Path, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        build_manifest(sample_video.parent, [sample_video]).model_dump_json(indent=2),
        encoding="utf-8",
    )
    output = tmp_path / "run"

    result = CliRunner().invoke(
        app,
        [
            "sample",
            "--manifest",
            str(manifest_path),
            "--profile",
            "adaptive5",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert (output / "sampling_result.json").exists()
    assert list((output / "frames").rglob("*.jpg"))


def test_probe_decode_uses_input_side_seek_for_each_sparse_target(
    sample_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    metadata = probe_video(sample_video)

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output), _checkerboard())
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("scanner.sampling.subprocess.run", fake_run)

    frames = decode_probe_frames(
        sample_video,
        metadata,
        tmp_path / "probe",
        SamplingConfig(hardware_acceleration="videotoolbox", decode_strategy="seek"),
    )

    assert len(commands) == len(frames)
    assert all(command.index("-ss") < command.index("-i") for command in commands)
    assert all(command[command.index("-hwaccel") + 1] == "videotoolbox" for command in commands)
    assert all(command.index("-hwaccel") < command.index("-ss") for command in commands)


def test_sequential_matches_seek_on_moving_frames(tmp_path):
    import subprocess
    video=tmp_path/'moving.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=3','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    metadata=probe_video(video)
    old=decode_probe_frames(video,metadata,tmp_path/'old',SamplingConfig(decode_strategy='seek'))
    new=decode_probe_frames(video,metadata,tmp_path/'new',SamplingConfig(decode_strategy='sequential'))
    assert [f.timestamp for f in old]==[f.timestamp for f in new]
    assert all(a.image.shape==b.image.shape for a,b in zip(old,new))
    assert max(np.abs(a.image.astype(float)-b.image.astype(float)).mean() for a,b in zip(old,new)) < 3


def test_sequential_short_clip_uses_one_ffmpeg_process(sample_video,tmp_path,monkeypatch):
    import scanner.sampling as sampling
    original=sampling.subprocess.run
    commands=[]
    metadata=probe_video(sample_video)
    def tracked(command,**kwargs):
        commands.append(command)
        return original(command,**kwargs)
    monkeypatch.setattr(sampling.subprocess,'run',tracked)
    frames=decode_probe_frames(sample_video,metadata,tmp_path/'new',SamplingConfig(decode_strategy='sequential',hardware_acceleration='none'))
    assert len(commands)==1
    assert len(frames)==len(target_probe_times(metadata.duration,SamplingConfig()))


def test_auto_hardware_failure_falls_back_without_partial_frames(sample_video, tmp_path, monkeypatch):
    import scanner.sampling as sampling
    metadata = probe_video(sample_video)
    monkeypatch.setattr(sampling.sys, "platform", "darwin")
    def fail(path, metadata, output, config, binary):
        output.mkdir()
        (output / "probe-0000.jpg").write_bytes(b"partial")
        raise sampling.SamplingError("decode_failed", "unsupported hardware codec")
    original = sampling._decode_seek
    def check_fallback(path, metadata, output, config, binary):
        assert not list(output.glob("probe-*.jpg"))
        assert config.hardware_acceleration == "none"
        return original(path, metadata, output, config, binary)
    monkeypatch.setattr(sampling, "_decode_sequential", fail)
    monkeypatch.setattr(sampling, "_decode_seek", check_fallback)
    frames = decode_probe_frames(sample_video, metadata, tmp_path / "fallback", SamplingConfig())
    assert len(frames) == len(target_probe_times(metadata.duration, SamplingConfig()))


def test_auto_non_mac_preserves_software_seek(sample_video, tmp_path, monkeypatch):
    import scanner.sampling as sampling
    metadata = probe_video(sample_video)
    monkeypatch.setattr(sampling.sys, "platform", "linux")
    original = sampling._decode_seek
    def checked(path, metadata, output, config, binary):
        assert config.hardware_acceleration == "none"
        return original(path, metadata, output, config, binary)
    monkeypatch.setattr(sampling, "_decode_seek", checked)
    monkeypatch.setattr(sampling, "_decode_sequential", lambda *a: pytest.fail("software sequential regression"))
    assert decode_probe_frames(sample_video, metadata, tmp_path / "linux", SamplingConfig())


@pytest.mark.parametrize("duration, expected", [(12, "sequential"), (45, "seek")])
def test_auto_mac_routes_by_duration(sample_video, tmp_path, monkeypatch, duration, expected):
    import scanner.sampling as sampling
    metadata = probe_video(sample_video).model_copy(update={"duration": duration})
    monkeypatch.setattr(sampling.sys, "platform", "darwin")
    routes = []
    def decoder(name):
        def run(path, metadata, output, config, binary):
            assert config.hardware_acceleration == "videotoolbox"
            routes.append(name)
            return []
        return run
    monkeypatch.setattr(sampling, "_decode_seek", decoder("seek"))
    monkeypatch.setattr(sampling, "_decode_sequential", decoder("sequential"))
    decode_probe_frames(sample_video, metadata, tmp_path, SamplingConfig())
    assert routes == [expected]


def test_explicit_hardware_failure_is_not_silently_overridden(sample_video, tmp_path, monkeypatch):
    import scanner.sampling as sampling
    metadata = probe_video(sample_video)
    def fail(*args):
        raise sampling.SamplingError("decode_failed", "unsupported")
    monkeypatch.setattr(sampling, "_decode_sequential", fail)
    monkeypatch.setattr(sampling, "_decode_seek", lambda *args: pytest.fail("unexpected fallback"))
    with pytest.raises(sampling.SamplingError, match="unsupported"):
        decode_probe_frames(sample_video, metadata, tmp_path,
                            SamplingConfig(hardware_acceleration="videotoolbox"))
