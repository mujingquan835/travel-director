"""Deterministic contracts for routing visual-understanding review work."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from director.visual_schema import ClipObservationBatch, VisualStrictModel


ReviewChannel = Literal["none", "chat", "local_page"]


class ReviewQuestion(VisualStrictModel):
    material_id: str
    relative_path: str
    fields: list[str]


class ReviewRoute(VisualStrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    channel: ReviewChannel
    pending_field_count: int = Field(ge=0)
    affected_material_count: int = Field(ge=0)
    questions: list[ReviewQuestion]
    reasons: list[str]


class ChatReviewBatch(VisualStrictModel):
    material_ids: list[str] = Field(min_length=1, max_length=3)
    questions: list[ReviewQuestion]


class PreparedVisualReview(VisualStrictModel):
    route: ReviewRoute
    chat_batches: list[ChatReviewBatch]
    html_path: str | None = None
    confirmation_path: str | None = None


def choose_review_route(
    observations: ClipObservationBatch,
    *,
    max_chat_fields: int = 5,
    max_chat_materials: int = 3,
    force_local_page: bool = False,
) -> ReviewRoute:
    """Choose a stable review channel from pending observation fields."""

    if max_chat_fields < 1 or max_chat_materials < 1:
        raise ValueError("review thresholds must be positive")

    fields_by_material: dict[str, tuple[str, set[str]]] = {}
    for item in observations.items:
        if not item.review_required_fields:
            continue
        material_id = item.material.material_id
        entry = fields_by_material.setdefault(
            material_id, (item.material.relative_path, set())
        )
        if item.material.relative_path < entry[0]:
            entry = (item.material.relative_path, entry[1])
            fields_by_material[material_id] = entry
        entry[1].update(item.review_required_fields)

    questions = [
        ReviewQuestion(
            material_id=material_id,
            relative_path=relative_path,
            fields=sorted(fields),
        )
        for material_id, (relative_path, fields) in sorted(
            fields_by_material.items(), key=lambda row: row[1][0]
        )
    ]
    pending = sum(len(question.fields) for question in questions)
    if pending == 0:
        channel: ReviewChannel = "none"
    elif (
        force_local_page
        or pending > max_chat_fields
        or len(questions) > max_chat_materials
    ):
        channel = "local_page"
    else:
        channel = "chat"
    return ReviewRoute(
        channel=channel,
        pending_field_count=pending,
        affected_material_count=len(questions),
        questions=questions,
        reasons=[f"pending_fields={pending}", f"affected_materials={len(questions)}"],
    )
