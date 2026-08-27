"""Explainable intrinsic Material Role candidates, never Editorial Roles."""

from __future__ import annotations

from scanner.schema import MaterialRole, RoleEvidence, ScannerCard


def infer_material_roles(
    card: ScannerCard,
) -> tuple[list[MaterialRole], dict[MaterialRole, RoleEvidence]]:
    roles: list[MaterialRole] = []
    evidence: dict[MaterialRole, RoleEvidence] = {}

    def add(role: MaterialRole, factor: float, rule: str, inputs: list[str]) -> None:
        if role in evidence:
            return
        input_scores = [card.confidence[key].score for key in inputs if key in card.confidence]
        if len(input_scores) != len(inputs):
            return
        score = round(max(0.0, min(1.0, min(input_scores))) * factor, 6)
        roles.append(role)
        evidence[role] = RoleEvidence(score=score, rules=[rule], inputs=inputs)

    if card.content.people_present is True:
        add(
            "human_story",
            0.85,
            "visible people provide human-story evidence",
            ["content.people_present"],
        )
    if card.content.scene_type is not None and card.shot_scale == "wide":
        add(
            "environment",
            0.8,
            "wide framing with a known scene supports environment coverage",
            ["content.scene_type", "shot_scale"],
        )
    if card.content.simple_action is not None:
        add(
            "experience",
            0.72,
            "a concrete observable action supports travel experience",
            ["content.simple_action"],
        )
    if card.shot_scale == "close_up" or (
        card.shot_scale == "close" and card.content.main_objects
    ):
        add(
            "detail",
            0.76,
            "tight framing with an identifiable object supports detail use",
            ["shot_scale", "content.main_objects"],
        )
    if (
        card.motion.directional_motion_ratio is not None
        and card.motion.directional_motion_ratio >= 0.75
        and card.motion.motion_level in {"medium", "high"}
    ):
        add(
            "transition",
            0.6,
            "directionally consistent camera or subject motion is transition evidence",
            ["motion.directional_motion_ratio", "motion.motion_level"],
        )
    if (
        card.content.scene_type in {"nature", "night_scene"}
        and card.motion.motion_level in {"low", "medium"}
    ):
        add(
            "atmosphere",
            0.65,
            "nature or night imagery with restrained motion supports atmosphere",
            ["content.scene_type", "motion.motion_level"],
        )
    return roles, evidence
