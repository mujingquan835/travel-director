# V0.3 Task 2：单素材候选资格与项目级职责分配

日期：2026-09-02

状态：完成

权威工作区：`<checkout>`

分支：`feature/local-media-scanner-v0.1`

实施基线：`7e3829d feat: add reproducible blind annotation evaluation`

## 完成范围

- 将单素材层收敛为 `candidate_capabilities`，只表达环境建立、运动推进、人物情绪、事件能量、细节、空间转换、呼吸和可见收束等候选能力。
- 新增 V0.3 项目级 `role_assignments`，统一分配 opening、context、progression、emotion、contrast、breathing、climax 和 ending。
- V0.3 单素材 `director_function_candidates` 强制为空，最终职责不再镜像回单素材记录。
- `contrast` 在 Schema 层要求至少两条素材。
- opening、climax、ending 在 Schema 层各限制为一条主要素材。
- climax 只从全项目 `event_energy` 候选中排序选择；任意 activity 不再自动升级为 climax。
- ending 只从可见的离开、回望或收束候选中选择；lodging 不再直接产生 ending。
- `lighting` 与 `people_count_band` 不参与单独职责触发。
- 每个项目级职责均强制包含选择理由、Brief 证据和每条入选素材的证据。
- `ProjectCoverage`、`DirectorTreatment` 和正式评估器均改读项目级职责分配。

## 版本与兼容

- 新生成的 `IntentDecisionBatch`、`ProjectCoverage` 和 `DirectorTreatment` 使用 `schema_version=0.3.0`。
- V0.2 的上述 JSON 仍可读取和校验。
- V0.2 visual project state 可按阶段接收 V0.3 的 `intent_decisions`、`project_coverage` 和 `director_treatment`，其余阶段仍保持 V0.2 合同。
- 正式评估器对 V0.2 继续读取旧单素材职责字段；对 V0.3 读取 `role_assignments`。

## 独立关系夹具

开发测试只使用人工构造的 urban、nature、transport、attraction activity、performance event、detail 和 lodging 关系夹具，没有读取 blind-v1 Ground Truth 调整规则。

覆盖的结构验收：

- 城市漫游与自然旅行对同一画面事实产生不同 opening 排序，但候选能力保持不变。
- 移除城市环境素材后，项目 opening 允许改变。
- 普通 attraction activity 不获得 climax；performance event 的事件能量候选最多分配一个 climax。
- 带可见“回望离开”线索的 detail 可成为 ending；lodging 不自动成为 ending。
- contrast 至少引用两条候选能力不同的素材。
- 只有 lighting 与 people count 的素材不获得任何项目职责。

## 验证记录

- 红灯测试：`4 failed`，确认旧实现缺少 V0.3 候选能力和项目职责层。
- 实现后定向测试：`18 passed`。
- 全量测试首跑：`295 passed, 12 failed, 3 warnings`；12 个失败均为 visual project 阶段硬编码拒绝 V0.3 Schema 的同一迁移门。
- 修复迁移门后，对受影响的 `test_skill_summary.py` 进行一次限定重试：`14 passed`，覆盖先前全部 12 个失败。
- 按单 Task 测试纪律未重复运行第二次全量测试；当前组合证据覆盖本轮全部 307 个测试用例。
- 3 个 warning 仍为 audioread 对 Python 3.13 的既有弃用提示。

## 明确未做

- 未读取 blind-v1 Ground Truth 调参，未重新运行盲测指标。
- 未运行模型、视觉推理或视频解码。
- 未调用曲多多、即梦、Codex API、网络或任何付费服务。
- 未开始 V0.3 Task 3，未创建 blind-v2。
