# 旅行导演：素材理解与导演决策实施计划 V2

日期：2026-08-31

状态：已批准；Task 1、Task 2、Task 3 已完成；Task 4 已按硬停止门结束为 `not_qualified`，回退 `scanner_only + assisted`

权威工作区：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`

分支：`feature/local-media-scanner-v0.1`
编写基线：`9f1616590baedbeab0f301d60ad9a4447d2a7afd`

> 本计划是对 `2026-08-31-visual-understanding-and-director-decision.md` 的可执行性复审版。V1 保留为讨论记录，后续实施以 V2 为准。本计划本身不授权开发、模型下载、视频推理、浏览器登录、曲多多/即梦调用或任何付费服务。

Task 1 执行证据：严格合同、Provider 接口、V0.1/V0.2 Stage Graph、阻塞停止规则和最小 CLI 已实现；目标测试 `26 passed`，完整回归 `148 passed, 3 warnings`；模型下载、视频推理与外部调用均为 0。

Task 2 执行证据：冻结 12 条开发集、12 条盲测集和 6 条保留集，复用 95 张已有 probe 图；空白标注模板、验证器、可离线导出/导入的画面复核页、独立导演判断复核页及重复素材确定性夹具已实现；定向回归 `27 passed`，真实浏览器检查 24 条素材和 95 张图片全部加载、控制台 0 错误；Scanner、视觉模型、视频解码与外部调用均为 0。

Task 3 执行证据：保存的 3 条 Scanner JSON fixture 已映射为 V0.2 `scanner_only` 观察；技术/CV 原始证据保持 `measured`，人物下界及弱 scene/action/object 只允许 `candidate` 或 `abstained`，影响导演判断的未知字段进入逐素材复核；V0.2 画面理解产物不含 `recommended_ranges/source_in/source_out`，时间线放置从整条源素材选择，V0.1 默认行为保持不变；指定回归 `21 passed`，Scanner、视觉模型、真实视频解码与外部调用均为 0。

Task 4 执行证据：用户明确批准后，唯一候选 `mlx-community/Qwen3-VL-4B-Instruct-4bit@2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b` 已下载到项目隔离缓存，真实权重 `3,093,767,283 bytes`、隔离目录约 `3.5 GB`。冷加载耗时 `2.4554s`，但在首条提示词构造前，swap 从 `1,343,162,941 bytes` 增至观测值 `2,732,190,597 bytes`，增量 `1,389,027,656 bytes / 1324.68 MiB`，超过 `512 MiB` 硬停止门；因此 0 条进入推理，100 条速度门无法实测，12 条开发集和盲测均未运行。候选记为 `not_qualified`，不安装缺失的 `jinja2` 后重试、不尝试第二模型；详细证据见 `docs/superpowers/audits/2026-08-31-qwen3-vl-4b-mlx-smoke-result.md`。

## 结论

第一阶段可以实现，但不能把“某个本地视觉模型一定能在当前 Mac 上稳定运行”当作前提。可交付方案必须同时满足以下条件：

1. 自动识别优先，但它只是可替换 Provider，不是整条链路的单点依赖。
2. 自动结果低置信度、模型不可用或能力验收失败时，转为本地人工确认；确认后的流程仍能生成导演方案和音乐风格推荐。
3. `automatic` 和 `assisted` 必须在结果中明确区分，不能把人工确认结果冒充成自动识别成功。
4. 先落版本化编排、人工回填和盲测框架，再接模型；不能把集成风险留到最后。
5. 第一阶段只理解整条素材，不推荐“最佳区间”；`source_in/source_out` 延后到音乐结构和时间线阶段。

只要用户愿意在低置信度项上做最少量确认，链路不存在技术性死路。若自动模型失败且用户也不确认，项目状态必须是 `blocked`，这是诚实的产品边界，不应伪造完成。

## 当前工作区审查

### 已存在且可复用

- Scanner 已有技术元数据、稀疏代表帧、CV 指标、候选视觉标签、缓存和错误记录。
- `benchmark/test_manifest.json` 已冻结 30 条素材；对应源文件和已有测试缩略图可用。
- 已保存的 30 条视觉运行结果包含 478 张 probe 图；建立评估包无需重新解码整批视频。
- `scanner.selection` 已有分层选择与独立集合选择函数。
- `clip_selector._available_ranges()` 在没有 `recommended_ranges` 时已经能回退到整条素材。
- 当前测试基线为 `137 passed, 3 warnings`；该结果只代表 V0.1，不代表本计划已经实现。

### 必须先补的缺口

- `director/project.py` 的阶段顺序、产物路径和 Schema 校验写死为 V0.1；直接加入新阶段会破坏旧项目恢复。
- `UserCreativeBrief` 只有固定结构化字段，没有“用户原始描述 → 规范化 → 用户确认”的合同。
- 当前没有明确的 `DirectorReasoningProvider`；不能默认依赖 Codex、云模型或某个尚未验证的本地模型。
- `render_manual_review_sheet()` 只能展示，不能导出人工修订 JSON，也没有导入校验闭环。
- V1 的 12 条样本同时用于调试和验收，会产生调参泄漏。
- 现有 30 张中点图未发现可用于验收的近重复对，重复识别不能混在语义盲测中虚假宣称已覆盖。
- V1 把评估模块错误放进 `scanner/`；导演判断评估应归属 `director/evaluation.py`。

## 交付边界

### 本阶段交付

- 整条素材的可追溯内容观察。
- 用户自然语言描述的规范化结果和确认记录。
- 素材与用户意图的匹配判断。
- 项目级导演主线、章节、情绪推进、素材职责与缺口。
- 最多三个离线音乐风格方向。
- 可在本地浏览器修改并导出 JSON 的人工复核页。
- 自动、人工辅助、阻塞三种状态的完整证据。

### 本阶段不交付

- 不计算最佳剪辑区间。
- 不搜索、试听、下载或推荐具体歌曲。
- 不调用曲多多、网易云、QQ 音乐、Spotify 或 Apple Music。
- 不调用即梦、Runway 或其他图像/视频/音乐生成服务。
- 不生成音乐、不生成音效、不调用剪映。
- 不批量运行 100 条视频，不重新跑已有 30 条 Detector/SigLIP 实验。

## 可完成的产品链路

```text
本地视频
  ↓
ScannerEvidenceBundle
  ├─ 技术/CV/代表帧/错误/重复证据
  └─ 每条最多 3—5 张受控尺寸代表图
  ↓
VisualUnderstandingProvider
  ├─ automatic：通过能力门的本地 VLM
  └─ scanner_only：只整理现有证据并主动弃权
  ↓
ClipObservationDraft
  ↓ 低置信度项
本地人工复核页 → visual_confirmation.json
  ↓
ConfirmedObservationSet  [automatic | assisted]
  +
用户原始描述 → NormalizedIntentDraft → brief_confirmation.json
  ↓
DirectorReasoningProvider
  ├─ deterministic：必须可用的规则与模板基线
  └─ local_reasoner：可选，只做证据受限的结构化增强
  ↓
DirectorTreatment
  ↓
MusicStyleRecommendation（离线，最多 3 项）
```

## 运行状态和回退规则

### 项目完成模式

- `automatic`：所有影响导演判断的必需观察均通过自动门槛，无待确认项。
- `assisted`：至少一项观察或 Brief 字段由用户确认/修订，后续链路完成。
- `blocked`：存在必需确认项，自动 Provider 无法可靠给出，且尚未获得用户确认。
- `failed`：输入损坏、合同不兼容或产物证据漂移，无法安全继续。

### 强制规则

- 低置信度字段必须进入 `review_required_fields`，不能用默认答案补齐。
- 单条素材的低置信度不阻止其他素材继续处理。
- 只有影响项目判断的必需字段才要求人工确认；可选描述字段允许 `unknown`。
- 人工修改必须保存原自动值、修改后值、修改时间和理由，不能覆盖原始推理证据。
- `reject_suggestion` 只能由不可解码、明确技术失败或已确认规则触发；弱语义不能导致淘汰。
- 任何原始视频都不移动、不删除、不改写。

## V0.2 稳定合同

```text
EvidenceRef =
  material_id?, artifact_path, field_path, frame_timestamp?, source_kind,
  status, confidence?, sha256?

MaterialRef =
  material_id, relative_path, source_sha256,
  size_bytes, mtime_ns, duration_seconds, fps, orientation, rotation?

ClipObservation =
  schema_version, file, provider, observation_status,
  technical_usability,
  content_families[], setting_candidates[], lighting_candidates[],
  people_presence_candidate, people_count_band_candidate,
  subject_candidates[], activity_candidates[],
  quality_evidence, motion_evidence, original_audio_value_candidate,
  duplicate_group_id,
  assertions[], unknown_fields[], review_required_fields[], errors[]

ObservationAssertion =
  field, value, status, confidence?, evidence_refs[]

RawCreativeBrief =
  schema_version, raw_description, optional_structured_hints

NormalizedIntentDraft =
  location?, travel_type?, target_duration_seconds?, orientation?,
  audience?, platform?, central_subject?, must_include[], must_avoid[],
  desired_story?, desired_emotion?, rhythm?, style?,
  people_focus?, authenticity_preference?, vocals?, instruments[],
  source_spans[], unknown_fields[], review_required_fields[]

BriefConfirmation =
  normalized_brief, status, changed_fields[], confirmed_at

IntentConditionedDecision =
  file, bucket, relevance_score, confidence,
  director_function_candidates[], reasons[], evidence_refs[],
  user_confirmation_required

ProjectCoverage =
  content_distribution, lighting_distribution, people_distribution,
  motion_distribution, duplicate_groups,
  available_director_functions, missing_director_functions,
  uncertainty_summary

DirectorTreatment =
  mode, logline, narrative_spine, chapters[], emotional_arc[],
  pacing_strategy, core_materials[], candidate_materials[],
  redundant_materials[], reject_suggestions[], review_required[],
  coverage_gaps[], evidence_refs[], unsupported_inferences[]

DirectorReview =
  treatment_sha256, status, mode, overrides[], confirmed_at?

EditorialOverride =
  material_id, original_bucket, bucket_override?,
  director_function_overrides[], force_include, force_exclude,
  user_note?, changed_at

MusicStyleRecommendation =
  direction_id, plain_description, genres[], moods[],
  bpm_min, bpm_max, instruments[], drum_density, vocals,
  energy_curve[], fit_reason, director_evidence_refs[]
```

枚举边界：

- `bucket`: `core | candidate | redundant | reject_suggestion | review_required`
- `director_function_candidates`: `opening | context | progression | emotion | contrast | breathing | climax | ending`
- `content_families`: `urban | nature | culture_architecture | food | transport | lodging | attraction_activity | performance_event | people | detail | other`
- 语义状态：`measured | candidate | confirmed | abstained | unavailable`
- V0.2 新产物使用 `schema_version: 0.2.0`；V0.1 只读兼容，不静默迁移、不覆盖历史 JSON。
- `material_id` 由输入清单中的源文件 SHA-256 稳定派生；文件移动或编辑器重连后仍能识别同一素材，路径不能单独充当身份。
- `DirectorReview` 与 `visual_confirmation.json` 分层：前者只修改编辑判断，后者只修正确认后的画面观察；两者都保留原值和审计记录。
- 本阶段的 `EditorialOverride` 不包含时间区间，不以人工复核之名重新引入“最佳区间”。

## 本地模型候选与能力门

### 候选选择

首选候选族为 [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)：官方模型卡标注 Apache-2.0、4B 参数，并声明图像、空间与视频理解能力。运行时优先评估 [MLX-VLM](https://github.com/Blaizzy/mlx-vlm/blob/main/README.md)，因为它提供多图输入接口；[MLX](https://mlx-framework.org/) 面向 Apple Silicon 的统一内存架构。

这只是候选，不是已确认可用结论。当前尚未证明“某个 Qwen3-VL 4-bit MLX 制品 + 当前 MLX-VLM 版本 + 当前 Mac”能够稳定组合，因此实施前必须锁定：

- 精确仓库、revision、许可证和量化方式。
- 实际下载体积和缓存目录。
- 当前机器的总内存、可用空间和卸载方法。
- MLX-VLM 对该精确 revision 的多图推理是否成功。
- JSON 结构化输出、中文素材描述和置信度/弃权行为是否满足合同。

### 输入策略

- 不把完整视频交给模型；每条只送 3—5 张已有代表帧组成的多图输入。
- 单帧长边默认不超过 768 px；若 smoke 显示资源压力，再降到 512 px并记录变更。
- 提示词只要求“看见什么”，禁止直接判断核心、淘汰、高潮或音乐。
- 输出限制为紧凑 JSON；解析失败最多修复并重试一次。
- 第一轮只跑 2 条 smoke；通过后最多跑 12 条开发集和 12 条盲测集各一次。

### 硬停止条件

- 模型或量化制品许可证不清晰。
- 下载体积未在授权前明确，或超过用户批准的上限。
- 2 条 smoke 任一导致 OOM、持续 swap 压力、进程崩溃或结构化输出连续失败。
- 进程树峰值内存达到实施前约定的机器安全上限；默认先以 11 GiB 为审查上限，必须结合实机总内存再确认。
- 不能对不确定内容弃权，或出现无证据的确定性人物/地点/事件描述。

触发停止条件后不试第二个模型，默认切换 `scanner_only + assisted`，整个产品链路继续；自动模式记录为 `not_qualified`。

## 评估设计

### 数据拆分

从现有 30 条冻结清单按元数据分层确定：

- 12 条开发集：只用于合同调试、提示词修正和阈值确定。
- 12 条盲测集：开发期间不查看模型评分结果、不调阈值，只在里程碑末运行一次。
- 6 条保留：不进入本里程碑，可用于未来回归。

选择只读取冻结 manifest、技术元数据和已有 CV 分层，不读取新模型预测。保存 selection seed、源 manifest 哈希和 membership 哈希。

### 人工标注顺序

1. 先只看代表帧，标注 24 条 `ClipObservation`；不展示模型结果和 Brief。
2. 在 6 条开发锚点上分别套用 3 个固定 Brief，标注应发生的职责变化。
3. 将 12 条盲测素材作为一个项目，针对一个冻结 Brief 标注素材桶、职责和项目覆盖。
4. 模型结果生成后再做对照，避免先看答案再改人工标准。

人工标签默认写入本地 `*.local.json` 并加入 `.gitignore`；仓库只提交模板、验证器、manifest 和标签文件哈希，避免实现阶段直接读取盲测答案。

### 重复素材单独验收

现有 30 张中点图没有足够的近重复对，不能拿它证明真实重复检测。另建确定性小夹具：

- exact：同一图像字节复制。
- near：轻度缩放/重编码后的同一画面。
- distinct：明显不同的画面。

夹具只验证算法边界；真实素材重复能力在没有真实标注对时必须标为 `not_evaluated_real_pair`。

### 自动模式通过门

- 不支持断言率：开发集 0，盲测集 0。
- `reject_suggestion` precision：100%。
- 人工标为核心的素材 recall：至少 80%。
- `content_families` Macro F1：盲测至少 0.70；同时报告每类样本数，避免小样本总分掩盖问题。
- 影响导演判断的自动完成率：盲测至少 50%；否则即使准确，也不能证明它有效降低人工负担。
- 所有 Director 判断和音乐理由均有可解析的素材证据或 Brief 引用。
- 所有人工认为应随 Brief 改变的锚点，系统至少出现一项有证据的桶位或职责变化。

任何硬门未通过，第一阶段仍可按 `assisted` 交付，但不得把自动 Provider 设为默认合格。

## 文件地图

计划新增：

- `local-media-scanner/director/visual_schema.py`
- `local-media-scanner/director/providers.py`
- `local-media-scanner/director/visual_understanding/scanner_evidence.py`
- `local-media-scanner/director/visual_understanding/local_vlm.py`（仅模型门获批后）
- `local-media-scanner/director/brief_interpreter.py`
- `local-media-scanner/director/intent_matcher.py`
- `local-media-scanner/director/director_treatment.py`
- `local-media-scanner/director/music_style_recommender.py`
- `local-media-scanner/director/visual_review.py`
- `local-media-scanner/director/evaluation.py`
- `local-media-scanner/benchmark/DIRECTOR_VISUAL_ANNOTATION_GUIDE.md`
- `local-media-scanner/benchmark/director_visual_dev_manifest.json`
- `local-media-scanner/benchmark/director_visual_blind_manifest.json`
- `local-media-scanner/benchmark/director_visual_briefs.json`
- `local-media-scanner/benchmark/director_visual_ground_truth.template.json`
- 对应的 `tests/director/test_*.py`

计划修改：

- `docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md`
- `local-media-scanner/director/schema.py`
- `local-media-scanner/director/project.py`
- `local-media-scanner/director/cli.py`
- `local-media-scanner/director/material_enrichment.py`
- `local-media-scanner/director/scanner_bridge.py`
- `local-media-scanner/director/clip_selector.py`
- `local-media-scanner/director/search_planner.py`
- `local-media-scanner/PROTOTYPE.md`
- `local-media-scanner/.gitignore`

明确不修改：

- `local-media-scanner/scanner/schema.py`
- Scanner 权重、阈值、缓存和既有运行产物
- `/Users/meimaodawang/Desktop/万岁山素材` 及其他原始素材目录
- 曲多多、即梦、音乐 Provider、剪映或外部平台集成

## 可执行任务

以下所有 `uv run` 命令均从 `local-media-scanner/` 目录执行；清单中写出完整 `cd`，避免在 worktree 根目录误跑。

### Task 1：版本化合同与编排骨架

**目标：** 第一笔开发先证明 V0.2 阶段可以完整编排，同时 V0.1 项目仍可只读恢复；不运行模型。

**文件：**

- 新增：`director/visual_schema.py`
- 新增：`director/providers.py`
- 新增：`tests/director/test_visual_schema.py`
- 新增：`tests/director/test_visual_project_e2e.py`
- 修改：`director/project.py`
- 修改：`director/cli.py`
- 修改：设计规格文档

**步骤：**

- [x] 先写失败测试：V0.1 项目可重新打开；V0.2 严格拒绝额外字段；不同版本不能互相误读。
- [x] 把单一 `LOCAL_STAGE_ORDER` 改为版本化 Stage Graph；V0.1 阶段顺序保持不变。
- [x] 给 V0.2 增加 `clip_observations → intent_brief → brief_confirmation → intent_decisions → project_coverage → director_treatment → director_review → music_style_recommendations → visual_review`。
- [x] 增加对应 `ProjectPaths` 和 `artifact_for()` 映射；所有产物继续使用原子写入和 SHA-256 证据。
- [x] 冻结由源文件 SHA-256 派生的 `material_id`；所有观察、判断和人工 override 都引用稳定 ID，同时保留相对路径用于展示与重连。
- [x] 定义 `VisualUnderstandingProvider`、`BriefInterpreterProvider`、`DirectorReasoningProvider` 接口和能力描述。
- [x] 用纯 fixture Provider 做一条 V0.2 stub E2E，证明阶段状态、恢复和产物哈希闭环，不实现业务逻辑。
- [x] CLI 增加 `init-visual-project` 和 `visual-status`，只创建/读取合同，不伪造完成产物。
- [x] 运行：`cd local-media-scanner && uv run pytest tests/director/test_project.py tests/director/test_visual_schema.py tests/director/test_visual_project_e2e.py -q`。
- [x] 同一失败类型最多修复并重跑一次；目标测试通过后运行一次 `cd local-media-scanner && uv run pytest -q`，随后在 worktree 根目录运行 `git diff --check`。
- [x] 提交：`git commit -m "feat: add versioned visual director workflow"`

**完成门：** V0.1 回归通过；V0.2 stub 可从初始化走到静态最终产物；没有模型、外部调用和真实视频解码。

### Task 2：开发集、盲测集和可回填人工工具

**目标：** 在模型前冻结评估答案和人工回退通道；不运行 Scanner 或视觉模型。

**文件：**

- 新增：6 个 `benchmark/director_visual_*` 文件
- 新增：`director/evaluation.py`
- 新增：`director/visual_review.py`
- 新增：`tests/director/test_visual_evaluation.py`
- 新增：`tests/director/test_visual_review.py`
- 修改：`.gitignore`

**步骤：**

- [x] 从 30 条冻结 manifest 生成 12/12/6 不重叠拆分，记录 seed 和哈希。
- [x] 复用已有 probe 图；不得重新批量解码视频。
- [x] 先写标注模板和验证器，再生成任何模型预测。
- [x] 复核页提供候选值、`unknown`、备注和“需要确认”字段，可离线下载 `visual_confirmation.json`。
- [x] CLI 增加 `render-visual-review`、`validate-visual-confirmation`、`import-visual-confirmation`。
- [x] 导入时保留原值与修改记录；不允许缺失素材、未知枚举或悬空证据引用。
- [x] 增加独立 `director_review.json`：允许改桶位、导演职责、强制保留/排除和备注，但不允许填写时间区间。
- [x] 用临时目录生成 exact/near/distinct 重复夹具，单独验证重复指标。
- [x] 运行：`cd local-media-scanner && uv run pytest tests/director/test_visual_evaluation.py tests/director/test_visual_review.py -q`；随后在 worktree 根目录运行 `git diff --check`。
- [x] 提交：`git commit -m "test: freeze visual evaluation and review workflow"`

**完成门：** 即使没有任何新模型，用户也能查看每条素材、填写最少必要字段、导出并重新导入通过验证的 JSON。

### Task 3：Scanner-only 证据基线与整条素材策略

**目标：** 建立不制造语义的零新增模型基线，并彻底证明第一阶段不依赖最佳区间。

**文件：**

- 新增：`director/visual_understanding/scanner_evidence.py`
- 新增：`tests/director/test_scanner_evidence_understanding.py`
- 修改：`director/scanner_bridge.py`
- 修改：`director/material_enrichment.py`
- 修改：`director/clip_selector.py`
- 修改：对应旧测试

**步骤：**

- [x] 将技术/CV 证据映射为 `measured`，弱 scene/action/object 映射为 `candidate` 或 `abstained`。
- [x] 人物下界不得变成精确人数；候选地点不得变成确定地点。
- [x] 新 V0.2 产物不生成 `recommended_ranges`；V0.1 JSON 仍可读取。
- [x] V0.2 clip placement 始终从整条源素材选择，只有时间线阶段才生成 in/out。
- [x] 用保存的 JSON fixture 跑基线，不解码视频、不加载模型。
- [x] 把所有会影响导演判断的未知项送入人工复核，不阻塞无关素材。
- [x] 运行：`cd local-media-scanner && uv run pytest tests/director/test_scanner_evidence_understanding.py tests/director/test_material_enrichment.py tests/director/test_clip_selector.py tests/director/test_scanner_bridge.py -q`；随后运行 `git diff --check`。
- [x] 提交：`git commit -m "feat: add scanner-only observation baseline"`。

**完成门：** Scanner-only 能生成诚实的草稿和人工确认任务；旧 V0.1 行为没有被静默改写。

### Task 4：一个本地 VLM 的受控能力验证

**目标：** 在用户单独批准下载后，判断自动识别是否真正降低人工负担；失败不阻塞后续任务。

**前置门：** 提交一页制品审计并获得明确批准。审计必须包含精确 URL/revision、许可证、下载体积、缓存位置、卸载命令、实机内存上限和 2 条 smoke 清单。

**文件：**

- 新增：`director/visual_understanding/local_vlm.py`
- 新增：`tests/director/test_local_vlm_contract.py`
- 新增：本地实验结果目录（默认 gitignored）

**步骤：**

- [x] 只评估一个精确模型制品；不并行下载第二个候选。
- [x] 先做无权重的 Provider 合同测试和假响应解析测试。
- [x] 获批后下载一次；2 条多图 smoke 在首条推理前因 swap 增量超过硬门停止，记录冷加载、swap 和 0 次推理事实。
- [x] 因 smoke 未通过，不运行 12 条开发集，不修提示词/阈值。
- [x] 因候选已失败，不运行 12 条盲测。
- [x] 按失败路径输出实机报告，不宣称自动模式通过。
- [x] 记录 `not_qualified` 并切回 `scanner_only + assisted`，不注册真实 `local_vlm` Runner。
- [x] 运行：定向测试 `14 passed`；完整回归 `175 passed, 3 warnings`；`git diff --check` 通过。
- [x] 提交仅包含代码、测试、审计和阶段摘要；模型权重、完整缓存、实验原始结果和用户素材均未提交。最终提交以本任务 `HEAD` 为准，避免 amend 后在提交正文中记录过期哈希。

**停止门：** 任一硬停止条件触发后立刻结束模型实验；不尝试第二模型，不延误 Task 5。

### Task 5：用户描述规范化与确认

**目标：** 接受中文自然语言描述，但不让错误解析静默进入导演方案。

**文件：**

- 新增：`director/brief_interpreter.py`
- 新增：`tests/director/test_brief_interpreter.py`
- 修改：`director/schema.py`
- 修改：`director/cli.py`

**步骤：**

- [ ] 增加 `raw_description`、规范化草稿、字段来源片段和确认合同。
- [ ] 必须提供 deterministic 基线：解析明确的时长、横竖屏和枚举关键词，其余字段允许未知。
- [ ] 若 Task 4 本地模型合格，可用同一运行时做结构化文本增强；不得因此新增第二个模型。
- [ ] 所有模式都展示规范化结果；影响方向的未知/冲突字段必须让用户确认。
- [ ] CLI 增加 `normalize-brief`、`render-brief-review`、`confirm-brief`。
- [ ] 测试中文自由描述、字段冲突、空描述、旧 V0.1 brief 和人工修订审计。
- [ ] 运行：`cd local-media-scanner && uv run pytest tests/director/test_brief_interpreter.py tests/director/test_schema.py tests/director/test_project.py -q`；随后运行 `git diff --check`。
- [ ] 提交：`git commit -m "feat: normalize and confirm creative brief"`。

**完成门：** 系统能说明每个结构化字段来自哪段用户文字；未确认的关键字段不会进入导演推理。

### Task 6：证据受限的导演判断

**目标：** 不依赖 Codex 或云模型，也能从确认后的素材观察和 Brief 生成可解释方案。

**文件：**

- 新增：`director/intent_matcher.py`
- 新增：`director/director_treatment.py`
- 新增：`tests/director/test_intent_matcher.py`
- 新增：`tests/director/test_director_treatment.py`
- 修改：`director/cli.py`

**步骤：**

- [ ] 实现必须可用的 deterministic Provider：规则计算五桶、素材职责、覆盖和缺口，用模板生成简洁导演方案。
- [ ] 每个桶位、职责、章节和情绪判断至少引用一个确认观察或 Brief 字段。
- [ ] `reject_suggestion` 只接受硬证据；重复项只进 `redundant`，不删除素材。
- [ ] 可选 local reasoner 只能在 deterministic 结构上改写/排序，不得引入合同外事实。
- [ ] 运行 6 条 × 3 Brief 锚点，验证预期的职责变化；运行 unsupported assertion 检查。
- [ ] CLI 增加 `build-director-treatment`。
- [ ] 运行：`cd local-media-scanner && uv run pytest tests/director/test_intent_matcher.py tests/director/test_director_treatment.py -q`；随后运行 `git diff --check`。
- [ ] 提交：`git commit -m "feat: build evidence-bound director treatment"`。

**完成门：** 关闭所有本地生成模型后仍可完成导演方案；打开增强层也不能越过证据边界。

### Task 7：离线音乐风格推荐

**目标：** 只从已确认的导演方案推导风格，不访问音乐平台。

**文件：**

- 新增：`director/music_style_recommender.py`
- 新增：`tests/director/test_music_style_recommender.py`
- 修改：`director/search_planner.py`
- 修改：`director/cli.py`

**步骤：**

- [ ] 输入必须是已完成 `DirectorTreatment + BriefConfirmation + ProjectCoverage`。
- [ ] 用可审计规则矩阵输出最多三个方向：流派、情绪、BPM 区间、配器、鼓点密度、能量曲线和适配理由。
- [ ] 三个方向至少在节奏、配器或情绪策略中的两项存在实质差异。
- [ ] 记录 `external_call_count=0`；不得输出具体歌曲、试听链接或伪造平台结果。
- [ ] CLI 增加 `recommend-music-styles`。
- [ ] 运行：`cd local-media-scanner && uv run pytest tests/director/test_music_style_recommender.py tests/director/test_search_planner.py -q`；随后运行 `git diff --check`。
- [ ] 提交：`git commit -m "feat: recommend offline music styles"`。

**完成门：** 用户能从导演方案理解为什么推荐这些风格；没有发生网络或付费调用。

### Task 8：全链路盲测与第一阶段交付

**目标：** 用冻结盲测集证明系统在自动或 assisted 模式下都能诚实完成。

**文件：**

- 修改：`director/visual_review.py`
- 修改：`director/evaluation.py`
- 修改：`PROTOTYPE.md`
- 修改：端到端测试

**步骤：**

- [ ] CLI 串联：`init → understand-materials → review/import → normalize/confirm-brief → build-treatment → recommend-styles → render-review`。
- [ ] 对 12 条盲测只运行一次完整本地流程；模型未合格时明确走 assisted。
- [ ] 静态报告展示素材观察、未知项、人工改动、导演主线、章节、缺口和三个音乐方向。
- [ ] 报告同时导出经验证的 `director_review.json`，并保证未来可以把低置信度、重复警告和用户备注映射成编辑器 Marker。
- [ ] 本地浏览器验收一次：图片可见、表单可改、JSON 可下载/导入、无远程依赖。
- [ ] 运行一次完整测试：`cd local-media-scanner && uv run pytest -q`，再于 worktree 根目录运行 `git diff --check`。
- [ ] 报告自动门、人工介入条数、错误数、耗时、峰值内存和外部调用数。
- [ ] 只有全部证据齐全后更新 `PROTOTYPE.md`；此时才按仓库约定新增阶段性 context 总结。
- [ ] 提交：`git commit -m "feat: complete visual director milestone"`。

**里程碑通过门：**

- 自动模式满足全部自动门，或 assisted 模式完成所有必需确认并清楚标记。
- `unsupported_inferences` 为空，`reject_suggestion` 无误伤。
- V0.1 回归和 V0.2 端到端测试均通过。
- 静态报告和所有 JSON 可从项目状态恢复。
- 曲多多、即梦和其他外部服务均为 `not_executed`。
- 没有把未执行模型、fixture、人工修订或候选语义写成自动完成。

## 每轮额度控制

- 每次只做一个 Task；Task 完成、目标测试通过并形成可提交差异后停止。
- 默认只打开该 Task 直接相关的文件，避免反复全文读取规格和历史日志。
- 每个 Task 先跑目标测试；同一失败类型最多修复并重跑一次。
- 全套测试只在 Task 1 兼容门和 Task 8 里程碑各运行一次。
- 真实素材/模型运行只发生在 Task 4：2 条 smoke、12 条开发、12 条盲测，各自最多一次规定重试。
- 复用现有 478 张 probe 图；不为评估包重新生成整批帧。
- 终端保留完整日志，对话只回报通过数、错例数、耗时、峰值内存、外部调用数和阻塞点。
- 任何 Task 若无法在当前轮形成测试通过的最小闭环，停止在最后一个已通过提交，不跨 Task 留半成品。

无法在开发前精确承诺 Codex token 数，但该拆分把高消耗集中在一次模型能力验证和一次盲测；其余任务主要是小范围 Schema、规则和测试，不需要 Codex 批量观看视频。

## 建议执行顺序

```text
本轮：只复核 V2
  ↓
Task 1：版本化合同 + 编排骨架
  ↓ 用户复核合同
Task 2：评估拆分 + 可回填人工工具
  ↓
Task 3：Scanner-only 基线
  ├─ 已能进入 assisted 流程
  └─ 用户另行批准模型下载？
       ├─ 是 → Task 4 单模型能力门
       └─ 否 → 跳过 Task 4，保持 assisted
  ↓
Task 5：用户描述规范化与确认
  ↓
Task 6：deterministic 导演方案
  ↓
Task 7：离线音乐风格推荐
  ↓
Task 8：一次盲测 + 静态交付
  ↓ 用户复核
另行规划具体音乐搜索、AI 生成、剪辑时间线和音效
```

## 后续编辑器交接门（不属于 V2 开发）

- V2 结束后仍保留内部 JSON 证据链和现有 FFmpeg 快速预览，不用 GUI 编辑器替代自动验收。
- 音乐结构和 `ClipPlacement.source_in/source_out` 真正形成后，优先实现只读 `clip_placements + sfx_plan + music asset → OpenTimelineIO` 导出器。
- 先用合成竖屏项目验证 Kdenlive 的素材重连、音乐轨、Marker 和项目方向；不直接生成版本易变的 `.kdenlive` XML。
- 在下一次时间线质量验收前，先修复“存在可用替代素材时仍出现同文件相邻”的已知问题。
- 只有真实出现长素材人工选段痛点时，才评估 LosslessCut CSV 往返；它不成为必装依赖，也不得删除或预切原始素材。

## 本轮复核结论

V2 不再要求先相信某个模型可用，也不把人工复核当作临时补丁。它把人工确认做成正式产物，把 deterministic Director 做成必备基线，并用版本化编排、开发/盲测拆分和精确失败状态避免“最后才发现无法完成”。

用户批准 V2 后，下一轮只执行 Task 1；不会自动进入模型下载或外部服务阶段。
