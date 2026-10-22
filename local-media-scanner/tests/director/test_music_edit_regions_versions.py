"""Regions draft/confirm versions are not music_version child projects.

Slice 1 of the confirm desk: one project holds an editable draft, immutable
confirmed snapshots, and read-only history. Export must name a confirmed id.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from director.music_edit_regions_schema import MusicEditRegion, MusicEditRegions
from director.music_edit_regions_versions import (
    RegionsActionReceipt,
    RegionsConfirmGateError,
    RegionsVersionError,
    confirm_regions_draft,
    current_regions_baseline,
    discard_regions_draft,
    export_fcpxml_for_confirmed_regions,
    is_regions_version_state_key,
    list_regions_receipts,
    list_regions_versions,
    load_regions_draft,
    load_regions_version,
    record_regions_export_receipt,
    replace_regions_version,
    require_confirmed_regions_version,
    save_regions_draft,
    stage_regions_reanalysis,
)
from director.schema import MusicEnding


SHA = "a" * 64
OTHER_SHA = "b" * 64


def _region(
    region_id: str,
    start: float,
    end: float,
    role: str,
    *,
    proxy: str,
    basis: str = "energy",
    content_need: str,
    shot: tuple[float, float, float],
) -> MusicEditRegion:
    mean, low, high = shot
    return MusicEditRegion(
        region_id=region_id,
        start=start,
        end=end,
        edit_role=role,
        musical_proxy=proxy,
        mean_energy=0.4,
        onset_rate=1.0,
        energy_slope=0.0,
        suggested_shot_mean_s=mean,
        shot_min_s=low,
        shot_max_s=high,
        snap_policy="free",
        desired_motion="low",
        content_need=content_need,
        confidence=0.5,
        evidence_basis=basis,
    )


def _document(source_sha256: str = SHA, *, middle_role: str = "narrative_hold") -> MusicEditRegions:
    """30s cover with a settle_outro closing window. Middle role is swappable."""

    return MusicEditRegions(
        source_sha256=source_sha256,
        duration_seconds=30.0,
        bpm=120.0,
        provider="heuristic_v1",
        downbeat_detector="every_fourth_beat",
        regions=[
            _region(
                "r1", 0.0, 10.0, "establish", proxy="intro",
                content_need="orientation_detail", shot=(3.2, 2.5, 4.0),
            ),
            _region(
                "r2", 10.0, 22.0, middle_role, proxy="rise",
                content_need="scenic_or_story", shot=(4.0, 3.0, 5.5),
            ),
            _region(
                "r3", 22.0, 30.0, "settle_outro", proxy="outro",
                content_need="closing_image", shot=(3.5, 2.5, 4.5),
            ),
        ],
        ending=MusicEnding(last_onset_seconds=28.0, behavior="decay"),
        confidence=0.5,
    )


def _with_role(document: MusicEditRegions, region_id: str, role: str, basis: str = "manual") -> MusicEditRegions:
    regions = [
        region.model_copy(update={"edit_role": role, "evidence_basis": basis})
        if region.region_id == region_id
        else region
        for region in document.regions
    ]
    return document.model_copy(update={"regions": regions})


def _project(tmp_path: Path):
    from director.project import create_visual_project
    from director.visual_schema import RawCreativeBrief

    return create_visual_project(
        tmp_path / "runs", "demo", RawCreativeBrief(raw_description="60秒旅行视频")
    )


def _listing(paths, version_id: str):
    return next(item for item in list_regions_versions(paths) if item.version_id == version_id)


def _confirmed_bytes(paths, version_id: str) -> bytes:
    return (paths.root / "music_edit_regions_versions" / "confirmed" / f"{version_id}.json").read_bytes()


def test_draft_listing_names_status_and_source_sha8_without_confirmed_at(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    document = _document()

    draft = save_regions_draft(paths, document)

    assert draft.status == "draft"
    assert draft.version_id == "regions-v01"
    assert draft.source_music_sha8 == SHA[:8]
    assert draft.confirmed_at is None
    assert draft.edited_at
    listing = _listing(paths, draft.version_id)
    assert listing.status == "draft"
    assert listing.source_music_sha8 == SHA[:8]
    assert listing.confirmed_at is None
    assert (paths.root / "music_edit_regions_versions" / "draft.json").is_file()
    assert (paths.root / "music_edit_regions_versions" / "index.json").is_file()
    receipts = list_regions_receipts(paths)
    assert [item.action for item in receipts] == ["draft_save"]
    assert receipts[0].version_id == "regions-v01"
    assert receipts[0].override is False
    assert receipts[0].reason is None


def test_confirm_locks_version_and_refuses_mutation(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    draft = save_regions_draft(paths, _document())

    listing = confirm_regions_draft(paths)

    assert listing.version_id == draft.version_id
    assert listing.status == "confirmed"
    assert listing.source_music_sha8 == SHA[:8]
    datetime.fromisoformat(listing.confirmed_at)
    stored = load_regions_version(paths, listing.version_id)
    assert stored.status == "confirmed"
    assert stored.regions.shot_track_locked is True
    assert stored.regions.guide_version == "creator-0.1"
    assert stored.confirmed_by == "user"
    assert stored.confirmed_at == listing.confirmed_at
    assert load_regions_draft(paths) is None
    assert not (paths.root / "music_edit_regions_versions" / "draft.json").exists()
    before = _confirmed_bytes(paths, listing.version_id)
    edited = _with_role(_document(), "r1", "narrative_hold")
    with pytest.raises(RegionsVersionError, match="immutable"):
        replace_regions_version(paths, listing.version_id, edited)
    assert _confirmed_bytes(paths, listing.version_id) == before
    with pytest.raises(RegionsVersionError, match="draft"):
        confirm_regions_draft(paths)
    assert _confirmed_bytes(paths, listing.version_id) == before
    from director.project import load_project_state

    hashes = load_project_state(paths).completed_artifact_hashes
    assert "music_edit_regions_version_draft" not in hashes
    assert hashes[f"music_edit_regions_version:{listing.version_id}"]
    confirm_receipts = [item for item in list_regions_receipts(paths) if item.action == "confirm"]
    assert len(confirm_receipts) == 1
    assert confirm_receipts[0].override is False
    assert confirm_receipts[0].reason is None
    assert confirm_receipts[0].version_id == listing.version_id


def test_second_confirm_keeps_prior_confirmed_as_read_only_history(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _document())
    first = confirm_regions_draft(paths)
    first_bytes = _confirmed_bytes(paths, first.version_id)
    save_regions_draft(paths, _with_role(_document(), "r1", "narrative_hold"))
    second = confirm_regions_draft(paths)

    assert first.version_id == "regions-v01"
    assert second.version_id == "regions-v02"
    assert _listing(paths, first.version_id).status == "history"
    assert _listing(paths, second.version_id).status == "confirmed"
    assert _listing(paths, first.version_id).confirmed_at
    assert _listing(paths, second.version_id).confirmed_at
    assert load_regions_version(paths, first.version_id).status == "confirmed"
    assert _confirmed_bytes(paths, first.version_id) == first_bytes
    with pytest.raises(RegionsVersionError, match="immutable"):
        replace_regions_version(paths, first.version_id, _document(middle_role="breath"))
    assert _confirmed_bytes(paths, first.version_id) == first_bytes


def test_force_confirm_requires_non_empty_reason_and_records_override(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _document(middle_role="unknown"))

    with pytest.raises(RegionsVersionError, match="unknown"):
        confirm_regions_draft(paths)
    with pytest.raises(RegionsVersionError, match="reason"):
        confirm_regions_draft(paths, force=True, reason=None)
    with pytest.raises(RegionsVersionError, match="reason"):
        confirm_regions_draft(paths, force=True, reason="   ")
    assert list_regions_versions(paths)[0].status == "draft"
    assert not (paths.root / "music_edit_regions_versions" / "confirmed").exists() or not any(
        (paths.root / "music_edit_regions_versions" / "confirmed").glob("*.json")
    )

    listing = confirm_regions_draft(paths, force=True, reason="  keep the unknown bridge  ")

    assert listing.status == "confirmed"
    receipt = next(item for item in list_regions_receipts(paths) if item.action == "confirm")
    assert receipt.override is True
    assert receipt.reason == "keep the unknown bridge"
    assert load_regions_version(paths, listing.version_id).regions.regions[1].edit_role == "unknown"


def test_clean_confirm_rejects_a_reason_without_force(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _document())

    with pytest.raises(RegionsVersionError, match="force"):
        confirm_regions_draft(paths, reason="not asked")

    assert load_regions_draft(paths) is not None
    assert not any(item.action == "confirm" for item in list_regions_receipts(paths))


def test_discard_draft_restores_confirmed_baseline(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    original = _document()
    save_regions_draft(paths, original)
    confirmed = confirm_regions_draft(paths)
    baseline = current_regions_baseline(paths)
    assert baseline.kind == "confirmed"
    assert baseline.version_id == confirmed.version_id
    assert baseline.source_music_sha8 == SHA[:8]
    before = _confirmed_bytes(paths, confirmed.version_id)

    edited = save_regions_draft(paths, _with_role(original, "r1", "narrative_hold"))
    assert edited.version_id == "regions-v02"
    assert edited.parent_version_id == confirmed.version_id
    assert load_regions_draft(paths).regions != load_regions_version(paths, confirmed.version_id).regions

    restored = discard_regions_draft(paths)

    assert restored == baseline
    assert load_regions_draft(paths) is None
    assert current_regions_baseline(paths) == baseline
    assert _confirmed_bytes(paths, confirmed.version_id) == before
    assert [item.version_id for item in list_regions_versions(paths)] == [confirmed.version_id]


def test_discard_draft_restores_analyzer_baseline_and_leaves_it_untouched(tmp_path: Path) -> None:
    from director.project import record_supporting_artifact

    paths = _project(tmp_path)
    original = _document()
    record_supporting_artifact(
        paths, paths.music_edit_regions, original, state_key="music_edit_regions"
    )
    original_bytes = paths.music_edit_regions.read_bytes()
    baseline = current_regions_baseline(paths)
    assert baseline.kind == "analyzer"
    assert baseline.version_id is None
    assert baseline.source_music_sha8 == SHA[:8]

    save_regions_draft(paths, _with_role(original, "r1", "hook"))
    restored = discard_regions_draft(paths)

    assert restored == baseline
    assert current_regions_baseline(paths) == baseline
    assert load_regions_draft(paths) is None
    assert list_regions_versions(paths) == []
    assert paths.music_edit_regions.read_bytes() == original_bytes


def test_discarded_draft_id_is_not_reused(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    first = save_regions_draft(paths, _document())

    discard_regions_draft(paths)
    second = save_regions_draft(paths, _document())

    assert first.version_id == "regions-v01"
    assert second.version_id == "regions-v02"
    assert load_regions_draft(paths).version_id == "regions-v02"


def test_discard_without_draft_is_a_no_write(tmp_path: Path) -> None:
    paths = _project(tmp_path)

    with pytest.raises(RegionsVersionError, match="draft"):
        discard_regions_draft(paths)

    assert not (paths.root / "music_edit_regions_versions").exists()


def test_export_gate_refuses_missing_id_latest_and_draft(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    draft = save_regions_draft(paths, _document())
    output = tmp_path / "package"

    for version_id in (None, "", "  ", "latest", "draft", draft.version_id):
        with pytest.raises(RegionsConfirmGateError):
            require_confirmed_regions_version(paths, version_id)
        with pytest.raises(RegionsConfirmGateError):
            export_fcpxml_for_confirmed_regions(paths, version_id, output)

    assert not output.exists()
    assert list(tmp_path.rglob("project.fcpxml")) == []


def test_export_gate_accepts_only_an_explicit_confirmed_or_history_id(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _document())
    first = confirm_regions_draft(paths)
    save_regions_draft(paths, _with_role(_document(), "r1", "narrative_hold"))
    second = confirm_regions_draft(paths)
    output = tmp_path / "package"

    with pytest.raises(RegionsConfirmGateError):
        require_confirmed_regions_version(paths, None)
    selected = require_confirmed_regions_version(paths, first.version_id)
    assert selected.version_id == first.version_id
    assert require_confirmed_regions_version(paths, second.version_id).version_id == second.version_id
    with pytest.raises(NotImplementedError, match="Slice 1"):
        export_fcpxml_for_confirmed_regions(paths, second.version_id, output)

    assert not output.exists()
    assert list(tmp_path.rglob("project.fcpxml")) == []


def test_receipt_schema_accepts_rerun_and_export_and_persists_export_hook(tmp_path: Path) -> None:
    created_at = "2026-10-19T00:00:00+00:00"
    for action in ("rerun", "export"):
        receipt = RegionsActionReceipt(
            receipt_id=f"regions-receipt-{action}",
            action=action,
            version_id="regions-v01",
            source_music_sha8=SHA[:8],
            created_at=created_at,
            regions_sha256=SHA,
        )
        assert receipt.action == action
        assert receipt.override is False
    with pytest.raises(ValidationError):
        RegionsActionReceipt(
            receipt_id="regions-receipt-bad",
            action="confirm",
            version_id="regions-v01",
            source_music_sha8=SHA[:8],
            created_at=created_at,
            regions_sha256=SHA,
            override=True,
            reason="   ",
        )

    paths = _project(tmp_path)
    save_regions_draft(paths, _document())
    confirmed = confirm_regions_draft(paths)
    with pytest.raises(RegionsConfirmGateError):
        record_regions_export_receipt(paths, "regions-v01-draft")
    draft = save_regions_draft(paths, _with_role(_document(), "r1", "narrative_hold"))
    with pytest.raises(RegionsConfirmGateError):
        record_regions_export_receipt(paths, draft.version_id)

    stored = record_regions_export_receipt(paths, confirmed.version_id)

    assert stored.action == "export"
    assert stored.version_id == confirmed.version_id
    assert stored.override is False
    assert any(
        item.action == "export" and item.receipt_id == stored.receipt_id
        for item in list_regions_receipts(paths)
    )
    assert list(tmp_path.rglob("project.fcpxml")) == []
    assert (paths.root / "music_edit_regions_versions" / "receipts" / f"{stored.receipt_id}.json").is_file()


def test_reanalysis_opens_or_replaces_a_draft_and_does_not_touch_confirmed(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _document())
    confirmed = confirm_regions_draft(paths)
    before = _confirmed_bytes(paths, confirmed.version_id)
    revised = _with_role(_document(), "r1", "narrative_hold")

    staged = stage_regions_reanalysis(paths, revised)

    assert staged.status == "draft"
    assert staged.version_id == "regions-v02"
    assert staged.parent_version_id == confirmed.version_id
    assert staged.regions == revised
    assert _confirmed_bytes(paths, confirmed.version_id) == before
    assert any(item.action == "rerun" and item.version_id == staged.version_id for item in list_regions_receipts(paths))

    again = stage_regions_reanalysis(paths, _with_role(_document(), "r1", "build"))
    assert again.version_id == staged.version_id
    assert again.regions.regions[0].edit_role == "build"
    from director.shot_slots import freeze_shot_track

    assert load_regions_version(paths, confirmed.version_id).regions == freeze_shot_track(_document())
    assert _confirmed_bytes(paths, confirmed.version_id) == before
    assert [item.status for item in list_regions_versions(paths)] == ["confirmed", "draft"]


def test_reanalysis_replaces_an_unconfirmed_draft(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _document())

    staged = stage_regions_reanalysis(paths, _with_role(_document(), "r2", "breath"))

    assert staged.version_id == "regions-v01"
    assert staged.regions.regions[1].edit_role == "breath"
    assert [item.version_id for item in list_regions_versions(paths)] == ["regions-v01"]
    assert not (paths.root / "music_edit_regions_versions" / "confirmed").exists()


def test_regions_versions_stay_on_one_track(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    save_regions_draft(paths, _document())

    with pytest.raises(RegionsVersionError, match="music_version"):
        save_regions_draft(paths, _document(OTHER_SHA))

    assert load_regions_draft(paths).source_music_sha256 == SHA


def test_regions_version_hash_keys_do_not_include_analyzer_artifact() -> None:
    assert is_regions_version_state_key("music_edit_regions_versions_index")
    assert is_regions_version_state_key("music_edit_regions_version_draft")
    assert is_regions_version_state_key("music_edit_regions_version:regions-v01")
    assert is_regions_version_state_key("music_edit_regions_receipt:regions-receipt-01")
    assert not is_regions_version_state_key("music_edit_regions")


def test_new_track_copy_excludes_regions_version_directory() -> None:
    from director.music_version import EVIDENCE_COPY_EXCLUDED

    assert "music_edit_regions_versions" in EVIDENCE_COPY_EXCLUDED
    assert "music_edit_regions.json" in EVIDENCE_COPY_EXCLUDED


def test_project_reanalyze_stages_a_draft_without_overwriting_confirmed(
    tmp_path: Path, click_track: Path
) -> None:
    from director.audio_import import freeze_and_analyze_music
    from director.music_edit_regions import build_project_music_edit_regions, load_music_edit_regions

    paths = _project(tmp_path)
    freeze_and_analyze_music(paths, click_track)
    build_project_music_edit_regions(paths.root)
    analyzed = load_music_edit_regions(paths)
    assert analyzed is not None
    save_regions_draft(paths, analyzed)
    if any(region.edit_role == "unknown" for region in analyzed.regions):
        confirmed = confirm_regions_draft(
            paths, force=True, reason="analyzer left an unknown region"
        )
    else:
        confirmed = confirm_regions_draft(paths)
    before = _confirmed_bytes(paths, confirmed.version_id)

    build_project_music_edit_regions(paths.root)

    assert _confirmed_bytes(paths, confirmed.version_id) == before
    draft = load_regions_draft(paths)
    assert draft is not None
    assert draft.version_id != confirmed.version_id
    assert draft.status == "draft"
    assert any(item.action == "rerun" for item in list_regions_receipts(paths))
