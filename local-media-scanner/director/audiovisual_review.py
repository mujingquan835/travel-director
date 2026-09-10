"""Subjective audiovisual listening and viewing review orchestration and receipt recording."""

from __future__ import annotations

import json
from pathlib import Path

from director.audiovisual_review_schema import AudiovisualReviewReport
from director.fcpxml_delivery import _atomic_write_json, _sha256


def record_audiovisual_review(receipt_path: Path, review_path: Path) -> dict:
    """Record subjective audiovisual review only after validating against schema and FCPXML integrity."""

    receipt_path = receipt_path.expanduser().resolve()
    review_path = review_path.expanduser().resolve()

    if not receipt_path.is_file():
        raise ValueError(f"receipt does not exist: {receipt_path}")
    if not review_path.is_file():
        raise ValueError(f"audiovisual review report does not exist: {review_path}")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") not in {"fcpxml_generated", "fcpxml_client_accepted"}:
        raise ValueError(
            "recording audiovisual review requires an existing fcpxml_generated or fcpxml_client_accepted receipt"
        )

    fcpxml_path = Path(receipt["fcpxml_path"])
    if not fcpxml_path.is_file() or _sha256(fcpxml_path) != receipt.get("fcpxml_sha256"):
        raise ValueError("FCPXML is missing or differs from the generated receipt")

    # Strict validation of review report against schema
    report = AudiovisualReviewReport.model_validate_json(review_path.read_text(encoding="utf-8"))

    # Update receipt with audiovisual review data
    audiovisual_status = "reviewed" if report.overall_verdict == "accepted" else "needs_revision"
    receipt["audiovisual_status"] = audiovisual_status
    receipt["audiovisual_review"] = report.model_dump(mode="json")

    # Close the loop on mix listening status if subjective review passed
    if report.overall_verdict == "accepted":
        if "music_adaptation" in receipt and isinstance(receipt["music_adaptation"], dict):
            receipt["music_adaptation"]["mix_listening_status"] = "reviewed"
        if "sound_design" in receipt and isinstance(receipt["sound_design"], dict):
            receipt["sound_design"]["mix_listening_status"] = "reviewed"
    else:
        if "music_adaptation" in receipt and isinstance(receipt["music_adaptation"], dict):
            receipt["music_adaptation"]["mix_listening_status"] = "needs_revision"
        if "sound_design" in receipt and isinstance(receipt["sound_design"], dict):
            receipt["sound_design"]["mix_listening_status"] = "needs_revision"

    _atomic_write_json(receipt_path, receipt)

    return {
        "status": audiovisual_status,
        "receipt_path": str(receipt_path),
        "reviewer": report.reviewer,
        "listening_environment": report.listening_environment,
        "reviewed_at": report.reviewed_at.isoformat(),
        "overall_verdict": report.overall_verdict,
        "silent_picture_verdict": report.silent_picture.verdict,
        "audio_only_verdict": report.audio_only.verdict,
        "combined_verdict": report.combined.verdict,
        "comparisons_count": len(report.comparisons) if report.comparisons else 0,
        "recommendations_count": len(report.revision_recommendations),
    }


def inspect_audiovisual_review(receipt_path: Path) -> dict:
    """Inspect and re-verify recorded audiovisual review in a receipt."""

    receipt_path = receipt_path.expanduser().resolve()
    if not receipt_path.is_file():
        raise ValueError(f"receipt does not exist: {receipt_path}")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if "audiovisual_review" not in receipt:
        raise ValueError("receipt contains no audiovisual review")

    report = AudiovisualReviewReport.model_validate(receipt["audiovisual_review"])
    expected_status = "reviewed" if report.overall_verdict == "accepted" else "needs_revision"
    if receipt.get("audiovisual_status") != expected_status:
        raise ValueError(
            f"audiovisual_status mismatch: expected {expected_status}, found {receipt.get('audiovisual_status')}"
        )

    if report.overall_verdict == "accepted":
        if "music_adaptation" in receipt and isinstance(receipt["music_adaptation"], dict):
            if receipt["music_adaptation"].get("mix_listening_status") != "reviewed":
                raise ValueError("music_adaptation mix_listening_status is not 'reviewed'")
        if "sound_design" in receipt and isinstance(receipt["sound_design"], dict):
            if receipt["sound_design"].get("mix_listening_status") != "reviewed":
                raise ValueError("sound_design mix_listening_status is not 'reviewed'")

    return {
        "status": receipt.get("audiovisual_status"),
        "receipt_path": str(receipt_path),
        "reviewer": report.reviewer,
        "listening_environment": report.listening_environment,
        "reviewed_at": report.reviewed_at.isoformat(),
        "overall_verdict": report.overall_verdict,
        "silent_picture_verdict": report.silent_picture.verdict,
        "audio_only_verdict": report.audio_only.verdict,
        "combined_verdict": report.combined.verdict,
        "comparisons_count": len(report.comparisons) if report.comparisons else 0,
        "recommendations": report.revision_recommendations,
    }
