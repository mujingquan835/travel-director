"""Render clean, human-readable Markdown delivery documents for editors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from director.delivery import FastModeTimeline


def render_fast_mode_markdown(timeline: FastModeTimeline) -> str:
    """Render a structured Markdown timeline delivery document."""
    lines: list[str] = [
        "# 🎬 旅行导演 — 快速模式时间线交付 (Fast Mode Timeline)",
        "",
        "> **交付说明**：本方案已完成音乐节拍骨架测算；音频包装状态见下文，尚未混音。画面采用文字占位；时间和节拍仅作参考，不是必切点。本 Skill 不剪辑音乐或画面。完整分段与快切/停留建议见 --build-guide。",
        "",
        "## 一、项目与音频概览",
        "",
        f"- **交付模式**: 快速模式 (Fast Mode — Rhythm Skeleton)",
        f"- **目标时长**: {timeline.target_duration_seconds:.1f} 秒",
        f"- **音乐标题**: {timeline.music_title or '已选定背景音乐'}",
        f"- **音乐资产路径**: `{timeline.music_asset_path}`",
        f"- **实测 BPM**: {timeline.bpm:.1f}" if timeline.bpm is not None else "- **实测 BPM**: 未检测",
        f"- **剪辑槽位数**: {len(timeline.slots)} 个建议参考区间",
        "",
        "---",
        "",
        "## 二、音频包装规划 (Audio Packaging)",
        "",
    ]

    if timeline.audio_packaging is not None:
        for name, report in timeline.audio_packaging.items():
            lines.append(f"- **{name} [{report.status}]**: {report.reason}")
        lines.append("")
    else:
        lines.extend(["- 历史交付未记录音效状态；不推断缺失原因。", ""])

    if timeline.sfx_assets is not None:
        lines.extend(["### 已冻结的音效文件", "", "导入下列项目内副本；音效库路径仅用于来源追踪。", ""])
        for asset in timeline.sfx_assets:
            lines.extend([
                f"- **{asset.role}**: `{asset.frozen_relative_path}`（相对项目根目录）",
                f"  - SHA-256: `{asset.sha256}`；时长: {asset.duration_seconds:.3f}s；字节数: {asset.size_bytes}",
                f"  - 来源: `{asset.source_absolute_path}`",
            ])
        if not timeline.sfx_assets:
            lines.append("- 本交付没有选中的音效，未冻结音效文件。")
        lines.append("")
    else:
        lines.extend(["- 历史方案未冻结音效字节；来源路径不代表可验证的音效副本。", ""])

    if timeline.hook_plan is not None:
        hp = timeline.hook_plan
        cfg = hp.config
        lines.extend([
            f"### 1. 黄金开场 Hook (0.0s - {hp.hook_duration_seconds:.1f}s)",
            f"- **上升音效 (Riser)**: `{hp.riser_path}` (音量: {int(cfg.riser_volume * 100)}%)",
            f"- **低音/重音冲击 (Hit/Drop)**: `{hp.hit_path}` (音量: {int(cfg.hit_volume * 100)}%)",
            f"- **BGM 闪避 (Ducking)**: 前 {hp.hook_duration_seconds:.1f}s BGM 压低至 {int(cfg.bgm_duck_level * 100)}%，随后 {cfg.bgm_recovery_seconds:.1f}s 平滑恢复",
            "",
        ])
    else:
        lines.extend([
            "### 1. 黄金开场 Hook",
            "- 未生成 Hook；以已记录状态为准，不推断淡入或其他混音处理。",
            "",
        ])

    if timeline.outro_plan is not None and timeline.outro_plan.sfx_path is not None:
        op = timeline.outro_plan
        lines.extend([
            f"### 2. 结尾收尾音效 (Outro Ringout)",
            f"- **触发时间**: {op.trigger_time_seconds:.2f}s",
            f"- **音效文件**: `{op.sfx_path}`",
            f"- **匹配理由**: {op.reason}",
            "",
        ])
    else:
        reason = timeline.outro_plan.reason if timeline.outro_plan else "未生成收尾音效规划，需人工检查剪辑点"
        lines.extend([
            "### 2. 结尾收尾音效",
            f"- {reason}",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 三、节拍参考网格（不是剪辑决定表） (Timeline Slots Grid)",
        "",
        "| 槽位 ID | 起止时间 | 时长 (s) | 音乐段落 | 能量 | 推荐运镜 | 镜头需求 / 叙事任务 | 填空引导建议 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for slot in timeline.slots:
        task = slot.narrative_task or slot.content_need
        guide = slot.visual_plan or _default_guide(slot.section_role, slot.desired_motion)
        lines.append(
            f"| `{slot.slot_id}` | {slot.start:.2f}s - {slot.end:.2f}s | {slot.duration:.2f} | "
            f"`{slot.section_role}` | {slot.energy:.2f} | `{slot.desired_motion}` | {task} | {guide} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 四、剪辑师填空实操指引",
        "",
        "1. **新建工程**：创建与素材相符分辨率与帧率的剪辑工程（如 1080×1920 竖屏 或 4K 横屏）。",
        "2. **导入音频**：将选定的背景音乐放置于 Track 1，如启用了 Hook 音效，在 0 秒处对齐叠加 Riser 与 Hit。",
        "3. **节拍标记**：可选用上方时间作为试听参考；先核对乐句、动作与叙事，不要求每拍或每个边界切换。",
        "4. **素材填空**：由用户依照画面建议自行判断素材与停留时长；本方案不分配素材、不生成源入出点。",
        "5. **微调转场**：仅在音乐、动作与叙事共同支持时考虑局部快切或转场；climax/rise 标签不代表必须快剪。",
        "",
    ])

    return "\n".join(lines)


def _default_guide(role: str, motion: str) -> str:
    guides = {
        "intro": "大景别全景或氛围特写，建立旅程环境",
        "rise": "中景/动态镜头，推进节奏与探索感",
        "breath": "舒缓空镜或人物情绪停留，给观众呼吸感",
        "climax": "视觉冲击力强、动作激烈或高潮瞬间快切",
        "outro": "收尾镜头、背影远去或定格余韵",
    }
    return guides.get(role, f"配合 {motion} 运镜强度的素材")
