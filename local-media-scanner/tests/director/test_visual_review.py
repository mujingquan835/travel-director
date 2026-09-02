from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from director.cli import app
from director.evaluation import (
    FieldConfirmation,
    GroundTruthRecord,
    VisualConfirmation,
)
from director.visual_review import (
    apply_visual_confirmation,
    build_automatic_director_review,
    prepare_visual_review,
    render_director_review,
    render_visual_review,
    validate_director_review,
    validate_visual_confirmation_against_observations,
)
from director.agent_batches import MaterialFrameMap, MaterialFrameSet, RepresentativeFrame
from director.visual_schema import (
    ClipObservation,
    ClipObservationBatch,
    DirectorReview,
    DirectorTreatment,
    EvidenceRef,
    MaterialRef,
    ObservationAssertion,
    TreatmentChapter,
)


SOURCE_HASH = "a" * 64
MATERIAL_ID = f"sha256:{SOURCE_HASH}"


def observations() -> ClipObservationBatch:
    evidence = EvidenceRef(
        material_id=MATERIAL_ID,
        artifact_path="scanner_result.json",
        field_path="items[0].technical.orientation",
        source_kind="scanner",
        status="measured",
        sha256="b" * 64,
    )
    return ClipObservationBatch(
        status="partial",
        mode="scanner_only",
        items=[
            ClipObservation(
                material=MaterialRef(
                    material_id=MATERIAL_ID,
                    relative_path="trip/clip-01.mov",
                    source_sha256=SOURCE_HASH,
                    size_bytes=100,
                    mtime_ns=123,
                    duration_seconds=8.5,
                    fps=25,
                    orientation="portrait",
                ),
                provider="scanner_only",
                observation_status="abstained",
                assertions=[
                    ObservationAssertion(
                        field="orientation",
                        value="portrait",
                        status="measured",
                        evidence_refs=[evidence],
                    )
                ],
                unknown_fields=["content_families"],
                review_required_fields=["content_families"],
            )
        ],
    )


def large_review_batch() -> ClipObservationBatch:
    base = observations().items[0]
    return observations().model_copy(
        update={
            "items": [
                base.model_copy(
                    update={
                        "review_required_fields": [
                            "content_families",
                            "setting",
                            "lighting",
                            "people_presence",
                            "people_count_band",
                            "technical_usability",
                        ]
                    }
                )
            ]
        }
    )


@pytest.fixture
def clean_observations() -> ClipObservationBatch:
    return observations().model_copy(
        update={
            "items": [
                observations().items[0].model_copy(
                    update={"review_required_fields": []}
                )
            ]
        }
    )


@pytest.fixture
def small_review_observations() -> ClipObservationBatch:
    return observations()


@pytest.fixture
def large_review_observations() -> ClipObservationBatch:
    return large_review_batch()


@pytest.fixture
def frame_map(tmp_path: Path) -> MaterialFrameMap:
    frame = tmp_path / "probe.jpg"
    Image.new("RGB", (4, 3), "red").save(frame, format="JPEG")
    source = observations().items[0].material
    return MaterialFrameMap(
        items=[
            MaterialFrameSet(
                material=source,
                frames=[RepresentativeFrame(path=str(frame), timestamp=12.345)],
            )
        ]
    )


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "review"


def test_none_route_creates_no_html(
    clean_observations: ClipObservationBatch,
    frame_map: MaterialFrameMap,
    output_dir: Path,
) -> None:
    artifact = prepare_visual_review(clean_observations, frame_map, output_dir)

    assert artifact.html_path is None
    assert not list(output_dir.glob("*.html"))


def test_chat_route_emits_questions_but_no_html(
    small_review_observations: ClipObservationBatch,
    frame_map: MaterialFrameMap,
    output_dir: Path,
) -> None:
    artifact = prepare_visual_review(small_review_observations, frame_map, output_dir)

    assert artifact.route.channel == "chat"
    assert artifact.chat_batches
    assert max(len(batch.material_ids) for batch in artifact.chat_batches) <= 3
    assert artifact.html_path is None
    assert not list(output_dir.glob("*.html"))


def test_local_page_route_emits_self_contained_html(
    large_review_observations: ClipObservationBatch,
    frame_map: MaterialFrameMap,
    output_dir: Path,
) -> None:
    artifact = prepare_visual_review(large_review_observations, frame_map, output_dir)

    html = Path(artifact.html_path).read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "visual_confirmation.json" in html
    assert "data:image/jpeg;base64," in html
    assert "t=12.345s" in html
    assert str(Path(frame_map.items[0].frames[0].path).resolve()) not in html


def test_local_page_hides_materials_that_do_not_need_review(
    large_review_observations: ClipObservationBatch,
    frame_map: MaterialFrameMap,
    output_dir: Path,
) -> None:
    resolved = observations().items[0].model_copy(
        update={
            "material": observations().items[0].material.model_copy(
                update={
                    "material_id": f"sha256:{'c' * 64}",
                    "relative_path": "trip/already-understood.mov",
                    "source_sha256": "c" * 64,
                }
            ),
            "unknown_fields": [],
            "review_required_fields": [],
        }
    )
    batch = large_review_observations.model_copy(
        update={"items": [*large_review_observations.items, resolved]}
    )

    artifact = prepare_visual_review(batch, frame_map, output_dir)

    html = Path(artifact.html_path).read_text(encoding="utf-8")
    assert "请帮旅行导演看懂这 1 段画面" in html
    assert "already-understood.mov" not in html


def test_local_page_route_rejects_missing_or_nonlocal_frames(
    large_review_observations: ClipObservationBatch,
    output_dir: Path,
) -> None:
    source = observations().items[0].material
    missing = MaterialFrameMap(
        items=[
            MaterialFrameSet(
                material=source,
                frames=[
                    RepresentativeFrame(
                        path=str((output_dir.parent / "missing.jpg").resolve()),
                        timestamp=1.0,
                    )
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="missing local representative frame"):
        prepare_visual_review(large_review_observations, missing, output_dir)

    remote = MaterialFrameMap(
        items=[
            MaterialFrameSet(
                material=source,
                frames=[
                    RepresentativeFrame(
                        path="https://example.com/frame.jpg",
                        timestamp=1.0,
                    )
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="missing local representative frame"):
        prepare_visual_review(large_review_observations, remote, output_dir)


def confirmation(source_hash: str) -> VisualConfirmation:
    return VisualConfirmation(
        source_observations_sha256=source_hash,
        status="completed",
        reviewer="manual-review",
        items=[
            FieldConfirmation(
                material_id=MATERIAL_ID,
                field="content_families",
                original_value=None,
                original_status="abstained",
                confirmed_value=["culture_architecture"],
                confirmed_status="confirmed",
                reviewer_note="画面明确为古建筑",
                changed_at="2026-08-31T15:00:00+08:00",
            )
        ],
    )


def test_review_page_is_offline_and_exports_confirmation(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jpg"
    Image.new("RGB", (4, 3), "blue").save(probe, format="JPEG")
    output = tmp_path / "review.html"
    render_visual_review(
        observations(),
        {MATERIAL_ID: [RepresentativeFrame(path=str(probe), timestamp=7.25)]},
        output,
    )

    html = output.read_text(encoding="utf-8")
    encoded = base64.b64encode(probe.read_bytes()).decode("ascii")
    assert "trip/clip-01.mov" in html
    assert "画面拍到了什么？" in html
    assert "城市街景" in html
    assert "生成画面确认文件" in html
    assert "输入合法 JSON" not in html
    assert "原值：" not in html
    assert "https://" not in html
    assert "source_in" not in html
    assert "source_out" not in html
    assert f"data:image/jpeg;base64,{encoded}" in html
    assert "t=7.250s" in html
    assert str(probe.resolve()) not in html


def test_confirmation_validation_and_import_preserve_original(tmp_path: Path) -> None:
    draft = observations()
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(draft.model_dump_json(), encoding="utf-8")
    source_hash = __import__("hashlib").sha256(draft_path.read_bytes()).hexdigest()
    confirmed = confirmation(source_hash)
    confirmation_path = tmp_path / "visual_confirmation.json"
    confirmation_path.write_text(confirmed.model_dump_json(), encoding="utf-8")

    validate_visual_confirmation_against_observations(confirmed, draft, source_hash)
    updated = apply_visual_confirmation(draft, confirmed, confirmation_path)

    assert draft.items[0].assertions[0].field == "orientation"
    assert updated.mode == "assisted"
    assertion = next(
        row for row in updated.items[0].assertions if row.field == "content_families"
    )
    assert assertion.status == "confirmed"
    assert assertion.value == ["culture_architecture"]
    assert assertion.evidence_refs[0].source_kind == "user_confirmation"
    assert "content_families" not in updated.items[0].review_required_fields


def test_prepare_visual_review_uses_original_file_bytes_for_confirmation_hash(
    large_review_observations: ClipObservationBatch,
    frame_map: MaterialFrameMap,
    output_dir: Path,
) -> None:
    observations_path = output_dir.parent / "observations.json"
    observations_path.write_text(
        large_review_observations.model_dump_json(indent=2), encoding="utf-8"
    )

    artifact = prepare_visual_review(
        large_review_observations,
        frame_map,
        output_dir,
        source_observations_sha256=__import__("hashlib").sha256(
            observations_path.read_bytes()
        ).hexdigest(),
    )
    html = Path(artifact.html_path).read_text(encoding="utf-8")
    source_hash = __import__("hashlib").sha256(observations_path.read_bytes()).hexdigest()

    assert f"source_observations_sha256:'{source_hash}'" in html

    confirmation_payload = {
        "schema_version": "0.2.0",
        "source_observations_sha256": source_hash,
        "status": "partial",
        "reviewer": "manual-review",
        "items": [
            {
                "material_id": MATERIAL_ID,
                "field": "content_families",
                "original_value": None,
                "original_status": "abstained",
                "confirmed_value": ["culture_architecture"],
                "confirmed_status": "confirmed",
                "reviewer_note": "matches bytes hash",
                "changed_at": "2026-09-01T12:00:00+08:00",
            }
        ],
    }
    confirmed = VisualConfirmation.model_validate(confirmation_payload)
    validate_visual_confirmation_against_observations(
        confirmed, large_review_observations, source_hash
    )


def test_prepare_visual_review_cli_passes_original_file_hash(tmp_path: Path) -> None:
    draft = large_review_batch()
    draft_path = tmp_path / "observations.json"
    draft_path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    frame = tmp_path / "probe.jpg"
    Image.new("RGB", (4, 3), "green").save(frame, format="JPEG")
    frame_map = MaterialFrameMap(
        items=[
            MaterialFrameSet(
                material=draft.items[0].material,
                frames=[RepresentativeFrame(path=str(frame), timestamp=2.5)],
            )
        ]
    )
    frame_map_path = tmp_path / "frame_map.json"
    frame_map_path.write_text(frame_map.model_dump_json(indent=2), encoding="utf-8")
    output_dir = tmp_path / "review"

    result = CliRunner().invoke(
        app,
        [
            "prepare-visual-review",
            "--observations",
            str(draft_path),
            "--frame-map",
            str(frame_map_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads((output_dir / "review_route.json").read_text(encoding="utf-8"))
    html = Path(payload["html_path"]).read_text(encoding="utf-8")
    source_hash = __import__("hashlib").sha256(draft_path.read_bytes()).hexdigest()
    assert f"source_observations_sha256:'{source_hash}'" in html


def test_noncanonical_observations_cli_round_trip_uses_exact_file_hash(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "probe.jpg"
    Image.new("RGB", (4, 3), "purple").save(frame, format="JPEG")
    observations_path = tmp_path / "observations.json"
    observations_path.write_text(
        """{
  "items": [
    {
      "review_required_fields": ["content_families", "setting", "lighting", "people_presence", "people_count_band", "technical_usability"],
      "provider": "scanner_only",
      "material": {
        "orientation": "portrait",
        "fps": 25,
        "duration_seconds": 8.5,
        "mtime_ns": 123,
        "size_bytes": 100,
        "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "relative_path": "trip/clip-01.mov",
        "material_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      },
      "assertions": [
        {
          "evidence_refs": [
            {
              "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
              "status": "measured",
              "source_kind": "scanner",
              "field_path": "items[0].technical.orientation",
              "artifact_path": "scanner_result.json",
              "material_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          ],
          "status": "measured",
          "value": "portrait",
          "field": "orientation"
        }
      ],
      "unknown_fields": ["content_families"],
      "observation_status": "abstained"
    }
  ],
  "mode": "scanner_only",
  "status": "partial",
  "schema_version": "0.2.0"
}
""",
        encoding="utf-8",
    )
    frame_map = MaterialFrameMap(
        items=[
            MaterialFrameSet(
                material=observations().items[0].material,
                frames=[RepresentativeFrame(path=str(frame), timestamp=2.5)],
            )
        ]
    )
    frame_map_path = tmp_path / "frame_map.json"
    frame_map_path.write_text(frame_map.model_dump_json(indent=2), encoding="utf-8")
    output_dir = tmp_path / "review"
    imported_path = tmp_path / "confirmed.json"
    confirmation_path = tmp_path / "visual_confirmation.json"
    runner = CliRunner()

    prepared = runner.invoke(
        app,
        [
            "prepare-visual-review",
            "--observations",
            str(observations_path),
            "--frame-map",
            str(frame_map_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert prepared.exit_code == 0, prepared.output
    route_payload = json.loads((output_dir / "review_route.json").read_text(encoding="utf-8"))
    html = Path(route_payload["html_path"]).read_text(encoding="utf-8")
    source_hash = __import__("hashlib").sha256(observations_path.read_bytes()).hexdigest()
    assert f"source_observations_sha256:'{source_hash}'" in html
    page_hash = re.search(r"source_observations_sha256:'([0-9a-f]{64})'", html)
    assert page_hash is not None
    assert page_hash.group(1) == source_hash

    confirmation_payload = {
        "schema_version": "0.2.0",
        "source_observations_sha256": page_hash.group(1),
        "status": "completed",
        "reviewer": "manual-review",
        "items": [
            {
                "material_id": MATERIAL_ID,
                "field": "content_families",
                "original_value": None,
                "original_status": "abstained",
                "confirmed_value": ["culture_architecture"],
                "confirmed_status": "confirmed",
                "reviewer_note": "family confirmed",
                "changed_at": "2026-09-01T12:00:00+08:00",
            },
            {
                "material_id": MATERIAL_ID,
                "field": "setting",
                "original_value": None,
                "original_status": "abstained",
                "confirmed_value": "outdoor",
                "confirmed_status": "confirmed",
                "reviewer_note": "setting confirmed",
                "changed_at": "2026-09-01T12:00:01+08:00",
            },
            {
                "material_id": MATERIAL_ID,
                "field": "lighting",
                "original_value": None,
                "original_status": "abstained",
                "confirmed_value": "daylight",
                "confirmed_status": "confirmed",
                "reviewer_note": "lighting confirmed",
                "changed_at": "2026-09-01T12:00:02+08:00",
            },
            {
                "material_id": MATERIAL_ID,
                "field": "people_presence",
                "original_value": None,
                "original_status": "abstained",
                "confirmed_value": "absent",
                "confirmed_status": "confirmed",
                "reviewer_note": "people presence confirmed",
                "changed_at": "2026-09-01T12:00:03+08:00",
            },
            {
                "material_id": MATERIAL_ID,
                "field": "people_count_band",
                "original_value": None,
                "original_status": "abstained",
                "confirmed_value": "none",
                "confirmed_status": "confirmed",
                "reviewer_note": "people count confirmed",
                "changed_at": "2026-09-01T12:00:04+08:00",
            },
            {
                "material_id": MATERIAL_ID,
                "field": "technical_usability",
                "original_value": None,
                "original_status": "abstained",
                "confirmed_value": "usable",
                "confirmed_status": "confirmed",
                "reviewer_note": "usability confirmed",
                "changed_at": "2026-09-01T12:00:05+08:00",
            },
        ],
    }
    confirmation_path.write_text(
        json.dumps(confirmation_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    imported = runner.invoke(
        app,
        [
            "import-visual-confirmation",
            "--observations",
            str(observations_path),
            "--confirmation",
            str(confirmation_path),
            "--output",
            str(imported_path),
        ],
    )

    assert imported.exit_code == 0, imported.output
    imported_payload = json.loads(imported_path.read_text(encoding="utf-8"))
    assert imported_payload["status"] == "completed"
    assert imported_payload["mode"] == "assisted"
    assert imported_payload["items"][0]["review_required_fields"] == []
    assert imported_payload["items"][0]["unknown_fields"] == []
    assert {
        assertion["field"] for assertion in imported_payload["items"][0]["assertions"]
    } >= {
        "orientation",
        "content_families",
        "setting",
        "lighting",
        "people_presence",
        "people_count_band",
        "technical_usability",
    }


def test_confirmation_rejects_wrong_hash_or_unknown_field(tmp_path: Path) -> None:
    draft = observations()
    confirmed = confirmation("c" * 64)
    with pytest.raises(ValueError, match="hash"):
        validate_visual_confirmation_against_observations(
            confirmed, draft, "d" * 64
        )

    bad = confirmed.model_copy(
        update={
            "source_observations_sha256": "d" * 64,
            "items": [
                confirmed.items[0].model_copy(update={"field": "invented_field"})
            ],
        }
    )
    with pytest.raises(ValueError, match="unknown field"):
        validate_visual_confirmation_against_observations(bad, draft, "d" * 64)


def test_confirmation_rejects_invalid_enum_value(tmp_path: Path) -> None:
    draft = observations()
    bad = confirmation("d" * 64).model_copy(
        update={
            "items": [
                confirmation("d" * 64).items[0].model_copy(
                    update={"confirmed_value": ["imaginary_category"]}
                )
            ]
        }
    )

    with pytest.raises(ValueError, match="invalid enum"):
        validate_visual_confirmation_against_observations(bad, draft, "d" * 64)


def test_director_review_form_has_overrides_but_no_ranges(tmp_path: Path) -> None:
    evidence = EvidenceRef(
        material_id=MATERIAL_ID,
        artifact_path="confirmed_observations.json",
        field_path="items[0]",
        source_kind="user_confirmation",
        status="confirmed",
        sha256="e" * 64,
    )
    treatment = DirectorTreatment(
        status="completed",
        mode="deterministic",
        logline="进入古城并逐步建立探索感。",
        narrative_spine="进入—探索—收束",
        chapters=[
            TreatmentChapter(
                chapter_id="opening",
                title="进入古城",
                director_functions=["opening"],
                material_ids=[MATERIAL_ID],
                evidence_refs=[evidence],
            )
        ],
        emotional_arc=[
            {"text": "期待", "evidence_refs": [evidence]},
            {"text": "探索", "evidence_refs": [evidence]},
        ],
        pacing_strategy="逐步加速",
        pacing_evidence_refs=[evidence],
        candidate_materials=[MATERIAL_ID],
        coverage_gaps=["ending"],
        evidence_refs=[evidence],
    )
    output = tmp_path / "director-review.html"
    render_director_review(treatment, output)

    html = output.read_text(encoding="utf-8")
    assert "director_review.json" in html
    assert "force_include" in html
    assert "bucket_override" in html
    assert "source_in" not in html
    assert "source_out" not in html


def test_visual_confirmation_cli_validates_and_imports(tmp_path: Path) -> None:
    draft = observations()
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(draft.model_dump_json(), encoding="utf-8")
    source_hash = __import__("hashlib").sha256(draft_path.read_bytes()).hexdigest()
    confirmed = confirmation(source_hash)
    confirmation_path = tmp_path / "confirmation.json"
    confirmation_path.write_text(confirmed.model_dump_json(), encoding="utf-8")
    output = tmp_path / "confirmed.json"
    runner = CliRunner()

    validated = runner.invoke(
        app,
        [
            "validate-visual-confirmation",
            "--observations",
            str(draft_path),
            "--confirmation",
            str(confirmation_path),
        ],
    )
    imported = runner.invoke(
        app,
        [
            "import-visual-confirmation",
            "--observations",
            str(draft_path),
            "--confirmation",
            str(confirmation_path),
            "--output",
            str(output),
        ],
    )

    assert validated.exit_code == 0, validated.output
    assert "valid" in validated.stdout
    assert imported.exit_code == 0, imported.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "assisted"


def test_director_review_cli_validates_hash_and_membership(tmp_path: Path) -> None:
    evidence = EvidenceRef(
        material_id=MATERIAL_ID,
        artifact_path="confirmed_observations.json",
        field_path="items[0]",
        source_kind="user_confirmation",
        status="confirmed",
        sha256="e" * 64,
    )
    treatment = DirectorTreatment(
        status="completed",
        mode="deterministic",
        logline="进入古城并逐步建立探索感。",
        narrative_spine="进入—探索—收束",
        chapters=[
            TreatmentChapter(
                chapter_id="opening",
                title="进入古城",
                director_functions=["opening"],
                material_ids=[MATERIAL_ID],
                evidence_refs=[evidence],
            )
        ],
        emotional_arc=[
            {"text": "期待", "evidence_refs": [evidence]},
            {"text": "探索", "evidence_refs": [evidence]},
        ],
        pacing_strategy="逐步加速",
        pacing_evidence_refs=[evidence],
        candidate_materials=[MATERIAL_ID],
        coverage_gaps=["ending"],
        evidence_refs=[evidence],
    )
    treatment_path = tmp_path / "treatment.json"
    treatment_path.write_text(treatment.model_dump_json(), encoding="utf-8")
    canonical = json.dumps(
        treatment.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    treatment_hash = __import__("hashlib").sha256(canonical.encode()).hexdigest()
    review = DirectorReview(
        treatment_sha256=treatment_hash,
        status="completed",
        mode="automatic",
        overrides=[],
        confirmed_at="2026-08-31T15:00:00+08:00",
    )
    review_path = tmp_path / "director_review.json"
    review_path.write_text(review.model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "validate-director-review",
            "--treatment",
            str(treatment_path),
            "--review",
            str(review_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "valid" in result.stdout


def test_build_automatic_director_review_is_hash_bound() -> None:
    evidence = EvidenceRef(
        material_id=MATERIAL_ID,
        artifact_path="observations.json",
        field_path="items[0].assertions[0]",
        source_kind="user_confirmation",
        status="confirmed",
        confidence=1.0,
        sha256="c" * 64,
    )
    treatment = DirectorTreatment(
        status="completed",
        mode="deterministic",
        logline="进入古城并逐步建立探索感。",
        narrative_spine="进入—探索—收束",
        chapters=[
            TreatmentChapter(
                chapter_id="opening",
                title="进入古城",
                director_functions=["opening"],
                material_ids=[MATERIAL_ID],
                evidence_refs=[evidence],
            )
        ],
        emotional_arc=[
            {"text": "期待", "evidence_refs": [evidence]},
            {"text": "探索", "evidence_refs": [evidence]},
        ],
        pacing_strategy="逐步加速",
        pacing_evidence_refs=[evidence],
        candidate_materials=[MATERIAL_ID],
        coverage_gaps=["ending"],
        evidence_refs=[evidence],
    )

    review = build_automatic_director_review(treatment)

    assert review.status == "completed"
    assert review.mode == "automatic"
    assert review.overrides == []
    assert review.confirmed_at is None
    validate_director_review(review, treatment)


def test_accept_director_treatment_cli_writes_automatic_review(tmp_path: Path) -> None:
    evidence = EvidenceRef(
        material_id=MATERIAL_ID,
        artifact_path="observations.json",
        field_path="items[0].assertions[0]",
        source_kind="user_confirmation",
        status="confirmed",
        confidence=1.0,
        sha256="c" * 64,
    )
    treatment = DirectorTreatment(
        status="completed",
        mode="deterministic",
        logline="进入古城并逐步建立探索感。",
        narrative_spine="进入—探索—收束",
        chapters=[
            TreatmentChapter(
                chapter_id="opening",
                title="进入古城",
                director_functions=["opening"],
                material_ids=[MATERIAL_ID],
                evidence_refs=[evidence],
            )
        ],
        emotional_arc=[
            {"text": "期待", "evidence_refs": [evidence]},
            {"text": "探索", "evidence_refs": [evidence]},
        ],
        pacing_strategy="逐步加速",
        pacing_evidence_refs=[evidence],
        candidate_materials=[MATERIAL_ID],
        coverage_gaps=["ending"],
        evidence_refs=[evidence],
    )
    treatment_path = tmp_path / "treatment.json"
    output = tmp_path / "director_review.json"
    treatment_path.write_text(treatment.model_dump_json(indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "accept-director-treatment",
            "--treatment",
            str(treatment_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "automatic"
    assert payload["overrides"] == []
    assert payload["confirmed_at"] is None
