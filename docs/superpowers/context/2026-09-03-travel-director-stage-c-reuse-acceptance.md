# Travel Director 阶段 C 旧数据复用验收

> **历史记录／验收结论已失效：** 本文将 12 条 benchmark 子集当成 274 条原始素材目录的恢复证据，不满足精确素材集合与源哈希绑定要求。不得再作为实施或验收依据。
>
> 当前唯一基线：[`2026-09-04-travel-director-two-stage-project-contract-context.md`](2026-09-04-travel-director-two-stage-project-contract-context.md)。

> 日期：2026-09-03
>
> 权威工作树：`<checkout>`
>
> 分支：`feature/local-media-scanner-v0.1`

## 复用输入

- 原始素材目录：`<footage-dir>`，当前仍存在，目录中有 274 个受支持视频文件。
- 原 Brief：`制作一条有进入、探索和收束结构的开封旅行短片，兼顾城市氛围与同行体验。`
- 已完成项目：`local-media-scanner/benchmark/runs/travel-director-skill-blind-v1`。
- 项目包含 12 条素材、2 个调用方视觉观察批次、Brief 确认、视觉确认、DirectorTreatment、DirectorReview、三条音乐提示词和最终总结。

## 为什么不重跑原始分析

早期的三视频 E2E 是 Scanner 管线测试，不是完整 Director 验收；但后续 `travel-director-skill-blind-v1` 已经是完整 Director 项目。该项目所有阶段 hash 仍有效，因此本阶段应验证新 `run` 对旧项目的恢复能力，而不应再解码、扫描或重做视觉观察。

## 实际验收

1. 使用 `travel-director status` 只读校验项目：`project_status=completed`、`run_state=completed`、九个阶段全部完成。
2. 使用原素材目录、原 Brief 和原项目调用新 `travel-director run`：直接返回 `completed`。
3. 第一次恢复写入 `visual/run_contract.json`，明确记录：
   - `models_enabled=false`
   - `external_services_enabled=false`
   - 原始素材绝对路径
   - 与原 Brief 一致的 SHA-256
4. 再次调用相同 `run`：仍直接返回 `completed`。
5. 第二次调用前后：
   - `project_state.json` SHA-256 均为 `a799af237c1d9591df0bdd77bbfe99684343e99aefbd64cc458c27f55dba5456`；
   - `visual/final_summary.json` SHA-256 均为 `c7436fc2b58c775e0adea5b82ed09881592466cdf1dc001491a489af898613b5`。
6. 复用验收发现旧总结仍列出两个实际不存在的可选文件 `input_manifest` 和 `review_route`。现已让总结生成器只在这些可选文件真实存在时列出，并允许确定性刷新派生的 `final_summary.json`；正式阶段产物与 `project_state.json` 均未改写。
7. 修复后 `final_summary.json` 列出的 12 个产物路径全部存在；连续两次运行的状态与总结哈希均保持不变。

## 结果

- 项目模式：`assisted`。
- 素材：12 / 12 成功，7 条主要采用，5 条备选，0 条待确认。
- 音乐提示词：恰好 3 条。
- `external_call_count=0`，所有外部服务均为 `not_executed`。
- 未重新扫描素材，未重做人物/视觉分析，未启动本地推理模型。
- 阶段 B 新增的聊天答复转换已由 fixture 行为测试覆盖；真实旧项目用于验证恢复和产物不变。
- 聚焦回归：`23 passed`；全量回归：`313 passed, 3 warnings`。三个 warning 均来自 Python 3.12 音频依赖的既有弃用提示。

## 停止点

阶段 A、B、C 已完成。当前无必做后续功能阶段；CLI 分层、旧原型清理、真实音乐生成和剪辑均不在本轮范围。
