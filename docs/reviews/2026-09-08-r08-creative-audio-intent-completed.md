# R08 创意音频意图与边界协调完成记录

日期：2026-09-08
范围：只生成音乐画面与音频包装建议，不剪辑音乐、不混音、不选择或剪辑画面、不渲染媒体。

## 完成内容

- 创意契约新增全局 `CreativeAudioIntent` 和分段 `SectionAudioIntent`。决策必须记录 `source` 与 `reason`；旧创意 JSON 缺少字段时按 `not_recorded` 读取，不改写历史文件。
- 支持明确禁用 Hook、禁用新增音效、保留或突出现场声、保留或要求静默空间。
- 优先级为：用户明确意图高于创意提案；同来源时分段高于全局；无结构化记录时使用通用条件式建议。自由文本仅保留为提案，不自动升级为强制策略。
- 跨层级合并产生的现场声与强制静默冲突只保留较高优先级决策，并在结果中记录被覆盖项。
- 已有时间线即使保存了 `ready` Hook，遇到更高优先级禁用意图时也只保留源状态用于溯源，不再输出 Hook 层或 Ducking 建议。
- 创意分段边界保持叙事权威。置信度至少 0.6 的音乐边界只形成 `aligned`、`near`、`mismatch`、`music_boundary_unavailable` 或 `target_cut_unanalyzed` 提示；默认容差 0.5 秒，不自动吸附或改写分段。

## 验证

- 定向测试：`62 passed`。
- 全量回归：`530 passed, 3 warnings`。3 条警告仍来自 `audioread` 导入 Python 3.12 已弃用的 `aifc`、`audioop`、`sunau`，本项未扩大警告范围。
- `git diff --check` 与 Python 编译检查通过。
- 仓库 Skill 与 `$CODEX_HOME/skills/travel-director` 完全一致。

## 真实案例

项目：`prototype/runs/travel-project-3d14b9a84b-timeline-e888731fc325da95`

交付：

- `guidance/fc5ae909571e4ecbb9a8/music_visual_guide.json`
- `guidance/fc5ae909571e4ecbb9a8/music_visual_guide.md`
- `guidance/fc5ae909571e4ecbb9a8/receipt.json`

验证结果：

- 旧创意没有结构化音频意图，正确显示为全局和五个分段均 `not_recorded`；没有从“保留入口现场底噪”等自由文本推断用户强制策略。
- 0 秒与音乐边界一致；6、18、34、49 秒显示偏移与局部试听窗口，但创意边界没有移动；60 秒标记为目标截点未分析。
- Fireflies 原曲结尾 `decay` 未套用到 60 秒目标截点，Outro 保持 `deferred`。
- `edited_or_mixed=false`，`external_call_count=0`。真实运行用补丁禁止 `subprocess.run`；除新增 guidance 交付外，项目内 5,773 个既有文件哈希一致。

## 下一项

R09：收敛交付保存入口。区分正式带收据交付与临时 validation artifact，修正 `save_fast_mode_delivery` 的“原子保存”误导，并确保正式 Runner 只有一个保存入口。
