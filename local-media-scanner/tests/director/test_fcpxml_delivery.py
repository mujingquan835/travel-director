from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from typer.testing import CliRunner

from director.cli import app
from director.fcpxml_delivery import export_fcpxml_decision, record_fcpxml_acceptance


def _media_fixture(root: Path) -> tuple[Path, Path, Path]:
    video = root / "video.mp4"
    music = root / "music.wav"
    sfx = root / "whoosh.wav"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=4:r=30",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
        ],
        check=True,
    )
    for output, duration, frequency in ((music, 4, 220), (sfx, 1, 440)):
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration}",
                "-c:a", "pcm_s16le", str(output),
            ],
            check=True,
        )
    return video, music, sfx


def _decision(path: Path, video: Path, music: Path, sfx: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "project_name": "concise-decision",
                "canvas": {
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                    "duration_seconds": 4,
                },
                "clips": [
                    {
                        "kind": "video",
                        "source_path": str(video),
                        "track": "main",
                        "timeline_in": 0,
                        "source_in": 0.5,
                        "duration": 3,
                        "gain": 0,
                    },
                    {
                        "kind": "music",
                        "source_path": str(music),
                        "track": "music",
                        "timeline_in": 0,
                        "source_in": 0,
                        "duration": 4,
                        "gain": 0.5,
                    },
                    {
                        "kind": "sfx",
                        "source_path": str(sfx),
                        "track": "whoosh",
                        "timeline_in": 1.5,
                        "source_in": 0,
                        "duration": 0.5,
                        "gain": 0.8,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_export_fcpxml_materializes_concise_decision(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)

    result = export_fcpxml_decision(decision, tmp_path / "package")

    assert result.status == "fcpxml_generated"
    assert result.external_call_count == 0
    assert result.video_segments == 1
    assert result.audio_segments == 2
    root = ET.parse(result.fcpxml_path).getroot()
    assert root.attrib == {"version": "1.9"}
    assert root.find(".//sequence").attrib["duration"] == "4s"
    assert len(root.findall(".//spine/asset-clip")) == 1
    assert len(root.findall(".//asset-clip/asset-clip")) == 2
    clips = {clip.attrib["name"]: clip for clip in root.findall(".//asset-clip")}
    assert clips["video.mp4"].attrib | {"volume": clips["video.mp4"].find("adjust-volume").attrib["amount"]} == {
        "ref": "asset-1", "name": "video.mp4", "offset": "0s", "start": "1/2s",
        "duration": "3s", "audioRole": "dialogue", "volume": "-96dB",
    }
    assert clips["music.wav"].attrib | {"volume": clips["music.wav"].find("adjust-volume").attrib["amount"]} == {
        "ref": "asset-2", "name": "music.wav", "lane": "-1", "offset": "1/2s",
        "start": "0s", "duration": "4s", "audioRole": "music", "volume": "-6.021dB",
    }
    assert clips["whoosh.wav"].attrib | {"volume": clips["whoosh.wav"].find("adjust-volume").attrib["amount"]} == {
        "ref": "asset-3", "name": "whoosh.wav", "lane": "-2", "offset": "2s",
        "start": "0s", "duration": "1/2s", "audioRole": "effects", "volume": "-1.938dB",
    }
    assets = root.findall(".//asset")
    assert [asset.attrib["name"] for asset in assets] == ["video.mp4", "music.wav", "whoosh.wav"]
    for asset in assets:
        linked = Path(unquote(urlparse(asset.attrib["src"]).path))
        assert linked.is_file()
        if asset.attrib["name"] == "whoosh.wav":
            assert linked.read_bytes() == (tmp_path / "whoosh.wav").read_bytes()
            assert linked.stat().st_ino != (tmp_path / "whoosh.wav").stat().st_ino
        else:
            assert linked.stat().st_ino == Path(tmp_path / asset.attrib["name"]).stat().st_ino
    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert receipt["decision_sha256"]
    assert receipt["fcpxml_sha256"]
    assert receipt["client_import"] == "not_tested"
    assert receipt["client_playback"] == "not_tested"
    assert receipt["client_edit_save"] == "not_tested"
    assert receipt["validation"] == {
        "serialized_timing_tracks_gains_match": True,
        "xml_well_formed": True,
        "source_ranges_within_media": True,
        "timeline_ranges_within_project": True,
        "same_track_non_overlapping": True,
        "material_references_exist": True,
    }


def test_export_fcpxml_rejects_overlapping_clips_on_one_track(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)
    payload = json.loads(decision.read_text(encoding="utf-8"))
    payload["clips"][2]["track"] = "music"
    decision.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="overlap on track music"):
        export_fcpxml_decision(decision, tmp_path / "package")

    assert not (tmp_path / "package").exists()


def test_export_fcpxml_cli_emits_machine_readable_result(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)

    invoked = CliRunner().invoke(
        app,
        ["export-fcpxml", "--decision", str(decision), "--output", str(tmp_path / "package")],
    )

    assert invoked.exit_code == 0, invoked.output
    result = json.loads(invoked.output)
    assert result["status"] == "fcpxml_generated"
    assert Path(result["fcpxml_path"]).is_file()


def test_record_fcpxml_acceptance_separates_generation_from_client_pass(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)
    generated = export_fcpxml_decision(decision, tmp_path / "package")

    accepted = record_fcpxml_acceptance(
        generated.receipt_path,
        application="剪映专业版 macOS",
        application_version="11.4.0",
        draft_name="concise-decision",
        observed_video_segments=1,
        observed_audio_segments=2,
        playhead_before="00:00:00:00",
        playhead_after="00:00:02:04",
        edit_asset="whoosh.wav",
        edit_field="volume_db",
        edit_before=-1.9,
        edit_after=-3.0,
        reopen_value=-3.0,
        accepted_at="2026-09-09T11:25:54+08:00",
    )

    receipt = json.loads(accepted.receipt_path.read_text(encoding="utf-8"))
    assert accepted.status == "fcpxml_client_accepted"
    assert receipt["status"] == "fcpxml_client_accepted"
    assert receipt["client_import"] == "passed"
    assert receipt["client_playback"] == "passed"
    assert receipt["client_edit_save"] == "passed"
    assert receipt["client_acceptance"]["save_reopen_observation"] == {
        "reopened_value": -3.0,
        "matches_saved_edit": True,
    }


def test_record_fcpxml_acceptance_rejects_unpersisted_edit(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)
    generated = export_fcpxml_decision(decision, tmp_path / "package")

    with pytest.raises(ValueError, match="reopened value differs"):
        record_fcpxml_acceptance(
            generated.receipt_path,
            application="剪映专业版 macOS",
            application_version="11.4.0",
            draft_name="concise-decision",
            observed_video_segments=1,
            observed_audio_segments=2,
            playhead_before="00:00:00:00",
            playhead_after="00:00:02:04",
            edit_asset="whoosh.wav",
            edit_field="volume_db",
            edit_before=-1.9,
            edit_after=-3.0,
            reopen_value=-1.9,
            accepted_at="2026-09-09T11:25:54+08:00",
        )


def _cue_decision(tmp_path):
    import shutil
    video, music, sfx = _media_fixture(tmp_path)
    path = tmp_path / 'cue-decision.json'
    _decision(path, video, music, sfx)
    payload = json.loads(path.read_text())
    payload['clips'] = [c for c in payload['clips'] if c['kind'] != 'sfx']
    payload['sfx_cues'] = [dict(cue_id=f'cut-{i}', role='whoosh', anchor_video_index=0,
                              event='cut to next shot', offset_seconds=1+i*.1,
                              duration=.4, gain=.5) for i in range(2)]
    path.write_text(json.dumps(payload))
    library = tmp_path / 'library'
    (library / '风声').mkdir(parents=True)
    shutil.copyfile(sfx, library / '风声' / 'Whoosh.wav')
    return path, library


def test_cues_match_and_materialize_as_independent_audio_tracks(tmp_path):
    path, library = _cue_decision(tmp_path)
    result = export_fcpxml_decision(path, tmp_path / 'out', library)
    receipt = json.loads(result.receipt_path.read_text())
    assert receipt['sfx_segments'] == 2
    assert len(receipt['sfx_matches']) == 2
    assert receipt['client_import'] == 'not_tested'
    root = ET.parse(result.fcpxml_path).getroot()
    nodes = root.findall('.//asset-clip[@audioRole="effects"]')
    assert len(nodes) == 2
    assert len({node.attrib['lane'] for node in nodes}) == 2
    # Parent starts at source 0.5s; timeline 1s must serialize to parent time 1.5s.
    assert {node.attrib['offset'] for node in nodes} == {'3/2s', '8/5s'}
    assert all(node.find('adjust-volume').attrib['amount'] == '-6.021dB' for node in nodes)
    packaged = [Path(m['packaged_path']) for m in receipt['materials'] if 'Whoosh' in m['source_path']]
    assert all(p.is_file() for p in packaged)
    original = packaged[0].read_bytes()
    (library / '风声' / 'Whoosh.wav').write_bytes(b'changed source')
    assert all(p.read_bytes() == original for p in packaged)


@pytest.mark.parametrize('change', ['missing', 'anchor', 'out_of_range', 'duplicate'])
def test_invalid_cues_never_silently_export_without_effects(tmp_path, change):
    path, library = _cue_decision(tmp_path)
    payload = json.loads(path.read_text())
    if change == 'missing':
        payload['sfx_cues'][0]['keywords'] = ['不存在的音效']
    elif change == 'anchor':
        payload['sfx_cues'][0]['anchor_video_index'] = 9
    elif change == 'duplicate':
        payload['sfx_cues'][1]['cue_id'] = payload['sfx_cues'][0]['cue_id']
    else:
        payload['sfx_cues'][0]['duration'] = 30
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        export_fcpxml_decision(path, tmp_path / 'out', library)
    assert not (tmp_path / 'out').exists()
