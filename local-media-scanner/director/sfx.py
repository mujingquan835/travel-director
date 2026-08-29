"""Plan selective location sound and SFX without generating any media."""

from __future__ import annotations

from collections import defaultdict

from director.schema import (
    ClipPlacement,
    MaterialScanResult,
    SfxCandidate,
    SfxPlan,
    SfxPlanItem,
)


ALLOWED_LABELS = {
    "water",
    "wind",
    "rain",
    "footsteps",
    "door",
    "vehicle",
    "mechanical",
    "applause",
    "cheer",
    "performance",
    "food",
    "glass",
    "whoosh_motion",
    "environment",
}

VISUALLY_GROUNDED_GENERATION_LABELS = {
    "water",
    "footsteps",
    "door",
    "vehicle",
    "mechanical",
    "food",
    "glass",
    "whoosh_motion",
}


def collect_sfx_candidates(
    materials: list[MaterialScanResult],
) -> list[SfxCandidate]:
    """Flatten allowed material candidates while preserving provenance."""

    unique: dict[tuple[str, str, float, str], SfxCandidate] = {}
    for material in materials:
        for candidate in material.sfx_candidates:
            normalized_label = candidate.label.strip().lower()
            if (
                normalized_label not in ALLOWED_LABELS
                or candidate.file != material.file
            ):
                continue
            normalized = candidate.model_copy(update={"label": normalized_label})
            key = (
                normalized.file,
                normalized.label,
                normalized.source_time_seconds,
                normalized.evidence_source,
            )
            current = unique.get(key)
            if current is None or normalized.confidence > current.confidence:
                unique[key] = normalized
    return sorted(
        unique.values(),
        key=lambda row: (row.file, row.source_time_seconds, row.label),
    )


def _has_local_audio_evidence(candidate: SfxCandidate) -> bool:
    source = candidate.evidence_source.lower()
    return "audio" in source or "location_sound" in source


def build_sfx_plan(
    placements: list[ClipPlacement],
    candidates: list[SfxCandidate],
) -> SfxPlan:
    """Choose original sound, an SFX suggestion, or silence after placement."""

    by_file: dict[str, list[SfxCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.label.strip().lower() in ALLOWED_LABELS:
            by_file[candidate.file].append(candidate)

    items: list[SfxPlanItem] = []
    timeline_cursor = 0.0
    previous_was_generated = False

    for placement in placements:
        trimmed = [
            candidate
            for candidate in by_file.get(placement.file, [])
            if placement.source_in
            <= candidate.source_time_seconds
            <= placement.source_out
        ]
        selected = max(
            trimmed,
            key=lambda row: (row.confidence, -row.source_time_seconds),
            default=None,
        )

        if selected is None:
            decision = "silence"
            label = None
            event_time = timeline_cursor
            reason = "No grounded SFX candidate falls inside the selected source range."
        else:
            label = selected.label.strip().lower()
            event_time = timeline_cursor + (
                selected.source_time_seconds - placement.source_in
            )
            if _has_local_audio_evidence(selected):
                decision = (
                    "keep_original"
                    if placement.section_role == "breath"
                    else "enhance_original"
                )
                reason = "Local audio evidence supports an authentic placed event."
            elif (
                label in VISUALLY_GROUNDED_GENERATION_LABELS
                and not previous_was_generated
            ):
                decision = "generate_sfx"
                reason = "A visible placed event supports one selective SFX suggestion."
            else:
                decision = "silence"
                reason = "Candidate evidence is insufficient or generation was already suggested adjacent."

        items.append(
            SfxPlanItem(
                file=placement.file,
                timeline_time_seconds=round(event_time, 6),
                decision=decision,
                label=label,
                reason=reason,
            )
        )
        previous_was_generated = decision == "generate_sfx"
        timeline_cursor += placement.source_out - placement.source_in

    return SfxPlan(status="completed", items=items)
