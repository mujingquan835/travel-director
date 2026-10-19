# Travel Director 两段式项目合同交接

## 完成范围

- 权威 worktree：`<checkout>`
- 分支：`feature/local-media-scanner-v0.1`
- `run_contract.json` 0.3.0 绑定绝对素材根目录、Brief SHA-256、受支持素材清单、文件大小、`mtime_ns`、`ctime_ns` 与源文件 SHA-256。
- 新项目首次绑定时每个素材只计算一次源 SHA-256；相同项目恢复只比较根目录、Brief 和文件快速身份，不重读源视频。
- 恢复时在任何工作流写入前校验合同；目录、Brief、素材增删或内容变化均返回 `blocked`。
- 新项目在创建目录前校验受支持素材清单。
- 0.2.0 合同保持原文件不变并使用其已有快速字段恢复；无合同旧项目只有在已完成观察能够证明精确素材集合与源哈希时才允许补建 0.3.0 合同。
- 无素材指纹的旧项目保持只读阻断，benchmark 子集不能绑定更大目录。
- 视觉阶段完成后返回 `waiting_for_music`，包含建议时长、恰好三条音乐提示词与 `provide_music` 动作；`completed` 保留给未来真正产生剪辑草稿的阶段。
- `run --response-file <downloaded-json>` 可导入本地页面下载的 Brief/画面确认。错误类型、错误哈希和重复导入均在不改写项目状态的前提下阻断。
- 正式 `$travel-director` Skill 已更新并同步到 `$CODEX_HOME/skills/travel-director`。

## 验收证据

- 基础收口聚焦测试：`58 passed in 3.70s`
- 基础收口完整测试：`329 passed, 3 warnings in 14.50s`
- 警告均为 `audioread` 对 Python 3.13 将移除标准库的弃用提示，与本开发包无关。
- Skill 源目录与安装目录 `diff -qr` 无差异。
- `external_call_count=0`；本轮未扫描真实 274 条素材，未调用模型、曲多多、即梦、Codex API 或任何外部/付费服务。

## 文档事实更正

- 2026-09-03 阶段 C 的“12 条 benchmark 子集复用验收 274 条原始目录”结论已标记失效。
- 阶段 B、Skill 简化、音乐 Provider/剪映旧文档原位保留，已加历史或部分过期标记并指回本文。

## 未纳入本开发包

1. 用户音乐导入与现有本地音乐分析。
2. 鼓点、高潮与抽帧占位时间线。
3. 验证开源方案并创建全新剪映草稿。

## Git 状态

本开发包尚未提交。工作树中同时存在此前阶段的未提交文件，后续提交前需按范围分组复核，不要清理或重置用户已有变更。

建议的两段式基础合同提交候选为：

- `.gitignore`
- `local-media-scanner/director/runner.py`
- `local-media-scanner/director/cli.py`
- `local-media-scanner/director/skill_summary.py`
- `local-media-scanner/skills/travel-director/SKILL.md`
- `local-media-scanner/skills/travel-director/references/workflow.md`
- `local-media-scanner/tests/director/test_runner.py`
- `local-media-scanner/tests/director/test_skill_summary.py`
- `local-media-scanner/tests/director/test_travel_director_skill.py`
- 本文，以及本轮添加失效标记的 6 份历史文档。

`2026-08-31-kdenlive-losslesscut-analysis-context.md` 和 `2026-08-31-visual-understanding-and-director-decision.md` 未在本轮修改，不属于上述提交候选。
