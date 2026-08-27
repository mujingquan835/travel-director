from __future__ import annotations

import cv2
import numpy as np
from typer.testing import CliRunner

from scanner.cli import app
from scanner.cv_metrics import aggregate_quality, frame_quality, measure_motion
from scanner.metadata import build_manifest
from scanner.sampling import ProbeFrame


def _checkerboard(width: int = 160, height: int = 120) -> np.ndarray:
    yy, xx = np.indices((height, width))
    gray = (((xx // 8) + (yy // 8)) % 2 * 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _sequence(images: list[np.ndarray]) -> list[ProbeFrame]:
    return [ProbeFrame(timestamp=float(index), image=image) for index, image in enumerate(images)]


def test_blur_reduces_laplacian_variance() -> None:
    sharp = _checkerboard()
    blurred = cv2.GaussianBlur(sharp, (21, 21), 0)

    assert frame_quality(sharp).laplacian_variance > frame_quality(blurred).laplacian_variance


def test_brightness_and_clipping_follow_expected_direction() -> None:
    dark = np.full((120, 160, 3), 5, np.uint8)
    bright = np.full((120, 160, 3), 250, np.uint8)

    dark_metrics = frame_quality(dark)
    bright_metrics = frame_quality(bright)
    assert dark_metrics.brightness_score < bright_metrics.brightness_score
    assert dark_metrics.dark_pixel_ratio > 0.9
    assert bright_metrics.bright_pixel_ratio > 0.9


def test_aggregate_quality_keeps_uncalibrated_scores_null() -> None:
    quality = aggregate_quality(_sequence([_checkerboard(), _checkerboard()]))

    assert quality.laplacian_variance_raw is not None
    assert quality.blur_score is None
    assert quality.quality_score is None


def test_motion_is_higher_for_translated_pattern() -> None:
    base = _checkerboard()
    static = _sequence([base, base.copy(), base.copy()])
    moving = _sequence([np.roll(base, shift, axis=1) for shift in (0, 4, 8)])

    assert measure_motion(moving).motion_intensity_raw > measure_motion(static).motion_intensity_raw


def test_consistent_pan_has_directional_motion_evidence() -> None:
    base = _checkerboard()
    pan = _sequence([np.roll(base, shift, axis=1) for shift in (0, 3, 6, 9)])

    assert measure_motion(pan).directional_motion_ratio > 0.7


def test_luma_change_detects_a_brightness_flash() -> None:
    dark = np.full((120, 160, 3), 20, np.uint8)
    bright = np.full((120, 160, 3), 230, np.uint8)

    assert measure_motion(_sequence([dark, bright])).luma_change_p90 > 0.7


def test_cv_profile_command_writes_raw_metrics(sample_video, tmp_path) -> None:
    manifest = build_manifest(sample_video.parent, [sample_video])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    output = tmp_path / "cv-run"

    result = CliRunner().invoke(
        app,
        ["cv-profile", "--manifest", str(manifest_path), "--output", str(output)],
    )

    assert result.exit_code == 0
    payload = (output / "cv_profile.json").read_text(encoding="utf-8")
    assert '"laplacian_variance_raw"' in payload
    assert '"motion_intensity_raw"' in payload
    assert '"quality_score": null' in payload
