"""Beat grid, onsets, accents, and 4-bar phrases.

librosa is the default. ``beat_this`` (MIT) is an optional extra: if it is not
installed, or its weights are not already on disk, analysis stays on librosa
and says so. This module never imports torch at import time.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import librosa
import numpy as np

from director.schema import (
    BeatEvent,
    BeatGap,
    BeatGridInfo,
    OnsetEvent,
    PhraseSpan,
)


_WEIGHT_SENTENCE = (
    "可选组件 beat_this（MIT，需要 torch）能估计强拍。"
    "第一次运行会从网络下载权重（small0 约 8MB，final0 约 78MB），"
    "缓存在本机后可以离线使用。确认台不会自动下载。"
)


def beat_this_module():
    """Import beat_this. Missing extra raises ImportError."""

    return importlib.import_module("beat_this.inference")


def beat_this_weight_files() -> list[Path]:
    """Checkpoint files already on disk. Does not download."""

    found: list[Path] = []
    named = os.environ.get("BEAT_THIS_CHECKPOINT", "").strip()
    if named:
        path = Path(named).expanduser()
        if path.is_file():
            found.append(path)
    torch_home = Path(os.environ.get("TORCH_HOME", str(Path.home() / ".cache" / "torch")))
    roots = [
        Path.home() / ".cache" / "beat_this",
        torch_home / "hub" / "checkpoints",
        torch_home / "beat_this",
    ]
    extra = os.environ.get("BEAT_THIS_CACHE", "").strip()
    if extra:
        roots.append(Path(extra).expanduser())
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(path for path in root.rglob("*") if path.is_file() and path.stat().st_size > 100_000)
    return found


def select_backend(requested: str) -> tuple[str, str]:
    """Return ``(librosa|beat_this, Chinese note)``.

    ``auto`` uses beat_this only when the package imports and a weight file is
    already cached. ``beat_this`` asks to run it; a missing install falls back.
    """

    if requested not in {"auto", "librosa", "beat_this"}:
        raise ValueError("beat_backend must be auto, librosa, or beat_this")
    if requested == "librosa":
        return "librosa", "拍点后端：librosa。" + _WEIGHT_SENTENCE
    try:
        beat_this_module()
        installed = True
    except ImportError:
        installed = False
    if not installed:
        if requested == "beat_this":
            return (
                "librosa",
                "拍点后端：librosa。请求了 beat_this，但没有安装，已回退。" + _WEIGHT_SENTENCE,
            )
        return "librosa", "拍点后端：librosa。未安装 beat_this，已回退。" + _WEIGHT_SENTENCE
    if requested == "auto" and not beat_this_weight_files():
        return (
            "librosa",
            "拍点后端：librosa。beat_this 已安装，但本机还没有权重，已回退，避免首次分析时下载。"
            + _WEIGHT_SENTENCE,
        )
    return "beat_this", "拍点后端：beat_this。权重在首次运行时下载到本机缓存，之后可以离线使用。"


def run_beat_this(path: Path) -> tuple[list[float], list[float]]:
    """Run File2Beats on one audio file. May download weights on first use."""

    module = beat_this_module()
    checkpoint = os.environ.get("BEAT_THIS_CHECKPOINT", "small0")
    device = os.environ.get("BEAT_THIS_DEVICE", "cpu")
    tracker = module.File2Beats(checkpoint_path=checkpoint, device=device, dbn=False)
    beats, downbeats = tracker(str(path))
    return [float(item) for item in beats], [float(item) for item in downbeats]


def plp_beat_count(onset_envelope: np.ndarray, sample_rate: int, hop_length: int) -> int:
    pulse = librosa.beat.plp(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=hop_length,
    )
    return int(np.flatnonzero(librosa.util.localmax(pulse)).size)


def track_beats(
    onset_envelope: np.ndarray,
    sample_rate: int,
    hop_length: int,
    *,
    trim: bool,
) -> tuple[float | None, np.ndarray]:
    tempo, frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=hop_length,
        trim=trim,
    )
    times = librosa.frames_to_time(frames, sr=sample_rate, hop_length=hop_length)
    bpm = float(np.asarray(tempo).reshape(-1)[0]) if np.size(tempo) else None
    if bpm is not None and bpm <= 0:
        bpm = None
    return bpm, np.asarray(times, dtype=np.float64)


def compare_beat_trackers(path: Path, sample_rate: int = 22_050, hop_length: int = 512) -> dict[str, float | int | None]:
    """Measure trim=True, trim=False, and plp on one file. For the 91-beat check."""

    audio, sr = librosa.load(path, sr=sample_rate, mono=True)
    duration = float(librosa.get_duration(y=audio, sr=sr))
    envelope = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=hop_length)
    bpm_trim, trimmed = track_beats(envelope, sr, hop_length, trim=True)
    bpm_full, full = track_beats(envelope, sr, hop_length, trim=False)
    return {
        "duration_seconds": round(duration, 3),
        "bpm_trim": None if bpm_trim is None else round(bpm_trim, 3),
        "bpm_trim_false": None if bpm_full is None else round(bpm_full, 3),
        "beats_trim_true": int(trimmed.size),
        "beats_trim_false": int(full.size),
        "plp_beats": plp_beat_count(envelope, sr, hop_length),
        "expected_trim_false": (
            None if not bpm_full else round(duration * bpm_full / 60.0, 3)
        ),
    }


def _low_onset(audio: np.ndarray, sample_rate: int, hop_length: int, full: np.ndarray) -> np.ndarray:
    try:
        spectrum = np.abs(librosa.stft(audio, hop_length=hop_length))
        freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=(spectrum.shape[0] - 1) * 2)
        if freqs.shape[0] != spectrum.shape[0]:
            freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=2048)
        low = freqs <= 250.0
        if freqs.shape[0] != spectrum.shape[0] or not np.any(low):
            return full
        band = librosa.onset.onset_strength(
            S=spectrum[low],
            sr=sample_rate,
            hop_length=hop_length,
        )
    except Exception:
        return full
    if len(band) == len(full):
        return np.asarray(band, dtype=np.float64)
    if len(band) < 2:
        return full
    source = np.linspace(0.0, 1.0, len(band))
    target = np.linspace(0.0, 1.0, len(full))
    return np.interp(target, source, band).astype(np.float64)


def _window_max(times: np.ndarray, envelope: np.ndarray, moment: float, half: float = 0.05) -> float:
    if not len(envelope):
        return 0.0
    mask = np.abs(times - moment) <= half
    if np.any(mask):
        return float(np.max(envelope[mask]))
    index = int(np.argmin(np.abs(times - moment)))
    return float(envelope[index])


def _normalize(values: list[float]) -> list[float]:
    peak = max(values) if values else 0.0
    if peak <= 0:
        return [0.0 for _ in values]
    return [float(np.clip(value / peak, 0.0, 1.0)) for value in values]


def _phase(low_values: list[float]) -> tuple[int, float]:
    if len(low_values) < 8:
        return 0, 0.0
    scores: list[float] = []
    for phase in range(4):
        group = [low_values[index] for index in range(phase, len(low_values), 4)]
        scores.append(sum(group) / len(group) if group else 0.0)
    order = sorted(range(4), key=lambda phase: scores[phase], reverse=True)
    best, second = scores[order[0]], scores[order[1]]
    confidence = (best - second) / best if best > 1e-9 else 0.0
    return order[0], float(np.clip(confidence, 0.0, 1.0))


def _nearest_index(times: list[float], moment: float) -> int | None:
    if not times:
        return None
    index = int(np.argmin(np.abs(np.asarray(times) - moment)))
    return index


def _downbeat_flags(
    count: int,
    times: list[float],
    *,
    model_downbeats: list[float] | None,
    low_values: list[float],
) -> tuple[list[bool], str, float]:
    if model_downbeats:
        flags = [False] * count
        matched: list[int] = []
        for moment in model_downbeats:
            index = _nearest_index(times, moment)
            if index is None or abs(times[index] - moment) > 0.05:
                continue
            flags[index] = True
            matched.append(index)
        if len(matched) >= 2:
            origin = matched[0]
            consistent = sum((index - origin) % 4 == 0 for index in matched)
            confidence = consistent / len(matched)
        else:
            confidence = 0.0
        return flags, "beat_this", float(np.clip(confidence, 0.0, 1.0))
    phase, confidence = _phase(low_values)
    if confidence < 0.10:
        flags = [index % 4 == 0 for index in range(count)]
        return flags, "every_fourth_beat", confidence
    flags = [(index - phase) % 4 == 0 for index in range(count)]
    return flags, "onset_phase_heuristic", confidence


def _phrases(
    events: list[BeatEvent],
    duration: float,
    confidence: float,
) -> list[PhraseSpan]:
    downbeats = [event for event in events if event.is_downbeat]
    if not downbeats:
        return []
    anchors = [0]
    cursor = 0
    sources = ["bar_grid_4"]
    while cursor < len(downbeats) - 1:
        target = min(cursor + 4, len(downbeats) - 1)
        stepped = None
        for index in range(cursor + 1, target + 1):
            delta = abs(downbeats[index].energy - downbeats[index - 1].energy)
            if delta >= 0.08:
                stepped = index
                break
        nxt = stepped if stepped is not None else target
        if nxt <= cursor:
            break
        anchors.append(nxt)
        sources.append("energy_step" if stepped is not None and nxt == stepped else "bar_grid_4")
        cursor = nxt
    phrases: list[PhraseSpan] = []
    period = 0.0
    if len(events) >= 2:
        period = events[1].t - events[0].t
    bar = 4 * period if period > 0 else 1.0
    for index, start_at in enumerate(anchors):
        start = downbeats[start_at].t
        end = downbeats[anchors[index + 1]].t if index + 1 < len(anchors) else duration
        if end <= start + 1e-3:
            continue
        bars = max(1, int(round((end - start) / bar))) if bar > 0 else 1
        phrases.append(
            PhraseSpan(
                id=f"p{index + 1:02d}",
                start=round(start, 3),
                end=round(end, 3),
                bars=bars,
                source=sources[index],
                confidence=round(min(1.0, max(0.0, confidence)), 3),
            )
        )
    return phrases


def build_rhythm(
    *,
    audio: np.ndarray,
    sample_rate: int,
    hop_length: int,
    duration: float,
    bpm: float | None,
    beat_times: np.ndarray,
    onset_envelope: np.ndarray,
    onset_times: np.ndarray,
    model_downbeats: list[float] | None,
    backend: str,
    note: str,
    plp_beats: int,
) -> dict[str, object]:
    """Turn measured beats into onsets, accents, gaps, downbeats, and phrases."""

    times = sorted({round(float(value), 6) for value in beat_times if 0.0 <= float(value) <= duration + 1e-3})
    empty = {
        "beat_backend": backend,
        "beat_backend_note": note,
        "onsets": [],
        "beat_events": [],
        "beat_grid": None,
        "phrases": [],
        "downbeat_detector": "every_fourth_beat",
        "downbeat_confidence": None,
        "meter_assumed": None,
        "analysis_warnings": [],
        "plp_beat_count": plp_beats,
        "beats_seconds": times,
        "downbeats_seconds": times[::4],
    }
    if bpm is None or bpm <= 0 or len(times) < 4:
        return empty

    frame_times = librosa.frames_to_time(
        np.arange(len(onset_envelope)),
        sr=sample_rate,
        hop_length=hop_length,
    )
    low = _low_onset(audio, sample_rate, hop_length, np.asarray(onset_envelope, dtype=np.float64))
    raw_strength = [_window_max(frame_times, onset_envelope, moment) for moment in times]
    low_strength = [_window_max(frame_times, low, moment) for moment in times]
    strength = _normalize(raw_strength)

    energies: list[float] = []
    for index, moment in enumerate(times):
        left = times[index - 1] if index else max(0.0, moment - (times[1] - times[0]))
        right = times[index + 1] if index + 1 < len(times) else min(duration, moment + (moment - times[index - 1] if index else 0.5))
        start = int(max(0.0, (left + moment) / 2.0) * sample_rate)
        end = int(min(duration, (moment + right) / 2.0) * sample_rate)
        segment = audio[start:max(start + 1, end)]
        energies.append(float(np.sqrt(np.mean(np.square(segment, dtype=np.float64)))))
    energy = _normalize(energies)

    flags, detector, confidence = _downbeat_flags(
        len(times),
        times,
        model_downbeats=model_downbeats,
        low_values=low_strength,
    )
    threshold = float(np.percentile(np.asarray(raw_strength, dtype=np.float64), 85))
    accents: list[bool] = []
    for index, value in enumerate(raw_strength):
        window = raw_strength[max(0, index - 8) : index]
        mean_prev = sum(window) / len(window) if window else 0.0
        accents.append(bool(value > 0 and (value >= threshold or (window and value >= mean_prev * 1.5))))

    bar = 0
    beat_in_bar = 0
    events: list[BeatEvent] = []
    for index, moment in enumerate(times):
        if flags[index] and index != 0 and beat_in_bar != 0:
            bar += 1
            beat_in_bar = 0
        events.append(
            BeatEvent(
                i=index,
                t=round(moment, 6),
                bar=bar,
                beat_in_bar=min(16, beat_in_bar),
                is_downbeat=flags[index],
                onset_strength=round(strength[index], 6),
                energy=round(energy[index], 6),
                accent=accents[index],
            )
        )
        beat_in_bar += 1

    phrases = _phrases(events, duration, confidence)
    starts = {phrase.start for phrase in phrases}
    events = [
        event.model_copy(update={"is_phrase_start": any(abs(event.t - start) <= 0.02 for start in starts)})
        for event in events
    ]

    period = 60.0 / bpm
    gaps = [
        BeatGap(start=round(left, 3), end=round(right, 3))
        for left, right in zip(times, times[1:])
        if right - left > 1.5 * period
    ]
    expected = duration * bpm / 60.0
    coverage = float(np.clip(len(times) / expected, 0.0, 1.0)) if expected else 0.0
    warnings = ["meter_assumed_4_4"]
    if detector == "every_fourth_beat":
        warnings.append("downbeat_phase_heuristic")
    if gaps:
        warnings.append("beat_grid_gaps")

    peak = float(np.max(onset_envelope)) if len(onset_envelope) else 0.0
    onsets: list[OnsetEvent] = []
    for index, moment in enumerate(onset_times):
        raw = _window_max(frame_times, onset_envelope, float(moment), 0.02)
        level = raw / peak if peak > 0 else 0.0
        onsets.append(
            OnsetEvent(id=f"o{index + 1:04d}", t=round(float(moment), 6), strength=round(float(np.clip(level, 0.0, 1.0)), 6))
        )

    return {
        "beat_backend": backend,
        "beat_backend_note": note,
        "onsets": onsets,
        "beat_events": events,
        "beat_grid": BeatGridInfo(period_s=round(period, 6), coverage=round(coverage, 6), gaps=gaps),
        "phrases": phrases,
        "downbeat_detector": detector,
        "downbeat_confidence": round(confidence, 6),
        "meter_assumed": 4,
        "analysis_warnings": warnings,
        "plp_beat_count": plp_beats,
        "beats_seconds": [event.t for event in events],
        "downbeats_seconds": [event.t for event in events if event.is_downbeat],
    }
