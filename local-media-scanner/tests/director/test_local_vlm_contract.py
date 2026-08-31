from __future__ import annotations

import json

import pytest

from director import providers
from director.visual_schema import MaterialRef
import director.visual_understanding as visual_understanding


SOURCE_SHA256 = "a" * 64
MATERIAL_ID = f"sha256:{SOURCE_SHA256}"


def material() -> MaterialRef:
    return MaterialRef(
        material_id=MATERIAL_ID,
        relative_path="trip/clip-01.mov",
        source_sha256=SOURCE_SHA256,
        size_bytes=1024,
        mtime_ns=123,
        duration_seconds=8.5,
        fps=25.0,
        orientation="portrait",
    )


def valid_response(*, low_confidence: bool = False) -> str:
    payload = {
        "technical_usability": "usable",
        "content_families": ["culture_architecture"],
        "setting": "outdoor",
        "lighting": "daylight",
        "people_presence": "present",
        "people_count_band": "few",
        "subject_candidates": ["古建筑", "游客"],
        "activity_candidates": ["步行"],
        "unknown_fields": [],
        "confidence_by_field": {
            "technical_usability": 0.92,
            "content_families": 0.88,
            "setting": 0.84,
            "lighting": 0.9,
            "people_presence": 0.91,
            "people_count_band": 0.78,
            "subject_candidates": 0.82,
            "activity_candidates": 0.4 if low_confidence else 0.76,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def config():
    return visual_understanding.LocalVlmConfig(
        model_id="mlx-community/Qwen3-VL-4B-Instruct-4bit",
        revision="2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b",
        runtime_package="mlx-vlm",
        runtime_version="0.6.17",
        review_confidence_threshold=0.7,
    )


def evidence() -> dict:
    return {
        "frame_paths": [
            "benchmark/probe/clip-01-00.jpg",
            "benchmark/probe/clip-01-01.jpg",
        ],
        "response_artifact_path": "runs/task4/clip-01-response.json",
    }


def test_provider_contract_is_local_weighted_and_abstention_capable() -> None:
    provider = visual_understanding.LocalVlmProvider(
        config(), lambda *_args: valid_response()
    )

    assert isinstance(provider, providers.VisualUnderstandingProvider)
    assert provider.capabilities.local_only is True
    assert provider.capabilities.requires_model_weights is True
    assert provider.capabilities.supports_abstention is True
    assert provider.capabilities.output_schema_version == "0.2.0"


def test_strict_fake_response_becomes_auditable_automatic_observation() -> None:
    provider = visual_understanding.LocalVlmProvider(
        config(), lambda *_args: valid_response()
    )

    observation = provider.observe(material(), evidence())
    assertions = {row.field: row for row in observation.assertions}

    assert observation.provider == "local_vlm"
    assert observation.observation_status == "automatic"
    assert observation.review_required_fields == []
    assert assertions["content_families"].value == ["culture_architecture"]
    assert assertions["content_families"].status == "candidate"
    assert assertions["content_families"].evidence_refs[0].source_kind == "visual_provider"
    assert assertions["content_families"].evidence_refs[0].sha256 is not None
    payload = observation.model_dump(mode="json")
    assert "source_in" not in payload
    assert "source_out" not in payload
    assert "recommended_ranges" not in payload


def test_low_confidence_field_requires_review_without_blocking_other_fields() -> None:
    provider = visual_understanding.LocalVlmProvider(
        config(), lambda *_args: valid_response(low_confidence=True)
    )

    observation = provider.observe(material(), evidence())
    assertions = {row.field: row for row in observation.assertions}

    assert observation.observation_status == "abstained"
    assert observation.review_required_fields == ["activity_candidates"]
    assert assertions["activity_candidates"].status == "candidate"
    assert assertions["content_families"].status == "candidate"


def test_parser_rejects_location_identity_or_editorial_fields() -> None:
    payload = json.loads(valid_response())
    payload["location"] = "开封"
    payload["best_range"] = {"source_in": 1.0, "source_out": 2.0}

    with pytest.raises(ValueError, match="invalid local VLM response"):
        visual_understanding.parse_local_vlm_response(
            json.dumps(payload, ensure_ascii=False)
        )


def test_parser_rejects_missing_confidence_for_supported_field() -> None:
    payload = json.loads(valid_response())
    del payload["confidence_by_field"]["lighting"]

    with pytest.raises(ValueError, match="confidence"):
        visual_understanding.parse_local_vlm_response(
            json.dumps(payload, ensure_ascii=False)
        )


def test_parser_accepts_fenced_json_but_not_freeform_repair() -> None:
    parsed = visual_understanding.parse_local_vlm_response(
        f"```json\n{valid_response()}\n```"
    )

    assert parsed.setting == "outdoor"
    with pytest.raises(ValueError, match="invalid local VLM response"):
        visual_understanding.parse_local_vlm_response("我看到了一座古建筑")


def test_parser_rejects_unknown_mixed_with_supported_content_family() -> None:
    payload = json.loads(valid_response())
    payload["content_families"] = ["unknown", "urban"]

    with pytest.raises(ValueError, match="unknown"):
        visual_understanding.parse_local_vlm_response(
            json.dumps(payload, ensure_ascii=False)
        )


def test_parser_rejects_people_presence_and_count_contradiction() -> None:
    payload = json.loads(valid_response())
    payload["people_presence"] = "absent"
    payload["people_count_band"] = "few"

    with pytest.raises(ValueError, match="people"):
        visual_understanding.parse_local_vlm_response(
            json.dumps(payload, ensure_ascii=False)
        )
