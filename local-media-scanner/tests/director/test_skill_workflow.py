from __future__ import annotations

import hashlib

import pytest

from director.skill_workflow import choose_review_route
from director.visual_schema import ClipObservation, ClipObservationBatch, MaterialRef


@pytest.fixture
def observation_batch() -> ClipObservationBatch:
    return ClipObservationBatch(
        status="partial",
        mode="scanner_only",
        items=[
            ClipObservation(
                material=MaterialRef(
                    material_id="sha256:" + "a" * 64,
                    relative_path="trip/clip-01.mov",
                    source_sha256="a" * 64,
                    size_bytes=100,
                    mtime_ns=123,
                    duration_seconds=8.5,
                    fps=25,
                    orientation="portrait",
                ),
                provider="scanner_only",
                observation_status="abstained",
            )
        ],
    )


def with_pending(
    observations: ClipObservationBatch, *, count: int, materials: int
) -> ClipObservationBatch:
    items = []
    for index in range(materials):
        source_sha256 = hashlib.sha256(f"material-{index}".encode()).hexdigest()
        fields = [f"field-{field}" for field in range(index, count, materials)]
        items.append(
            ClipObservation(
                material=MaterialRef(
                    material_id=f"sha256:{source_sha256}",
                    relative_path=f"trip/clip-{index + 1:02d}.mov",
                    source_sha256=source_sha256,
                    size_bytes=100,
                    mtime_ns=123,
                    duration_seconds=8.5,
                    fps=25,
                    orientation="portrait",
                ),
                provider="scanner_only",
                observation_status="abstained",
                review_required_fields=fields,
            )
        )
    return observations.model_copy(update={"items": items})


def test_no_pending_fields_requires_no_review(observation_batch):
    route = choose_review_route(observation_batch)
    assert route.channel == "none"
    assert route.pending_field_count == 0


def test_five_fields_across_three_materials_stays_in_chat(observation_batch):
    route = choose_review_route(with_pending(observation_batch, count=5, materials=3))
    assert route.channel == "chat"


@pytest.mark.parametrize("fields,materials", [(6, 3), (5, 4)])
def test_exceeding_either_threshold_requires_local_page(
    observation_batch, fields, materials
):
    route = choose_review_route(
        with_pending(observation_batch, count=fields, materials=materials)
    )
    assert route.channel == "local_page"


def test_explicit_page_request_overrides_small_review(observation_batch):
    pending = with_pending(observation_batch, count=1, materials=1)
    route = choose_review_route(pending, force_local_page=True)
    assert route.channel == "local_page"
