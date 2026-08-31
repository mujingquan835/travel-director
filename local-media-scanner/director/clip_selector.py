"""Place Scanner materials onto timeline slots with auditable constraints."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from director.schema import (
    ClipPlacement,
    MaterialScanResult,
    ProviderError,
    TimelineSlot,
)


class ClipSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reserve_top_fraction: float = Field(default=0.1, gt=0.0, le=1.0)
    duration_weight: float = Field(default=0.2, ge=0.0)
    motion_weight: float = Field(default=0.25, ge=0.0)
    quality_weight: float = Field(default=0.2, ge=0.0)
    diversity_weight: float = Field(default=0.15, ge=0.0)
    impact_weight: float = Field(default=0.2, ge=0.0)


class PlacementResult(list[ClipPlacement]):
    """List-compatible placements carrying explicit degradation status."""

    def __init__(
        self,
        placements: list[ClipPlacement] | None = None,
        *,
        status: str = "completed",
        errors: list[ProviderError] | None = None,
    ) -> None:
        super().__init__(placements or [])
        self.status = status
        self.errors = errors or []


def _available_ranges(
    material: MaterialScanResult,
    required_seconds: float,
    *,
    use_recommended_ranges: bool = True,
) -> tuple[list[tuple[float, float]], bool]:
    if material.analysis_status == "failed":
        return [], False
    ranges = (
        [(row.start, row.end) for row in material.recommended_ranges]
        if use_recommended_ranges and material.recommended_ranges
        else [(0.0, material.technical.duration)]
    )
    available = [
        (start, min(end, material.technical.duration))
        for start, end in ranges
        if min(end, material.technical.duration) - start >= required_seconds
    ]
    if available:
        return available, False
    if (
        use_recommended_ranges
        and material.recommended_ranges
        and material.technical.duration >= required_seconds
    ):
        return [(0.0, material.technical.duration)], True
    return [], False


def _impact(material: MaterialScanResult) -> float:
    if material.visual_impact_score is not None:
        return material.visual_impact_score
    raw_motion = material.motion_evidence.motion_intensity_raw
    return raw_motion / (raw_motion + 1.0) if raw_motion is not None else 0.0


def _motion_fit(material: MaterialScanResult, desired: str) -> float:
    levels = {"low": 0.2, "medium": 0.5, "high": 0.8}
    candidate = material.motion_evidence.motion_level_candidate
    if candidate not in levels or desired not in levels:
        return 0.5
    return 1.0 - abs(levels[candidate] - levels[desired])


def _quality(material: MaterialScanResult) -> float:
    raw = material.quality_evidence.laplacian_variance_raw
    return raw / (raw + 100.0) if raw is not None else 0.5


def _scene_diversity(
    material: MaterialScanResult,
    previous_scenes: set[str],
) -> float:
    current = set(material.scene_candidates)
    if not current or not previous_scenes:
        return 0.5
    return 1.0 if current.isdisjoint(previous_scenes) else 0.25


def _score(
    material: MaterialScanResult,
    slot: TimelineSlot,
    available_range: tuple[float, float],
    previous_scenes: set[str],
    config: ClipSelectionConfig,
) -> dict[str, float]:
    available_duration = available_range[1] - available_range[0]
    duration_fit = min(1.0, slot.duration / available_duration)
    components = {
        "duration_fit": duration_fit,
        "motion_fit": _motion_fit(material, slot.desired_motion),
        "quality_evidence": _quality(material),
        "candidate_scene_diversity": _scene_diversity(material, previous_scenes),
        "visual_impact": _impact(material),
    }
    impact_weight = config.impact_weight * (
        1.75 if slot.section_role == "climax" else 0.5
    )
    components["total"] = (
        components["duration_fit"] * config.duration_weight
        + components["motion_fit"] * config.motion_weight
        + components["quality_evidence"] * config.quality_weight
        + components["candidate_scene_diversity"] * config.diversity_weight
        + components["visual_impact"] * impact_weight
    )
    return components


def _reserved_files(
    materials: list[MaterialScanResult],
    config: ClipSelectionConfig,
) -> set[str]:
    evidenced = [
        item
        for item in materials
        if item.analysis_status != "failed"
        and (
            item.visual_impact_score is not None
            or item.motion_evidence.motion_intensity_raw is not None
        )
    ]
    if not evidenced:
        return set()
    count = max(1, math.ceil(len(evidenced) * config.reserve_top_fraction))
    ranked = sorted(evidenced, key=lambda item: (-_impact(item), item.file))
    return {item.file for item in ranked[:count]}


def place_clips(
    slots: list[TimelineSlot],
    materials: list[MaterialScanResult],
    config: ClipSelectionConfig,
    *,
    use_recommended_ranges: bool = True,
) -> PlacementResult:
    """Choose deterministic source ranges while preserving Scanner uncertainty."""

    reserved = _reserved_files(materials, config)
    used_files: set[str] = set()
    previous_group: str | None = None
    previous_scenes: set[str] = set()
    placements: list[ClipPlacement] = []
    errors: list[ProviderError] = []

    for slot in slots:
        eligible = []
        for item in materials:
            ranges, relaxed_range = _available_ranges(
                item,
                slot.duration,
                use_recommended_ranges=use_recommended_ranges,
            )
            if ranges:
                eligible.append((item, ranges[0], relaxed_range))
        relaxed: list[str] = []
        unique = [row for row in eligible if row[0].file not in used_files]

        if slot.section_role == "climax":
            reserved_unique = [row for row in unique if row[0].file in reserved]
            if reserved_unique:
                pool = reserved_unique
            elif unique:
                pool = unique
            else:
                reserved_reuse = [row for row in eligible if row[0].file in reserved]
                pool = reserved_reuse or eligible
        else:
            unreserved_unique = [row for row in unique if row[0].file not in reserved]
            if unreserved_unique:
                pool = unreserved_unique
            elif unique:
                pool = unique
                relaxed.append("reserved_for_climax_unavailable")
            else:
                unreserved_reuse = [
                    row for row in eligible if row[0].file not in reserved
                ]
                pool = unreserved_reuse or eligible

        if not unique and pool:
            relaxed.append("reused_after_unique_exhausted")

        non_duplicate = [
            row
            for row in pool
            if row[0].duplicate_group_id is None
            or row[0].duplicate_group_id != previous_group
        ]
        if non_duplicate:
            pool = non_duplicate
        elif pool:
            relaxed.append("adjacent_duplicate_group_unavoidable")

        if not pool:
            errors.append(
                ProviderError(
                    stage="clip_selection",
                    code="insufficient_material",
                    message=f"No usable source range can fill {slot.slot_id}.",
                )
            )
            continue

        ranked = []
        for item, available_range, relaxed_range in pool:
            components = _score(
                item,
                slot,
                available_range,
                previous_scenes,
                config,
            )
            reserved_bonus = (
                1.0
                if slot.section_role == "climax" and item.file in reserved
                else 0.0
            )
            ranked.append(
                (
                    components["total"] + reserved_bonus,
                    item.file,
                    item,
                    available_range,
                    relaxed_range,
                    components,
                )
            )
        ranked.sort(key=lambda row: (-row[0], row[1]))
        _, _, selected, selected_range, relaxed_range, components = ranked[0]
        if relaxed_range:
            relaxed.append("recommended_range_unavailable")
        source_in = selected_range[0]
        source_out = source_in + slot.duration
        placements.append(
            ClipPlacement(
                slot_id=slot.slot_id,
                file=selected.file,
                source_in=round(source_in, 6),
                source_out=round(source_out, 6),
                source_duration=selected.technical.duration,
                section_role=slot.section_role,
                duplicate_group_id=selected.duplicate_group_id,
                score_components=components,
                relaxed_constraints=relaxed,
            )
        )
        used_files.add(selected.file)
        previous_group = selected.duplicate_group_id
        previous_scenes = set(selected.scene_candidates)

    return PlacementResult(
        placements,
        status="partial" if errors else "completed",
        errors=errors,
    )


def place_clips_v0_2(
    slots: list[TimelineSlot],
    materials: list[MaterialScanResult],
    config: ClipSelectionConfig,
) -> PlacementResult:
    """Place V0.2 clips from whole sources; in/out exists only at this timeline step."""

    return place_clips(
        slots,
        materials,
        config,
        use_recommended_ranges=False,
    )
