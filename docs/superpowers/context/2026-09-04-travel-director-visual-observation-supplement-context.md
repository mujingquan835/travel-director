# Travel Director 画面观察补充合同修复交接

## 本阶段目标

修复真实素材人工观察结果只填写 `content_families` 后，Runner 将批次误判为已完成、无法继续补齐其余观察字段的问题。保持现有 Director 规则、Scanner、内部九阶段和公开两段式项目合同不变。

## 权威位置与边界

- 权威 worktree：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`
- 实现目录：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner`
- 分支：`feature/local-media-scanner-v0.1`
- 真实素材目录：`/Users/meimaodawang/Desktop/万岁山素材`
- 真实项目：`prototype/runs/travel-project-3d14b9a84b`
- 本阶段没有修改 Director 规则，没有重命名源素材，也没有调用本地视觉模型、曲多多、即梦、Codex API 或任何外部、付费服务。

## 实施结果

- 同一批次现在允许存在一个基础 `AgentBatchResult` 和多个补充结果文件。
- 补充结果只能填充原先缺失的字段，或重复提交完全相同的值；尝试修改既有断言会被拒绝。
- Runner 会合并基础结果和 `results/supplements/batch-xxx-*.json`，按照每条素材实际缺失字段生成下一次 `required_fields`，不会再把只填一个字段的批次视为完成。
- 派生的合并观察草稿仅在 `clip_observations` 尚未发布时原子刷新，避免恢复流程改写已经发布的观察产物。
- 没有联系图的素材明确记录为 `observation_status=unavailable`，保留未知字段，不再要求用户进行穷举式画面确认。
- 正式 Skill 和视觉观察合同已同步更新，要求覆盖 Runner 返回的全部 `required_fields`，并明确补充结果的单调追加约束。

## 真实项目恢复结果

- 输入目录识别到 270 个受支持视频。
- 27 个观察批次中，256 条素材具有可用联系图并已通过补充结果补齐观察字段。
- 14 条没有联系图的素材按 `unavailable` 处理。
- Brief 已确认：地点为开封，节奏为中等，旅行类型为人文旅行。
- Runner 当前公开状态为 `waiting_for_music`，内部 `current_stage=visual_review`，`external_call_count=0`。
- 项目已输出建议时长 60 秒和恰好三条音乐提示词；当前开发包尚不接受或分析音乐。

## 验收证据

- 聚焦测试：`52 passed in 1.92s`
- 完整测试（提交前重新执行）：`333 passed, 3 warnings in 13.65s`
- 三条警告来自 `audioread` 对 `aifc`、`audioop`、`sunau` 的弃用引用，与本次修复无关。
- `git diff --check` 通过。
- Skill 官方快速校验通过：`Skill is valid!`
- 仓库 Skill 与 `/Users/meimaodawang/.codex/skills/travel-director` 安装目录一致。

## 本阶段提交范围

本阶段代码提交只包含以下 6 个修复文件：

1. `local-media-scanner/director/agent_observations.py`
2. `local-media-scanner/director/runner.py`
3. `local-media-scanner/skills/travel-director/SKILL.md`
4. `local-media-scanner/skills/travel-director/references/visual-observation-contract.md`
5. `local-media-scanner/tests/director/test_agent_observations.py`
6. `local-media-scanner/tests/director/test_runner.py`

本文作为阶段上下文备份单独保留，不混入上述代码提交。此前未跟踪的两份 2026-08-31 历史文档同样不纳入提交。

代码提交：`5a4a775 fix: support incremental visual observations`

## 后续独立开发包

下一开发包是“用户音乐导入与现有本地音乐分析接入”：原子保存用户提供的本地音乐并绑定哈希，复用现有 `music_analysis.py` 识别 BPM、鼓点、段落、高潮和结尾。该开发包开始前应重新复核接口与测试边界，不在本阶段继续实现。

抽帧图片占位时间线、剪映全新草稿导出以及保留原编号顺序的素材重命名，继续作为后续独立工作，不与音乐导入包混合。
