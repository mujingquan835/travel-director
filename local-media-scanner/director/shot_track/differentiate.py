"""Pick one theme technique per fast-cut version.

Timestamps stay on the beat grid from ``fastcut.generate``. The seed only
orders cards whose scores are equal. No model call.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from director.shot_track.fastcut import EPS, generate

CARDS_PATH = Path(__file__).resolve().parent / "techniques" / "cards.json"
RHYTHM_ROLES = frozenset({"build", "peak_cut"})
R_MIN = 0.2
T_MIN = 0.5
THEME_REPEAT_MAX = 3
USES_PER_MINUTE = 6
KINDS_MAX = 3
BAR_GAP = 2

# Theme → (build variant, peak variant). ``ladder`` / ``burst`` are the 0.3 tables.
THEME_RHYTHM = {
    "contrast_rhythm": ("dense_then_release", "contrast_hold"),
    "whitespace": ("linear", "half_time"),
    "freeze": ("ladder", "burst"),
    "push_in": ("push", "push"),
    "speed_conditional": ("speed", "speed"),
}
_DEFAULT_VARIANT = {"ladder": None, "burst": None}


@dataclass(frozen=True)
class PlannedUse:
    technique_id: str
    name_zh: str
    region_id: str
    region_role: str
    anchor: str
    anchor_s: float
    span_beats: float
    slot_ids: tuple[str, ...]
    evidence_zh: str
    why_zh: str
    fallback_zh: str
    steps_zh: tuple[str, ...]
    footage_zh: str
    fcpxml_zh: str


@dataclass(frozen=True)
class TechniquePrior:
    theme_id: str
    pairs: tuple[tuple[str, str], ...]
    sequences: tuple[tuple[str, str, float, tuple[str, ...]], ...]


@dataclass(frozen=True)
class TechniquePlan:
    seed: str
    theme_id: str
    theme_name_zh: str
    summary_zh: str
    reselect_zh: str
    uses: tuple[PlannedUse, ...]
    rhythm: dict[str, str | None]
    slot_names: dict[str, tuple[str, str]]


def load_cards() -> list[dict]:
    payload = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    return list(payload["cards"])


def technique_seed(audio_sha256: str, version_id: str | None, user_options: dict | None) -> str:
    blob = json.dumps(
        {
            "audio_sha256": audio_sha256 or "",
            "version_id": version_id or "",
            "user_options": user_options or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _near(moment: float, points: list[float], eps: float = EPS) -> bool:
    return any(abs(moment - point) <= eps for point in points)


def song_features(desk: dict) -> dict:
    accents = [float(item) for item in (desk.get("accent_seconds") or [])]
    if not accents:
        raw = desk.get("onsets_seconds") or []
        accents = [float(item["t"] if isinstance(item, dict) else item) for item in raw]
    accents = sorted(accents)
    regions = list(desk.get("regions") or [])
    starts = [float(region["start"]) for region in regions]
    hits = sum(1 for start in starts if _near(start, accents))
    downbeats = [float(item) for item in desk.get("downbeats_seconds") or []]
    offbeat = 0
    for accent in accents:
        if downbeats and not _near(accent, downbeats):
            offbeat += 1
    gaps = [accents[index + 1] - accents[index] for index in range(len(accents) - 1)]
    energies = [float(region.get("mean_energy") or 0.0) for region in regions]
    build = next((region for region in regions if region.get("edit_role") == "build"), None)
    peak = next((region for region in regions if region.get("edit_role") == "peak_cut"), None)
    jump = 0.0
    if build is not None and peak is not None:
        jump = float(peak.get("mean_energy") or 0.0) - float(build.get("mean_energy") or 0.0)
    build_bars = 0
    if build is not None:
        start, end = float(build["start"]), float(build["end"])
        build_bars = sum(1 for moment in downbeats if start - EPS <= moment < end - EPS) or 1
    low_energy = False
    if energies:
        midpoint = sorted(energies)[len(energies) // 2]
        low_energy = any(value < midpoint * 0.45 for value in energies)
    confidence = desk.get("downbeat_confidence")
    return {
        "boundary_sync": hits / max(1, len(regions)),
        "offbeat_accent_ratio": offbeat / max(1, len(accents)) if accents else 0.0,
        "max_accent_gap_s": max(gaps) if gaps else 0.0,
        "energy_jump": jump,
        "build_bars": build_bars,
        "low_energy": low_energy,
        "bpm": float(desk.get("bpm") or 0.0),
        "downbeat_confidence": None if confidence is None else float(confidence),
        "downbeat_detector": str(desk.get("downbeat_detector") or ""),
        "duration_seconds": float(desk.get("duration_seconds") or 0.0),
    }


def _forbidden(card: dict, features: dict) -> bool:
    for rule in card.get("contraindications") or []:
        code = rule.get("code")
        if code == "low_downbeat_confidence":
            confidence = features["downbeat_confidence"]
            if confidence is not None and confidence < float(rule.get("max_exclusive", 0.5)):
                return True
        elif code == "downbeat_detector" and features["downbeat_detector"] == rule.get("equals"):
            return True
    return False


def _score(card_id: str, features: dict) -> float:
    """Experience weights. Equal scores are the only place the seed is used."""

    sync = float(features["boundary_sync"])
    gap = float(features["max_accent_gap_s"])
    jump = float(features["energy_jump"])
    offbeat = float(features["offbeat_accent_ratio"])
    bpm = float(features["bpm"] or 0.0)
    bars = int(features["build_bars"])
    if card_id == "contrast_rhythm":
        bonus = 0.15 if jump >= 0.12 else 0.0
        return 0.20 + 1.20 * sync + bonus
    if card_id == "whitespace":
        bonus = 0.25 if gap >= 6.0 else 0.0
        if features["low_energy"]:
            bonus += 0.15
        return 0.30 + bonus
    if card_id == "freeze":
        return 0.90 - sync + 0.25 * offbeat
    if card_id == "push_in":
        return 0.36 + (0.10 if bars >= 4 else 0.0)
    if card_id == "speed_conditional":
        tempo = 0.06 if 90.0 <= bpm <= 150.0 else 0.0
        return 0.32 + tempo + 0.15 * sync
    return 0.0


def _eligible(card: dict, features: dict, style: str) -> bool:
    if style not in (card.get("styles") or []):
        return False
    if _forbidden(card, features):
        return False
    song = (card.get("triggers") or {}).get("song") or {}
    window = song.get("bpm")
    bpm = float(features["bpm"] or 0.0)
    if window and bpm and not (float(window[0]) <= bpm <= float(window[1])):
        return False
    return bool((card.get("triggers") or {}).get("region_roles"))


def _rank(cards: list[dict], features: dict, style: str, seed: str) -> list[dict]:
    scored = [(card, round(_score(card["id"], features), 4)) for card in cards if _eligible(card, features, style)]
    scored.sort(
        key=lambda item: (
            -item[1],
            hashlib.sha256(f"{seed}:{item[0]['id']}".encode("utf-8")).hexdigest(),
        )
    )
    return [card for card, _score_value in scored]


def _bar_index(moment: float, downbeats: list[float]) -> int:
    return sum(1 for beat in downbeats if beat <= moment + EPS)


def _use_limit(duration: float) -> int:
    if duration <= 0:
        return 1
    return max(1, int(USES_PER_MINUTE * duration / 60.0 + 1e-9))


def _beat_s(desk: dict) -> float:
    beats = [float(item) for item in desk.get("beats_seconds") or []]
    if len(beats) >= 2:
        gaps = sorted(beats[index + 1] - beats[index] for index in range(len(beats) - 1))
        return gaps[len(gaps) // 2] or 0.5
    bpm = float(desk.get("bpm") or 120.0)
    return 60.0 / bpm if bpm else 0.5


def _evidence(card: dict, region: dict, features: dict) -> str:
    sync = features["boundary_sync"]
    confidence = features["downbeat_confidence"]
    confidence_text = "未知" if confidence is None else f"{confidence:.2f}"
    return (
        f"{region['region_id']} 是{region.get('edit_role')}，段首重音对齐 {sync:.2f}，"
        f"重音最大间隔 {features['max_accent_gap_s']:.1f} 秒，强拍置信度 {confidence_text}。"
        f"所以用{card['name_zh']}。"
    )


def _fcpxml_text(card: dict) -> str:
    block = card.get("fcpxml") or {}
    carry = "、".join(block.get("expressible") or []) or "片段名"
    missing = "、".join(block.get("not_expressible") or []) or "没有"
    return f"能带上：{carry}。带不上：{missing}。"


def _footage_text(card: dict) -> str:
    needs = card.get("footage_needs") or {}
    parts = [str(needs.get("shot") or ""), str(needs.get("motion") or "")]
    optional = needs.get("optional")
    if optional:
        parts.append(str(optional))
    return "，".join(part for part in parts if part)


def _place_uses(card: dict, desk: dict, slots: list[dict], features: dict) -> tuple[PlannedUse, ...]:
    roles = set((card.get("triggers") or {}).get("region_roles") or [])
    regions = [region for region in desk.get("regions") or [] if region.get("edit_role") in roles]
    order = {"peak_cut": 0, "build": 1, "hook": 2, "establish": 3, "settle_outro": 4}
    regions.sort(key=lambda region: (order.get(region.get("edit_role"), 9), float(region["start"])))
    downbeats = [float(item) for item in desk.get("downbeats_seconds") or []]
    limit = min(THEME_REPEAT_MAX, _use_limit(float(desk.get("duration_seconds") or 0.0)))
    chosen: list[dict] = []
    bars: list[int] = []
    for region in regions:
        if len(chosen) >= limit:
            break
        bar = _bar_index(float(region["start"]), downbeats)
        if any(abs(bar - previous) < BAR_GAP for previous in bars):
            continue
        chosen.append(region)
        bars.append(bar)
    beat = _beat_s(desk)
    span = float((card.get("timing_contract") or {}).get("span_beats") or 4)
    anchor_name = str((card.get("timing_contract") or {}).get("anchor") or "downbeat")
    uses: list[PlannedUse] = []
    for region in chosen:
        anchor_s = float(region["start"])
        end_s = min(float(region["end"]), anchor_s + span * beat)
        slot_ids = tuple(
            slot["slot_id"]
            for slot in slots
            if slot["region_id"] == region["region_id"] and anchor_s - EPS <= float(slot["start"]) < end_s - 1e-9
        )
        if not slot_ids:
            owned = [slot for slot in slots if slot["region_id"] == region["region_id"]]
            if not owned:
                continue
            nearest = min(owned, key=lambda slot: abs(float(slot["start"]) - anchor_s))
            slot_ids = (nearest["slot_id"],)
        evidence = _evidence(card, region, features)
        uses.append(
            PlannedUse(
                technique_id=card["id"],
                name_zh=card["name_zh"],
                region_id=region["region_id"],
                region_role=str(region.get("edit_role") or ""),
                anchor=anchor_name,
                anchor_s=round(anchor_s, 3),
                span_beats=span,
                slot_ids=slot_ids,
                evidence_zh=evidence,
                why_zh=evidence,
                fallback_zh=str((card.get("footage_needs") or {}).get("without_footage") or "退回原来的切法。"),
                steps_zh=tuple(card.get("jianying_steps_zh") or []),
                footage_zh=_footage_text(card),
                fcpxml_zh=_fcpxml_text(card),
            )
        )
    return tuple(uses)


def _rhythm_for(theme_id: str, desk: dict) -> dict[str, str | None]:
    build_name, peak_name = THEME_RHYTHM.get(theme_id, ("ladder", "burst"))
    rhythm: dict[str, str | None] = {}
    for region in desk.get("regions") or []:
        role = region.get("edit_role")
        if role == "build":
            rhythm[region["region_id"]] = _DEFAULT_VARIANT.get(build_name, build_name)
        elif role == "peak_cut":
            rhythm[region["region_id"]] = _DEFAULT_VARIANT.get(peak_name, peak_name)
    return rhythm


def beat_sequences(slots: list[dict], desk: dict) -> tuple[tuple[str, str, float, tuple[str, ...]], ...]:
    sequences = []
    for region in desk.get("regions") or []:
        role = str(region.get("edit_role") or "")
        if role not in RHYTHM_ROLES:
            continue
        owned = [slot for slot in slots if slot.get("region_id") == region["region_id"]]
        tokens = tuple(f"{round(float(slot.get('beats') or 0.0) * 2) / 2:.1f}" for slot in owned)
        sequences.append(
            (
                str(region["region_id"]),
                role,
                float(region["end"]) - float(region["start"]),
                tokens,
            )
        )
    return tuple(sequences)


def _pairs(uses: tuple[PlannedUse, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted({(use.technique_id, use.region_role) for use in uses}))


def diversity_parts(left_theme: str, left_pairs, left_sequences, right_theme: str, right_pairs, right_sequences) -> dict:
    left_set = set(left_pairs)
    right_set = set(right_pairs)
    union = left_set | right_set
    jaccard = (len(left_set & right_set) / len(union)) if union else 1.0
    weight = 0.0
    similarity = 0.0
    for region_id, role, duration, tokens in left_sequences:
        match = next((item for item in right_sequences if item[0] == region_id and item[1] == role), None)
        if match is None:
            match = next((item for item in right_sequences if item[1] == role), None)
        if match is None:
            continue
        span = min(duration, match[2])
        ratio = SequenceMatcher(None, list(tokens), list(match[3])).ratio() if tokens or match[3] else 1.0
        similarity += span * ratio
        weight += span
    rhythm = 1.0 if weight <= 0 else 1.0 - similarity / weight
    motif = 0 if left_theme == right_theme else 1
    return {
        "R": rhythm,
        "T": 1.0 - jaccard,
        "M": motif,
        "ok": rhythm >= R_MIN and (1.0 - jaccard) >= T_MIN and motif == 1,
    }


def _candidate_prior(theme_id: str, uses: tuple[PlannedUse, ...], sequences) -> TechniquePrior:
    return TechniquePrior(theme_id=theme_id, pairs=_pairs(uses), sequences=tuple(sequences))


def prior_from_regions(regions) -> TechniquePrior | None:
    theme = getattr(regions, "technique_theme_id", None)
    if not theme:
        return None
    uses = tuple(
        PlannedUse(
            technique_id=use.technique_id,
            name_zh=use.name_zh,
            region_id=use.region_id,
            region_role=use.region_role,
            anchor=use.anchor,
            anchor_s=use.anchor_s,
            span_beats=use.span_beats,
            slot_ids=tuple(use.slot_ids),
            evidence_zh=use.evidence_zh,
            why_zh=use.why_zh,
            fallback_zh=use.fallback_zh,
            steps_zh=tuple(use.steps_zh),
            footage_zh=use.footage_zh,
            fcpxml_zh=use.fcpxml_zh,
        )
        for use in regions.technique_uses
    )
    desk = {
        "regions": [
            {
                "region_id": region.region_id,
                "start": region.start,
                "end": region.end,
                "edit_role": region.edit_role,
            }
            for region in regions.regions
        ]
    }
    slots = [
        {"region_id": slot.region_id, "beats": slot.beat_length if slot.beat_length is not None else float(slot.beats)}
        for slot in regions.shot_slots
    ]
    return TechniquePrior(theme_id=theme, pairs=_pairs(uses), sequences=beat_sequences(slots, desk))


def diversity_documents(left, right) -> dict:
    prior_left = prior_from_regions(left)
    prior_right = prior_from_regions(right)
    if prior_left is None or prior_right is None:
        return {"R": 0.0, "T": 0.0, "M": 0, "ok": False}
    return diversity_parts(
        prior_left.theme_id,
        prior_left.pairs,
        prior_left.sequences,
        prior_right.theme_id,
        prior_right.pairs,
        prior_right.sequences,
    )


def _summarize(card: dict, uses: tuple[PlannedUse, ...]) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for use in uses:
        if use.name_zh not in counts:
            order.append(use.name_zh)
        counts[use.name_zh] = counts.get(use.name_zh, 0) + 1
    if not order:
        return card["name_zh"]
    return " · ".join(f"{name} ×{counts[name]}" for name in order)


def _slot_names(uses: tuple[PlannedUse, ...]) -> dict[str, tuple[str, str]]:
    names: dict[str, tuple[str, str]] = {}
    for use in uses:
        for slot_id in use.slot_ids:
            names[slot_id] = (use.technique_id, use.name_zh)
    return names


def _as_prior(item) -> TechniquePrior | None:
    if item is None:
        return None
    if isinstance(item, TechniquePrior):
        return item
    if getattr(item, "technique_theme_id", None):
        return prior_from_regions(item)
    return None


def plan_fastcut(
    desk: dict,
    style: str,
    *,
    version_id: str | None = None,
    user_options: dict | None = None,
    prior=None,
) -> tuple[list[dict], float, TechniquePlan | None]:
    """Return fast-cut slots, the beat length, and the technique plan.

    Narrative is not handled here. With no eligible card the slots stay on the
    default rhythm and the plan is omitted.
    """

    options = {"style": style}
    if user_options:
        options.update(user_options)
    seed = technique_seed(str(desk.get("source_sha256") or ""), version_id, options)
    cards = load_cards()
    features = song_features(desk)
    ranked = _rank(cards, features, style, seed)
    locked = options.get("theme_id")
    if isinstance(locked, str):
        preferred = [card for card in ranked if card["id"] == locked]
        rest = [card for card in ranked if card["id"] != locked]
        ranked = preferred + rest
    priors = [item for item in (_as_prior(entry) for entry in (prior or [])) if item is not None]
    if not ranked:
        slots, beat_s = generate(desk, style)
        return slots, beat_s, None

    best: tuple[dict, list[dict], float, tuple[PlannedUse, ...], tuple] | None = None
    best_score = -1.0
    chosen_reason = ""
    rejected = False
    for card in ranked:
        rhythm = _rhythm_for(card["id"], desk)
        slots, beat_s = generate(desk, style, rhythm=rhythm)
        uses = _place_uses(card, desk, slots, features)
        sequences = beat_sequences(slots, desk)
        if priors:
            checks = [
                diversity_parts(card["id"], _pairs(uses), sequences, item.theme_id, item.pairs, item.sequences)
                for item in priors
            ]
            if not all(item["ok"] for item in checks):
                rejected = True
                floor = min(item["R"] for item in checks) if checks else 0.0
                if floor > best_score:
                    best_score = floor
                    best = (card, slots, beat_s, uses, sequences)
                continue
        best = (card, slots, beat_s, uses, sequences)
        chosen_reason = ""
        break
    else:
        chosen_reason = "和已确认的版本比，差异不够，候选用完了。" if rejected else ""
    if best is None:
        slots, beat_s = generate(desk, style)
        return slots, beat_s, None
    card, slots, beat_s, uses, _sequences = best
    if card["id"] == "freeze":
        wanted = {use.slot_ids[0] for use in uses if use.slot_ids}
        for slot in slots:
            if slot["slot_id"] in wanted and not slot.get("ramp"):
                slot["ramp"] = "freeze"
    plan = TechniquePlan(
        seed=seed,
        theme_id=card["id"],
        theme_name_zh=card["name_zh"],
        summary_zh=_summarize(card, uses),
        reselect_zh=chosen_reason,
        uses=uses,
        rhythm=_rhythm_for(card["id"], desk),
        slot_names=_slot_names(uses),
    )
    return slots, beat_s, plan
