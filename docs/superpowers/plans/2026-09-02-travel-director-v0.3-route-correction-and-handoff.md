# 旅行导演 V0.3 路线校正与新窗口交接

日期：2026-09-02

状态：路线校正已完成，待新窗口复核；尚未开始 V0.3 开发

权威工作区：`<checkout>`

分支：`feature/local-media-scanner-v0.1`

当前 HEAD：`d044526 feat: add independent blind annotation review`

## 1. 本文用途

本文取代“继续修补 V0.2 单素材静态导演标签”的后续路线，作为 V0.3 的设计边界、实施顺序和新窗口交接入口。

本文不授权开发，不授权重新运行视觉模型或批量解码视频，也不授权调用曲多多、即梦、Codex API 或任何外部/付费服务。新窗口必须先复核本文，再进入逐 Task 实施。

## 2. 产品主线是否偏移

产品主线没有根本偏移，仍然是：

```text
本地素材事实观察
  ↓
用户自然语言描述规范化与确认
  ↓
结合用户意图判断素材价值
  ↓
项目级导演方案
  ↓
固定输出 3 个音乐生成提示词，每条不超过 200 字
```

当前已完成的 Scanner、Brief、画面观察、人工辅助、DirectorTreatment 和音乐提示词合同仍可复用。

执行重点出现了三处偏移：

1. 把开场、结尾、对比、高潮等项目级导演关系实现成了单素材静态标签。
2. 让开发阶段 Ground Truth 页面占据了过多产品注意力，用户体验上接近重复确认。
3. 对人数档位、精细灯光等低编辑价值字段投入过多，而正式评估器尚未闭环。

## 3. 当前事实与证据状态

### 3.1 已提交并可复用

- V0.2 主链路及阶段合同已经实现。
- Scanner 只提供本地证据，不生成最佳区间。
- 调用当前智能体的视觉能力，不绑定具体模型，不递归创建 Codex 任务。
- 自动观察、人工辅助和阻塞状态明确区分。
- 独立盲测页面只显示冻结的 12 条 blind 素材，不显示系统预测。
- 已有 `render-blind-annotation-review` 和 `validate-blind-annotation`，但没有正式评估命令。
- 最终音乐部分固定输出 3 个可复制提示词，每条不超过 200 字，`external_call_count=0`。

### 3.2 用户 Brief 已确认

当前盲测项目采用以下用户意图：

- 地点：开封
- 旅行类型：城市漫游
- 目标时长：60 秒
- 画幅：横屏
- 风格：纪实探索
- 情绪：探索
- 节奏：中等

这些字段是 Brief 输入，不是从画面猜测出的事实。

### 3.3 独立标注文件状态

前一窗口中，用户曾提供并完成 `blind_annotation.json`，且修正了人物存在与人数档位冲突。该文件当时通过 `validate-blind-annotation`，记录过的 SHA-256 为：

```text
dda2c751aba3de2fa5a718a3c6861b694c20ff527ed2a4367f5c192c74693f1b
```

但截至本文写入时，原路径 `<downloads>/blind_annotation.json` 已不存在，仓库内也没有该文件。它从未成为提交到 Git 的正式制品。

因此新窗口不得声称当前仍持有 Ground Truth，也不得凭历史对话重建内容。开始正式评估前，必须让用户重新提供原文件，或从用户确认的可靠副本恢复，并重新运行哈希绑定校验。

恢复后建议存放为：

```text
local-media-scanner/benchmark/manual_review/travel-director-skill-blind-v1/blind_annotation.local.json
```

`benchmark/manual_review/` 已被 `.gitignore` 排除，避免把独立人工答案提交进仓库。

### 3.4 当前指标只属于临时诊断

前一窗口使用一次性只读脚本得到过以下诊断，不是仓库正式报告：

- 原始视觉观察：人物存在约 83.3% 端到端准确率，人数档位约 25%，内容类型 micro F1 约 42.1%。
- assisted 视觉观察：人数档位仍约 25%，内容类型 micro F1 约 47.6%。
- 当前 Director：桶位准确率约 50%，职责 exact-set accuracy 为 0%，职责 micro F1 约 58.3%。
- 高潮被过度触发；开场、结尾、对比几乎没有正确产出。

这些数字只能用于指出问题方向。正式评估器落地前，不得把它们作为发布指标、回归阈值或“已经提升”的证据。

## 4. 根因判断

当前 `director/intent_matcher.py` 使用静态内容映射：

```text
urban               → opening + context
lodging             → ending
attraction_activity → progression + climax
performance_event   → emotion + climax
任意 activity       → progression + climax
```

这个实现把两类概念混在了一起：

- 单素材事实与候选资格：素材里有什么、是否可用、是否相关、是否重复。
- 项目级编辑关系：哪条负责开场、哪几条形成对比、哪条是相对高潮、如何收尾。

开场、高潮、对比和结尾不是画面的固有属性：

- 开场与结尾依赖全片顺序和叙事目标。
- 高潮依赖与项目内其他素材的相对强度比较。
- 对比至少依赖两个素材或两个素材组之间的差异。
- “有动作”只说明可能具备推进能力，不能直接升级为高潮。
- “住宿”不是结尾的必要条件。

因此继续增加静态映射只会对现有 12 条素材过拟合，不是可持续路线。

## 5. V0.3 校正后的架构

V0.3 保留 V0.2 的画面观察和 Brief 合同，只重构观察之后的导演决策边界。

```text
ClipObservation
  │ 只保存可见事实和 Scanner 证据
  ↓
MaterialEligibility
  │ 单素材级：可用性、意图相关度、重复、候选能力、证据和不确定性
  ↓
ProjectRoleAssignment
  │ 项目级：跨素材比较、排序、配对、章节覆盖和职责配额
  ↓
DirectorTreatment
  │ 项目主线、章节、情绪推进、候选素材和缺口
  ↓
3 × MusicGenerationPromptRecommendation
```

### 5.1 单素材层只回答什么

- 技术上是否可用。
- 与用户 Brief 是否相关。
- 是否属于重复或近重复候选。
- 是否具备环境建立、运动推进、人物情绪、事件、细节、空间转换等候选能力。
- 哪些判断有直接证据，哪些需要弃权或人工确认。

单素材层不得直接宣称“这是最终高潮”“这是最终开场”或“这是最终结尾”。

### 5.2 项目级层如何分配职责

- `opening`：从环境建立、方向感或进入感最强的候选中选择。
- `context`：允许多条素材共同交代地点、环境和旅行状态。
- `progression`：来自移动、行为、地点变化或事件展开。
- `emotion`：来自人物、事件、感官细节和可感知反应。
- `contrast`：由空间、活动、灯光、人物密度或节奏差异形成配对关系。
- `breathing`：由低运动、细节、空镜或停顿感素材承担。
- `climax`：在全项目内相对排序后选择少量高能量或高叙事价值素材。
- `ending`：从离开、回望、放松、余韵或视觉收束候选中选择，不绑定住宿。

对当前 60 秒原型，默认只允许少量主要开场、高潮和结尾职责；具体数量由项目级策略决定并保留配置入口，不能让所有有活动的素材都成为高潮。

### 5.3 视觉字段优先级

核心字段：

- `technical_usability`
- `content_families`
- `setting`
- `people_presence`
- Scanner 的 `orientation`、`motion_level`、`duplicate_group_id`
- 直接可见的 `subject_candidates`、`activity_candidates`

辅助字段：

- `lighting`
- `people_count_band`

辅助字段可以影响排序或解释，但在没有独立可靠性证据前，不得单独触发核心桶位、硬淘汰或项目级职责。

## 6. V0.3 实施顺序

### Task 1：恢复 Ground Truth 并实现正式评估器

目标：先把评估计算变成可重复制品，不修改任何 Director 规则。

前置输入门：

1. 用户重新提供或确认恢复 `blind_annotation.json`。
2. 用当前冻结 split、Brief 和 annotation 重新运行 `validate-blind-annotation`。
3. 记录真实文件路径和 SHA-256；校验失败立即停止。

预计修改文件：

- `local-media-scanner/director/evaluation.py`
- `local-media-scanner/director/cli.py`
- `local-media-scanner/tests/director/test_visual_evaluation.py`
- 必要时新增一个小型评估报告 Schema；不修改 `intent_matcher.py`。

新增 CLI：

```text
travel-director evaluate-blind-annotation
```

固定输入：

- 冻结 split
- Brief confirmation
- 已校验 blind annotation
- raw merged observations
- assisted canonical observations
- 当前 intent decisions

固定输出：一个版本化 JSON 报告，至少包含：

- 数据集、Brief、答案和预测文件 SHA-256。
- raw 与 assisted 两条视觉结果分别报告，禁止混合。
- 枚举字段 coverage、covered accuracy、end-to-end accuracy。
- `content_families` 的 micro/macro F1、标签全集和 zero-division 规则。
- Director bucket accuracy 与 confusion matrix。
- Director function 的逐标签 precision/recall/F1、micro F1 和 exact-set accuracy。
- `evaluation_mode`、样本数、未覆盖项和 `external_call_count=0`。

验收门：

- 同一组输入重复运行生成相同语义内容和相同输入哈希。
- 缺失、未完成、membership 不一致或 Brief 哈希不一致时硬停止。
- raw 与 assisted 指标在报告结构中明确分离。
- 本 Task 不改变预测规则，因此旧预测结果必须保持不变。
- 定向测试一次；最多一次修复重试；完整测试一次；`git diff --check` 一次。
- 不运行模型、不重新解码视频、不访问网络。

### Task 2：引入单素材候选资格与项目级职责分配

目标：移除“内容类型直接等于最终导演职责”的核心依赖。

预计修改文件：

- `local-media-scanner/director/visual_schema.py`
- `local-media-scanner/director/intent_matcher.py`
- `local-media-scanner/director/director_treatment.py`
- `local-media-scanner/tests/director/test_intent_matcher.py`
- `local-media-scanner/tests/director/test_director_treatment.py`
- 必要时调整项目阶段兼容测试，但不得破坏 V0.1/V0.2 旧制品恢复。

实施要求：

1. 保留五桶位，但把桶位与最终导演职责解耦。
2. 为单素材形成可追溯的候选能力，不直接产生最终开场/高潮/结尾。
3. 在项目级对全部可用素材统一排序、配对和分配职责。
4. `contrast` 必须引用至少两个素材或两个素材组。
5. `climax` 必须是项目相对排序结果，并有数量上限。
6. `opening` 与 `ending` 必须根据项目覆盖和叙事收束选择，不使用单一内容类别硬编码。
7. `people_count_band` 与 `lighting` 只作弱证据，不能单独触发硬结论。
8. 每个项目级职责必须保留 Brief 引用、素材证据引用和选择理由。

验收门：

- 任意带 activity 的素材不再自动获得 climax。
- lodging 不再自动获得 ending。
- 同一素材在不同 Brief 下可以获得不同候选排序，但画面事实不变。
- 调换素材集合后，开场、高潮、对比或结尾允许发生项目级变化。
- 弱视觉字段缺失时链路保持弃权或降权，不伪造确定性。
- 旧项目合同如需迁移，必须有明确 schema version 和兼容测试。
- 不使用当前 blind 12 条答案调阈值或逐条修补规则。

### Task 3：建立 V0.3 开发集和新盲测

目标：避免把当前 blind-v1 既当诊断集又当新版本验收集。

规则：

- 当前 12 条 blind-v1 只作为 V0.2 冻结基线。
- V0.3 规则开发优先使用开发集和人工构造的小型关系夹具。
- 最终验收使用现有 6 条 reserve 加少量第二段旅程的新素材，形成 blind-v2。
- blind-v2 在规则冻结后只运行一次。
- 如果结果未达目标，记录失败并开启下一评估版本；不得在同一 blind-v2 上继续调参后再次宣称独立提升。

评估重点：

- 不再只追求单素材职责 exact-set。
- 同时检查章节覆盖、职责排序、高潮数量控制、对比配对有效性和证据完整性。
- 自动视觉结果与 assisted 结果分别报告。
- 数据量仍小时，不制定虚假的通用准确率承诺；先看是否稳定优于 V0.2 基线及是否消除结构性错误。

### Task 4：收敛到最终 Skill 体验

目标：让普通用户只使用 `$travel-director`，不接触开发评测表。

正式用户流程：

1. 本地扫描和受控联系图观察。
2. 规范化并确认用户描述。
3. 只询问真正影响导演判断的未知项。
4. 输出项目导演思路、章节、素材分工与缺口。
5. 输出 3 个不超过 200 字的音乐生成提示词。

人工路由保持：

- 待确认不超过 5 个字段且不超过 3 条素材：在聊天中一次确认。
- 超过任一阈值：才生成本地复核页。
- 独立盲测页面只属于 `benchmark`，永远不进入正常 Skill 流程。

验收门：

- 正常 Skill 不要求用户填写 Ground Truth、bucket 或 director function。
- 最终摘要不暴露内部 JSON 字段名。
- 本地网页只作为必要的 assisted 工具，不是产品主入口。
- 最终仍固定输出 3 条音乐提示词，外部调用为 0。

## 7. 明确不做

V0.3 当前阶段不做：

- 不更换或下载新的本地视觉模型。
- 不把调用方智能体绑定到具体 Codex 型号。
- 不调用 Codex API。
- 不重新批量运行 100 条视频。
- 不生成最佳剪辑区间。
- 不调用曲多多、网易云、QQ 音乐、Spotify 或 Apple Music。
- 不调用即梦、Runway 或其他生成服务。
- 不生成音乐或音效。
- 不接入剪映、Kdenlive 或其他编辑器。
- 不把 blind-v1 的人工答案提交到仓库。

音乐服务、音乐生成、时间线和编辑器属于后续阶段，必须再次获得用户明确授权。

## 8. 额度与执行纪律

每个窗口只推进一个 Task：

1. 先核对权威 worktree、分支、HEAD、Git 状态和输入文件。
2. 先运行一组最小失败测试，再修改实现。
3. 定向测试一次；失败后最多修复并重试一次。
4. 完整测试只在该 Task 末运行一次。
5. 真实视频 smoke 每个里程碑最多一次；Task 1、Task 2 默认不需要。
6. 不重复生成现有联系图，不重复读取全部 12 条素材画面。
7. 所有外部服务保持 `not_executed`。
8. 未完成时明确记录 partial/blocked，不以文档或部分测试代替完成。

Task 1 与 Task 2 主要消耗代码阅读、测试和规则推理额度，不需要视觉模型推理；预计显著低于重新跑模型或重新分析整批视频。

## 9. Git 与工作区边界

新窗口必须从以下路径开始：

```text
<checkout>
```

不要在根目录 `main` 判断 Scanner 缺失或重做已有功能。

本文写入前，权威 worktree 中已有以下无关未跟踪文件，后续不得顺手删除、覆盖或纳入本路线提交：

- `docs/superpowers/context/2026-08-31-audio-provider-and-jianying-plan-context.md`
- `docs/superpowers/context/2026-08-31-kdenlive-losslesscut-analysis-context.md`
- `docs/superpowers/plans/2026-08-31-audio-provider-and-jianying-handoff.md`
- `docs/superpowers/plans/2026-08-31-visual-understanding-and-director-decision.md`

本路线新增的唯一计划文件是本文。

## 10. 新窗口启动检查清单

新窗口先执行只读检查：

```bash
git worktree list
git -C <checkout> status --short
git -C <checkout> log -1 --oneline
```

然后完整阅读：

1. 本文。
2. `docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md` 顶部 V0.2 修正。
3. `docs/superpowers/plans/2026-08-31-visual-understanding-and-director-decision-v2.md`。
4. `local-media-scanner/benchmark/DIRECTOR_VISUAL_ANNOTATION_GUIDE.md`。
5. `local-media-scanner/director/evaluation.py`。
6. `local-media-scanner/director/intent_matcher.py`。

新窗口第一句话建议使用：

```text
请在权威 worktree 中阅读 docs/superpowers/plans/2026-09-02-travel-director-v0.3-route-correction-and-handoff.md，先检查 Git 和 blind annotation 输入状态。本轮只复核并实施 V0.3 Task 1：恢复并校验 Ground Truth、实现正式 evaluate-blind-annotation 评估器；不要修改 Director 规则，不要调用模型、曲多多、即梦、Codex API 或任何付费服务。
```

## 11. 当前停止点

路线校正和新窗口交接文档已经完成。

当前停止在 V0.3 Task 1 开发之前。下一窗口首先要解决的不是视觉模型，也不是 Director 调参，而是恢复用户独立标注文件并建立可重复、可审计的正式评估器。
