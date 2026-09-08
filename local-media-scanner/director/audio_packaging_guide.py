"""Audio-packaging advice only. This module never reads, edits, mixes or renders audio."""
from __future__ import annotations

from typing import Any


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


def build_audio_packaging_advice(timeline, direction, music) -> dict[str, Any]:
    """Translate saved plans into conditional editorial advice, never a rendered mix."""
    target = timeline.target_duration_seconds
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
    }
    if hook is not None:
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

    section_advice = []
    for section in direction.sections:
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
        section_advice.append({
            "section_id": section.section_id,
            "start": section.start,
            "end": section.end,
            "picture_context": section.visual_plan,
            "proposals": proposals,
            "layering_check": [
                "推进层是否服务该段的实际能量变化？",
                "释放层是否对位明确画面事件？",
                "主体、低频/尾音是否与画面尺度和停留时长相称？",
                "点缀层是否呼应可见细节？",
                "各层是否有变化和留白，而非持续堆叠？",
            ],
        })

    truncated = target < music.duration_seconds - 1e-6
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
        "### 开场 Hook", "",
        f"- 原计划状态：{advice['hook']['status']['source_status']}；建议状态：{advice['hook']['status']['advice_status']}；{advice['hook']['status']['reason']}",
        f"- 画面锚点：{advice['hook']['visual_anchor']}（创意提案，尚非确认事件）",
    ]
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
        if section["proposals"]:
            for proposal in section["proposals"]:
                lines.append(f"- 原创意建议：{proposal['proposal']}。{proposal['required_annotation']}")
        else:
            lines.append("- 未提出音效；允许保留音乐、现场声或静默空间。")
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
