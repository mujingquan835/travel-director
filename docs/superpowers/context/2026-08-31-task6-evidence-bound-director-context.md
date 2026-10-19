# 旅行导演 Task 6 证据受限导演判断上下文

日期：2026-08-31

权威工作区：`<checkout>`

分支：`feature/local-media-scanner-v0.1`

## 阶段结论

- Task 6 已形成纯 deterministic 闭环：确认后的 `ClipObservationBatch + BriefConfirmation` → `IntentDecisionBatch` → `ProjectCoverage` → `DirectorTreatment`。
- 系统按 `core / candidate / redundant / reject_suggestion / review_required` 五桶处理素材。语义不匹配只能成为候选；只有素材不可用状态，或 `measured/confirmed` 的 `technical_usability=unusable` 才能触发硬淘汰建议。
- 明确重复组只标记为 `redundant`，不会删除源素材；尚未完成确认的观察批次被阻止进入导演推理。
- 每条桶位和素材职责、每个章节、每项情绪弧线与节奏策略都携带观察或 Brief 证据引用；未知 assertion 通过白名单被忽略，不进入理由或方案。

## 已实现接口

- `build_intent_decisions(observations, brief)`：五桶、相关度、导演职责和理由。
- `build_project_coverage(observations, decisions)`：内容分布、重复组、已有职责和职责缺口。
- `build_director_treatment(decisions, coverage, brief)`：logline、叙事主线、章节、证据化情绪弧线、节奏、五桶清单和补拍缺口。
- `validate_treatment_enhancement(...)`：为未来调用方智能体预留证据、桶位、职责和覆盖的结构漂移验证；它不等于自然语言事实校验，因此本阶段不开放自由文本增强、不调用智能体，也不绑定模型。
- `travel-director build-director-treatment`：一次生成三个 Stage JSON，输出路径必须互不相同且不得覆盖输入。

## 验证证据

- 6 条确认素材分别套用城市漫游、美食旅行、自然旅行三个 Brief，得到三个不同桶位签名。
- 定向测试：`13 passed in 0.23s`。
- 完整回归：`196 passed, 3 warnings in 9.74s`；3 条均为 `audioread` 依赖的 Python 3.13 弃用预警，不是本任务失败。
- `git diff --check` 通过。
- 视频解码、模型调用、模型下载、浏览器操作、曲多多、即梦、音乐平台和付费服务调用均为 0。

## 下一步

- 下一实施任务是 Task 7：仅从已确认的导演方案、Brief 和覆盖缺口生成最多三个离线音乐风格方向。
- Task 7 不搜索曲名、不访问音乐平台、不下载或生成音乐。
