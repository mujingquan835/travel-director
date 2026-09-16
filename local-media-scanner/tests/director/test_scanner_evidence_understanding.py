from __future__ import annotations

import hashlib
import json
from pathlib import Path

from director import scanner_bridge
from scanner.schema import ErrorRecord, ScannerResult


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "scanner_result_exp09.json"
)
SOURCE_HASHES = {
    "2026_02_06_18_26_40_IMG_0229.MOV": "49c62b132b8544179ce149ec978d429c8c2143864f27e79aa1bc57548264d230",
    "2026_02_06_18_39_36_IMG_0233.MOV": "220853e618d4d9a4fd96604353c550f357a4e8bf84261ee5deb34299712a2954",
    "2026_02_06_19_12_26_IMG_0244.MOV": "30cd7169efe7ba70764aa7a5aafd6d9ec7ec92726bcc12a99e684d79ceeb3432",
}


def load_saved_result() -> ScannerResult:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.setdefault("requested_device", "mps")
    payload.setdefault("actual_device", "mps")
    return ScannerResult.model_validate(payload)


def build_saved_observations(result: ScannerResult | None = None):
    payload = result or load_saved_result()
    return scanner_bridge.build_scanner_only_observations(
        payload,
        source_hashes=SOURCE_HASHES,
        artifact_path=str(FIXTURE),
        artifact_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
    )


def assertions_by_field(observation) -> dict[str, object]:
    return {row.field: row for row in observation.assertions}


def test_saved_scanner_json_maps_technical_and_cv_values_as_measured() -> None:
    batch = build_saved_observations()

    assert batch.mode == "scanner_only"
    assert batch.status == "partial"
    assert len(batch.items) == 3
    first = batch.items[0]
    assertions = assertions_by_field(first)
    assert assertions["duration_seconds"].status == "measured"
    assert assertions["orientation"].value == "landscape"
    assert assertions["brightness_score"].status == "measured"
    assert assertions["motion_intensity_raw"].status == "measured"
    assert all(
        row.evidence_refs[0].artifact_path == str(FIXTURE)
        for row in assertions.values()
        if row.evidence_refs
    )


def test_people_lower_bound_and_weak_semantics_never_become_confirmed_facts() -> None:
    batch = build_saved_observations()
    people_item = next(
        item
        for item in batch.items
        if item.material.relative_path == "2026_02_06_18_39_36_IMG_0233.MOV"
    )
    assertions = assertions_by_field(people_item)

    assert assertions["people_count_lower_bound"].value == 2
    assert assertions["people_count_lower_bound"].status == "candidate"
    assert "people_count" not in assertions
    assert assertions["subject_candidates"].status == "abstained"
    assert assertions["subject_candidates"].value is None
    assert "location" not in assertions
    assert "confirmed_scene" not in assertions
    assert set(people_item.review_required_fields) >= {
        "content_families",
        "setting",
        "lighting",
        "people_presence",
        "people_count_band",
    }


def test_scanner_only_v02_contains_no_recommended_ranges() -> None:
    batch = build_saved_observations()
    payload = json.loads(batch.model_dump_json())

    assert all("recommended_ranges" not in item for item in payload["items"])
    assert all("source_in" not in item and "source_out" not in item for item in payload["items"])


def test_one_failed_material_is_unavailable_without_blocking_other_items() -> None:
    result = load_saved_result()
    result.items[0].analysis_status = "failed"
    result.items[0].errors = [
        ErrorRecord(stage="decode", code="fixture_failure", message="saved failure")
    ]

    batch = build_saved_observations(result)

    assert batch.status == "partial"
    assert batch.items[0].observation_status == "unavailable"
    assert batch.items[0].errors[0].code == "fixture_failure"
    assert all(
        item.observation_status != "unavailable" for item in batch.items[1:]
    )
