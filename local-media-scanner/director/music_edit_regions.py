"""Derive music edit-region candidates from an existing ``MusicStructure``.

M0 of the music_edit_regions contract: provider ``heuristic_v1`` only. It maps
the measured energy sections onto contract edit roles (hook, establish,
narrative_hold, build, peak_cut, breath, settle_outro, unknown) and writes a
sibling ``music_edit_regions.json`` bound to the frozen music hash. Purely
local and deterministic; it never calls an external service and never claims
confirmed phrases or downbeats.

Confirmed edit-region versions are a different store. See
``director.music_edit_regions_versions`` — those drafts and locks are not
``music_version`` child projects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import Field

from director.boundary_snap import snap_bound_list
from director.music_edit_regions_schema import (
    BOUNDARY_TOLERANCE_SECONDS,
    MISSING_SETTLE_OUTRO,
    OUTRO_INVARIANT_MIN_DURATION,
    EditRegionProvider,
    EditRole,
    MusicEditRegion,
    MusicEditRegions,
    MusicalProxy,
    outro_window_seconds,
)
from director.schema import MusicEnding, MusicStructure, MusicStructureSection, StrictModel


SUPPORTED_PROVIDERS = frozenset({"heuristic_v1"})
BEAT_GRID_PROXY_WARNING = "onset_rate_from_beat_grid_proxy"
HOOK_WINDOW_SOFT = "hook_window_soft"
SHORT_REGION_UNMERGED = "short_region_unmerged"
TARGET_WINDOW_CLIPPED = "target_window_clipped"
PEAK_SHOT_MIN = 0.5
PEAK_SHOT_MAX = 1.4


class EditRegionConfig(StrictModel):
    """Contract §4 inputs plus the §8 thresholds used by heuristic_v1."""

    provider: EditRegionProvider = "heuristic_v1"
    enable_hook_region: bool = True
    target_duration_seconds: float | None = Field(default=None, gt=0.0)
    min_region_seconds: float = Field(default=4.0, gt=0.0, le=30.0)
    energy_window_seconds: float = Field(default=1.0, gt=0.0, le=5.0)
    hook_max_seconds: float = Field(default=3.0, gt=0.0)
    hook_duration_ratio: float = Field(default=0.08, gt=0.0, lt=1.0)
    breath_energy_ratio: float = Field(default=0.45, gt=0.0, lt=1.0)
    slope_threshold: float = Field(default=0.08, gt=0.0, lt=1.0)
    peak_energy_percentile: float = Field(default=80.0, gt=0.0, lt=100.0)
    peak_onset_percentile: float = Field(default=70.0, gt=0.0, lt=100.0)
    narrative_onset_percentile: float = Field(default=50.0, gt=0.0, lt=100.0)
    entry_lookback_seconds: float = Field(default=4.0, gt=0.0)
    onset_rate_tolerance: float = Field(default=0.05, ge=0.0, lt=1.0)
    shot_style: Literal["narrative", "travel", "event"] | None = None


# Contract §7 defaults: (mean, min, max, motion, content_need, proxy).
ROLE_DEFAULTS: dict[str, tuple[float, float, float, str, str, MusicalProxy]] = {
    "hook": (0.9, 0.6, 1.2, "high", "attention_hook", "intro"),
    "establish": (3.2, 2.5, 4.0, "low", "orientation_detail", "intro"),
    "narrative_hold": (4.0, 3.0, 5.5, "low", "scenic_or_story", "rise"),
    "build": (2.0, 1.5, 2.5, "medium", "forward_motion", "rise"),
    "peak_cut": (1.0, PEAK_SHOT_MIN, PEAK_SHOT_MAX, "high", "high_visual_impact", "climax"),
    "breath": (4.5, 3.5, 6.0, "low", "reflective_pause", "breath"),
    "settle_outro": (3.5, 2.5, 4.5, "low", "closing_image", "outro"),
    "unknown": (3.0, 1.5, 5.0, "medium", "unspecified", "unknown"),
}
BEAT_SNAP_ROLES = frozenset({"peak_cut", "hook", "build"})


def peak_shot_mean(bpm: float | None) -> float:
    """``max(0.5, 60/bpm)`` (1.0 without bpm), clamped into the peak budget."""

    mean = 1.0 if not bpm else max(PEAK_SHOT_MIN, 60.0 / bpm)
    return min(PEAK_SHOT_MAX, max(PEAK_SHOT_MIN, mean))


def _r3(value: float) -> float:
    return float(round(value, 3))


def _r6(value: float) -> float:
    return float(round(value, 6))


class _Signal:
    """Energy points and beat grid of the analysed window."""

    def __init__(self, structure: MusicStructure, duration: float) -> None:
        points = [p for p in structure.energy_curve if p.time_seconds < duration]
        self.times = np.asarray([p.time_seconds for p in points], dtype=np.float64)
        self.values = np.asarray([p.value for p in points], dtype=np.float64)
        self.beats = np.asarray(
            [b for b in structure.beats_seconds if 0.0 <= b < duration], dtype=np.float64
        )
        self.duration = duration

    def mean(self, start: float, end: float) -> float:
        if not len(self.values):
            return 0.0
        mask = (self.times >= start - 1e-9) & (self.times < end - 1e-9)
        if not mask.any():
            index = int(np.searchsorted(self.times, start, side="right")) - 1
            return float(self.values[max(0, index)])
        return float(np.mean(self.values[mask]))

    def slope(self, start: float, end: float) -> float:
        middle = (start + end) / 2.0
        mask = (self.times >= start - 1e-9) & (self.times < end - 1e-9)
        if int(mask.sum()) < 2:
            return 0.0
        return self.mean(middle, end) - self.mean(start, middle)

    def entry_slope(self, start: float, lookback: float) -> float:
        if start < 1.0:
            return 0.0
        before = self.mean(max(0.0, start - lookback), start)
        after = self.mean(start, min(self.duration, start + lookback / 2.0))
        return after - before

    def beat_rate(self, start: float, end: float) -> float:
        count = int(((self.beats >= start) & (self.beats < end)).sum())
        return count / (end - start)

    def step(self, bin_index: int, window: float) -> float:
        # |E[k] - E[k-1]| for the energy step entering bin k.
        if bin_index <= 0 or bin_index >= len(self.values):
            return -1.0
        return abs(float(self.values[bin_index] - self.values[bin_index - 1]))


def _clip_structure(
    structure: MusicStructure, config: EditRegionConfig
) -> tuple[float, MusicEnding, list[str]]:
    duration = structure.duration_seconds
    if config.target_duration_seconds is None or config.target_duration_seconds >= duration:
        return duration, structure.ending, []
    clipped = config.target_duration_seconds
    last = structure.ending.last_onset_seconds
    ending = MusicEnding(
        last_onset_seconds=last if last is not None and last <= clipped else None,
        behavior="unknown",
    )
    return clipped, ending, [TARGET_WINDOW_CLIPPED]


def _refined_section_boundaries(
    sections: list[MusicStructureSection],
    signal: _Signal,
    duration: float,
    window: float,
) -> list[float]:
    """Existing section boundaries, each nudged ±1 energy window to the sharpest step.

    The legacy section detector can land one window early/late; nudging keeps
    region means from absorbing a neighbour's bin. Ties keep the original.
    """

    raw = sorted({s.start for s in sections if 0.0 < s.start < duration})
    refined: list[float] = []
    for boundary in raw:
        index = int(round(boundary / window))
        best, best_step = boundary, signal.step(index, window)
        for candidate in (index - 1, index + 1):
            step = signal.step(candidate, window)
            if step > best_step + 1e-9:
                best, best_step = candidate * window, step
        if 0.0 < best < duration:
            refined.append(best)
    return sorted(set(refined))


def _merge_short(
    bounds: list[float], signal: _Signal, min_seconds: float
) -> tuple[list[float], bool]:
    """Merge regions shorter than ``min_seconds`` into the closer-energy neighbour."""

    bounds = list(bounds)
    while len(bounds) > 2:
        lengths = [b - a for a, b in zip(bounds, bounds[1:])]
        short = [i for i, length in enumerate(lengths) if length < min_seconds - 1e-9]
        if not short:
            break
        i = short[0]
        energy = signal.mean(bounds[i], bounds[i + 1])
        left = signal.mean(bounds[i - 1], bounds[i]) if i > 0 else None
        right = signal.mean(bounds[i + 1], bounds[i + 2]) if i + 2 < len(bounds) else None
        if right is None or (left is not None and abs(left - energy) <= abs(right - energy)):
            del bounds[i]  # merge into left neighbour
        else:
            del bounds[i + 1]  # merge into right neighbour
    lengths = [b - a for a, b in zip(bounds, bounds[1:])]
    return bounds, any(length < min_seconds - 1e-9 for length in lengths)


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if values else 0.0


def _section_confidence(sections: list[MusicStructureSection], start: float, end: float) -> float:
    total = weight = 0.0
    for section in sections:
        overlap = min(section.end, end) - max(section.start, start)
        if overlap > 0:
            total += section.confidence * overlap
            weight += overlap
    return total / weight if weight else 0.4


def analyze_music_edit_regions(
    structure: MusicStructure, config: EditRegionConfig | None = None
) -> MusicEditRegions:
    """Map measured energy sections to contract edit roles (heuristic_v1)."""

    config = config or EditRegionConfig()
    if config.provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"provider {config.provider} is not available in M0; use heuristic_v1"
        )
    duration, ending, warnings = _clip_structure(structure, config)
    real_onsets = bool(structure.onsets)
    if not real_onsets:
        warnings.append(BEAT_GRID_PROXY_WARNING)
    for code in structure.analysis_warnings:
        if code not in warnings:
            warnings.append(code)
    signal = _Signal(structure, duration)
    window = config.energy_window_seconds
    tol = BOUNDARY_TOLERANCE_SECONDS

    # Fixed windows: opening hook window and contract closing window.
    hook_end = (
        _r3(min(config.hook_max_seconds, config.hook_duration_ratio * duration))
        if config.enable_hook_region
        else 0.0
    )
    carve_outro = duration >= OUTRO_INVARIANT_MIN_DURATION
    outro_start = _r3(duration - outro_window_seconds(duration)) if carve_outro else duration
    if hook_end >= outro_start - tol:
        hook_end = 0.0

    sections = [s for s in structure.sections if s.start < duration]
    inner = [
        b
        for b in _refined_section_boundaries(sections, signal, duration, window)
        if hook_end + tol < b < outro_start - tol
    ]
    middle_start = hook_end
    middle, unmerged = _merge_short(
        [middle_start, *inner, outro_start], signal, config.min_region_seconds
    )
    bounds: list[float] = ([0.0] if hook_end > 0 else []) + middle
    if carve_outro:
        bounds.append(duration)
    bounds = [_r3(b) for b in bounds]
    bounds[-1] = _r3(duration)
    raw_bounds = list(bounds)
    # Roles use the raw bounds. A sub-bar snap must not flip them: the user's
    # 8–25s establish became unknown once 8.0 moved to 8.74 and the neighbour
    # took the single establish slot.
    snapped_bounds = list(raw_bounds)
    if structure.beat_events and structure.bpm:
        period = (
            structure.beat_grid.period_s
            if structure.beat_grid is not None and structure.beat_grid.period_s > 0
            else 60.0 / structure.bpm
        )
        beat_times = [beat.t for beat in structure.beat_events if beat.t <= duration + 1e-6]
        down_times = [
            beat.t for beat in structure.beat_events if beat.is_downbeat and beat.t <= duration + 1e-6
        ]
        snapped_bounds = snap_bound_list(
            raw_bounds,
            duration,
            down_times,
            beat_times,
            period,
            structure.downbeat_confidence,
        )
    paired = list(zip(raw_bounds, snapped_bounds))
    spans = []
    snapped_spans: list[tuple[float, float]] = []
    for (raw_start, start), (raw_end, end) in zip(paired, paired[1:]):
        if raw_end - raw_start > tol:
            spans.append((raw_start, raw_end))
            snapped_spans.append((start, end))
    if unmerged:
        warnings.append(SHORT_REGION_UNMERGED)

    # Song-level statistics (contract §8).
    energy_values = signal.values.tolist()
    e_med = float(np.median(signal.values)) if energy_values else 0.0
    e_p80 = _percentile(energy_values, config.peak_energy_percentile)
    if real_onsets:
        rates = []
        for start, end in spans:
            onset_count = sum(1 for onset in structure.onsets if start <= onset.t < end)
            rates.append(onset_count / (end - start))
    else:
        rates = [signal.beat_rate(a, b) for a, b in spans]
    rate_p70 = _percentile(rates, config.peak_onset_percentile)
    rate_p50 = _percentile(rates, config.narrative_onset_percentile)
    rate_slack = 1.0 + config.onset_rate_tolerance
    eps = 1e-6
    # Loudest non-hook / non-outro span (dominant mid-song energy).
    mid_energies = [
        signal.mean(a, b)
        for index, (a, b) in enumerate(spans)
        if not (hook_end > 0 and index == 0)
        and not (carve_outro and a >= outro_start - tol)
    ]
    max_mid_energy = max(mid_energies) if mid_energies else 0.0

    roles: list[EditRole] = []
    establish_taken = False
    hook_soft = False
    missing_settle = False
    for index, (start, end) in enumerate(spans):
        mean_energy = signal.mean(start, end)
        rate = rates[index]
        slope = signal.slope(start, end)
        length = end - start
        is_hook_window = hook_end > 0 and index == 0
        in_outro = carve_outro and start >= outro_start - tol
        role: EditRole
        if in_outro:
            if mean_energy <= e_med + eps or ending.behavior in {"decay", "fade"}:
                role = "settle_outro"
            else:
                role = "unknown"
                missing_settle = True
        elif is_hook_window:
            dense = rate > 0 and rate * rate_slack >= rate_p50
            if dense or mean_energy >= e_med - eps:
                role = "hook"
            else:
                role = "establish"
                establish_taken = True
                hook_soft = True
        elif length < config.min_region_seconds - 1e-9:
            role = "unknown"
        elif (
            # Energy gate uses the same relative percentile slack as onset_rate (§13).
            mean_energy * rate_slack >= e_p80 - eps
            and (
                # While onset_rate is beat-grid proxy, Ē>=e_p80 (outside hook/outro) suffices for peak_cut.
                BEAT_GRID_PROXY_WARNING in warnings
                or rate * rate_slack >= rate_p70
                or signal.entry_slope(start, config.entry_lookback_seconds)
                > config.slope_threshold
            )
        ) or (
            # Dominant mid-song energy under beat-grid proxy (pointwise E_p80 can be outro-skewed).
            BEAT_GRID_PROXY_WARNING in warnings
            and not is_hook_window
            and not in_outro
            and mean_energy >= max_mid_energy - eps
            and mean_energy >= e_med - eps
        ):
            role = "peak_cut"
        elif mean_energy <= e_med * config.breath_energy_ratio + eps:
            role = "breath"
        elif slope > config.slope_threshold:
            role = "build"
        elif not establish_taken and abs(slope) <= config.slope_threshold:
            role = "establish"
            establish_taken = True
        elif abs(slope) <= config.slope_threshold and rate <= rate_p50 * rate_slack:
            role = "narrative_hold"
        else:
            role = "unknown"
        if role == "establish":
            establish_taken = True
        roles.append(role)
    if hook_soft:
        warnings.append(HOOK_WINDOW_SOFT)
    if missing_settle:
        warnings.append(MISSING_SETTLE_OUTRO)

    regions: list[MusicEditRegion] = []
    for index, ((start, end), role) in enumerate(zip(spans, roles)):
        snapped_start, snapped_end = snapped_spans[index]
        if snapped_end - snapped_start <= tol:
            snapped_start, snapped_end = start, end
        mean, shot_min, shot_max, motion, need, proxy = ROLE_DEFAULTS[role]
        if role == "peak_cut":
            mean = peak_shot_mean(structure.bpm)
        if role == "narrative_hold" and end > duration * 0.6 + tol:
            proxy = "unknown"
        confidence = _section_confidence(sections, start, end)
        if role == "unknown":
            confidence = min(confidence, 0.4)
        regions.append(
            MusicEditRegion(
                region_id=f"r{index + 1:02d}",
                start=_r3(snapped_start),
                end=_r3(snapped_end),
                edit_role=role,
                musical_label=None,
                musical_proxy=proxy,
                mean_energy=_r6(min(1.0, max(0.0, signal.mean(start, end)))),
                onset_rate=_r6(rates[index]),
                energy_slope=_r6(signal.slope(start, end)),
                suggested_shot_mean_s=_r3(mean),
                shot_min_s=shot_min,
                shot_max_s=shot_max,
                snap_policy=(
                    "downbeat"
                    if role in BEAT_SNAP_ROLES
                    and structure.downbeat_detector == "beat_this"
                    and (structure.downbeat_confidence or 0.0) >= 0.7
                    else "beat"
                    if role in BEAT_SNAP_ROLES
                    else "free"
                ),
                desired_motion=motion,
                content_need=need,
                confidence=_r6(confidence),
                evidence_basis="energy",
                start_raw_s=_r3(start) if abs(start - snapped_start) >= 0.001 else None,
                end_raw_s=_r3(end) if abs(end - snapped_end) >= 0.001 else None,
            )
        )

    weighted = sum(r.confidence * (r.end - r.start) for r in regions) / duration
    provider = config.provider
    if structure.beat_backend == "beat_this" and provider == "heuristic_v1":
        provider = "beat_this+heuristic"
    document = MusicEditRegions(
        source_sha256=structure.source_sha256,
        duration_seconds=_r3(duration),
        bpm=structure.bpm,
        provider=provider,
        beats_seconds=[b for b in structure.beats_seconds if b < duration],
        downbeats_seconds=[b for b in structure.downbeats_seconds if b < duration],
        downbeat_cluster_times=list(structure.downbeat_cluster_times),
        downbeat_detector=structure.downbeat_detector,
        energy_curve=[p for p in structure.energy_curve if p.time_seconds < duration],
        regions=regions,
        ending=ending,
        confidence=_r6(min(structure.confidence, weighted)),
        warnings=warnings,
        beat_backend=structure.beat_backend,
        beat_backend_note=structure.beat_backend_note,
        onsets=[onset for onset in structure.onsets if onset.t < duration],
        beats=[beat for beat in structure.beat_events if beat.t < duration],
        beat_grid=structure.beat_grid,
        phrases=[phrase for phrase in structure.phrases if phrase.start < duration],
        downbeat_confidence=structure.downbeat_confidence,
        meter_assumed=structure.meter_assumed,
        plp_beat_count=structure.plp_beat_count,
    )
    if document.beats:
        from director.shot_slots import plan_shot_slots

        if config.shot_style:
            document = document.model_copy(update={"shot_style": config.shot_style})
            document = plan_shot_slots(document, style=config.shot_style)
        else:
            document = plan_shot_slots(document)
    return document


def load_music_edit_regions(paths: Any) -> MusicEditRegions | None:
    """Return the project's edit regions only when they match the frozen music.

    Missing or stale files (bound to another ``source_sha256``) are treated as
    absent so downstream consumers fall back to ``MusicStructure.sections``.
    """

    from director.audio_import import load_music_evidence
    from director.project import ProjectConflict, _sha256_file, load_project_state

    evidence = load_music_evidence(paths)
    recorded = load_project_state(paths).completed_artifact_hashes.get("music_edit_regions")
    if evidence is None or recorded is None or not paths.music_edit_regions.is_file():
        return None
    if _sha256_file(paths.music_edit_regions) != recorded:
        raise ProjectConflict("supporting artifact hash drifted: music_edit_regions")
    regions = MusicEditRegions.model_validate_json(
        paths.music_edit_regions.read_text(encoding="utf-8")
    )
    asset, _ = evidence
    if regions.source_sha256 != asset.source_sha256:
        return None
    return regions


def build_project_music_edit_regions(
    project: Path, config: EditRegionConfig | None = None
) -> dict[str, Any]:
    """Analyse a project's frozen music and record ``music_edit_regions.json``.

    A previous file bound to another track (or produced with another config) is
    replaced; an unchanged result is left byte-identical. When the regions
    version store already exists, the candidate is also staged as a draft and
    confirmed snapshots are left untouched.
    """

    from director.audio_import import load_music_evidence
    from director.project import load_project_state, open_project, record_supporting_artifact

    config = config or EditRegionConfig()
    paths = open_project(project)
    evidence = load_music_evidence(paths)
    if evidence is None:
        raise ValueError(
            "music_edit_regions requires frozen music; import music with --music first"
        )
    asset, structure = evidence
    regions = analyze_music_edit_regions(structure, config)
    if regions.source_sha256 != asset.source_sha256:
        raise ValueError("music analysis is bound to a different source")

    previous_sha: str | None = None
    had_previous = "music_edit_regions" in load_project_state(paths).completed_artifact_hashes
    if had_previous and paths.music_edit_regions.is_file():
        try:
            previous_sha = MusicEditRegions.model_validate_json(
                paths.music_edit_regions.read_text(encoding="utf-8")
            ).source_sha256
        except ValueError:
            previous_sha = None
    before = (
        paths.music_edit_regions.read_bytes() if paths.music_edit_regions.is_file() else None
    )
    record_supporting_artifact(
        paths, paths.music_edit_regions, regions, state_key="music_edit_regions"
    )
    # Version store, when present, receives a new or replaced draft. Confirmed
    # snapshots stay write-once; this never rewrites music_edit_regions_versions/confirmed.
    from director.music_edit_regions_versions import stage_reanalysis_if_versioned

    stage_reanalysis_if_versioned(paths, regions)
    after = paths.music_edit_regions.read_bytes()
    if before is None:
        status = "created"
    elif before == after:
        status = "unchanged"
    else:
        status = "regenerated"
    return {
        "status": status,
        "music_edit_regions": str(paths.music_edit_regions),
        "source_sha256": regions.source_sha256,
        "previous_source_sha256": previous_sha,
        "invalidated_previous": status == "regenerated",
        "provider": regions.provider,
        "duration_seconds": regions.duration_seconds,
        "region_count": len(regions.regions),
        "edit_roles": [region.edit_role for region in regions.regions],
        "warnings": regions.warnings,
        "candidate_status": "unconfirmed_candidates",
        "external_call_count": 0,
    }
