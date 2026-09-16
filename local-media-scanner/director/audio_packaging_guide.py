"""Audio-packaging advice only. This module never reads, edits, mixes or renders audio."""
from __future__ import annotations

from typing import Any


_INTENT_DEFAULTS = {
    "hook_policy": "conditional",
    "added_sfx_policy": "conditional",
    "original_sound_priority": "normal",
    "silence_priority": "normal",
}


def _intent_decision(global_intent, section_intent, field: str) -> dict[str, Any]:
    """Resolve one field without deriving intent from prose."""
    candidates = []
    for scope, intent, specificity in (
        ("global", global_intent, 0),
        ("section", section_intent, 1),
    ):
        if intent is None or getattr(intent, field, None) is None:
            continue
        source = getattr(intent, "source", "not_recorded")
        rank = {"not_recorded": 0, "creative_proposal": 10, "user_explicit": 20}[source]
        candidates.append((rank + specificity, scope, intent))
    if not candidates:
        return {"value": _INTENT_DEFAULTS[field], "source": "default", "scope": "default",
                "reason": "未记录结构化意图；不从自由文本推断。", "explicit": False,
                "priority_rank": -1}
    priority_rank, scope, intent = max(candidates, key=lambda item: item[0])
    return {"value": getattr(intent, field), "source": intent.source, "scope": scope,
            "reason": intent.reason, "explicit": True, "priority_rank": priority_rank}


def _boundary_assessment(time: float, music_boundaries: list[float], tolerance: float,
                         *, target_cut_unanalyzed: bool = False) -> dict[str, Any]:
    if target_cut_unanalyzed:
        return {"creative_boundary": time, "status": "target_cut_unanalyzed",
                "nearest_music_boundary": None, "offset_seconds": None,
                "review_window": None,
                "resolution": "保留创意目标截点并单独试听；不套用原曲结尾或自动吸附。"}
    if not music_boundaries:
        return {"creative_boundary": time, "status": "music_boundary_unavailable",
                "nearest_music_boundary": None, "offset_seconds": None,
                "review_window": None,
                "resolution": "保留创意叙事边界；音乐边界证据不足。"}
    nearest = min(music_boundaries, key=lambda value: (abs(value - time), value))
    offset = nearest - time
    if abs(offset) <= 1e-6:
        status = "aligned"
        resolution = "创意边界与可靠音乐分析边界一致，可作为试听锚点。"
        window = [time, time]
    elif abs(offset) <= tolerance:
        status = "near"
        resolution = "保留创意叙事边界；在两者之间试听转折，是否调整由叙事、动作和听感共同决定。"
        window = [min(time, nearest), max(time, nearest)]
    else:
        status = "mismatch"
        resolution = "创意叙事边界优先；在创意边界附近试听，并另行比较最近音乐提示点，不自动移动分段。"
        window = [max(0.0, time - tolerance), time + tolerance]
    return {"creative_boundary": time, "status": status,
            "nearest_music_boundary": nearest, "offset_seconds": round(offset, 6),
            "review_window": window, "resolution": resolution}


def _reconcile_space_intent(original: dict[str, Any], silence: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a conflict created by merging valid global and section policies."""
    if silence["value"] != "required" or original["value"] not in {"preserve", "foreground"}:
        return original, silence
    original = dict(original)
    silence = dict(silence)
    if silence["priority_rank"] > original["priority_rank"]:
        original.update(value="normal", overridden_by="higher_priority_required_silence")
    else:
        silence.update(value="normal", overridden_by="higher_priority_original_sound")
    return original, silence


def _plan_status(timeline, name: str) -> dict[str, str]:
    report = (timeline.audio_packaging or {}).get(name)
    if report is None:
        return {"source_status": "unknown", "advice_status": "unknown", "reason": "历史交付未记录该项状态。"}
    advice_status = {
        "ready": "needs_visual_and_listening_review",
        "disabled": "disabled",
        "no_match": "candidate_unavailable",
        "unavailable": "candidate_unavailable",
        "deferred": "deferred",
    }[report.status]
    return {"source_status": report.status, "advice_status": advice_status, "reason": report.reason}


def _layer(
    function: str,
    timing: str,
    condition: str,
    source: str | None = None,
    source_status: str = "not_selected",
    necessity: str = "conditional",
) -> dict[str, Any]:
    return {
        "function": function,
        "timing": timing,
        "necessity": necessity,
        "condition": condition,
        "candidate_source": source,
        "candidate_status": source_status if source else "not_selected",
        "decision": "use_only_if_visual_anchor_is_confirmed",
    }


def build_audio_packaging_advice(timeline, direction, music,
                                 boundary_tolerance_seconds: float = 0.5) -> dict[str, Any]:
    """Translate saved plans into conditional editorial advice, never a rendered mix."""
    target = timeline.target_duration_seconds
    if boundary_tolerance_seconds <= 0:
        raise ValueError("boundary tolerance must be positive")
    hook = timeline.hook_plan
    outro = timeline.outro_plan
    hook_status = _plan_status(timeline, "hook")
    outro_status = _plan_status(timeline, "outro")
    assets = []
    verified_sources = set()
    for asset in timeline.sfx_assets or []:
        verified_sources.add(asset.source_relative_path)
        assets.append({"role": asset.role, "frozen_relative_path": asset.frozen_relative_path,
                       "sha256": asset.sha256, "duration_seconds": asset.duration_seconds,
                       "status": "verified_candidate_not_mixed"})

    def candidate_status(source: str) -> str:
        return "verified_frozen_candidate" if source in verified_sources else "provenance_only_unverified"

    global_intent = getattr(direction, "audio_intent", None)
    first_section_intent = getattr(direction.sections[0], "audio_intent", None)
    hook_policy = _intent_decision(global_intent, None, "hook_policy")
    first_added_sfx = _intent_decision(global_intent, first_section_intent, "added_sfx_policy")
    first_original = _intent_decision(global_intent, first_section_intent, "original_sound_priority")
    first_silence = _intent_decision(global_intent, first_section_intent, "silence_priority")
    first_original, first_silence = _reconcile_space_intent(first_original, first_silence)

    hook_advice: dict[str, Any] = {
        "status": hook_status,
        "visual_anchor": direction.sections[0].visual_plan,
        "visual_anchor_status": "creative_proposal_not_confirmed_event",
        "layers": [],
        "bgm_relationship": None,
        "review_questions": [
            "开场是否确有可对位的揭示、动作或标题出现点？",
            "叠加后是否遮蔽入口现场声或音乐识别度？",
            "若没有明确画面变化，是否应只保留音乐或现场声？",
        ],
        "effective_intent": {"hook_policy": hook_policy, "added_sfx_policy": first_added_sfx,
                             "original_sound_priority": first_original, "silence_priority": first_silence},
    }
    hook_suppression = None
    if hook_policy["value"] == "disabled":
        hook_suppression = "Hook 被结构化意图禁用；源计划候选不得进入建议。"
    elif (first_added_sfx["value"] == "disabled"
          and first_added_sfx["priority_rank"] >= hook_policy["priority_rank"]):
        hook_suppression = "开场分段禁用新增音效，且没有更高优先级的 Hook 许可。"
    elif (first_silence["value"] == "required"
          and first_silence["priority_rank"] >= hook_policy["priority_rank"]):
        hook_suppression = "开场要求静默空间，优先级高于通用 Hook。"
    if hook_suppression:
        hook_advice["status"] = {"source_status": hook_status["source_status"],
                                 "advice_status": "disabled_by_higher_priority_intent",
                                 "reason": hook_suppression}
        hook_advice["suppression_reason"] = hook_suppression
    elif hook is not None:
        peak = hook.hook_duration_seconds - hook.config.hit_pre_trigger_seconds
        recover_end = hook.hook_duration_seconds + hook.config.bgm_recovery_seconds
        hook_advice["layers"] = [
            _layer("推进", f"0.00–{peak:.2f}s", "仅在画面向揭示点推进时使用；不把一条 Riser 从头机械拉到尾。", hook.riser_path, candidate_status(hook.riser_path)),
            _layer("释放", f"建议落点 {peak:.2f}s", "只对位明确的画面变化；没有动作或揭示点则取消。", hook.hit_path, candidate_status(hook.hit_path)),
            _layer("转场主体", f"落点附近，时长待试听", "只有存在方向或空间变化时才建议 Whoosh；当前没有独立已验证候选。"),
            _layer("低频/尾音支撑", "释放点之后，长度待画面停留决定", "仅用于需要撑住的大场景；当前不得自动添加。"),
            _layer("细节点缀", "具体动作发生点", "必须能说出机械、铃声或环境细节所对应的可见变化；否则不加。"),
        ]
        hook_advice["bgm_relationship"] = {
            "status": "parameter_proposal_needs_listening",
            "segments": [
                {"start": 0.0, "end_exclusive": hook.hook_duration_seconds, "level": hook.config.bgm_duck_level, "purpose": "为开场音效组预留空间"},
                {"start": hook.hook_duration_seconds, "end_exclusive": recover_end, "from_level": hook.config.bgm_duck_level, "to_level": 1.0, "purpose": "平滑恢复"},
                {"start": recover_end, "end_exclusive": target, "level": 1.0, "purpose": "恢复原音乐电平"},
            ],
            "boundary_rule": "区间左闭右开，边界不重复；这里只描述参数，不执行处理。",
        }
        if first_original["value"] in {"preserve", "foreground"} or first_silence["value"] == "preserve":
            constraint = "现场声或静默空间优先；只有确认不遮蔽时才保留 Hook 层。"
            hook_advice["priority_constraint"] = constraint
            for layer in hook_advice["layers"]:
                layer["decision"] = "lower_priority_than_original_sound_or_silence"

    section_advice = []
    reliable_music_sections = [row for row in music.sections
                               if music.confidence >= 0.6 and row.confidence >= 0.6]
    music_boundaries = sorted({value for row in reliable_music_sections
                               for value in (row.start, row.end)
                               if 0 <= value <= target})
    truncated = target < music.duration_seconds - 1e-6
    for section in direction.sections:
        section_intent = getattr(section, "audio_intent", None)
        effective = {
            field: _intent_decision(global_intent, section_intent, field)
            for field in ("added_sfx_policy", "original_sound_priority", "silence_priority")
        }
        effective["original_sound_priority"], effective["silence_priority"] = _reconcile_space_intent(
            effective["original_sound_priority"], effective["silence_priority"]
        )
        proposals = []
        for proposal in section.sfx_plan:
            if proposal.startswith(("不", "避免")):
                proposal_type = "guardrail"
                requirement = "作为限制条件保留，无需寻找音效层。"
            elif any(term in proposal for term in ("原声", "环境声", "底噪")):
                proposal_type = "source_sound_space"
                requirement = "实施前确认素材确有可用原声并标出时间范围；没有则保留音乐或留白，不虚构声音。"
            else:
                proposal_type = "effect_layer"
                requirement = "实施前标出具体画面事件及时间；无法对位则取消。"
            proposals.append({
                "proposal": proposal,
                "proposal_type": proposal_type,
                "status": "creative_proposal_needs_visual_and_listening_check",
                "required_annotation": requirement,
            })
            if proposal_type == "effect_layer":
                if effective["added_sfx_policy"]["value"] == "disabled":
                    proposals[-1]["status"] = "suppressed_by_added_sfx_policy"
                elif effective["silence_priority"]["value"] == "required":
                    proposals[-1]["status"] = "suppressed_by_required_silence"
                elif effective["silence_priority"]["value"] == "preserve":
                    proposals[-1]["status"] = "lower_priority_than_preserved_silence"
                elif effective["original_sound_priority"]["value"] in {"preserve", "foreground"}:
                    proposals[-1]["status"] = "lower_priority_than_original_sound"
            elif proposal_type == "source_sound_space" and effective["original_sound_priority"]["value"] in {"preserve", "foreground"}:
                proposals[-1]["status"] = "preferred_by_original_sound_intent"
        start_boundary = _boundary_assessment(section.start, music_boundaries,
                                              boundary_tolerance_seconds)
        end_boundary = _boundary_assessment(
            section.end, music_boundaries, boundary_tolerance_seconds,
            target_cut_unanalyzed=truncated and abs(section.end - target) <= 1e-6,
        )
        internal_boundaries = [value for value in music_boundaries
                               if section.start + 1e-6 < value < section.end - 1e-6]
        if effective["silence_priority"]["value"] == "required":
            priority_order = ["required_silence", "narrative_boundary", "music_cue", "added_sfx_disabled"]
        elif effective["original_sound_priority"]["value"] in {"preserve", "foreground"}:
            priority_order = ["original_sound", "narrative_boundary", "music", "added_sfx"]
        elif effective["silence_priority"]["value"] == "preserve":
            priority_order = ["preserved_silence_space", "narrative_boundary", "original_sound", "music", "added_sfx"]
        else:
            priority_order = ["narrative_boundary", "original_sound", "music", "conditional_added_sfx"]
        section_advice.append({
            "section_id": section.section_id,
            "start": section.start,
            "end": section.end,
            "picture_context": section.visual_plan,
            "proposals": proposals,
            "effective_intent": effective,
            "priority_order": priority_order,
            "boundary_alignment": {"start": start_boundary, "end": end_boundary,
                                   "internal_music_boundaries": internal_boundaries},
            "layering_check": [
                "推进层是否服务该段的实际能量变化？",
                "释放层是否对位明确画面事件？",
                "主体、低频/尾音是否与画面尺度和停留时长相称？",
                "点缀层是否呼应可见细节？",
                "各层是否有变化和留白，而非持续堆叠？",
            ],
        })

    if truncated:
        outro_status = {
            "source_status": outro_status["source_status"],
            "advice_status": "deferred",
            "reason": "目标截点早于当前音乐分析的原曲结尾；截点收尾特征尚未分析。",
        }
    outro_advice = {
        "status": outro_status,
        "target_cut_seconds": target,
        "source_music_ending_behavior": music.ending.behavior,
        "source_music_ending_applicable": not truncated,
        "candidate_source": None if truncated else (outro.sfx_path if outro else None),
        "recommendation": (
            "先试听并判断目标截点是硬停、渐弱、衰减还是未定；当前不推荐自动添加 Outro。"
            if truncated
            else "依据完整原曲结尾和画面停留长度复核释放、低频及尾音；没有画面对位时允许不加。"
        ),
        "review_questions": [
            "目标截点之后是否仍需要尾音支撑画面？",
            "尾音是否覆盖或干扰最后一段现场声？",
            "画面是明确落点还是开放式离场？",
        ],
    }

    return {
        "schema_version": "1.0.0",
        "artifact_kind": "audio_packaging_advice",
        "edited_or_mixed": False,
        "principle": "关键节点先判断画面事件，再按推进、释放、主体、支撑、点缀分配功能；层数由需要决定，可以为零。",
        "anti_overdesign_rule": "每层必须说明画面对位；无法说明则删除。分层不是固定叠加 3–5 条音效。",
        "intent_priority_rule": "用户明确意图 > 创意提案 > 通用包装建议；同来源时分段意图 > 全局意图。结构化字段未记录时不从自由文本推断禁用或强制策略。",
        "boundary_policy": {"tolerance_seconds": boundary_tolerance_seconds,
                            "rule": "创意边界承载叙事并保持不变；可靠音乐边界只提供试听锚点。near/mismatch 均不自动吸附。"},
        "hook": hook_advice,
        "sections": section_advice,
        "outro": outro_advice,
        "verified_assets": assets,
        "asset_note": "有冻结副本时仅表示候选字节可追踪，不表示已混音或已通过听感；无冻结记录时路径只作来源参考。",
        "final_review": [
            "先检查是否存在安静段和原声抬起空间。",
            "逐层说明功能和画面对位，删除没有依据的层。",
            "试听瞬态、低频、尾音是否与画面尺度匹配。",
            "检查音效组是否遮蔽音乐、人物声或环境声。",
            "确认目标截点的实际听感，不能套用原曲结尾分析。",
        ],
    }


def render_audio_packaging_markdown(advice: dict[str, Any]) -> list[str]:
    lines = [
        "## 音频包装建议（不执行混音）", "",
        advice["principle"], advice["anti_overdesign_rule"], "",
        f"- 意图优先级：{advice['intent_priority_rule']}",
        f"- 边界规则：{advice['boundary_policy']['rule']}（容差 {advice['boundary_policy']['tolerance_seconds']:.2f}s）", "",
        "### 开场 Hook", "",
        f"- 原计划状态：{advice['hook']['status']['source_status']}；建议状态：{advice['hook']['status']['advice_status']}；{advice['hook']['status']['reason']}",
        f"- 画面锚点：{advice['hook']['visual_anchor']}（创意提案，尚非确认事件）",
    ]
    hook_intent = advice["hook"]["effective_intent"]
    lines.append(
        "- 生效意图：Hook={hook}，新增音效={sfx}，现场声={original}，静默={silence}。".format(
            hook=hook_intent["hook_policy"]["value"],
            sfx=hook_intent["added_sfx_policy"]["value"],
            original=hook_intent["original_sound_priority"]["value"],
            silence=hook_intent["silence_priority"]["value"],
        )
    )
    if advice["hook"].get("suppression_reason"):
        lines.append(f"- 抑制原因：{advice['hook']['suppression_reason']}")
    if advice["hook"].get("priority_constraint"):
        lines.append(f"- 优先约束：{advice['hook']['priority_constraint']}")
    for layer in advice["hook"]["layers"]:
        source = ""
        if layer["candidate_source"]:
            label = "冻结候选已验证" if layer["candidate_status"] == "verified_frozen_candidate" else "来源参考，未冻结验证"
            source = f"；候选：`{layer['candidate_source']}`（{label}）"
        lines.append(f"- {layer['function']}｜{layer['timing']}：{layer['condition'].rstrip('。')}{source}。")
    bgm = advice["hook"]["bgm_relationship"]
    if bgm:
        lines.extend(["", "BGM 电平建议（需试听）："])
        for segment in bgm["segments"]:
            level = f"{segment['level']:.0%}" if "level" in segment else f"{segment['from_level']:.0%}→{segment['to_level']:.0%}"
            lines.append(f"- {segment['start']:.2f}–{segment['end_exclusive']:.2f}s：{level}，{segment['purpose']}")
        lines.append(f"- 边界：{bgm['boundary_rule']}")
    lines.extend(["", "### 分段声画建议", ""])
    for section in advice["sections"]:
        lines.append(f"#### {section['section_id']}｜{section['start']:.2f}–{section['end']:.2f}s")
        lines.append(f"- 画面语境：{section['picture_context']}")
        intent = section["effective_intent"]
        lines.append(
            "- 生效意图：新增音效={sfx}，现场声={original}，静默={silence}；排序：{order}。".format(
                sfx=intent["added_sfx_policy"]["value"],
                original=intent["original_sound_priority"]["value"],
                silence=intent["silence_priority"]["value"],
                order=" > ".join(section["priority_order"]),
            )
        )
        if section["proposals"]:
            for proposal in section["proposals"]:
                lines.append(
                    f"- 原创意建议：{proposal['proposal']}。状态：{proposal['status']}。{proposal['required_annotation']}"
                )
        else:
            lines.append("- 未提出音效；允许保留音乐、现场声或静默空间。")
        for label, boundary in (("起点", section["boundary_alignment"]["start"]),
                                ("终点", section["boundary_alignment"]["end"])):
            nearest = boundary["nearest_music_boundary"]
            nearest_text = "无可靠音乐边界" if nearest is None else f"最近音乐边界 {nearest:.2f}s"
            offset = boundary["offset_seconds"]
            offset_text = "" if offset is None else f"，偏移 {offset:+.2f}s"
            window = boundary["review_window"]
            window_text = "" if window is None else f"；试听窗口 {window[0]:.2f}–{window[1]:.2f}s"
            lines.append(
                f"- {label} {boundary['creative_boundary']:.2f}s：{boundary['status']}，{nearest_text}{offset_text}{window_text}。{boundary['resolution']}"
            )
        internal = section["boundary_alignment"]["internal_music_boundaries"]
        if internal:
            lines.append("- 段内音乐提示点：" + "、".join(f"{value:.2f}s" for value in internal) + "；仅作试听提示，不拆改创意分段。")
        lines.append("")
    outro = advice["outro"]
    lines.extend([
        "### 结尾 Outro", "",
        f"- 原计划状态：{outro['status']['source_status']}；建议状态：{outro['status']['advice_status']}；{outro['status']['reason']}",
        f"- {outro['recommendation']}",
        f"- 原曲结尾行为 `{outro['source_music_ending_behavior']}` 对目标截点适用：{'是' if outro['source_music_ending_applicable'] else '否'}。", "",
        "### 最终检查", "",
    ])
    lines.extend(f"- {item}" for item in advice["final_review"])
    lines.extend(["", "以上均为编辑建议，不是混音参数交付，也不表示听感已经通过。", ""])
    return lines
