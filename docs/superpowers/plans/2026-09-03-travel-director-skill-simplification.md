# Travel Director Skill 设计简化与改善方案

> **历史记录／部分过期：** 单一 `run` 入口和薄 Skill 方向仍有效；阶段 C 、`completed` 终点及旧恢复结论已被两段式项目合同取代。
>
> 当前唯一基线：[`../context/2026-09-04-travel-director-two-stage-project-contract-context.md`](../context/2026-09-04-travel-director-two-stage-project-contract-context.md)。

> 日期：2026-09-03
>
> 历史状态：阶段 A、B 已实施；阶段 C 的旧验收结论已失效
>
> 权威工作树：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`
>
> 适用范围：当前“本地素材理解 -> 导演方案 -> 3 条音乐生成提示词”阶段

## 1. 结论

Travel Director 当前的问题不是核心能力不足，而是开发期的阶段、校验器、评测器和旧原型入口被一起暴露给了正式 Skill，导致用户流程和维护流程都过重。

改善方向是：

- 保留已经验证的扫描、缓存、联系表、受控视觉观察、导演角色判断、项目级覆盖检查和 3 条音乐提示词能力；
- 用户侧只保留 `$travel-director` 一个入口；
- Skill 内部只围绕一个幂等的 `run` 状态机工作，不再逐阶段手工串联命令；
- Ground Truth、blind annotation、评估器全部留在开发评测层，不进入正式 Skill；
- 旧音乐分析、时间线、音效和渲染原型退出当前产品路径，暂不删除代码；
- 不恢复本地视觉模型路线，也不接入任何外部或付费服务。

本次应做“入口和编排收缩”，而不是继续扩展 schema、阶段或评测规模。

## 2. 已确认的产品契约

### 2.1 用户输入

用户只提供两项内容：

1. 本地旅行视频素材目录；
2. 一段自然语言创作意图。

不得要求用户理解项目状态文件、Ground Truth、blind annotation、字段桶、阶段图或内部 CLI。

### 2.2 用户得到的结果

默认只交付一份可读的最终总结，至少包含：

- 素材理解依据及明确限制；
- 素材采用、舍弃和待确认结论；
- 项目级导演结构、素材角色和节奏建议；
- 恰好 3 条、每条不超过 200 个字符的音乐（含音效）生成提示词。

当前阶段不交付成片、剪辑时间线、具体歌曲搜索、音乐下载或音效方案。

### 2.3 交互原则

- 没有实质冲突或证据缺口时，不发起确认；
- 少量问题直接在对话中一次性确认；
- 仅当待确认字段超过 5 个或涉及素材超过 3 个时，才生成本地确认页；
- 用户修改意见视为一次增量覆盖，不重新跑完整流程；
- 无法从证据判断的内容必须保留“不确定”，不能用推测补齐。

## 3. 当前复杂度从哪里产生

### 3.1 三套不同用途的系统混在一个入口

当前 Director CLI 同时承载：

1. 正式 Skill 的视觉素材理解和导演方案；
2. Ground Truth、blind annotation 和评估器等研发工具；
3. 旧的音乐搜索、音乐分析、时间线、音效和渲染原型。

它们面向的使用者、稳定性要求和完成定义不同，不应继续由同一份正式工作流串联。

### 3.2 开发阶段被当成用户流程

当前视觉项目显式记录 9 个阶段：

`clip_observations -> intent_brief -> brief_confirmation -> intent_decisions -> project_coverage -> director_treatment -> director_review -> music_style_recommendations -> visual_review`

每阶段又存在草稿、校验和记录动作。这样有利于早期定位问题，但不应成为 Skill 的操作界面。

### 3.3 命令数量代替了产品编排

当前 Director CLI 有 34 个命令，Scanner CLI 有 16 个命令；已安装 Skill 的工作流参考中出现 36 次 `uv run` 调用。正式 Skill 实际承担了人工工作流引擎的职责，因此容易重复执行、漏阶段和产生版本漂移。

### 3.4 版本语义已经漂移

已安装 Skill 和仓库 Skill 源当前仍以“V0.2 visual path”描述流程，而代码 HEAD 已包含 V0.3 的项目级导演角色语义。继续在现有结构上添加 Task 或新页面，会放大文档、产物和代码之间的不一致。

## 4. 目标形态

### 4.1 用户侧：一个入口

用户只调用：

```text
$travel-director <素材目录> <创作描述>
```

Skill 负责定位权威工作树、推进流程、读取必要联系表、发起必要确认并返回最终总结。用户无需运行任何子命令。

### 4.2 Skill 内部：一个幂等状态机

保留一个正式推进命令：

```text
travel-director run --input <素材目录> --brief <创作描述> [--project <项目目录>]
```

同一命令可以安全重复调用。每次从现有状态继续推进，直到返回以下一种状态：

| 状态 | 含义 | Skill 动作 |
|---|---|---|
| `needs_visual_observation` | 联系表已准备好，等待调用方观察 | 读取指定联系表并提交受控观察结果 |
| `needs_user_confirmation` | 存在影响结论的证据冲突 | 在对话中提问，或按阈值打开本地页 |
| `completed` | 最终总结已生成且通过确定性校验 | 向用户交付唯一总结 |
| `blocked` | 输入、缓存或项目状态存在不可自动修复的问题 | 给出具体阻断原因，不猜测 |

调用方完成相应动作后，再次执行同一个 `run`。这样保留“调用方负责视觉观察”的边界，同时去掉 9 个阶段和几十个命令的手工编排。

另保留一个只读诊断命令：

```text
travel-director status --project <项目目录>
```

正式命令面目标从 34 个收缩为 `run`、`status` 两个；帮助和版本信息使用标准选项提供。

### 4.3 最小持久化产物

正式流程只承诺以下稳定产物：

1. `project_state.json`：输入指纹、当前状态、完成时间和失败原因；
2. `observations.json`：受控视觉观察及其证据引用；
3. `director_plan.json`：确定性的导演判断和 3 条提示词；
4. `final_summary.json`：经校验的最终结果，由对话层生成唯一用户可读总结。

联系表、扫描缓存和批次清单属于可复用中间证据，可以继续保留在内部目录。现有细粒度阶段产物在兼容期内可以继续生成，但不再作为正式接口，也不要求 Skill 逐一操作。

## 5. 能力保留、下沉与退出清单

| 当前能力 | 决策 | 目标位置 |
|---|---|---|
| 本地 Scanner、缓存、素材指纹 | 保留 | 内部基础设施 |
| 联系表和批次规划 | 保留 | `run` 自动准备 |
| 调用方受控视觉观察 | 保留 | `needs_visual_observation` 动作 |
| 不确定性与证据边界 | 保留并强化 | `observations.json` 和最终总结 |
| 项目级导演角色与覆盖校验 | 保留 | `run` 内部确定性逻辑 |
| 3 条音乐生成提示词 | 保留 | 最终结果固定组成 |
| 小规模聊天确认 / 大规模本地页 | 保留 | `needs_user_confirmation` 路由 |
| Ground Truth、blind annotation、正式评估器 | 下沉 | 独立开发评测入口 |
| Task 3 / blind-v2 扩展 | 停止 | 不进入当前路线 |
| Brief 强制确认 | 取消默认执行 | 只有冲突时确认 |
| Director Review 自动接受记录 | 取消默认执行 | 用户提出修改时记录覆盖 |
| 旧音乐搜索、分析、时间线、音效、渲染命令 | 退出当前 Skill | 兼容期保留在 legacy/lab 入口 |
| 本地视觉模型 | 不恢复 | 非当前路线 |
| 曲多多、即梦、Codex API、其他付费服务 | 禁止调用 | 未来必须另行明确授权 |

Task 1 已完成的 Ground Truth 恢复和 `evaluate-blind-annotation` 应作为研发基础设施保留，但它只用于验证评测数据，不构成用户交付，也不应驱动正式 Skill 的下一步。

## 6. 目录和入口边界

建议按用途拆成三层，而不是立即大规模移动文件：

```text
travel-director/             正式产品入口：run、status
travel-director-benchmark/   Ground Truth、blind annotation、评估器
travel-director-lab/         旧音乐/时间线/渲染原型，仅供研发
scanner/                     内部素材证据层，不直接面向 Skill 用户
```

第一阶段只建立命令分组和调用边界，不删除旧模块。等简化流程通过一次真实素材回归后，再决定是否物理迁移或删除代码，避免在产品契约尚未稳定时进行无收益重构。

## 7. Skill 文档简化

### 7.1 新的 `SKILL.md` 只保留四类信息

1. 何时触发；
2. 接收哪两个用户输入；
3. 如何循环处理 `run` 返回的四种状态；
4. 禁止事项和最终交付格式。

不再在入口文档列出阶段命令、schema 细节、Ground Truth、blind 评测或旧原型。

### 7.2 参考文档按需读取

- `visual-observation-contract.md`：仅在状态为 `needs_visual_observation` 时读取；
- `runtime-contract.md`：只记录四种状态、输入输出和恢复规则；
- benchmark 和 legacy 各自拥有开发文档，不被正式 Skill 引用。

目标不是用另一份长文替代现有长文，而是让正式 Skill 的默认路径可以在一屏内理解。

## 8. 实施顺序

### 阶段 A：冻结和封装

- 暂停 Task 3、blind-v2 和新的 Director 规则开发；
- 为现有能力增加 `run` 和 `status` 封装；
- `run` 只调用已有模块，不改变导演判断规则；
- 建立旧项目读取兼容测试和幂等恢复测试。

阶段 A 的完成标准：同一项目可以通过反复调用一个命令，从初始化推进到完成，中断后可恢复，结果与现有正式流程一致。

### 阶段 B：替换正式 Skill 编排

- 将 `SKILL.md` 改为状态驱动的短入口；
- 默认不读取 benchmark 或 legacy 文档；
- 无冲突时由 Runner 生成兼容确认产物，不对用户暴露确认仪式；
- 少量聊天答复由最小转换层生成现有 hash 绑定产物；
- 保留 `final_summary.json` 作为机器真相，不新增输出协议。

阶段 B 的完成标准：用户只给目录和描述即可完成一次流程，不看到内部阶段或评测术语。

### 阶段 C：真实素材验收

- 用用户提供的一组本地真实素材完成无外部调用的端到端流程；
- 验证联系表观察、少量确认、结果输出和项目恢复；
- 对同一项目重跑一次，确认不重复扫描或覆盖有效产物。

阶段 C 的完成标准：用户只提供目录和描述即可获得可追溯的导演结果和三条提示词，`external_call_count=0`，同一项目可安全恢复。

### 可选工程整理：不阻断交付

- Ground Truth、blind annotation 和评估器可在日后移入独立研发入口；
- 旧音乐、时间线、音效和渲染命令可标记为 legacy/lab；
- 不为完成当前 Skill 而删除或物理迁移底层命令。

## 9. 验收标准

### 用户体验

- 用户只提供素材目录和自然语言描述；
- 用户只需要知道 `$travel-director`；
- 没有证据冲突时，全程不要求确认；
- 最终只展示一份总结和恰好 3 条提示词；
- 正常对话中不出现 Ground Truth、blind annotation、schema 或阶段图术语。

### 行为边界

- Scanner 不给素材分配开场、高潮、结尾等导演角色；
- 导演判断必须引用已记录的视觉证据，缺证据时保留不确定；
- 不调用本地视觉模型、曲多多、即梦、Codex API 或其他外部/付费服务；
- 不生成成片、时间线、音效方案或具体歌曲下载结果。

### 工程质量

- `run` 幂等：重复执行不会重复写入相同阶段或改变既有有效结论；
- 可恢复：在扫描、观察、确认任一节点中断后可继续；
- 兼容：现有 V0.2/V0.3 项目可以读取，不强制一次性迁移；
- 评测隔离：正式 Skill 不调用 benchmark 命令，Task 1 评估器仍能独立运行；
- 范围可见：正式 Skill 只调用 `run`，`status` 仅用于诊断；其余底层入口不进入 Skill。

## 10. 本轮停止点

本文件同时作为阶段性上下文总结。阶段 A、B 已获用户确认并完成；阶段 C 复用原始素材目录、原 Brief 和已完成的 12 条素材 Director 项目验收通过。

已确认的实施决定：单 Skill + 幂等 `run`、评测工具不进入正式 Skill、旧原型不进入当前流程、无冲突时不向用户显示 Brief 或 DirectorReview 确认仪式。

当前无必做后续实施阶段。不自动启动 CLI 整理，也不补做 Task 3。

## 11. 阶段 A 实施记录

实施日期：2026-09-03。

已完成：

- 新增 `travel-director run`：接收素材目录、自然语言 Brief 和可选项目目录；
- 新增 `travel-director status`：只读检查现有项目阶段及等待状态；
- `run` 复用现有 Scanner、视觉观察、Brief、DirectorTreatment、DirectorReview、音乐提示词和总结实现；
- 本地扫描始终以 `detector=None`、`vision_encoder=None` 运行，不加载本地模型；
- 返回 `needs_visual_observation`、`needs_user_confirmation`、`completed` 或 `blocked`，相同项目可重复调用；
- 已完成的 V0.2/V0.3 阶段按已记录 hash 读取，不重新计算或覆盖；
- 将原有 `skill-summary` 写入逻辑提取为共享函数，旧命令行为保持兼容；
- 新增幂等恢复、旧视觉项目续跑、只读状态和篡改阻断测试。

验证证据：

- 聚焦回归：`24 passed`；
- 完整测试：`312 passed, 3 warnings`；
- 三项 warning 均来自 Python 3.13 将移除的 `aifc`、`audioop`、`sunau` 依赖提示，与本次封装无关；
- CLI 已在 `local-media-scanner` 项目目录验证，`run` 和 `status` 帮助可正常发现；
- 未运行真实视频回归，未调用模型、曲多多、即梦、Codex API 或其他外部/付费服务。

本阶段有意未做：

- 未缩减旧 CLI 命令的可见范围；该工作已降为可选工程整理；
- 未在阶段 A 改写正式 `SKILL.md`；该工作已在阶段 B 完成；
- 阶段 B 保留 BriefConfirmation 和 DirectorReview 兼容产物，但正常流程不对用户暴露它们；
- 未迁移、删除 benchmark 或 legacy/lab 代码；
- 未修改 Director 判断规则，未实施 Task 3 或 blind-v2。
