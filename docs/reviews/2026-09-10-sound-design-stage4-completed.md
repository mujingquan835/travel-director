# 第四项：声音事件设计与修订记录

2026-09-10。阶段完成：声音事件合同、时间锚点与预响对齐算法、分层角色与听觉前后景、现场声与素材库区隔、显式缺口记录、听审记录绑定、不可变修订差异比对、FCPXML三绑定导出接入、本地测试与Skill安装。未完成实际剪映客户端验收、成片主观混音审美验收。未提交Git、未推送或运行本轮CI。

## 已实现的变化

以前音效模块（`director/sfx_matching.py`）仅根据角色和文件名关键词筛选文件，按最短时长挑选并固定 `source_in=0, offset_seconds>=0`，导致声音重音因文件前奏延迟到达、高频whoosh堆叠、现场声与素材库混淆。新流程把音效从“选文件”提升为“设计声音事件”：

1. **时间锚点对齐而非文件起点**：
   - 区分画面触发时刻 `event_time`、声音内部重音时刻 `source_anchor_time` 与源入点 `source_in`；
   - 自动计算预响 $\text{pre\_roll} = \text{source\_anchor\_time} - \text{source\_in}$；
   - 时间线落轨公式：$\text{timeline\_in} = \text{event\_time} - \text{pre\_roll}$；
   - 声音瞬态重音在 $\text{timeline\_in} + \text{pre\_roll} = \text{event\_time}$ 处与视觉事件精确对齐；
   - 严格拒绝预响超出时间线起点（$\text{timeline\_in} < 0$）或音频结束越过项目画布的非法配置，不静默截断前奏。
2. **三级职能角色与三层听觉前后景**：
   - 角色分工：
     - `location_ambient`：建立场所环境与空间感，保持连续性，禁止每刀切换硬重启；
     - `action_foley`：响应具体画面主体动作，必须绑定视觉触发原因；
     - `transition_accent`：转场强调（whoosh/hit/riser），必须有明确叙事理由，禁止默认每刀添加。
   - 听觉深度：`foreground`（前景焦点）、`midground`（中景伴随）、`background`（背景氛围）。
3. **真实性区隔与显式缺口**：
   - `location_recorded`（现场声）：严格核验证实来自素材视频或录音，禁止素材库音效伪称现场声；
   - `library_sfx`（素材库）：明确选曲与设计理由；
   - `missing_gap`（显式缺口）：现场声不可用（如严重风噪）或缺少对应音效时，显式记录缺口，不使用生硬杂音冒充。
4. **与音乐的互动关系**：
   - `parallel`：独立并存混音；
   - `music_ducked`：需要音乐避让；
   - `music_silent`：在第三项音乐适配规划的 `silence` 留白区间内发声；程序校验留白覆盖度；
   - `accent_sync`：与音乐适配的节奏或转折事件同步对齐。
5. **严谨听审证据**：
   - 听审状态：`not_listened`、`source_listened`、`context_reviewed`；
   - 凡声称听审必须绑定具备听审人、方式、时区时间和笔记的 `SoundListeningRecord`，且区间完全覆盖使用范围；
   - 最终混音听审 `mix_listening_status` 诚实保持 `not_reviewed`，程序校验不代表听感好听。

## 版本修订与三绑定联合导出

- 初版与修订均输出至独立目录，禁止原目录覆盖；
- 修订使用 `--parent` 自动生成字段级 before/after 差异，记录父版哈希；
- 派生决策在继承第二项 `shot_group` 绑定与第三项 `music_adaptation` 绑定的基础上，追加 `sound_design` 绑定；
- `export-fcpxml` 现同时复核镜头组、音乐适配和声音设计三份证据快照，将视频、音乐、音效分配至不同音轨 lane，并生成完整的 `receipt.json`。

## 文件与调用

源码根目录：`<checkout>/local-media-scanner`。

- [声音设计实现](file://<checkout>/local-media-scanner/director/sound_design.py)
- [声音设计合同](file://<checkout>/local-media-scanner/director/sound_design_schema.py)
- [Skill参考规范](file://<checkout>/local-media-scanner/skills/travel-director/references/sound-design.md)
- [导出接入与合同更新](file://<checkout>/local-media-scanner/director/fcpxml_delivery.py)
- [单元测试套件](file://<checkout>/local-media-scanner/tests/director/test_sound_design.py)
- 本地安装入口：`$CODEX_HOME/skills/travel-director/SKILL.md`；调用名 `$travel-director`。

从源码根运行 CLI：

```bash
uv run travel-director build-sound-design --plan <plan.json绝对路径> --output <新版本目录>
uv run travel-director build-sound-design --plan <修订plan.json> --parent <前版sound_design.json> --output <新修订目录>
uv run travel-director inspect-sound-design --sound-design <sound_design.json>
uv run travel-director export-fcpxml --decision <返回的edit_decision.json> --output <新交付目录>
```

## 验证结果

- 全量测试通过：**638 passed，3 个既有依赖弃用警告，45.67 秒**。
- 本轮新增 14 项测试，覆盖时间锚点计算、预响超界拒绝、画布溢出、源区间越界、库音效冒充现场声拒绝、missing_gap 无轨记录、听审记录覆盖度、版本差异比对、不可变覆盖拦截、包络关键点合法性、以及画面组+音乐适配+声音设计**三绑定联合导出**与防篡改核验。
- Skill validator 通过：13 个文件，22 个本地链接有效；`git diff --check` 通过；本机安装后 resolver、validator 及 inspect 均通过。
- [完整测试日志](file://<checkout>/local-media-scanner/validation/sound-design-20260910/tests.log)

## 真实数据端到端验证

沿用前序阶段的真实万岁山项目素材（画面组：IMG_0229 + IMG_0230 共 2.133333 秒；音乐：106 秒原曲适配，含 1.0–1.3 秒留白停顿）。

1. **缺口声明**：第一镜头（IMG_0229）现场环境声因风噪过大，明确声明为 `missing_gap`，不胡乱添加素材库声效；
2. **拟音锚点**：第二镜头（IMG_0230）内部 1.466667 秒处发生车辆滑过遮挡动作（继承第一项 ±0.133 秒观察误差）。选用素材库 `CZG_Whoosh_006.wav`，测得其内部重音位于 0.20 秒，取 `source_in=0.05`，预响 0.15 秒；
   $$\text{timeline\_in} = 1.466667 - 0.15 = 1.316667 \text{ 秒}$$
   该拟音片段在 1.316667 秒进入，瞬态重音正好落在 1.466667 秒，与画面遮挡完全同步。
3. **版本修订对比**：
   - 初版（v1）：时长 0.50 秒，增益 0.6，尾音策略 `ring_out`，完成源音试听；
   - 第二版（v2）：延长时长至 0.60 秒以保留完整余韵，增益降至 0.45 避免掩盖 1.3 秒恢复的音乐，尾音策略改为 `fade_out`，并完成混音上下文试听；
   - 修订比对生成 **9 处字段级变化**，涵盖 duration, base_gain, fade_out, tail_policy, listening records 等。
4. **FCPXML 交付物化**：
   - 成功导出含 2 段视频、2 段音乐和 1 段声音设计拟音的 FCPXML 工程；
   - 视频轨位于主轨，音乐轨分配为 `lane="-1"`，拟音轨分配为 `lane="-2"`；
   - 独立反算 XML 确认：音效偏移量为 `6116667/1000000s`（对齐主轨原点），增益为 `-6.936dB`（对应 0.45 线性振幅比）；
   - 交付包收据中 `shot_group_evidence_validated`、`music_adaptation_evidence_validated` 和 `sound_design_evidence_validated` 均记录为 `true`。

### 产物链接

- [真实声音设计计划 v1](file://<checkout>/local-media-scanner/validation/sound-design-20260910/plan-v1.json)
- [初版声音设计结果 v1](file://<checkout>/local-media-scanner/validation/sound-design-20260910/v1/sound_design.json)
- [真实声音设计计划 v2](file://<checkout>/local-media-scanner/validation/sound-design-20260910/plan-v2.json)
- [修订版声音设计及差异 v2](file://<checkout>/local-media-scanner/validation/sound-design-20260910/v2/sound_design.json)
- [FCPXML交付工程](file://<checkout>/local-media-scanner/validation/sound-design-20260910/package/project.fcpxml)
- [导出收据与三绑定证据](file://<checkout>/local-media-scanner/validation/sound-design-20260910/package/receipt.json)
- [全链路历史哈希检查](file://<checkout>/local-media-scanner/validation/sound-design-20260910/history-check.json)
