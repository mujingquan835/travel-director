"""Local-only evidence enrichment for Director material records."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import subprocess
from typing import Iterable

import numpy as np
from PIL import Image

from director.schema import (
    AudioValueCandidate,
    MaterialScanResult,
    RecommendedRange,
    SfxCandidate,
)


SFX_LABELS = {
    "water": "water",
    "river": "water",
    "sea": "water",
    "rain": "rain",
    "vehicle": "vehicle",
    "car": "vehicle",
    "train": "vehicle",
    "food": "food",
    "glass": "glass",
}


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_thumbnail(run_dir: Path, relpath: str) -> Path | None:
    candidate = Path(relpath)
    choices = [candidate] if candidate.is_absolute() else [run_dir / candidate, run_dir.parent / candidate]
    return next((path for path in choices if path.is_file()), None)


def _dhash(path: Path) -> int:
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("L").resize((9, 8)), dtype=np.int16)
    differences = pixels[:, 1:] > pixels[:, :-1]
    value = 0
    for bit in differences.flat:
        value = (value << 1) | int(bit)
    return value


def _hamming(first: int, second: int) -> int:
    return (first ^ second).bit_count()


def _duplicate_groups(
    materials: list[MaterialScanResult], input_root: Path, run_dir: Path
) -> dict[int, str]:
    parents = list(range(len(materials)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        left, right = find(first), find(second)
        if left != right:
            parents[right] = left

    source_hashes = [
        _sha256_file(input_root / material.source.relative_path)
        for material in materials
    ]
    frame_hashes: list[list[int]] = []
    for material in materials:
        hashes: list[int] = []
        for frame in material.representative_frames:
            resolved = _resolve_thumbnail(run_dir, frame.thumbnail_relpath)
            if resolved is not None:
                hashes.append(_dhash(resolved))
        frame_hashes.append(hashes)

    for first in range(len(materials)):
        for second in range(first + 1, len(materials)):
            if source_hashes[first] is not None and source_hashes[first] == source_hashes[second]:
                union(first, second)
                continue
            matches = sum(
                _hamming(left, right) <= 6
                for left in frame_hashes[first]
                for right in frame_hashes[second]
            )
            if matches >= 2:
                union(first, second)

    members: dict[int, list[int]] = {}
    for index in range(len(materials)):
        members.setdefault(find(index), []).append(index)
    output: dict[int, str] = {}
    for indexes in members.values():
        if len(indexes) < 2:
            continue
        identity = "\n".join(sorted(materials[index].file for index in indexes))
        group_id = f"dup-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
        for index in indexes:
            output[index] = group_id
    return output


def _sample_starts(duration: float) -> list[float]:
    if duration <= 2.0:
        return [0.0]
    return sorted({0.0, max(0.0, duration / 2.0 - 1.0), max(0.0, duration - 2.0)})


def _decode_audio_windows(path: Path, duration: float) -> list[np.ndarray]:
    windows: list[np.ndarray] = []
    for start in _sample_starts(duration):
        completed = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                f"{start:.6f}",
                "-t",
                "2",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "-",
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout:
            windows.append(np.frombuffer(completed.stdout, dtype="<f4").copy())
    return windows


def _audio_evidence(path: Path, duration: float) -> AudioValueCandidate:
    if not path.is_file():
        return AudioValueCandidate(status="unavailable", reason="source file is unavailable")
    windows = _decode_audio_windows(path, duration)
    if not windows:
        return AudioValueCandidate(status="unavailable", reason="no decodable audio stream")
    samples = np.concatenate(windows)
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    clipping_ratio = float(np.mean(np.abs(samples) >= 0.99))
    spectrum = np.abs(np.fft.rfft(samples)) + 1e-12
    flatness = float(math.exp(float(np.mean(np.log(spectrum)))) / float(np.mean(spectrum)))
    frame_size = 400
    frame_count = len(samples) // frame_size
    if frame_count >= 2:
        frames = samples[: frame_count * frame_size].reshape(frame_count, frame_size)
        frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
        changes = np.maximum(np.diff(frame_rms), 0.0)
        threshold = float(changes.mean() + changes.std())
        onset_density = float(np.count_nonzero(changes > threshold) / (len(samples) / 16000.0))
    else:
        onset_density = 0.0
    return AudioValueCandidate(
        status="candidate",
        rms=rms,
        clipping_ratio=clipping_ratio,
        spectral_flatness=min(max(flatness, 0.0), 1.0),
        onset_density=onset_density,
        reason="measured from at most three sparse two-second mono windows",
    )


def _recommended_ranges(material: MaterialScanResult) -> list[RecommendedRange]:
    duration = material.technical.duration
    intervals = [
        (max(0.0, frame.timestamp - 2.0), min(duration, frame.timestamp + 2.0), frame.reasons)
        for frame in material.representative_frames
    ]
    intervals = [row for row in intervals if row[1] > row[0]]
    if not intervals and duration > 0:
        intervals = [(0.0, min(duration, 4.0), ["technical_fallback"])]
    merged: list[tuple[float, float, list[str]]] = []
    for start, end, reasons in sorted(intervals):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end, previous_reasons = merged[-1]
            merged[-1] = (
                previous_start,
                max(previous_end, end),
                sorted(set(previous_reasons) | set(reasons)),
            )
        else:
            merged.append((start, end, list(reasons)))
    return [RecommendedRange(start=start, end=end, reasons=reasons) for start, end, reasons in merged]


def _sfx_candidates(material: MaterialScanResult) -> list[SfxCandidate]:
    timestamp = material.representative_frames[0].timestamp if material.representative_frames else 0.0
    labels = {
        SFX_LABELS[token.lower()]
        for token in material.object_candidates
        if token.lower() in SFX_LABELS
    }
    return [
        SfxCandidate(
            file=material.file,
            label=label,
            source_time_seconds=timestamp,
            confidence=0.5,
            evidence_source="scanner_object_candidate",
        )
        for label in sorted(labels)
    ]


def enrich_materials(
    materials: Iterable[MaterialScanResult],
    input_root: Path,
    run_dir: Path,
    *,
    generate_recommended_ranges: bool = True,
) -> list[MaterialScanResult]:
    output = [material.model_copy(deep=True) for material in materials]
    groups = _duplicate_groups(output, input_root, run_dir)
    for index, material in enumerate(output):
        material.duplicate_group_id = groups.get(index)
        material.original_audio_value_candidate = _audio_evidence(
            input_root / material.source.relative_path,
            material.technical.duration,
        )
        material.recommended_ranges = (
            _recommended_ranges(material) if generate_recommended_ranges else []
        )
        material.sfx_candidates = _sfx_candidates(material)
    return output
