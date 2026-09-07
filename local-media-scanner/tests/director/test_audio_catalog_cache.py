from pathlib import Path
from unittest.mock import patch
import wave

import pytest

from director.audio_catalog_cache import get_audio_catalog


def write_audio(path, seconds=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * (8000 * seconds))


def test_cache_reuse_and_add_modify_delete(isolated_audio_library):
    root = isolated_audio_library
    song = root / '音乐/旅拍风/song/30s.wav'
    write_audio(song)
    first, signature = get_audio_catalog()
    with patch('director.audio_catalog_cache.build_audio_catalog', side_effect=AssertionError('cache miss')):
        assert get_audio_catalog()[0] == first
    write_audio(song, 2)
    changed, changed_signature = get_audio_catalog()
    assert changed_signature != signature
    assert changed.tracks[0].versions['30s'].duration_seconds == 2
    other = root / '音乐/旅拍风/other/30s.wav'
    write_audio(other)
    assert len(get_audio_catalog()[0].tracks) == 2
    song.unlink()
    assert len(get_audio_catalog()[0].tracks) == 1


def test_corrupt_cache_rebuilds(isolated_audio_library, tmp_path):
    write_audio(isolated_audio_library / '音乐/旅拍风/song/30s.wav')
    first, _ = get_audio_catalog()
    cache = next((tmp_path / 'audio-cache').glob('*.json'))
    cache.write_text('{broken')
    rebuilt, _ = get_audio_catalog()
    assert rebuilt.tracks == first.tracks
