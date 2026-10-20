"""Precomputed waveform peaks for the confirm desk.

Peaks are a display cache, not a project artifact. They are keyed by the
frozen track sha256 and stored outside the project, never in
``project_state.json``. PCM is decoded with ffmpeg to mono 8 kHz when ffmpeg
is on PATH; a 16-bit wav falls back to the stdlib ``wave`` module. Buckets are
about 20 per second and capped, so a 10-minute track stays a small JSON file.
The browser draws the cached peaks and does not decode the file itself.
"""

from __future__ import annotations

import array
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

SAMPLE_RATE = 8000
BUCKETS_PER_SECOND = 20
MAX_BUCKETS = 20000


def peaks_cache_dir() -> Path:
    raw = os.environ.get("TRAVEL_DIRECTOR_PEAKS_CACHE")
    path = Path(raw) if raw else Path.home() / ".cache" / "travel-director" / "waveform-peaks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def peak_buckets(samples: array.array, sample_rate: int = SAMPLE_RATE) -> list[float]:
    """Collapse mono PCM-16 samples into normalized absolute peaks."""

    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if not samples:
        return [0.0]
    duration = len(samples) / sample_rate
    count = max(1, min(MAX_BUCKETS, int(round(duration * BUCKETS_PER_SECOND)) or 1))
    step = len(samples) / count
    peaks: list[float] = []
    for index in range(count):
        start = int(index * step)
        end = max(start + 1, int((index + 1) * step))
        segment = samples[start:end]
        if not segment:
            peaks.append(0.0)
            continue
        peak = max(abs(int(min(segment))), abs(int(max(segment)))) / 32768
        peaks.append(round(min(1.0, peak), 4))
    return peaks


def _decode_ffmpeg(path: Path) -> array.array | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    completed = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout:
        return None
    raw = completed.stdout
    if len(raw) % 2:
        raw = raw[:-1]
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _decode_wav(path: Path) -> array.array:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError("without ffmpeg only 16-bit wav can be drawn")
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if channels > 1:
        mono = array.array("h")
        for index in range(0, len(samples) - channels + 1, channels):
            chunk = samples[index : index + channels]
            mono.append(int(sum(chunk) / channels))
        samples = mono
    if rate == SAMPLE_RATE or not samples:
        return samples
    target_len = max(1, int(len(samples) * SAMPLE_RATE / rate))
    resized = array.array("h")
    last = len(samples) - 1
    for index in range(target_len):
        source = min(last, int(index * rate / SAMPLE_RATE))
        resized.append(samples[source])
    return resized


def decode_mono_s16_8k(path: Path) -> array.array:
    decoded = _decode_ffmpeg(path)
    if decoded is not None:
        return decoded
    return _decode_wav(path)


def load_or_build_peaks(path: Path, source_sha256: str) -> dict:
    """Return cached peaks for ``source_sha256``, building them on a miss."""

    cache = peaks_cache_dir() / f"{source_sha256}.json"
    if cache.is_file():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("source_sha256") == source_sha256 and payload.get("peaks"):
            return payload
    samples = decode_mono_s16_8k(path)
    peaks = peak_buckets(samples, SAMPLE_RATE)
    duration = len(samples) / SAMPLE_RATE if samples else 0.0
    payload = {
        "source_sha256": source_sha256,
        "sample_rate": SAMPLE_RATE,
        "duration_seconds": round(duration, 4),
        "peaks": peaks,
    }
    temporary = cache.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(cache)
    return payload
