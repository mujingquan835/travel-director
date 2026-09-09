"""Bounded low-resolution probing and sparse representative selection."""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence

import cv2
import numpy as np

from scanner.config import SamplingConfig
from scanner.schema import FrameRecord, TechnicalMetadata


Reason = Literal["temporal", "motion", "scene_change"]


class SamplingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProbeFrame:
    timestamp: float
    image: np.ndarray = field(compare=False, repr=False)


@dataclass
class FrameCandidate:
    timestamp: float
    image: np.ndarray = field(compare=False, repr=False)
    reasons: list[Reason] = field(default_factory=list)
    score: float = 0.0


def target_probe_times(duration: float, config: SamplingConfig) -> list[float]:
    if duration <= 0:
        return []
    count = min(config.max_probe_frames, max(1, int(np.ceil(duration * 2.0))))
    return [duration * (index + 0.5) / count for index in range(count)]


def _scale_filter(max_edge: int) -> str:
    return (
        f"scale='if(gt(iw,ih),{max_edge},-2)':"
        f"'if(gt(iw,ih),-2,{max_edge})'"
    )


def decode_probe_frames(
    path: Path,
    metadata: TechnicalMetadata,
    output_dir: Path,
    config: SamplingConfig,
    ffmpeg_bin: str = "ffmpeg",
) -> list[ProbeFrame]:
    automatic_hardware = config.hardware_acceleration == "auto"
    hardware = config.hardware_acceleration
    if automatic_hardware:
        hardware = "videotoolbox" if sys.platform == "darwin" else "none"
    resolved = config.model_copy(update={"hardware_acceleration": hardware})
    sequential = config.decode_strategy == "sequential" or (
        config.decode_strategy == "auto" and metadata.duration <= 30
        and hardware == "videotoolbox"
    )
    try:
        return (_decode_sequential if sequential else _decode_seek)(
            path, metadata, output_dir, resolved, ffmpeg_bin
        )
    except SamplingError as exc:
        if not automatic_hardware or hardware == "none" or exc.code == "ffmpeg_missing":
            raise
        # Unsupported hardware/codec and incomplete batch output retain the
        # original accurate software seek path. Never reuse partial batch files.
        logging.getLogger(__name__).warning(
            "Hardware probe failed for %s (%s); falling back to software seek",
            path.name, exc.code,
        )
        for partial in output_dir.glob("probe-*.jpg"):
            partial.unlink()
        return _decode_seek(
            path, metadata, output_dir,
            config.model_copy(update={"hardware_acceleration": "none"}), ffmpeg_bin,
        )


def _decode_sequential(
    path: Path, metadata: TechnicalMetadata, output_dir: Path,
    config: SamplingConfig, ffmpeg_bin: str,
) -> list[ProbeFrame]:
    """Decode short clips once; keep the existing target times and selection budget."""
    times = target_probe_times(metadata.duration, config)
    if not times:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    # selected_n counts emitted frames. Each threshold selects the first source
    # frame at or after that target, without scaling every decoded source frame.
    thresholds = "+".join(f"gte(t,{t:.6f})" for t in times)
    command = [ffmpeg_bin, "-v", "error", "-threads", "2"]
    if config.hardware_acceleration != "none":
        command.extend(["-hwaccel", config.hardware_acceleration])
    command.extend([
        "-i", str(path), "-an", "-sn", "-dn", "-filter_threads", "1",
        "-vf", f"setpts=PTS-STARTPTS,select='gt({thresholds},selected_n)',{_scale_filter(config.probe_max_edge)}",
        "-vsync", "0", "-frames:v", str(len(times)), "-q:v", "3",
        "-start_number", "0", "-y", str(output_dir / "probe-%04d.jpg"),
    ])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise SamplingError("ffmpeg_missing", f"ffmpeg not found: {ffmpeg_bin}") from exc
    if completed.returncode != 0:
        raise SamplingError("decode_failed", completed.stderr.strip() or "sequential decode failed")
    frames = []
    for index, timestamp in enumerate(times):
        image = cv2.imread(str(output_dir / f"probe-{index:04d}.jpg"))
        if image is not None:
            frames.append(ProbeFrame(timestamp=timestamp, image=image))
    if len(frames) != len(times):
        raise SamplingError("incomplete_frames", f"Expected {len(times)} probe frames, decoded {len(frames)}")
    return frames


def _decode_seek(
    path: Path, metadata: TechnicalMetadata, output_dir: Path,
    config: SamplingConfig, ffmpeg_bin: str,
) -> list[ProbeFrame]:
    times = target_probe_times(metadata.duration, config)
    if not times:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[ProbeFrame] = []
    for index, timestamp in enumerate(times):
        image_path = output_dir / f"probe-{index:04d}.jpg"
        command = [ffmpeg_bin, "-v", "error"]
        if config.hardware_acceleration != "none":
            command.extend(["-hwaccel", config.hardware_acceleration])
        command.extend([
            "-ss",
            f"{timestamp:.6f}",
            "-i",
            str(path),
            "-an",
            "-frames:v",
            "1",
            "-vf",
            _scale_filter(config.probe_max_edge),
            "-q:v",
            "3",
            "-y",
            str(image_path),
        ])
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise SamplingError("ffmpeg_missing", f"ffmpeg not found: {ffmpeg_bin}") from exc
        if completed.returncode != 0:
            raise SamplingError("decode_failed", completed.stderr.strip() or "ffmpeg probe decode failed")
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        frames.append(ProbeFrame(timestamp=timestamp, image=image))
    if not frames:
        raise SamplingError("no_decodable_frames", f"No frames decoded from {path.name}")
    return frames


def perceptual_hash(image: np.ndarray) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in bits.flat:
        value = (value << 1) | int(bit)
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _nearest_frame(frames: Sequence[ProbeFrame], target: float) -> ProbeFrame:
    return min(frames, key=lambda frame: abs(frame.timestamp - target))


def _motion_candidates(frames: Sequence[ProbeFrame]) -> list[tuple[float, int]]:
    scored: list[tuple[float, int]] = []
    for index in range(1, len(frames)):
        previous = cv2.cvtColor(frames[index - 1].image, cv2.COLOR_BGR2GRAY)
        current = cv2.cvtColor(frames[index].image, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        magnitude = np.linalg.norm(flow, axis=2)
        diagonal = np.hypot(current.shape[0], current.shape[1])
        delta = max(frames[index].timestamp - frames[index - 1].timestamp, 1e-3)
        scored.append((float(np.median(magnitude) / (diagonal * delta)), index))
    return sorted(scored, reverse=True)


def _hsv_histogram(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(histogram, histogram)
    return histogram


def _scene_candidates(frames: Sequence[ProbeFrame]) -> list[tuple[float, int]]:
    histograms = [_hsv_histogram(frame.image) for frame in frames]
    scores = [
        (float(cv2.compareHist(histograms[index - 1], histograms[index], cv2.HISTCMP_BHATTACHARYYA)), index)
        for index in range(1, len(frames))
    ]
    return sorted(scores, reverse=True)


def _add_candidate(
    selected: list[FrameCandidate],
    frame: ProbeFrame,
    reason: Reason,
    score: float,
    duration: float,
    deduplicate_visuals: bool = True,
) -> None:
    minimum_gap = max(0.25, duration * 0.08)
    frame_hash = perceptual_hash(frame.image)
    for candidate in selected:
        if abs(candidate.timestamp - frame.timestamp) <= minimum_gap:
            if reason not in candidate.reasons:
                candidate.reasons.append(reason)
            candidate.score = max(candidate.score, score)
            return
        if deduplicate_visuals and _hamming(perceptual_hash(candidate.image), frame_hash) <= 5:
            if reason not in candidate.reasons:
                candidate.reasons.append(reason)
            candidate.score = max(candidate.score, score)
            return
    selected.append(FrameCandidate(frame.timestamp, frame.image, [reason], score))


def select_representatives(
    frames: Sequence[ProbeFrame],
    duration: float,
    profile: Literal["temporal3", "adaptive5"],
) -> list[FrameCandidate]:
    if not frames:
        return []
    selected: list[FrameCandidate] = []
    for fraction in (0.2, 0.5, 0.8):
        _add_candidate(
            selected,
            _nearest_frame(frames, duration * fraction),
            "temporal",
            1.0,
            duration,
            deduplicate_visuals=profile == "adaptive5",
        )
    if profile == "adaptive5" and len(frames) > 1:
        motion = _motion_candidates(frames)
        scene = _scene_candidates(frames)
        if motion:
            score, index = motion[0]
            _add_candidate(selected, frames[index], "motion", score, duration)
        if scene:
            score, index = scene[0]
            _add_candidate(selected, frames[index], "scene_change", score, duration)
    return sorted(selected[:5], key=lambda candidate: candidate.timestamp)


def extract_representative_thumbnails(
    path: Path,
    candidates: Sequence[FrameCandidate],
    output_dir: Path,
    max_edge: int = 720,
    ffmpeg_bin: str = "ffmpeg",
) -> list[FrameRecord]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[FrameRecord] = []
    for index, candidate in enumerate(candidates):
        output = output_dir / f"{round(candidate.timestamp * 1000):08d}-{index:02d}.jpg"
        command = [
            ffmpeg_bin,
            "-v",
            "error",
            "-ss",
            f"{candidate.timestamp:.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            _scale_filter(max_edge),
            "-q:v",
            "2",
            "-y",
            str(output),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0 or not output.exists():
            raise SamplingError("thumbnail_failed", completed.stderr.strip() or f"No thumbnail at {candidate.timestamp}")
        records.append(
            FrameRecord(
                timestamp=candidate.timestamp,
                reasons=candidate.reasons,
                thumbnail_relpath=output.as_posix(),
            )
        )
    return records
