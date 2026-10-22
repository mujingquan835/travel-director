"""Similar songs and later versions must not share one fast-cut rhythm."""

from __future__ import annotations

import hashlib
import json

from director.shot_slots import plan_shot_slots
from director.shot_track.creator_guidance import creator_guidance, timing_hash
from director.shot_track.differentiate import diversity_documents, prior_from_regions
from director.shot_track.fastcut import MIN_SLOT_S, build_grid, validate
from director.music_edit_regions_versions import confirm_regions_draft, load_regions_version, save_regions_draft
from tests.director.test_music_edit_regions_versions import _confirmed_bytes, _project
from tests.director.test_shot_slots import _document, _region

R_MIN = 0.2
T_MIN = 0.5


def _song(accent_at: set[int], *, confidence: float = 0.8, detector: str = "onset_phase_heuristic"):
    regions = [
        _region("r01", 0.0, 8.0, "hook", (0.9, 0.6, 1.2)),
        _region("r02", 8.0, 24.0, "establish", (3.2, 2.5, 4.0)),
        _region("r03", 24.0, 40.0, "build", (2.0, 1.5, 2.5)),
        _region("r04", 40.0, 52.0, "peak_cut", (1.0, 0.5, 1.4)),
        _region("r05", 52.0, 60.0, "settle_outro", (3.5, 2.5, 4.0)),
    ]
    document = _document(regions, 60.0, accent_at=accent_at)
    return document.model_copy(
        update={"downbeat_confidence": confidence, "downbeat_detector": detector}
    )


def _travel(document, version_id: str, prior=None):
    return plan_shot_slots(document, style="travel", version_id=version_id, prior=prior or [])


def _assert_d(left, right) -> dict:
    score = diversity_documents(left, right)
    assert score["T"] >= T_MIN, score
    assert score["R"] >= R_MIN, score
    assert score["M"] == 1, score
    return score


def _desk(document) -> dict:
    return {
        "beats_seconds": list(document.beats_seconds),
        "downbeats_seconds": list(document.downbeats_seconds),
        "regions": [
            {"region_id": region.region_id, "start": region.start, "end": region.end, "edit_role": region.edit_role}
            for region in document.regions
        ],
        "duration_seconds": document.duration_seconds,
        "phrases": [],
    }


def _rows(document) -> list[dict]:
    return [
        {
            "slot_id": slot.slot_id,
            "region_id": slot.region_id,
            "region_role": next(region.edit_role for region in document.regions if region.region_id == slot.region_id),
            "start": slot.start,
            "end": slot.end,
            "length_s": slot.end - slot.start,
            "beats": slot.beat_length if slot.beat_length is not None else float(slot.beats),
            "shot_type": slot.shot_type,
            "pattern_role": slot.pattern_role,
            "flurry_group": slot.flurry_group,
            "cut_on": slot.cut_on,
            "ramp": slot.ramp,
            "transition": slot.transition or "cut",
            "flash": bool(slot.flash),
        }
        for slot in document.shot_slots
    ]


def test_similar_songs_change_theme_and_rhythm():
    left = _travel(_song({0, 4, 16, 32}), "regions-v01")
    right = _travel(_song({0, 8, 20, 36}), "regions-v01")
    score = _assert_d(left, right)
    assert left.technique_theme_id != right.technique_theme_id
    assert left.technique_theme_id
    assert right.technique_theme_id
    assert score["M"] == 1


def test_three_versions_of_one_song_diverge_pairwise():
    song = _song({0, 4, 16, 32})
    first = _travel(song, "regions-v01")
    second = _travel(song, "regions-v02", prior=[prior_from_regions(first)])
    third = _travel(song, "regions-v03", prior=[prior_from_regions(first), prior_from_regions(second)])
    themes = {first.technique_theme_id, second.technique_theme_id, third.technique_theme_id}
    assert len(themes) == 3
    _assert_d(first, second)
    _assert_d(first, third)
    _assert_d(second, third)


def test_same_seed_is_byte_identical():
    song = _song({0, 4, 16, 32})
    options = {"style": "travel", "intensity": "standard"}
    first = plan_shot_slots(song, style="travel", version_id="regions-v01", user_options=options)
    second = plan_shot_slots(song, style="travel", version_id="regions-v01", user_options=options)
    assert first.technique_seed == second.technique_seed
    assert len(first.technique_seed) == 64
    digest = hashlib.sha256(first.model_dump_json().encode()).hexdigest()
    assert digest == hashlib.sha256(second.model_dump_json().encode()).hexdigest()


def test_cuts_stay_on_the_grid_and_pass_validation():
    song = _song({0, 4, 16, 32})
    planned = _travel(song, "regions-v01")
    grid = [moment for moment, _kind in build_grid(song.beats_seconds)]
    grid.extend(region.start for region in song.regions)
    grid.append(song.duration_seconds)
    for slot in planned.shot_slots:
        assert any(abs(slot.start - moment) <= 0.02 for moment in grid), slot.slot_id
        assert slot.end - slot.start >= MIN_SLOT_S - 1e-6
    rows = _rows(planned)
    assert validate(rows, _desk(planned), 0.5) == []
    guided = creator_guidance(rows, _desk(planned), "travel")
    assert timing_hash(rows) == timing_hash(guided)


def test_budget_spacing_evidence_and_contrast_taboo():
    planned = _travel(_song({0, 4, 16, 32}), "regions-v01")
    uses = planned.technique_uses
    assert uses
    assert len({use.technique_id for use in uses}) <= 3
    assert len(uses) <= 6
    assert len(uses) == len({use.region_id for use in uses})
    assert 2 <= len(uses) <= 3
    assert any(use.region_role == "peak_cut" for use in uses)
    downbeats = list(planned.downbeats_seconds)
    bars = []
    for use in uses:
        assert use.evidence_zh.strip()
        bars.append(sum(1 for beat in downbeats if beat <= use.anchor_s + 0.06))
    assert all(abs(left - right) >= 2 for left, right in zip(sorted(bars), sorted(bars)[1:]))

    quiet = _travel(_song({0, 4, 16, 32}, confidence=0.4), "regions-v01")
    assert all(use.technique_id != "contrast_rhythm" for use in quiet.technique_uses)
    heuristic = _travel(
        _song({0, 4, 16, 32}, detector="every_fourth_beat"),
        "regions-v01",
    )
    assert all(use.technique_id != "contrast_rhythm" for use in heuristic.technique_uses)


def test_confirmed_snapshot_keeps_the_theme_when_rules_change(tmp_path, monkeypatch):
    from director.shot_track import fastcut

    song = _song({0, 8, 20, 36})
    paths = _project(tmp_path)
    save_regions_draft(paths, plan_shot_slots(song, style="travel"))
    listing = confirm_regions_draft(paths)
    confirmed = load_regions_version(paths, listing.version_id)
    assert confirmed.regions.technique_seed
    assert confirmed.regions.technique_theme_id
    assert confirmed.regions.shot_track_locked is True
    before = _confirmed_bytes(paths, listing.version_id)
    frozen = json.dumps(
        [slot.model_dump(mode="json") for slot in confirmed.regions.shot_slots],
        ensure_ascii=False,
        sort_keys=True,
    )
    monkeypatch.setattr(fastcut, "RULES_VERSION", "fastcut-9.9")
    again = load_regions_version(paths, listing.version_id)
    assert _confirmed_bytes(paths, listing.version_id) == before
    assert again.regions.technique_theme_id == confirmed.regions.technique_theme_id
    assert (
        json.dumps(
            [slot.model_dump(mode="json") for slot in again.regions.shot_slots],
            ensure_ascii=False,
            sort_keys=True,
        )
        == frozen
    )
