from __future__ import annotations

from scanner.roles import infer_material_roles
from scanner.schema import (
    ConfidenceScore,
    ContentAnalysis,
    MotionMetrics,
    QualityMetrics,
    ScannerCard,
    SourceRecord,
    TechnicalMetadata,
)


def _card() -> ScannerCard:
    return ScannerCard(
        file="person.mov",
        source=SourceRecord(relative_path="person.mov", size_bytes=1, mtime_ns=1),
        analysis_status="complete",
        technical=TechnicalMetadata(
            duration=8,
            width=1920,
            height=1080,
            fps=30,
            orientation="landscape",
            codec="h264",
        ),
        quality=QualityMetrics(exposure_status="normal"),
        motion=MotionMetrics(
            motion_level="medium",
            static_or_dynamic="dynamic",
            directional_motion_ratio=0.8,
        ),
        content=ContentAnalysis(
            people_present=True,
            people_count_estimate=2,
            people_type=["adult"],
            scene_type="theme_park",
            main_objects=["person", "building"],
            simple_action="walking",
        ),
        shot_scale="medium",
        confidence={
            "content.people_present": ConfidenceScore(score=0.9, source="detector"),
            "content.simple_action": ConfidenceScore(score=0.7, source="vision"),
            "motion.directional_motion_ratio": ConfidenceScore(score=0.9, source="cv"),
            "motion.motion_level": ConfidenceScore(score=0.7, source="cv"),
        },
    )


def test_role_candidate_has_rules_and_inputs() -> None:
    roles, evidence = infer_material_roles(_card())

    assert "human_story" in roles
    assert evidence["human_story"].rules
    assert "content.people_present" in evidence["human_story"].inputs
    assert not {"opening", "climax", "ending"} & set(roles)


def test_role_score_is_limited_by_input_confidence() -> None:
    roles, evidence = infer_material_roles(_card())

    assert "human_story" in roles
    assert evidence["human_story"].score == 0.765
    assert evidence["experience"].score == 0.504
    assert evidence["transition"].score == 0.42


def test_unusable_or_unknown_content_does_not_invent_roles() -> None:
    card = _card().model_copy(
        update={
            "content": ContentAnalysis(),
            "motion": MotionMetrics(),
            "shot_scale": None,
        }
    )

    roles, evidence = infer_material_roles(card)

    assert roles == []
    assert evidence == {}
