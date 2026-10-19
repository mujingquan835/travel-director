"""Contract for music edit-region candidates (music_edit_regions.json).

Sibling artifact of ``MusicStructure`` (which keeps its own 0.1.0 schema).
See skills/travel-director/references/music-edit-regions.md for the contract.
Regions are unconfirmed, energy-derived editing hypotheses, never listening
evidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from director.schema import EnergyPoint, MusicEnding, ProviderError, StrictModel


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
DownbeatDetector = Literal["every_fourth_beat", "beat_this", "allin1", "unknown"]


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
    enabled: bool = True

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


class MusicEditRegions(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_seconds: float = Field(gt=0.0)
    bpm: float | None = Field(default=None, gt=0.0)
    provider: EditRegionProvider
    beats_seconds: list[float] = Field(default_factory=list)
    downbeats_seconds: list[float] = Field(default_factory=list)
    downbeat_detector: DownbeatDetector
    energy_curve: list[EnergyPoint] = Field(default_factory=list)
    regions: list[MusicEditRegion]
    ending: MusicEnding
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ProviderError] = Field(default_factory=list)

    @model_validator(mode="after")
    def region_invariants(self) -> "MusicEditRegions":
        for message in region_invariant_violations(self):
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
