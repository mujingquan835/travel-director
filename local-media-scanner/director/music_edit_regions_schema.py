"""Contract for music edit-region candidates (music_edit_regions.json).

Sibling artifact of ``MusicStructure`` (which keeps its own 0.1.0 schema).
See skills/travel-director/references/music-edit-regions.md for the contract.
Regions are unconfirmed, energy-derived editing hypotheses, never listening
evidence.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

from pydantic import Field, field_validator, model_serializer, model_validator

from director.schema import (
    BeatEvent,
    BeatGridInfo,
    EnergyPoint,
    MusicEnding,
    OnsetEvent,
    PhraseSpan,
    ProviderError,
    StrictModel,
)


BOUNDARY_TOLERANCE_SECONDS = 0.001
OUTRO_WINDOW_MIN_SECONDS = 8.0
OUTRO_WINDOW_RATIO = 0.12
OUTRO_INVARIANT_MIN_DURATION = 12.0
MISSING_SETTLE_OUTRO = "missing_settle_outro"

EditRole = Literal[
    "hook",
    "establish",
    "narrative_hold",
    "build",
    "peak_cut",
    "breath",
    "settle_outro",
    "unknown",
]
MusicalLabel = Literal[
    "intro", "verse", "chorus", "bridge", "drop", "outro", "other", "unknown"
]
MusicalProxy = Literal["intro", "rise", "breath", "climax", "outro", "unknown"]
EditRegionProvider = Literal["heuristic_v1", "allin1", "beat_this+heuristic", "hybrid"]
DownbeatDetector = Literal[
    "every_fourth_beat",
    "onset_phase_heuristic",
    "beat_this",
    "allin1",
    "unknown",
]
ShotType = Literal["远", "细", "动", "脸", "空", "转", "?"]
ShotPace = Literal["hold", "medium", "fast"]
ShotStyle = Literal["narrative", "travel", "event"]
PatternRole = Literal[
    "hero",
    "base",
    "flurry",
    "bridge",
    "hit",
    "ramp_in",
    "lift",
    "breath",
    "final",
    "pickup",
    "placeholder",
]
RampKind = Literal["ramp_in", "ramp_out", "slow", "freeze"]
TransitionKind = Literal["whip", "match", "zoom", "mask", "fade", "cut"]
GuideTransition = Literal["whip", "match", "zoom", "mask", "mask_optional", "fade", "cut", "end"]
ShotSize = Literal["远", "全", "中", "近", "特写", "细节"]
StoryBeat = Literal["钩子", "到达", "探索", "高潮", "回味", "收尾", "待定"]
MotionKind = Literal["→", "←", "hold", "any"]
SoundCue = Literal[
    "嗖声",
    "上升音",
    "重击",
    "只留音乐",
    "环境声提前",
    "环境声延续",
    "现场声抬起",
    "跟音乐收",
]
CutOn = Literal["downbeat", "beat", "half", "edge", "accent"]
ReasonCode = Literal[
    "HOOK_BEAT",
    "PHRASE_START",
    "DOWNBEAT_HOLD",
    "LONG_SHORT",
    "SECTION_TRANSITION",
    "DOWNBEAT_CUT",
    "BUILD_RAMP",
    "PRE_DROP_WHIP",
    "HIT_HOLD",
    "ACCENT_FLURRY",
    "PEAK_BREATH_2BEAT",
    "PEAK_DECEL",
    "POST_PEAK_BREATH",
    "FINAL_HOLD",
    "BREATH_HOLD",
    "ROLE_UNKNOWN_BAR_GRID",
    "GRID_GAP_ONSET",
    "PHRASE_REGULAR",
]
BudgetException = Literal["below_min_ramp", "below_min_transition"]
_NARRATIVE_REASONS = frozenset(get_args(ReasonCode))
_FASTCUT_REASON = re.compile(r"^(TRAVEL|EVENT)_[A-Z0-9_]+$")
_SLOT_STYLE_FIELDS = frozenset(
    {
        "style",
        "pattern_role",
        "flurry_group",
        "ramp",
        "transition",
        "flash",
        "cut_on",
        "rules_version",
        "beat_length",
    }
)
_SLOT_GUIDE_FIELDS = frozenset(
    {
        "shot_size",
        "motion",
        "transition_in",
        "transition_out",
        "sound_cue",
        "story_beat",
        "content_hint",
    }
)
_DOCUMENT_STYLE_FIELDS = frozenset({"shot_style", "shot_rules_version", "guide_version"})


def _omit_empty_style_fields(data: object, keys: frozenset[str]) -> object:
    """Drop unset fastcut fields so a narrative dump stays byte-identical."""

    if isinstance(data, dict):
        for key in keys:
            if data.get(key) is None:
                data.pop(key, None)
        if data.get("sound_cues") == []:
            data.pop("sound_cues", None)
    return data


def outro_window_seconds(duration: float) -> float:
    """Length of the closing window defined by the contract (§6.6, §8)."""

    return max(OUTRO_WINDOW_MIN_SECONDS, OUTRO_WINDOW_RATIO * duration)


class MusicEditRegion(StrictModel):
    region_id: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float
    edit_role: EditRole
    musical_label: MusicalLabel | None = None
    musical_proxy: MusicalProxy
    mean_energy: float = Field(ge=0.0, le=1.0)
    onset_rate: float = Field(ge=0.0)
    energy_slope: float
    suggested_shot_mean_s: float = Field(gt=0.0)
    shot_min_s: float = Field(gt=0.0)
    shot_max_s: float = Field(gt=0.0)
    snap_policy: Literal["downbeat", "beat", "free"]
    desired_motion: Literal["low", "medium", "high"]
    content_need: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_basis: Literal["energy", "structure_model", "hybrid", "manual"]
    cut_summary_zh: str = ""
    slot_count: int = Field(default=0, ge=0)
    start_raw_s: float | None = None
    end_raw_s: float | None = None

    @model_validator(mode="after")
    def positive_length_and_shot_budget(self) -> "MusicEditRegion":
        # Invariant 3 (no negative length) and invariant 4 (shot budget order).
        if self.end <= self.start:
            raise ValueError(f"region {self.region_id} must have end > start")
        if self.shot_max_s <= self.shot_min_s:
            raise ValueError(f"region {self.region_id} requires shot_max_s > shot_min_s")
        if not self.shot_min_s <= self.suggested_shot_mean_s <= self.shot_max_s:
            raise ValueError(
                f"region {self.region_id} requires shot_min_s <= suggested_shot_mean_s <= shot_max_s"
            )
        return self


class SlotEvidence(StrictModel):
    beat_ids: list[int] = Field(default_factory=list)
    downbeat_ids: list[int] = Field(default_factory=list)
    onset_ids: list[str] = Field(default_factory=list)
    phrase_id: str | None = None
    energy_bins: list[int] = Field(default_factory=list)
    region_id: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    params: dict[str, float] = Field(default_factory=dict)


class ShotSlot(StrictModel):
    slot_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float
    beats: int = Field(ge=0)
    pace: ShotPace
    shot_type: ShotType
    reason_code: str = Field(min_length=1)
    reason_zh: str = Field(min_length=1)
    accent_at_start: bool = False
    breath_after: bool = False
    budget_exception: BudgetException | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: SlotEvidence
    style: ShotStyle | None = None
    pattern_role: PatternRole | None = None
    flurry_group: str | None = None
    ramp: RampKind | None = None
    transition: TransitionKind | None = None
    flash: bool | None = None
    cut_on: CutOn | None = None
    rules_version: str | None = None
    beat_length: float | None = Field(default=None, ge=0.0)
    shot_size: ShotSize | None = None
    motion: MotionKind | None = None
    transition_in: GuideTransition | None = None
    transition_out: GuideTransition | None = None
    sound_cue: SoundCue | None = None
    sound_cues: list[SoundCue] = Field(default_factory=list)
    story_beat: StoryBeat | None = None
    content_hint: str | None = None

    @field_validator("reason_code")
    @classmethod
    def known_reason(cls, value: str) -> str:
        if value in _NARRATIVE_REASONS or _FASTCUT_REASON.fullmatch(value):
            return value
        raise ValueError(f"unknown reason_code {value}")

    @model_validator(mode="after")
    def positive_length(self) -> "ShotSlot":
        if self.end <= self.start:
            raise ValueError(f"slot {self.slot_id} must have end > start")
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        return _omit_empty_style_fields(handler(self), _SLOT_STYLE_FIELDS | _SLOT_GUIDE_FIELDS)


class RegionCutAnchor(StrictModel):
    region_id: str = Field(min_length=1)
    boundary_s: float = Field(ge=0.0)
    snapped_s: float = Field(ge=0.0)
    offset_s: float
    rule: Literal["downbeat", "beat", "offbeat_boundary", "edge", "beyond_bar"]
    boundary_raw_s: float | None = None
    explanation_zh: str = ""
    pending: bool = False


class MusicEditRegions(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_seconds: float = Field(gt=0.0)
    bpm: float | None = Field(default=None, gt=0.0)
    provider: EditRegionProvider
    beats_seconds: list[float] = Field(default_factory=list)
    downbeats_seconds: list[float] = Field(default_factory=list)
    downbeat_cluster_times: list[float] = Field(default_factory=list)
    downbeat_detector: DownbeatDetector
    energy_curve: list[EnergyPoint] = Field(default_factory=list)
    regions: list[MusicEditRegion]
    ending: MusicEnding
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ProviderError] = Field(default_factory=list)
    beat_backend: str = ""
    beat_backend_note: str = ""
    onsets: list[OnsetEvent] = Field(default_factory=list)
    beats: list[BeatEvent] = Field(default_factory=list)
    beat_grid: BeatGridInfo | None = None
    phrases: list[PhraseSpan] = Field(default_factory=list)
    downbeat_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    meter_assumed: int | None = None
    plp_beat_count: int | None = Field(default=None, ge=0)
    region_cut_anchors: list[RegionCutAnchor] = Field(default_factory=list)
    shot_slots: list[ShotSlot] = Field(default_factory=list)
    breath_marks: list[float] = Field(default_factory=list)
    shot_style: ShotStyle | None = None
    shot_rules_version: str | None = None
    guide_version: str | None = None
    shot_track_locked: bool = False

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = _omit_empty_style_fields(handler(self), _DOCUMENT_STYLE_FIELDS)
        if isinstance(data, dict) and data.get("shot_track_locked") is False:
            data.pop("shot_track_locked", None)
        return data

    @model_validator(mode="after")
    def region_invariants(self) -> "MusicEditRegions":
        for message in region_invariant_violations(self):
            raise ValueError(message)
        for message in slot_reference_violations(self):
            raise ValueError(message)
        return self


def region_invariant_violations(document: MusicEditRegions) -> list[str]:
    """Return every contract §6 invariant (1–6) violated by ``document``.

    Invariant 7 (run-to-run stability) is a property of the producer and is
    covered by tests rather than by a single document.
    """

    tol = BOUNDARY_TOLERANCE_SECONDS
    regions = document.regions
    duration = document.duration_seconds
    problems: list[str] = []
    # 1. non-empty and starts at zero.
    if not regions:
        return ["invariant 1: regions must not be empty"]
    if abs(regions[0].start) > tol:
        problems.append("invariant 1: first region must start at 0")
    # 2. contiguous and ends at duration; 3. no overlap / negative length.
    for previous, current in zip(regions, regions[1:]):
        gap = current.start - previous.end
        if gap < -tol:
            problems.append(
                f"invariant 3: regions {previous.region_id} and {current.region_id} overlap"
            )
        elif gap > tol:
            problems.append(
                f"invariant 2: regions {previous.region_id} and {current.region_id} are not contiguous"
            )
    if abs(regions[-1].end - duration) > tol:
        problems.append("invariant 2: last region must end at duration_seconds")
    for region in regions:
        if region.end - region.start <= 0:
            problems.append(f"invariant 3: region {region.region_id} has non-positive length")
        # 4. shot budget order (also enforced per region model).
        if not region.shot_min_s <= region.suggested_shot_mean_s <= region.shot_max_s:
            problems.append(f"invariant 4: region {region.region_id} shot budget is out of order")
    # 5. peak_cut and breath never overlap in time.
    peaks = [region for region in regions if region.edit_role == "peak_cut"]
    breaths = [region for region in regions if region.edit_role == "breath"]
    for peak in peaks:
        for breath in breaths:
            if min(peak.end, breath.end) - max(peak.start, breath.start) > tol:
                problems.append(
                    f"invariant 5: peak_cut {peak.region_id} overlaps breath {breath.region_id}"
                )
    # 6. closing window carries a settle/outro region, or honestly says it does not.
    if duration >= OUTRO_INVARIANT_MIN_DURATION:
        window_start = duration - outro_window_seconds(duration)
        in_window = [region for region in regions if region.end > window_start + tol]
        settled = any(
            region.edit_role == "settle_outro"
            or region.musical_label == "outro"
            or region.musical_proxy == "outro"
            for region in in_window
        )
        if not settled:
            if MISSING_SETTLE_OUTRO not in document.warnings:
                problems.append(
                    "invariant 6: closing window lacks settle_outro and warning missing_settle_outro"
                )
            inside = [region for region in in_window if region.start >= window_start - tol]
            if not inside or any(region.edit_role != "unknown" for region in inside):
                problems.append(
                    "invariant 6: unsettled closing window must be marked unknown"
                )
    return problems


def slot_reference_violations(document: MusicEditRegions) -> list[str]:
    """Evidence refs must point at beats, onsets, phrases, energy bins, or regions."""

    slots = document.shot_slots
    if not slots:
        return []
    problems: list[str] = []
    tol = BOUNDARY_TOLERANCE_SECONDS
    beat_by_id = {beat.i: beat for beat in document.beats}
    onset_ids = {onset.id for onset in document.onsets}
    phrase_ids = {phrase.id for phrase in document.phrases}
    region_ids = {region.region_id for region in document.regions}
    energy_count = len(document.energy_curve)
    if abs(slots[0].start) > tol:
        problems.append("slots must start at 0")
    if abs(slots[-1].end - document.duration_seconds) > tol:
        problems.append("slots must end at duration_seconds")
    seen: set[str] = set()
    for previous, slot in zip(slots, slots[1:]):
        if abs(slot.start - previous.end) > tol:
            problems.append(
                f"slots {previous.slot_id} and {slot.slot_id} are not contiguous"
            )
    for slot in slots:
        if slot.slot_id in seen:
            problems.append(f"duplicate slot id {slot.slot_id}")
        seen.add(slot.slot_id)
        if slot.region_id not in region_ids:
            problems.append(f"slot {slot.slot_id} region {slot.region_id} is missing")
        evidence = slot.evidence
        if evidence.region_id not in region_ids:
            problems.append(f"slot {slot.slot_id} evidence region is missing")
        if evidence.rule != slot.reason_code:
            problems.append(f"slot {slot.slot_id} evidence rule does not match reason_code")
        for beat_id in evidence.beat_ids:
            if beat_id not in beat_by_id:
                problems.append(f"slot {slot.slot_id} beat {beat_id} is missing")
        for beat_id in evidence.downbeat_ids:
            beat = beat_by_id.get(beat_id)
            if beat is None or not beat.is_downbeat:
                problems.append(f"slot {slot.slot_id} downbeat {beat_id} is missing")
        for onset_id in evidence.onset_ids:
            if onset_id not in onset_ids:
                problems.append(f"slot {slot.slot_id} onset {onset_id} is missing")
        if evidence.phrase_id is not None and evidence.phrase_id not in phrase_ids:
            problems.append(f"slot {slot.slot_id} phrase {evidence.phrase_id} is missing")
        for bin_index in evidence.energy_bins:
            if bin_index < 0 or bin_index >= energy_count:
                problems.append(f"slot {slot.slot_id} energy bin {bin_index} is missing")
        if slot.reason_code == "HIT_HOLD" and slot.accent_at_start:
            accents = {
                beat.i
                for beat in document.beats
                if beat.accent and abs(beat.t - slot.start) <= 0.02
            }
            if not accents.intersection(evidence.beat_ids):
                problems.append(f"slot {slot.slot_id} HIT_HOLD is not on an accent beat")
        if (
            slot.shot_type == "?"
            and slot.reason_code != "ROLE_UNKNOWN_BAR_GRID"
            and slot.pattern_role != "placeholder"
        ):
            problems.append(f"slot {slot.slot_id} pending type needs ROLE_UNKNOWN_BAR_GRID")
    return problems
