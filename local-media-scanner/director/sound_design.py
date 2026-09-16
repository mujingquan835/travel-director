"""Sound event design: temporal anchoring, auditory planes, listening provenance, and downstream FCPXML binding."""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from typing import Any

from director.fcpxml_delivery import FcpxmlClipDecision, FcpxmlEditDecision
from director.project import _atomic_write, _canonical_bytes, _sha256_file
from director.sound_design_schema import SoundDesignPlan


def _read(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path | str, value: Any) -> None:
    _atomic_write(Path(path), _canonical_bytes(value))


def _diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict) and set(before) == set(after):
        return [
            item
            for key in sorted(before)
            for item in _diff(before[key], after[key], f"{path}/{key}")
        ]
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [
            item
            for i, (a, b) in enumerate(zip(before, after))
            for item in _diff(a, b, f"{path}/{i}")
        ]
    return [{"path": path or "/", "before": before, "after": after}]


def _probe_audio_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            if rate > 0:
                return float(frames) / float(rate)
    except Exception:
        pass
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def _resolve(plan: SoundDesignPlan) -> tuple[dict[str, Any], FcpxmlEditDecision]:
    from director.music_adaptation import validate_music_adaptation_export
    from director.shot_group import validate_group_export

    base_path = plan.base_decision.resolve()
    if not base_path.is_file():
        raise ValueError(f"base_decision file does not exist: {base_path}")
    base = FcpxmlEditDecision.model_validate_json(base_path.read_text(encoding="utf-8"))
    if base.sound_design is not None:
        raise ValueError(
            "use the original base decision plus --parent; do not chain derived sound design EDLs as bases"
        )

    project_duration = base.canvas.duration_seconds
    group = validate_group_export(base)
    adaptation = validate_music_adaptation_export(base)

    listeners = {r.listening_id: r for r in plan.listening}
    for record in plan.listening:
        src = record.source_path.resolve()
        if not src.is_file():
            raise ValueError(f"listening record audio source does not exist: {src}")
        src_dur = _probe_audio_duration(src)
        if record.source_out > src_dur + 1e-6:
            raise ValueError(
                f"listening record source_out ({record.source_out:.4f}s) exceeds audio duration ({src_dur:.4f}s)"
            )

    def verify_listened(listening_id: str, source_path: Path, start: float, end: float) -> None:
        rec = listeners.get(listening_id)
        if rec is None:
            raise ValueError(f"unknown listening_id: {listening_id}")
        if rec.source_path.resolve() != source_path.resolve():
            raise ValueError(
                f"listening record source path ({rec.source_path}) does not match cue source path ({source_path})"
            )
        if rec.source_in > start + 1e-6 or rec.source_out < end - 1e-6:
            raise ValueError(
                f"listening record [{rec.source_in:.4f}, {rec.source_out:.4f}] does not cover required range [{start:.4f}, {end:.4f}]"
            )

    resolved_cues: list[dict[str, Any]] = []
    sfx_clips: list[dict[str, Any]] = []
    track_names = {c.track for c in base.clips}

    for cue in plan.cues:
        visual = cue.visual_anchor
        source = cue.source

        if visual.event_time > project_duration + 1e-6:
            raise ValueError(
                f"cue '{cue.cue_id}': visual event_time ({visual.event_time:.4f}s) exceeds project duration ({project_duration:.4f}s)"
            )

        if visual.anchor_type == "shot_action":
            if group is not None:
                shots_map = {s["shot_id"]: s for s in group["shots"]}
                if visual.shot_id not in shots_map:
                    raise ValueError(
                        f"cue '{cue.cue_id}': visual anchor shot_id '{visual.shot_id}' not found in bound shot group"
                    )
                shot = shots_map[visual.shot_id]
                shot_in = shot["timeline_in"]
                shot_out = shot_in + shot["duration"]
                if not (shot_in - 1e-6 <= visual.event_time <= shot_out + 1e-6):
                    raise ValueError(
                        f"cue '{cue.cue_id}': event_time ({visual.event_time:.4f}s) lies outside shot '{visual.shot_id}' timeline window [{shot_in:.4f}, {shot_out:.4f}]"
                    )
            else:
                video_clips = [c for c in base.clips if c.kind == "video"]
                if not any(c.timeline_in - 1e-6 <= visual.event_time <= c.timeline_in + c.duration + 1e-6 for c in video_clips):
                    raise ValueError(
                        f"cue '{cue.cue_id}': event_time ({visual.event_time:.4f}s) does not fall inside any video clip"
                    )
        elif visual.anchor_type == "cut_transition":
            cut_points = [c.timeline_in for c in base.clips if c.kind == "video"]
            cut_points.extend(c.timeline_in + c.duration for c in base.clips if c.kind == "video")
            if not any(abs(visual.event_time - cut) < 0.25 for cut in cut_points):
                raise ValueError(
                    f"cue '{cue.cue_id}': transition event_time ({visual.event_time:.4f}s) is not near any video cut boundary"
                )

        if source.sound_type == "missing_gap":
            resolved_cues.append({
                "cue_id": cue.cue_id,
                "role": cue.role,
                "auditory_plane": cue.auditory_plane,
                "music_relation": cue.music_relation,
                "sound_type": "missing_gap",
                "status": "gap_recorded",
                "selection_reason": cue.selection_reason,
                "listening_status": "not_listened",
                "visual_event_time": visual.event_time,
                "description": visual.description,
            })
            continue

        src_path = source.source_path.resolve()
        if not src_path.is_file():
            raise ValueError(f"cue '{cue.cue_id}': audio file does not exist: {src_path}")
        file_duration = _probe_audio_duration(src_path)

        if source.sound_type == "location_recorded":
            src_str = str(src_path).lower()
            if "音效及音乐" in str(src_path) or "/sfx/" in src_str or "sound_effects" in src_str or "风声" in str(src_path):
                raise ValueError(
                    f"cue '{cue.cue_id}': library SFX file cannot be claimed as location_recorded"
                )

        if source.source_in + source.duration > file_duration + 1e-6:
            raise ValueError(
                f"cue '{cue.cue_id}': source range [{source.source_in:.4f}, {source.source_in + source.duration:.4f}] exceeds audio duration ({file_duration:.4f}s)"
            )
        if source.source_anchor_time > file_duration + 1e-6:
            raise ValueError(
                f"cue '{cue.cue_id}': source_anchor_time ({source.source_anchor_time:.4f}s) exceeds audio duration ({file_duration:.4f}s)"
            )

        if cue.listening_status in ("source_listened", "context_reviewed"):
            verify_listened(cue.listening_id, src_path, source.source_in, source.source_in + source.duration)

        pre_roll = source.source_anchor_time - source.source_in
        timeline_in = visual.event_time - pre_roll
        if timeline_in < -1e-6:
            raise ValueError(
                f"cue '{cue.cue_id}': pre_roll ({pre_roll:.4f}s) causes timeline_in ({timeline_in:.4f}s) to precede project start (0s)"
            )
        if timeline_in + source.duration > project_duration + 1e-6:
            raise ValueError(
                f"cue '{cue.cue_id}': timeline end ({timeline_in + source.duration:.4f}s) exceeds project duration ({project_duration:.4f}s)"
            )
        timeline_in = max(0.0, round(timeline_in, 6))

        if cue.music_relation == "music_silent":
            if adaptation is not None:
                silence_intervals = [
                    m for m in adaptation["plan"]["mapping"] if m["kind"] == "silence"
                ]
                clip_start = timeline_in
                clip_end = timeline_in + source.duration
                has_overlap = any(
                    max(clip_start, seg["project_in"]) < min(clip_end, seg["project_out"])
                    for seg in silence_intervals
                )
                if not has_overlap:
                    raise ValueError(
                        f"cue '{cue.cue_id}': music_relation is 'music_silent' but time interval [{clip_start:.4f}, {clip_end:.4f}] does not overlap any music silence in bound music adaptation"
                    )
            else:
                music_clips = [c for c in base.clips if c.kind == "music"]
                clip_start = timeline_in
                clip_end = timeline_in + source.duration
                if any(max(clip_start, m.timeline_in) < min(clip_end, m.timeline_in + m.duration) for m in music_clips):
                    raise ValueError(
                        f"cue '{cue.cue_id}': music_relation is 'music_silent' but music is present during interval [{clip_start:.4f}, {clip_end:.4f}]"
                    )
        elif cue.music_relation == "accent_sync":
            if adaptation is not None:
                music_events = adaptation["plan"]["events"]
                has_accent = any(abs(visual.event_time - ev["project_time"]) < 0.25 for ev in music_events)
                if not has_accent:
                    raise ValueError(
                        f"cue '{cue.cue_id}': music_relation is 'accent_sync' but no music event found within 0.25s of visual event_time ({visual.event_time:.4f}s)"
                    )

        track = f"sfx-{cue.role}-{cue.cue_id}"
        if track in track_names:
            raise ValueError(f"cue '{cue.cue_id}': audio track conflict with '{track}'")
        track_names.add(track)

        clip_dict = {
            "kind": "sfx",
            "source_path": str(src_path),
            "track": track,
            "timeline_in": timeline_in,
            "source_in": round(source.source_in, 6),
            "duration": round(source.duration, 6),
            "gain": cue.envelope.base_gain,
        }
        sfx_clips.append(clip_dict)

        resolved_cues.append({
            "cue_id": cue.cue_id,
            "role": cue.role,
            "auditory_plane": cue.auditory_plane,
            "music_relation": cue.music_relation,
            "sound_type": source.sound_type,
            "status": "clip_materialized",
            "track": track,
            "timeline_in": timeline_in,
            "source_in": round(source.source_in, 6),
            "duration": round(source.duration, 6),
            "source_anchor_time": source.source_anchor_time,
            "visual_event_time": visual.event_time,
            "pre_roll": round(pre_roll, 6),
            "tail_policy": source.tail_policy,
            "gain": cue.envelope.base_gain,
            "envelope": cue.envelope.model_dump(mode="json"),
            "selection_reason": cue.selection_reason,
            "listening_status": cue.listening_status,
            "listening_id": cue.listening_id,
            "source_path": str(src_path),
            "description": visual.description,
        })

    playable_cues = [c for c in plan.cues if c.source.sound_type != "missing_gap"]
    if not playable_cues:
        overall_listening = "not_listened"
    elif all(c.listening_status == "context_reviewed" for c in playable_cues):
        overall_listening = "all_context_reviewed"
    elif all(c.listening_status in ("source_listened", "context_reviewed") for c in playable_cues):
        overall_listening = "source_ranges_reviewed"
    elif any(c.listening_status in ("source_listened", "context_reviewed") for c in playable_cues):
        overall_listening = "partial_review"
    else:
        overall_listening = "not_listened"

    roles_count = {
        "location_ambient": sum(c.role == "location_ambient" for c in plan.cues),
        "action_foley": sum(c.role == "action_foley" for c in plan.cues),
        "transition_accent": sum(c.role == "transition_accent" for c in plan.cues),
    }
    planes_count = {
        "foreground": sum(c.auditory_plane == "foreground" for c in plan.cues),
        "midground": sum(c.auditory_plane == "midground" for c in plan.cues),
        "background": sum(c.auditory_plane == "background" for c in plan.cues),
    }

    all_clips = [c.model_dump(mode="json") for c in base.clips] + sfx_clips
    derived_decision = FcpxmlEditDecision.model_validate({
        **base.model_dump(mode="json"),
        "clips": all_clips,
    })

    manifest = {
        "schema_version": "1.0.0",
        "status": "sound_design_validated",
        "base_decision_path": str(base_path),
        "base_decision_sha256": _sha256_file(base_path),
        "listening_status": overall_listening,
        "mix_listening_status": "not_reviewed",
        "plan": plan.model_dump(mode="json"),
        "cues": resolved_cues,
        "roles": roles_count,
        "auditory_planes": planes_count,
        "playable_segments": len(sfx_clips),
        "missing_gaps": sum(c.source.sound_type == "missing_gap" for c in plan.cues),
        "parent": None,
        "changes": [],
    }

    return manifest, derived_decision


def build_sound_design(
    plan_path: Path | str,
    output_dir: Path | str,
    parent_path: Path | str | None = None,
) -> dict[str, Any]:
    """Validate a sound design plan, check anchor alignments and listening provenance, and write immutable output."""

    plan_file = Path(plan_path).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve()

    if not plan_file.is_file():
        raise ValueError(f"plan does not exist: {plan_file}")
    if target_dir.exists():
        raise FileExistsError(f"refusing to overwrite output: {target_dir}")

    plan = SoundDesignPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    manifest, derived_decision = _resolve(plan)

    if parent_path is not None:
        p_file = Path(parent_path).expanduser().resolve()
        if not p_file.is_file():
            raise ValueError(f"parent sound design does not exist: {p_file}")
        parent_data = _read(p_file)
        if parent_data.get("status") != "sound_design_validated":
            raise ValueError("parent must be a validated sound design document")
        diff = _diff(parent_data["plan"], manifest["plan"])
        manifest["parent"] = {
            "path": str(p_file),
            "sha256": _sha256_file(p_file),
        }
        manifest["changes"] = diff

    target_dir.mkdir(parents=True)
    sound_design_json = target_dir / "sound_design.json"
    _write(sound_design_json, manifest)

    binding_hash = _sha256_file(sound_design_json)
    from director.shot_group_schema import ShotGroupBinding
    derived_decision.sound_design = ShotGroupBinding(
        path=sound_design_json,
        sha256=binding_hash,
    )
    decision_json = target_dir / "edit_decision.json"
    _write(decision_json, json.loads(derived_decision.model_dump_json()))

    return {
        "status": manifest["status"],
        "sound_design_path": str(sound_design_json),
        "sound_design_sha256": binding_hash,
        "decision_path": str(decision_json),
        "listening_status": manifest["listening_status"],
        "mix_listening_status": manifest["mix_listening_status"],
        "roles": manifest["roles"],
        "auditory_planes": manifest["auditory_planes"],
        "playable_segments": manifest["playable_segments"],
        "missing_gaps": manifest["missing_gaps"],
        "changes": manifest["changes"],
    }


def inspect_sound_design(sound_design_path: Path | str) -> dict[str, Any]:
    """Revalidate an existing sound design manifest and its media sources."""

    path = Path(sound_design_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"sound design file does not exist: {path}")
    data = _read(path)
    if data.get("schema_version") != "1.0.0" or data.get("status") != "sound_design_validated":
        raise ValueError("invalid sound design schema or unvalidated status")

    plan = SoundDesignPlan.model_validate(data["plan"])
    recomputed_manifest, _ = _resolve(plan)

    if data.get("parent") is not None:
        recomputed_manifest["parent"] = data["parent"]
        recomputed_manifest["changes"] = data["changes"]

    _write(path, recomputed_manifest)
    return {
        "status": "sound_design_inspected",
        "path": str(path),
        "sha256": _sha256_file(path),
        "listening_status": recomputed_manifest["listening_status"],
        "mix_listening_status": recomputed_manifest["mix_listening_status"],
        "roles": recomputed_manifest["roles"],
        "auditory_planes": recomputed_manifest["auditory_planes"],
        "playable_segments": recomputed_manifest["playable_segments"],
        "missing_gaps": recomputed_manifest["missing_gaps"],
        "parent": recomputed_manifest["parent"],
        "changes_count": len(recomputed_manifest["changes"]),
    }


def validate_sound_design_export(decision: FcpxmlEditDecision) -> dict[str, Any] | None:
    """Validate that the decision's sound_design binding matches the serialized audio clips."""

    binding = decision.sound_design
    if binding is None:
        return None

    path = binding.path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"bound sound design does not exist: {path}")
    if _sha256_file(path) != binding.sha256:
        raise ValueError("bound sound design sha256 mismatch")

    data = _read(path)
    if data.get("status") != "sound_design_validated":
        raise ValueError("bound sound design is not in validated status")

    decision_sfx = [c for c in decision.clips if c.kind == "sfx"]
    resolved_playable = [c for c in data["cues"] if c.get("status") == "clip_materialized"]
    if len(decision_sfx) != len(resolved_playable):
        raise ValueError(
            f"bound sound design defines {len(resolved_playable)} clips, but decision has {len(decision_sfx)}"
        )

    return data
