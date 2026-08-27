"""Traditional computer-vision measurements with uncalibrated raw outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

from scanner.sampling import ProbeFrame
from scanner.schema import MotionMetrics, QualityMetrics


@dataclass(frozen=True)
class FrameQualityRaw:
    laplacian_variance: float
    brightness_score: float
    dark_pixel_ratio: float
    bright_pixel_ratio: float


def _luminance(image: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(image.astype(np.float32))
    return 0.0722 * b + 0.7152 * g + 0.2126 * r


def frame_quality(image: np.ndarray) -> FrameQualityRaw:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    luminance = _luminance(image)
    return FrameQualityRaw(
        laplacian_variance=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        brightness_score=float(np.mean(luminance) / 255.0),
        dark_pixel_ratio=float(np.mean(luminance <= 5.0)),
        bright_pixel_ratio=float(np.mean(luminance >= 250.0)),
    )


def _exposure_status(brightness: float, dark_ratio: float, bright_ratio: float) -> str:
    if dark_ratio > 0.25 and bright_ratio > 0.15:
        return "mixed"
    if brightness < 0.18 and dark_ratio > 0.35:
        return "underexposed"
    if brightness > 0.82 and bright_ratio > 0.20:
        return "overexposed"
    return "normal"


def aggregate_quality(frames: Sequence[ProbeFrame]) -> QualityMetrics:
    if not frames:
        return QualityMetrics()
    measured = [frame_quality(frame.image) for frame in frames]
    laplacian = float(np.median([item.laplacian_variance for item in measured]))
    brightness = float(np.median([item.brightness_score for item in measured]))
    dark_ratio = float(np.median([item.dark_pixel_ratio for item in measured]))
    bright_ratio = float(np.median([item.bright_pixel_ratio for item in measured]))
    return QualityMetrics(
        laplacian_variance_raw=laplacian,
        blur_score=None,
        brightness_score=brightness,
        dark_pixel_ratio=dark_ratio,
        bright_pixel_ratio=bright_ratio,
        exposure_status=_exposure_status(brightness, dark_ratio, bright_ratio),
        quality_score=None,
    )


def measure_motion(frames: Sequence[ProbeFrame]) -> MotionMetrics:
    if len(frames) < 2:
        return MotionMetrics()
    intensities: list[float] = []
    direction_ratios: list[float] = []
    luma_changes: list[float] = []
    for previous_frame, current_frame in zip(frames, frames[1:]):
        previous = cv2.cvtColor(previous_frame.image, cv2.COLOR_BGR2GRAY)
        current = cv2.cvtColor(current_frame.image, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        magnitude = np.linalg.norm(flow, axis=2)
        diagonal = float(np.hypot(current.shape[0], current.shape[1]))
        delta = max(current_frame.timestamp - previous_frame.timestamp, 1e-3)
        intensities.append(float(np.median(magnitude) / (diagonal * delta)))

        mean_magnitude = float(np.mean(magnitude))
        if mean_magnitude <= 1e-8:
            direction_ratios.append(0.0)
        else:
            mean_vector = np.mean(flow.reshape(-1, 2), axis=0)
            direction_ratios.append(float(np.clip(np.linalg.norm(mean_vector) / mean_magnitude, 0.0, 1.0)))

        luma_difference = np.abs(current.astype(np.float32) - previous.astype(np.float32)) / 255.0
        luma_changes.append(float(np.percentile(luma_difference, 90)))

    return MotionMetrics(
        motion_intensity_raw=float(np.median(intensities)),
        motion_intensity=None,
        motion_level="unknown",
        static_or_dynamic="unknown",
        directional_motion_ratio=float(np.median(direction_ratios)),
        luma_change_p90=float(max(luma_changes)),
    )

