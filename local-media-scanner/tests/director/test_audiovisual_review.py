from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from director.audiovisual_review import inspect_audiovisual_review, record_audiovisual_review
from director.audiovisual_review_schema import (
    AudioOnlyReview,
    AudiovisualReviewReport,
    CombinedReview,
    SilentPictureReview,
    VariantComparison,
)
from director.cli import app
from director.fcpxml_delivery import export_fcpxml_decision
from tests.director.test_fcpxml_delivery import _decision, _media_fixture


def _valid_report_dict(verdict: str = "accepted") -> dict:
    sub_verdict = "acceptable" if verdict == "accepted" else "needs_revision"
    return {
        "reviewer": "Director Reviewer",
        "listening_environment": "studio_monitor_headphones",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "silent_picture": {
            "temporal_flow": "Pacing feels natural across consecutive cuts without dragging or micro-stutters.",
            "event_clarity": "Vehicle motion and road presence are immediately readable by viewers.",
            "cut_connection_validity": "Cut is motivated by subject vehicle moving through frame with directional match.",
            "verdict": sub_verdict,
            "notes": "Silent picture flow passes visual inspection with strong narrative continuity.",
        },
        "audio_only": {
            "ambient_continuity": "Background environment maintains room tone without abrupt cut restarts.",
            "foley_anchor_sync": "Vehicle whoosh sound accent lands accurately on visual occlusion with 0.15s pre-roll.",
            "dynamic_range_and_planes": "Sound effects occupy midground while music ducks cleanly during accent moments.",
            "verdict": sub_verdict,
            "notes": "Audio mix has clear spatial depth and realistic acoustic pre-roll.",
        },
        "combined": {
            "foreground_competition": "Music and foley do not fight for foreground; sound accent breathes naturally.",
            "rhythm_breathing": "Audiovisual impact arrives together at 1.467s visual event.",
            "verdict": sub_verdict,
            "notes": "Combined audiovisual performance achieves satisfying dramatic impact.",
        },
        "comparisons": [
            {
                "variant_id": "A_baseline",
                "description": "Baseline cut with naive file-start alignment and un-ducked music.",
                "findings": "Sound accent arrives 150ms late; music clashes with foley transient.",
                "verdict": "baseline",
            },
            {
                "variant_id": "C_sound_revised",
                "description": "Pre-roll acoustic alignment with 0.45 gain and tailored fade-out.",
                "findings": "Transient lands exactly on vehicle occlusion; music pause breathes naturally.",
                "verdict": "improved",
            },
        ],
        "overall_verdict": verdict,
        "revision_recommendations": [] if verdict == "accepted" else ["Reduce foley gain by 1.5dB to prevent masking."],
    }


def test_record_audiovisual_review_accepted(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)
    package = tmp_path / "package"
    exported = export_fcpxml_decision(decision, package)

    # Mock music_adaptation and sound_design in receipt to test mix_listening_status update
    receipt_data = json.loads(exported.receipt_path.read_text(encoding="utf-8"))
    receipt_data["music_adaptation"] = {"mix_listening_status": "not_reviewed"}
    receipt_data["sound_design"] = {"mix_listening_status": "not_reviewed"}
    exported.receipt_path.write_text(json.dumps(receipt_data), encoding="utf-8")

    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps(_valid_report_dict("accepted")), encoding="utf-8")

    result = record_audiovisual_review(exported.receipt_path, review_file)
    assert result["status"] == "reviewed"
    assert result["overall_verdict"] == "accepted"
    assert result["comparisons_count"] == 2

    # Check receipt contents
    updated_receipt = json.loads(exported.receipt_path.read_text(encoding="utf-8"))
    assert updated_receipt["audiovisual_status"] == "reviewed"
    assert updated_receipt["audiovisual_review"]["reviewer"] == "Director Reviewer"
    assert updated_receipt["music_adaptation"]["mix_listening_status"] == "reviewed"
    assert updated_receipt["sound_design"]["mix_listening_status"] == "reviewed"

    # Inspect command
    inspected = inspect_audiovisual_review(exported.receipt_path)
    assert inspected["status"] == "reviewed"
    assert inspected["overall_verdict"] == "accepted"


def test_record_audiovisual_review_needs_revision(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)
    package = tmp_path / "package"
    exported = export_fcpxml_decision(decision, package)

    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps(_valid_report_dict("needs_revision")), encoding="utf-8")

    result = record_audiovisual_review(exported.receipt_path, review_file)
    assert result["status"] == "needs_revision"
    assert result["overall_verdict"] == "needs_revision"
    assert result["recommendations_count"] == 1

    inspected = inspect_audiovisual_review(exported.receipt_path)
    assert inspected["status"] == "needs_revision"


def test_schema_rejects_inconsistent_verdict() -> None:
    data = _valid_report_dict("accepted")
    # Inconsistency: sub-review needs_revision but overall accepted
    data["silent_picture"]["verdict"] = "needs_revision"
    with pytest.raises(ValueError, match="cannot declare overall_verdict='accepted'"):
        AudiovisualReviewReport.model_validate(data)


def test_schema_requires_recommendations_on_needs_revision() -> None:
    data = _valid_report_dict("needs_revision")
    data["revision_recommendations"] = []
    with pytest.raises(ValueError, match="requires at least one revision recommendation"):
        AudiovisualReviewReport.model_validate(data)


def test_schema_requires_timezone_aware_date() -> None:
    data = _valid_report_dict("accepted")
    data["reviewed_at"] = "2026-09-10T12:00:00"  # No timezone
    with pytest.raises(ValueError, match="timezone-aware"):
        AudiovisualReviewReport.model_validate(data)


def test_record_audiovisual_review_rejects_tampered_fcpxml(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)
    package = tmp_path / "package"
    exported = export_fcpxml_decision(decision, package)

    # Tamper with FCPXML
    exported.fcpxml_path.write_text("<tampered/>", encoding="utf-8")

    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps(_valid_report_dict("accepted")), encoding="utf-8")

    with pytest.raises(ValueError, match="FCPXML is missing or differs"):
        record_audiovisual_review(exported.receipt_path, review_file)


def test_cli_record_and_inspect_audiovisual_review(tmp_path: Path) -> None:
    video, music, sfx = _media_fixture(tmp_path)
    decision = tmp_path / "decision.json"
    _decision(decision, video, music, sfx)
    package = tmp_path / "package"
    exported = export_fcpxml_decision(decision, package)

    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps(_valid_report_dict("accepted")), encoding="utf-8")

    runner = CliRunner()
    rec_result = runner.invoke(
        app,
        [
            "record-audiovisual-review",
            "--receipt",
            str(exported.receipt_path),
            "--review",
            str(review_file),
        ],
    )
    assert rec_result.exit_code == 0
    parsed = json.loads(rec_result.stdout)
    assert parsed["status"] == "reviewed"

    insp_result = runner.invoke(
        app,
        [
            "inspect-audiovisual-review",
            "--receipt",
            str(exported.receipt_path),
        ],
    )
    assert insp_result.exit_code == 0
    insp_parsed = json.loads(insp_result.stdout)
    assert insp_parsed["overall_verdict"] == "accepted"
