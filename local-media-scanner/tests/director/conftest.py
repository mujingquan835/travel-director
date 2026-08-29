from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture
def click_track(tmp_path: Path) -> Path:
    sample_rate = 22_050
    duration_seconds = 60
    audio = np.zeros(sample_rate * duration_seconds, dtype=np.float32)
    click_length = int(0.045 * sample_rate)
    click_shape = np.exp(-np.linspace(0.0, 8.0, click_length)).astype(np.float32)

    def section_amplitude(time_seconds: float) -> float:
        if time_seconds < 7.0:
            return 0.35
        if time_seconds < 24.0:
            return 0.65
        if time_seconds < 31.0:
            return 0.08
        if time_seconds < 54.0:
            return 0.9
        return 0.45

    for beat_time in np.arange(0.0, duration_seconds, 0.5):
        start = int(beat_time * sample_rate)
        end = min(start + click_length, len(audio))
        audio[start:end] += section_amplitude(float(beat_time)) * click_shape[: end - start]

    final_start = int(59.5 * sample_rate)
    audio[final_start : final_start + click_length] += click_shape
    output = tmp_path / "click-track-120bpm.wav"
    sf.write(output, audio, sample_rate, subtype="PCM_16")
    return output
