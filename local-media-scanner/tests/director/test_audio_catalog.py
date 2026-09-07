"""Tests for audio_catalog.py."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from director.audio_catalog import (
    CatalogTrack,
    CatalogVersion,
    SfxEntry,
    _classify_sfx_role,
    _classify_version_tag,
    _extract_keywords,
    resolve_audio_root,
)


def test_classify_version_tag():
    assert _classify_version_tag("song_czg1.wav") == "czg1"
    assert _classify_version_tag("song_CZG2.mp3") == "czg2"
    assert _classify_version_tag("track_czg3.m4a") == "czg3"
    assert _classify_version_tag("music_full.wav") == "full"
    assert _classify_version_tag("track_30s_缩混.wav") == "30s"
    assert _classify_version_tag("track_60s_缩混.wav") == "60s"
    assert _classify_version_tag("track_55s_缩混.wav") == "60s"
    assert _classify_version_tag("track_64s_缩混.wav") == "60s"
    assert _classify_version_tag("track_30s.wav") == "30s"
    assert _classify_version_tag("track_random.wav") == "full"


def test_classify_sfx_role():
    assert _classify_sfx_role("Rising_Hit.wav", "上升音效") == "hook_hit"
    assert _classify_sfx_role("Rise_SubDrop.wav", "上升音效") == "hook_subdrop"
    assert _classify_sfx_role("Whoosh_Riser.wav", "风声") == "riser"
    assert _classify_sfx_role("Wind_Whoosh.wav", "风声") == "whoosh"
    assert _classify_sfx_role("End_Hit.wav", "收尾") == "outro_hit"
    assert _classify_sfx_role("End_Cliff.wav", "收尾") == "outro_hit"
    assert _classify_sfx_role("End_Piano.wav", "收尾") == "outro_piano"
    assert _classify_sfx_role("DJi_Fly.wav", "DJi无人机音效") == "env_drone"
    assert _classify_sfx_role("Bird_Sing.wav", "环境") == "env_ambient"


def test_extract_keywords():
    assert _extract_keywords("旅拍风") == ["旅拍风"]
    assert _extract_keywords("中国风｜古风") == ["中国风", "古风"]
    assert _extract_keywords("流行 摇滚") == ["流行", "摇滚"]
    assert _extract_keywords("轻音乐、钢琴") == ["轻音乐", "钢琴"]
    assert _extract_keywords("民谣｜ 吉他 、 抒情") == ["民谣", "吉他", "抒情"]


def test_resolve_audio_root_env_var(tmp_path):
    # Setup temporary directory
    test_dir = tmp_path / "test_audio"
    test_dir.mkdir()
    
    with patch.dict(os.environ, {"TRAVEL_DIRECTOR_AUDIO_ROOT": str(test_dir)}):
        resolved = resolve_audio_root()
        assert resolved == test_dir.resolve()


def test_catalog_track_model_validation():
    # Valid model
    track = CatalogTrack(
        track_id="test_track",
        title="Test Track",
        category="Test Category",
        versions={
            "full": CatalogVersion(
                version_tag="full",
                relative_path="Test Category/Test Track/full.wav",
                duration_seconds=120.5,
                format="wav"
            )
        },
        keywords=["Test", "Category"]
    )
    assert track.title == "Test Track"

    # Invalid version_tag
    with pytest.raises(ValidationError):
        CatalogVersion(
            version_tag="invalid",  # type: ignore
            relative_path="path.wav",
            duration_seconds=10.0,
            format="wav"
        )
        
    # Extra fields forbidden
    with pytest.raises(ValidationError):
        CatalogTrack(
            track_id="t1",
            title="T",
            category="C",
            versions={},
            keywords=[],
            extra_field="invalid"  # type: ignore
        )


def test_sfx_entry_model_validation():
    # Valid model
    sfx = SfxEntry(
        sfx_id="sfx_1",
        name="Wind",
        category="风声",
        role="whoosh",
        relative_path="风声/Wind.wav",
        duration_seconds=5.0
    )
    assert sfx.name == "Wind"

    # Invalid category
    with pytest.raises(ValidationError):
        SfxEntry(
            sfx_id="sfx_2",
            name="Test",
            category="Invalid",  # type: ignore
            role="whoosh",
            relative_path="path.wav",
            duration_seconds=1.0
        )
        
    # Invalid role
    with pytest.raises(ValidationError):
        SfxEntry(
            sfx_id="sfx_3",
            name="Test",
            category="环境",
            role="invalid",  # type: ignore
            relative_path="path.wav",
            duration_seconds=1.0
        )



@pytest.mark.parametrize("music_dir,sfx_dir", [("音乐", "音效"), ("BGM", "SFX")])
def test_real_audio_scan_to_recommendation(tmp_path, music_dir, sfx_dir):
    """Exercise ffprobe and the shared catalog across the module boundary."""
    import wave
    from director.audio_catalog import build_audio_catalog
    from director.music_recommender import recommend_music

    music = tmp_path / music_dir / "旅拍风" / "测试曲" / "30s.wav"
    sfx = tmp_path / sfx_dir / "上升音效" / "Rising_Hit.wav"
    ambient = tmp_path / sfx_dir / "风沙.wav"
    for path in (music, sfx, ambient):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\0\0" * 8000)
    # Empty legacy directories must not hide a populated Chinese library.
    if music_dir == "音乐":
        (tmp_path / "BGM").mkdir()
        (tmp_path / "SFX").mkdir()
    catalog = build_audio_catalog(tmp_path)
    assert len(catalog.tracks) == 1
    assert len(catalog.sfx) == 2
    assert any(e.relative_path == "风沙.wav" and e.role == "env_ambient" for e in catalog.sfx)
    result = recommend_music(catalog, "旅行", 1)
    assert Path(result.recommendations[0].version_path) == music.resolve()
    assert result.recommendations[0].version_duration_seconds == pytest.approx(1)


def test_missing_library_directories_do_not_create_source_folders(tmp_path):
    from director.audio_catalog import build_audio_catalog

    missing_root = tmp_path / "missing-directories"
    missing_root.mkdir()
    with pytest.raises(ValueError, match="Missing audio library directories"):
        build_audio_catalog(missing_root)
    assert list(missing_root.iterdir()) == []
