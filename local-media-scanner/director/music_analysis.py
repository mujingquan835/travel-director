"""Measure local audio structure without trusting provider metadata."""

from __future__ import annotations

import hashlib
from pathlib import Path

import librosa
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from director.schema import (
    EnergyPoint,
    MusicEnding,
    MusicStructure,
    MusicStructureSection,
)


class AudioAnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_rate: int = Field(default=22_050, ge=8_000, le=96_000)
    hop_length: int = Field(default=512, ge=128, le=4_096)
    energy_window_seconds: float = Field(default=1.0, gt=0.0, le=5.0)
    min_section_seconds: float = Field(default=2.0, ge=1.0, le=10.0)
    breath_energy_ratio: float = Field(default=0.45, gt=0.0, lt=1.0)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _energy_curve(
    audio: np.ndarray,
    sample_rate: int,
    window_seconds: float,
) -> tuple[np.ndarray, list[EnergyPoint]]:
    window_samples = max(1, int(sample_rate * window_seconds))
    values: list[float] = []
    points: list[EnergyPoint] = []
    peak = 0.0

    for start in range(0, len(audio), window_samples):
        segment = audio[start : start + window_samples]
        rms = float(np.sqrt(np.mean(np.square(segment, dtype=np.float64))))
        values.append(rms)
        peak = max(peak, rms)

    normalized = np.asarray(values, dtype=np.float64)
    if peak > 0:
        normalized /= peak
    for index, value in enumerate(normalized):
        points.append(
            EnergyPoint(
                time_seconds=round(index * window_seconds, 6),
                value=float(np.clip(value, 0.0, 1.0)),
            )
        )
    return normalized, points


def _change_boundaries(
    energy: np.ndarray,
    duration: float,
    config: AudioAnalysisConfig,
) -> list[float]:
    if len(energy) < 3:
        return [0.0, duration]

    padded = np.pad(energy, (1, 1), mode="edge")
    smooth = np.convolve(padded, np.ones(3) / 3.0, mode="valid")
    deltas = np.abs(np.diff(smooth))
    threshold = max(0.08, float(np.percentile(deltas, 80)))
    candidates = [index + 1 for index, value in enumerate(deltas) if value >= threshold]

    clusters: list[list[int]] = []
    for candidate in candidates:
        if clusters and candidate - clusters[-1][-1] <= 2:
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])

    selected: list[float] = []
    for cluster in clusters:
        strongest = max(cluster, key=lambda index: deltas[index - 1])
        boundary = strongest * config.energy_window_seconds
        if (
            boundary >= config.min_section_seconds
            and duration - boundary >= config.min_section_seconds
        ):
            selected.append(boundary)

    return [0.0, *selected, duration]


def _build_sections(
    energy: np.ndarray,
    duration: float,
    config: AudioAnalysisConfig,
) -> list[MusicStructureSection]:
    boundaries = _change_boundaries(energy, duration, config)
    median_energy = float(np.median(energy)) if len(energy) else 0.0
    maximum_energy = float(np.max(energy)) if len(energy) else 0.0
    sections: list[MusicStructureSection] = []

    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        first_bin = int(start / config.energy_window_seconds)
        last_bin = max(first_bin + 1, int(np.ceil(end / config.energy_window_seconds)))
        section_values = energy[first_bin:last_bin]
        mean_energy = float(np.mean(section_values)) if len(section_values) else 0.0

        if mean_energy <= median_energy * config.breath_energy_ratio:
            role = "breath"
            confidence = 0.9
        elif index == 0 and start == 0:
            role = "intro"
            confidence = 0.75
        elif index == len(boundaries) - 2:
            role = "outro"
            confidence = 0.75
        elif maximum_energy > 0 and mean_energy >= maximum_energy * 0.82:
            role = "climax"
            confidence = 0.8
        elif end <= duration * 0.6:
            role = "rise"
            confidence = 0.65
        else:
            role = "unknown"
            confidence = 0.4

        sections.append(
            MusicStructureSection(
                start=round(start, 6),
                end=round(end, 6),
                role=role,
                energy=float(np.clip(mean_energy, 0.0, 1.0)),
                confidence=confidence,
            )
        )
    return sections


def _ending(
    audio: np.ndarray,
    sample_rate: int,
    onset_times: np.ndarray,
    duration: float,
) -> MusicEnding:
    last_onset = float(onset_times[-1]) if len(onset_times) else None
    if last_onset is None:
        behavior = "unknown"
    elif duration - last_onset <= 0.75:
        behavior = "hard_stop"
    else:
        tail_samples = max(1, int(sample_rate * 0.5))
        prior_samples = max(tail_samples + 1, int(sample_rate * 2.0))
        tail_rms = float(np.sqrt(np.mean(np.square(audio[-tail_samples:]))))
        prior_rms = float(np.sqrt(np.mean(np.square(audio[-prior_samples:]))))
        behavior = "decay" if prior_rms > 0 and tail_rms < prior_rms * 0.5 else "fade"
    return MusicEnding(
        last_onset_seconds=round(last_onset, 6) if last_onset is not None else None,
        behavior=behavior,
    )


def analyze_music(path: Path, config: AudioAnalysisConfig) -> MusicStructure:
    """Analyze one local audio file from decoded samples and return measured timings."""

    audio_path = path.resolve()
    if audio_path.suffix.lower() not in {".wav", ".mp3", ".m4a"}:
        raise ValueError("audio must be WAV, MP3, or M4A")

    audio, sample_rate = librosa.load(
        audio_path,
        sr=config.sample_rate,
        mono=True,
    )
    if len(audio) == 0:
        raise ValueError("audio contains no decoded samples")
    duration = float(librosa.get_duration(y=audio, sr=sample_rate))
    onset_envelope = librosa.onset.onset_strength(
        y=audio,
        sr=sample_rate,
        hop_length=config.hop_length,
    )
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=config.hop_length,
    )
    beat_times = librosa.frames_to_time(
        beat_frames,
        sr=sample_rate,
        hop_length=config.hop_length,
    )
    onset_times = librosa.onset.onset_detect(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=config.hop_length,
        units="time",
    )
    energy, energy_points = _energy_curve(
        audio,
        sample_rate,
        config.energy_window_seconds,
    )
    measured_bpm = float(np.asarray(tempo).reshape(-1)[0]) if np.size(tempo) else None
    expected_beats = duration * measured_bpm / 60.0 if measured_bpm else 0.0
    beat_coverage = min(1.0, len(beat_times) / expected_beats) if expected_beats else 0.0

    return MusicStructure(
        source_sha256=_sha256_file(audio_path),
        duration_seconds=round(duration, 6),
        bpm=round(measured_bpm, 6) if measured_bpm else None,
        beats_seconds=[round(float(value), 6) for value in beat_times],
        downbeats_seconds=[
            round(float(value), 6) for value in beat_times[::4]
        ],
        energy_curve=energy_points,
        sections=_build_sections(energy, duration, config),
        ending=_ending(audio, sample_rate, onset_times, duration),
        confidence=float(np.clip(0.4 + 0.6 * beat_coverage, 0.0, 1.0)),
    )
