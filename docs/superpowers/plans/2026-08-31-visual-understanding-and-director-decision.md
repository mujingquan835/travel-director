# 旅行导演：素材理解、导演决策与音乐风格推荐实施计划

日期：2026-08-31  
状态：待用户复核，未开始开发  
权威工作区：`<checkout>`  
分支：`feature/local-media-scanner-v0.1`  
编写基线：`9f1616590baedbeab0f301d60ad9a4447d2a7afd`

> 本计划根据 2026-08-31 的产品修正，替代原计划中“扫描阶段推荐最佳区间”和“先由音乐驱动画面理解”的部分。实施顺序改为：素材事实识别 → 结合用户描述理解素材 → 形成项目级导演方案 → 推荐音乐风格 → 用户确认后再进入曲库或 AI 生成。本计划不授权开发、模型下载、外部登录、浏览器操作、付费调用或音乐生成。

## 目标

在不逐帧调用重型模型、不消耗外部服务额度的前提下，建立可审阅、可弃权、可评估的“旅行导演”第一阶段：

1. 读取 Scanner 的本地证据，对整条素材形成保守的内容观察。
2. 把同一批素材放入用户描述的语境中，判断它对本次旅行表达的价值。
3. 从项目整体而不是单条视频出发，输出故事主线、情绪推进、素材职责与缺口。
4. 将导演方案转换为最多三个音乐风格方向，不搜索、不下载、不生成音乐。
5. 用小规模人工对照集证明结果是否有用，再决定是否引入一个新的本地视觉模型。

## 产品主链路

```text
本地视频
  ↓
ScannerEvidence              # 技术元数据、稀疏帧、原始 CV、候选语义、重复证据
  ↓
ClipObservation              # 与用户意图无关的整条素材观察，可 unknown/abstained
  +
UserIntentBrief              # 用户想表达什么，而不只是地点和时长
  ↓
IntentConditionedDecision    # 核心 / 候选 / 重复备选 / 淘汰建议 / 待人工确认
  ↓
DirectorTreatment            # 故事主线、章节、情绪曲线、节奏、素材职责、缺口
  ↓
MusicStyleRecommendation     # 最多 3 个音乐风格方向
  ↓ 用户复核门
曲库参考 / AI 音乐提示词 / 音乐生成 / 时间线剪辑
```

## 核心产品决策

### 1. 不在素材理解阶段计算“最佳区间”

- `ClipObservation` 和 `IntentConditionedDecision` 都以整条素材为单位。
- 稀疏代表帧只用于证明系统看过哪些时间点，不自动扩展成推荐起止区间。
- 只有音乐结构和时间线槽位已经确定后，`ClipPlacement` 才根据整条素材时长计算 `source_in/source_out`。
- 当前 `recommended_ranges` 已被 `material_enrichment.py` 生成并被 `clip_selector.py` 消费。实施时先停止生成和消费，再提供 V0.1 旧产物迁移；不能直接删除字段破坏历史 JSON。

### 2. Scanner 只提供证据，Director 才作编辑判断

- 技术元数据、代表帧来源、错误、缓存与原始 CV 数值可以直接保留。
- `people_present` 仍是候选；人数只允许粗粒度或下界。
- 当前 `scene_type`、`shot_scale`、`simple_action`、`main_objects` 不能升级成事实。
- `opening`、`emotion`、`climax`、`ending` 等素材职责必须同时引用用户意图和项目级证据，不能由 Scanner 单字段直接推出。

### 3. “理解素材”分成两层

第一层是与用户无关的观察：画面大致包含什么、人物是否可能出现、是室内/室外/日景/夜景候选、运动与技术质量证据、是否重复。

第二层是与本次创作有关的决策：这条素材是否支撑用户想讲的旅行、与其他素材是否重复、可以承担什么叙事职责、为什么保留或淘汰。

同一条素材在“热闹城市探索”和“安静亲子回忆”两个 Brief 下允许得到不同的 Director 决策。

### 4. 音乐推荐消费导演方案，不直接消费弱视觉标签

音乐推荐输入应是 `DirectorTreatment + UserIntentBrief + ProjectCoverage`。它输出风格、情绪、BPM 区间、乐器、鼓点密度、能量曲线和匹配理由；第一阶段不输出具体歌曲，不访问曲多多、Spotify、Apple Music、网易云或 QQ 音乐。

## 稳定合同草案

```text
EvidenceRef = artifact, field, frame_timestamp, status, confidence

ClipObservation =
  file, observation_status,
  technical_usability, quality_evidence, motion_evidence,
  content_families[], setting_candidates[], lighting_candidates[],
  people_presence_candidate, people_count_band_candidate,
  subject_candidates[], activity_candidates[],
  original_audio_value_candidate, duplicate_group_id,
  evidence_refs[], unknown_fields[], errors[]

UserIntentBrief =
  location, travel_type, target_duration_seconds, orientation,
  audience, platform, central_subject, must_include[], must_avoid[],
  desired_story, desired_emotion, rhythm, style,
  people_focus, authenticity_preference, vocals, instruments[]

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
  logline, narrative_spine, chapters[], emotional_arc[], pacing_strategy,
  core_materials[], candidate_materials[], redundant_materials[],
  reject_suggestions[], review_required[], coverage_gaps[],
  evidence_refs[], unsupported_inferences[]

MusicStyleRecommendation =
  direction_id, plain_description, genres[], moods[],
  bpm_min, bpm_max, instruments[], drum_density, vocals,
  energy_curve[], fit_reason, director_evidence_refs[]
```

枚举边界：

- `bucket`: `core | candidate | redundant | reject_suggestion | review_required`
- `director_function_candidates`: `opening | context | progression | emotion | contrast | breathing | climax | ending`
- `content_families`: `urban | nature | culture_architecture | food | transport | lodging | attraction_activity | performance_event | people | detail | other`
- 所有语义观察均需要 `measured | candidate | abstained | unavailable` 状态。
- `reject_suggestion` 只是建议，不删除、不移动、不覆盖原文件。

## 人工验收设计

第一轮不追求“大而全模型分数”，而是验证产品判断是否可用。

### 固定评估包

- 从现有冻结素材清单中，按元数据和已有人工标签盲选 12 条，避免先看新模型输出再挑样本。
- 保留长短、横竖屏、人物有无、室内外、日夜、运动强弱和重复候选的覆盖。
- 对同一组 12 条素材固定三个不同 Brief：
  1. 明亮、有推进感的城市探索。
  2. 温暖、重人物关系的旅行回忆。
  3. 安静、重空间与文化质感的旅行短片。
- 人工标注分两次完成：先标 `ClipObservation`，再在看见 Brief 后标 `IntentConditionedDecision`，避免把导演偏好混入事实标签。

### 通过条件

- 硬性淘汰误伤：人工认为可用的素材被系统建议淘汰为 0 条。
- 证据追溯：100% 的导演判断和音乐理由至少引用一个真实证据或用户 Brief 字段。
- 不支持推断：没有由“检测到人物”直接产生“主角/人物故事”的结果。
- 弃权保留：证据不足时输出 `review_required` 或 `abstained`，不填充虚假事实。
- Brief 敏感性：同一批素材在三个 Brief 下产生可解释的职责或排序变化，而不是复制同一套答案。
- 重复处理：重复素材仍保留文件记录，只把非首选项放入 `redundant`。
- 音乐方向：每个 Brief 最多三项，方向之间有实质差异，并能回指 `DirectorTreatment`。
- 人工复核：用户能在静态报告中完成“同意 / 改桶 / 补充说明”，无需先看原始 JSON。

## 成本与停止规则

- 每次 Codex 只实施一个 Task，目标 60—120 分钟内形成可提交结果。
- Task 1—3 不下载模型、不解码新素材、不跑现有模型。
- 如需新本地模型，必须在 Task 4 前单独给出模型大小、许可证、M1 Pro 兼容性和预计运行量，并获得用户授权。
- Task 4 最多评估一个新模型：一次 2 条 smoke、一次 12 条评估、同一失败类型最多修复并重跑一次。
- 每个 Task 先跑目标测试；只有里程碑结束时跑一次全套测试。
- 第一里程碑最多执行一次真实素材 smoke，不运行 100 条全管线，不重复现有 30 条 Detector/SigLIP 实验。
- Codex/云端视觉不得批量读取视频帧；如未来验证，只允许少量盲测，并单列调用量与成本。
- 所有日志和详细结果留在本地，回报只给字段覆盖、错例数、耗时和阻塞原因。
- 每个 Task 单独提交。若时间不足，缩小当次 Task，不留下跨任务半成品。
- 曲多多、即梦、Spotify、Apple Music、网易云、QQ 音乐、Runway 和其他外部服务全部保持 `not_executed`。

## 文件地图

计划新增：

- `local-media-scanner/director/visual_schema.py`
- `local-media-scanner/director/visual_understanding/base.py`
- `local-media-scanner/director/visual_understanding/scanner_evidence.py`
- `local-media-scanner/director/intent_matcher.py`
- `local-media-scanner/director/director_treatment.py`
- `local-media-scanner/director/music_style_recommender.py`
- `local-media-scanner/director/visual_review.py`
- `local-media-scanner/tests/director/test_visual_schema.py`
- `local-media-scanner/tests/director/test_scanner_evidence_understanding.py`
- `local-media-scanner/tests/director/test_intent_matcher.py`
- `local-media-scanner/tests/director/test_director_treatment.py`
- `local-media-scanner/tests/director/test_music_style_recommender.py`
- `local-media-scanner/tests/director/test_visual_review.py`
- `local-media-scanner/benchmark/DIRECTOR_VISUAL_ANNOTATION_GUIDE.md`
- `local-media-scanner/benchmark/director_visual_manifest.json`
- `local-media-scanner/benchmark/director_visual_briefs.json`
- `local-media-scanner/benchmark/director_visual_ground_truth.template.json`

计划修改：

- `docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md`
- `local-media-scanner/director/schema.py`
- `local-media-scanner/director/material_enrichment.py`
- `local-media-scanner/director/scanner_bridge.py`
- `local-media-scanner/director/clip_selector.py`
- `local-media-scanner/director/search_planner.py`
- `local-media-scanner/director/project.py`
- `local-media-scanner/PROTOTYPE.md`

明确不修改：

- `local-media-scanner/scanner/schema.py`
- Scanner 模型权重、阈值、缓存、Ground Truth 和既有运行产物
- `<footage-dir>` 或其他原始素材目录
- 曲多多、即梦、音乐 Provider 和剪映集成代码

## 可执行任务

### Task 1：冻结素材理解合同、人工标准和兼容策略

**目标：** 不运行任何模型，先确定系统应该输出什么、哪些字段允许未知、如何处理旧 `recommended_ranges`。

**文件：**

- 新增：`local-media-scanner/director/visual_schema.py`
- 新增：`local-media-scanner/tests/director/test_visual_schema.py`
- 新增：`local-media-scanner/benchmark/DIRECTOR_VISUAL_ANNOTATION_GUIDE.md`
- 修改：`docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md`

- [ ] 先写失败测试：严格拒绝额外字段；语义字段必须包含状态；Director 判断必须有 Brief ID、理由和证据引用。
- [ ] 增加 `ClipObservation`、`IntentConditionedDecision`、`ProjectCoverage`、`DirectorTreatment`、`MusicStyleRecommendation` 的 V0.1 严格合同。
- [ ] 在标注指南中区分“可见事实”“候选解释”“导演判断”，给出正反例。
- [ ] 在设计稿中删除“全量扫描/二次分析推荐最佳区间”的产品要求，写明 in/out 只属于音乐时间线阶段。
- [ ] 冻结兼容策略：旧 `MaterialScanResult.recommended_ranges` 暂时可读，新链路不生成、不消费；历史 JSON 不重写。
- [ ] 运行：`cd local-media-scanner && uv run pytest tests/director/test_visual_schema.py -q`
- [ ] 运行：`git diff --check`
- [ ] 提交：`git commit -m "docs: freeze visual understanding contracts"`

**完成门：** 用户复核合同和标注标准。未复核前不进入 Task 2。

### Task 2：冻结 12 条素材 × 3 个 Brief 的人工评估包

**目标：** 用现有清单建立小而稳定的对照集，不运行 Scanner 或视觉模型。

**文件：**

- 新增：`local-media-scanner/benchmark/director_visual_manifest.json`
- 新增：`local-media-scanner/benchmark/director_visual_briefs.json`
- 新增：`local-media-scanner/benchmark/director_visual_ground_truth.template.json`
- 新增：`local-media-scanner/scanner/director_visual_evaluation.py`
- 新增：`local-media-scanner/tests/test_director_visual_evaluation.py`

- [ ] 写失败测试：必须恰好 12 条唯一素材；不得与不存在的文件或 Brief 关联；每条素材必须先有事实标注，才能添加 Brief 条件判断。
- [ ] 从现有冻结 manifest 做一次元数据分层选择；选择过程不得读取新模型预测。
- [ ] 固定三个 Brief，并记录 selection seed、源 manifest 哈希和 12 条 membership 哈希。
- [ ] 生成空白标注模板，不替用户填写导演结论。
- [ ] 实现只读验证器，检查枚举、证据引用、Brief 关联和矛盾标签。
- [ ] 运行：`cd local-media-scanner && uv run pytest tests/test_director_visual_evaluation.py -q`
- [ ] 运行：`git diff --check`
- [ ] 提交：`git commit -m "test: freeze director visual evaluation pack"`

**完成门：** 12 条素材和三个 Brief 可人工观看、可标注；没有模型运行记录。

### Task 3：建立只消费现有 Scanner 证据的零新增模型基线

**目标：** 先证明系统能诚实整理现有证据，不依赖新模型填满语义字段。

**文件：**

- 新增：`local-media-scanner/director/visual_understanding/base.py`
- 新增：`local-media-scanner/director/visual_understanding/scanner_evidence.py`
- 新增：`local-media-scanner/tests/director/test_scanner_evidence_understanding.py`
- 修改：`local-media-scanner/director/scanner_bridge.py`
- 修改：`local-media-scanner/director/material_enrichment.py`

- [ ] 定义可替换 `VisualUnderstandingProvider`；输入为 `MaterialScanResult`，输出为 `ClipObservation`。
- [ ] 写失败测试：弃权的 scene/action/object 不得复制；人物下界不得变成精确人数；不得产生主角、故事或最佳区间。
- [ ] 映射可靠技术证据和候选字段，所有不可靠字段进入 `unknown_fields`。
- [ ] 停止 `_recommended_ranges()` 的新链路调用，但暂时保留旧函数和旧 Schema 读取能力。
- [ ] 用保存的 Scanner fixture 跑一次纯 JSON 基线，不解码视频、不加载模型。
- [ ] 运行目标测试一次；同一失败类型最多修复重跑一次。
- [ ] 提交：`git commit -m "feat: add evidence-only visual understanding baseline"`

**通过门：** 基线可能覆盖不高，但不能制造确定语义。若报告仍显示伪确定字段，停止而不是降低弃权。

### Task 4：评估一个本地视觉理解候选，未证明增益则不接入

**目标：** 只在用户再次批准模型下载后，用固定 12 条评估包验证一个本地视觉模型是否值得接入。

**前置门：** 先提交一页能力审计，包含模型来源、许可证、下载大小、M1 Pro/MPS 或 MLX 支持、预计内存、单条耗时和卸载方式；用户明确批准后才执行。

**候选接口文件：**

- 新增：`local-media-scanner/director/visual_understanding/local_vlm.py`
- 新增：`local-media-scanner/tests/director/test_local_vlm_contract.py`
- 新增：`local-media-scanner/benchmark/director_visual_evaluation.py`

- [ ] 只允许一个新候选模型，不并行下载多个模型。
- [ ] 所有提示词只要求结构化旅游内容观察，不要求模型直接决定核心/淘汰/高潮。
- [ ] 先用 2 条素材 smoke，确认加载、结构化输出、峰值内存和耗时。
- [ ] smoke 通过后只跑固定 12 条；保存原始结构化输出和模型 revision。
- [ ] 与 Scanner-only 基线比较字段覆盖、人工一致性、幻觉数和弃权质量。
- [ ] 接入门槛：没有新增硬性淘汰误伤；不支持事实为 0；至少两个核心内容维度相对基线有可复核增益。
- [ ] 若不达标，保留实验结论但不进入默认 Provider，不尝试第二个模型。
- [ ] 若达标，默认仍支持 `scanner_only`，本地 VLM 为显式配置项。
- [ ] 提交：`git commit -m "exp: evaluate one local visual understanding provider"`

**停止门：** OOM、单条超过预先批准时限、结构化输出连续失败或许可证不清晰，任一出现即停止。

### Task 5：实现基于用户描述的素材判断与项目级导演方案

**目标：** 同一批素材在不同 Brief 下产生不同且有证据的导演判断。

**文件：**

- 新增：`local-media-scanner/director/intent_matcher.py`
- 新增：`local-media-scanner/director/director_treatment.py`
- 新增：`local-media-scanner/tests/director/test_intent_matcher.py`
- 新增：`local-media-scanner/tests/director/test_director_treatment.py`
- 修改：`local-media-scanner/director/schema.py`
- 修改：`local-media-scanner/director/project.py`

- [ ] 扩展 `UserCreativeBrief`：故事目标、核心人物、必含、避用、受众、平台、真实感偏好；旧字段保持兼容。
- [ ] 写失败测试：没有 Brief 不得生成 DirectorTreatment；每个职责和桶位必须引用 Brief 与素材证据。
- [ ] 实现五桶判断：`core/candidate/redundant/reject_suggestion/review_required`。
- [ ] `reject_suggestion` 只允许由不可解码、明确技术失败或人工规则支持；弱语义不允许触发硬淘汰。
- [ ] 聚合项目覆盖与缺口，生成 logline、章节候选、情绪弧线和节奏策略。
- [ ] 对相同 12 条素材运行三个固定 Brief，验证结果不是同一模板复制。
- [ ] 只把紧凑结构化 `ProjectCoverage + Brief` 交给导演推理层；不得传全部帧或长日志，设置输入大小上限。
- [ ] 提交：`git commit -m "feat: add intent-conditioned director treatment"`

**完成门：** 用户能看懂为什么某条素材被归入某桶，并能指出修改意见；系统能明确列出缺什么素材。

### Task 6：把导演方案转换为三个音乐风格方向

**目标：** 先推荐风格，不访问曲库、不生成音乐。

**文件：**

- 新增：`local-media-scanner/director/music_style_recommender.py`
- 新增：`local-media-scanner/tests/director/test_music_style_recommender.py`
- 修改：`local-media-scanner/director/search_planner.py`

- [ ] 写失败测试：输入必须包含已完成的 `DirectorTreatment`；输出最多三项；每项必须引用导演证据。
- [ ] 根据章节、情绪弧线、运动覆盖和用户节奏偏好输出 BPM、流派、乐器、鼓点密度、能量曲线。
- [ ] 三个方向必须在节奏、配器或情绪策略上有实质差异，不能只换形容词。
- [ ] 保留当前 `MusicSearchBrief` 作为后续适配层，但不让它直接消费弱 Scanner 标签。
- [ ] 对三个固定 Brief 生成离线结果，记录 `external_call_count=0`。
- [ ] 提交：`git commit -m "feat: recommend music styles from director treatment"`

**完成门：** 用户只看素材报告和三个音乐方向就能做选择；没有具体曲名、链接或外部调用。

### Task 7：制作静态人工复核报告并完成第一里程碑验收

**目标：** 把“素材识别 → 用户意图 → 导演方案 → 音乐风格”放在一个本地静态页面中复核。

**文件：**

- 新增：`local-media-scanner/director/visual_review.py`
- 新增：`local-media-scanner/tests/director/test_visual_review.py`
- 修改：`local-media-scanner/PROTOTYPE.md`

- [ ] 报告按五桶展示 12 条素材，显示代表帧、候选语义、未知字段、理由和证据引用。
- [ ] 同页显示用户 Brief、导演主线、章节、情绪弧线、素材缺口和三个音乐方向。
- [ ] 不嵌入原视频、不复制原文件、不依赖远程脚本或网络资源。
- [ ] 浏览器只做一次本地报告验收：图片加载、无横向溢出、所有桶可达、未知/候选状态明显区分。
- [ ] 运行一次完整测试：`cd local-media-scanner && uv run pytest -q`
- [ ] 运行一次 `git diff --check`。
- [ ] 写阶段结果到 `PROTOTYPE.md`；只有这一里程碑真实完成后才新增一份 context 总结文件。
- [ ] 提交：`git commit -m "feat: add visual director review milestone"`

**里程碑通过门：**

- 人工评估包满足本计划通过条件。
- 静态报告可本地复核。
- 没有新外部服务调用。
- 没有把 Fixture、候选语义或未执行步骤写成真实完成。
- 用户复核第一里程碑后，才规划曲多多、音乐提示词或 AI 生成阶段。

## 推荐执行顺序

```text
本轮：只复核本计划
  ↓
Task 1：合同 + 标注标准
  ↓ 用户复核
Task 2：12 条 × 3 Brief 人工评估包
  ↓
Task 3：Scanner-only 零新增模型基线
  ↓ 用户看静态样例与字段覆盖
Task 4：可选，一个本地模型，需另行批准
  ↓
Task 5：意图条件化导演方案
  ↓
Task 6：三个音乐风格方向
  ↓
Task 7：静态复核与里程碑验收
  ↓ 用户复核
另行规划曲库 / AI 音乐 / 时间线 / 音效
```

## 本轮复核点

请在开始 Task 1 前确认以下四点：

1. 是否接受“整条素材判断，最佳区间延后到音乐时间线阶段”。
2. 是否接受五桶增加 `review_required`，避免证据不足时强行保留或淘汰。
3. 是否接受固定 12 条素材同时套用三个 Brief，专门验证导演判断会随用户描述变化。
4. 是否接受先完成 Scanner-only 基线，再单独决定是否下载一个本地视觉模型。

