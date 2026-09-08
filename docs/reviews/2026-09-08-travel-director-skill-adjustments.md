# Travel Director Skill 整体复盘与修改清单

日期：2026-09-08。性质：基于源码、已安装 Skill 与历史案例文件的审查；本文件提出修改要求，不表示这些修改已经实现。

## 1. 审查范围与基线

- 权威功能工作树：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`。
- 包目录：上述工作树的 `local-media-scanner`；下文代码路径均相对于包目录，`../.github` 相对于仓库根目录。
- 功能分支：`feature/local-media-scanner-v0.1`，本次读取 HEAD 为 `c45e1d9`；本地 main 为 `f886676`，不能混用两者报告功能。
- 已安装 `/Users/meimaodawang/.codex/skills/travel-director` 与功能分支 `skills/travel-director` 经目录比较一致。
- 已读：Skill 入口、workflow、creative-direction、visual-observation-contract、安装与工作区解析脚本，以及 Runner、交付存储、时间线、音效和粗剪相关实现。
- 测试基线来自上一阶段：本地 452 passed、3 warnings；GitHub Actions run 34102081885 成功。本次为文档审查，没有重跑全量测试或刷新远端 PR 状态。
- 真实案例：`prototype/runs/travel-project-3d14b9a84b`，万岁山素材、60 秒竖屏目标、用户选定 Fireflies。

## 2. 总体判断

当前具备本地素材观察、创意方案、用户选曲、音乐冻结分析、快速时间线 JSON/Markdown 的方案交付能力。`completed` 的边界是占位时间线方案完成。真实素材填槽、带 Hook/Outro 的完整混音预览、编辑工程交付尚未形成同一条正式 Runner 流程。

现阶段主要矛盾是能力边界、修订机制和实际交付的一致性。应先收口规范和失败报告，再为同一首音乐建立可追踪的交付修订，之后接入一条有范围限制的真实预览流程。

保留的设计：单一 `run` 入口；原始输入与 Brief 不变；观察证据可追溯；不确定字段允许 abstain；用户选曲；音乐字节冻结；交付收据校验；历史产物不覆盖；本地流程 `external_call_count=0`。独立盲测属于评估支线，不能要求普通用户提供 Ground Truth，也不能把历史测试通过数当作剪辑质量指标。

## 3. 需要修改的项目

优先级：P1 为正式交付或下一轮预览前必须处理；P2 为提升质量与可维护性；P3 为后续扩展。

执行进度：R01–R05 已完成，R06–R12 未执行。每次只处理一项，报告后暂停。下文问题证据保留审查时基线。

### R01 · P1 · 统一能力说明和交付措辞

**状态：已完成（2026-09-08）**。已修改仓库首页、包 README、Skill 入口与 workflow；同步已安装 Skill，目录比较一致。验证：Skill 测试 10 passed；完整测试依赖 dry-run 无变更；CLI run --help 正常；git diff --check 通过。未在全新机器重装环境，未重跑全量媒体测试。阶段记录见同目录 `2026-09-08-r01-delivery-documentation-completed.md`。

**证据**：`README.md` 仍写“不创建时间线”，与现有 Runner 不符；开发安装命令只有 `--extra dev`，而 CI 全量测试安装 `dev` 和 `vision`。`workflow.md` 已说明 completed 是占位方案，Skill 主入口没有同样清晰地强调这一点。

**修改位置**：`README.md`、`skills/travel-director/SKILL.md`、`references/workflow.md`（位于同一 Skill 下）。

**要求**：明确区分方案交付、预览交付、编辑工程交付；列出实际支持的模式。保留唯一 Runner 入口；说明 Python 3.12、FFmpeg/ffprobe，以及运行环境和完整测试环境的不同依赖。不能用“安装 vision 测试依赖”暗示正常流程会启动模型。

**验收**：新用户按 README 能安装并调用；completed 回复必须包含实际产物、占位槽位状态与尚未生成的交付类型；正文不再出现与实现冲突的范围说明。

### R02 · P1 · 工作区解析必须尊重显式配置

**状态：已完成（2026-09-08）**。无效配置立即失败；支持包与仓库根路径；当前 checkout 优先，关联候选多于一个则明确报歧义；移除本机硬编码路径。新增 12 个解析用例，全量 464 passed、3 条原有警告；已同步全局 Skill。详见 `2026-09-08-r02-workspace-resolution-completed.md`。

**证据**：`skills/travel-director/scripts/resolve_workspace.py` 将无效 `--workspace` 加入候选后继续回退，可能静默选择其他 checkout；候选包含作者机器绝对路径和特定 worktree 名称。

**修改位置**：解析脚本、Skill workflow、`tests/director/test_travel_director_skill.py`。

**要求**：显式路径无效时返回明确错误；环境配置无效时也说明原因；支持仓库根目录下的 `local-media-scanner`；自动发现多个有效 checkout 时采用可解释规则或报告歧义。运行诊断应能确认实际包路径和代码版本。

**验收**：临时目录测试覆盖错误显式路径、仓库根入口、多 worktree、无作者目录环境；不能声称使用一个分支却运行另一个分支。

### R03 · P1 · 音效失败必须可见

**状态：已完成**。新交付记录 Hook/Outro 状态与原因；可选资源缺失明确降级，程序异常阻塞；新增 --require-sfx 支持必需音效校验；旧交付保持可读且不覆盖。全量 478 passed、3 条原有警告，Skill 已同步。详见 `2026-09-08-r03-audio-packaging-status-completed.md`。

**证据**：`runner._build_and_record_delivery` 对音效库读取使用 `except Exception: pass`；`delivery.build_fast_mode_timeline` 对 Hook/Outro 异常转为 None。目录不可用、没有匹配与程序错误可能都表现为没有音效的 completed。

**修改位置**：`director/runner.py`、`director/delivery.py`、`director/export/markdown.py`、相关 delivery/runner 测试、workflow。

**要求**：记录包装状态和原因，区分未启用、无匹配、资源不可用、生成失败；可选音效缺失允许带明确降级说明交付；意外代码错误不能被当成正常无音效。用户明确要求的必需音效缺失应返回可操作的阻塞原因。

**验收**：缺目录、缺 Riser、无 Outro 匹配、模拟程序异常分别有可辨认结果；JSON、Markdown 与用户回复一致。

### R04 · P1 · 同音乐的时间线修订

**状态：已完成**。新增 --new-timeline-revision；独立子项目、算法与输入指纹、继承证据校验、收据来源绑定、重复请求复用。真实 Fireflies 新修订 23 槽位，原项目 5764 个文件哈希不变。详见 `2026-09-08-r04-timeline-revision-completed.md`。

**证据**：`director/music_version.py` 明确拒绝相同音乐内容；`timeline_delivery_store.py` 保护已完成产物；原案例正式交付仍是 17 槽位和旧 SubDrop，23 槽位高潮改进保存在独立 validation 目录。

**修改位置**：Runner/CLI、交付存储、项目结构、Skill workflow；新增专门的修订模块及其测试，具体接口在本项实施计划中确定。

**要求**：同音乐、同素材、同创意允许显式创建新时间线修订；记录父交付、算法版本、配置和输入哈希；复用已校验观察及音乐分析；每版独立收据；重复相同请求幂等；旧版与旧状态不可覆盖。新增接口落地前不能在 Skill 中写成现有命令。

**验收**：Fireflies 原版逐文件哈希不变，新版使用当前算法和确定性 Hook；重复运行得到同一修订；输入损坏或中断不形成伪 completed。

**对上轮建议的修正**：新建项目只能作为隔离验收手段，不能替代修订机制。用新 Brief 或复制改状态绕过锁定会损失追溯性，不作为推荐流程。

### R05 · P1 · 音效字节可追踪，Outro 同样确定性

**状态：已完成**。Outro 保留匹配条件并按路径稳定选择；新 Runner 交付冻结所选音效并记录来源、实测时长、大小、SHA-256；交付/恢复校验副本。全量 494 passed、3 条原有警告。详见 `2026-09-08-r05-sfx-assets-completed.md`。

**证据**：Hook 已按时长误差与路径稳定排序；`outro_builder.select_outro_sfx` 仍返回输入序列中的第一个匹配。Hook/Outro 计划保存路径，当前交付收据仅绑定 JSON/Markdown，未绑定音效文件字节。

**修改位置**：`director/outro_builder.py`、`hook_builder.py`、音效资产模型及交付存储、`tests/director/test_hook_outro.py`。

**要求**：Outro 定义稳定排序和同分规则；选择后记录音效来源、时长和 SHA-256，渲染前校验或冻结资产。路径排序只保证目录重排一致，不能保证同路径文件替换后内容一致。

**验收**：正序、倒序、多个排列的结果一致；同路径更换字节被识别；已完成版本不因音效库更新悄悄换音效。

### R06 · P1 · 真实素材填槽与预览接入

**证据**：快速交付产出 `FastModeSlot`；现有 `clip_selector.place_clips` 消费 `TimelineSlot` 与 `MaterialScanResult`；Runner 尚未将此链路接入快速交付。观察契约不允许从稀疏帧直接声明精确素材入出点。

**修改位置**：`director/delivery.py`、`clip_selector.py`、`runner.py`、`render.py`；新增最小适配层与端到端测试；能力通过后更新 Skill。

**要求**：明确观察证据与选片输入之间的映射；尊重 rejected/unknown、创意段素材 IDs 和缺口；入出点由剪辑阶段产生，不伪称视觉观察结论；记录每槽素材、源区间、选择理由及约束放宽。无素材可填时报告 partial，不压缩时间轴掩盖空槽。

**验收**：先输出可审查的 placements，再生成 720×1280 预览；区间不越界、覆盖目标时长、拒绝素材不出现；保留原交付；失败保留可重试证据。仅预览可播放仍不代表剪辑质量验收通过。

### R07 · P1 · 预览接入实际音频包装并校验边界

**证据**：`render.build_ffmpeg_command` 目前混合 BGM 与部分素材原声，没有消费 HookPlan/OutroPlan。Hook 音量表达式在相邻闭区间相加，2 秒和恢复终点存在边界叠加风险；恢复时间未设正数约束。现有相关测试主要检查滤镜字符串，未证明听感和混音电平。

**修改位置**：`director/hook_builder.py`、`outro_builder.py`、`render.py`、配置模型与音频测试。

**要求**：统一 BGM、Hook、Outro、原声的时间轴；用互斥分段表达式避免边界重复；规定恢复时间为零时的合法行为或拒绝配置；处理无音轨素材；报告混音峰值及尾部处理。总时长与计划一致。

**验收**：用已知振幅测试音验证 Ducking 与恢复边界；检查音效定位和无源音轨情形；Fireflies 实际预览试听前 2.3 秒及最后 5 秒。原曲 61.38 秒截为 60 秒时，继续保留“截点未分析”的事实，不能把原曲 decay 当作 60 秒听感结论。

### R08 · P2 · 让包装遵循创意意图

**证据**：创意契约允许空 SFX 计划；快速交付只要有音效条目便自动构建 Hook，尚未把创意的静默/音效空间要求映射为包装策略。槽位按中点继承创意分段，可能跨越叙事边界。

**修改位置**：creative schema、delivery、timeline、creative-direction 参考和相关测试。

**要求**：尊重用户禁用 Hook 或留白需求；保留 source section ID 和包装理由；定义叙事边界与节拍吸附的优先规则和容差，避免把跨段镜头描述成完全属于一段。

**验收**：无 Hook 创意不会被自动叠加；分段交界能解释时间偏移；高潮强化不凭空制造不存在的素材或事件。

### R09 · P2 · 收敛交付保存入口

**证据**：`delivery.save_fast_mode_delivery` 注释称原子保存，实际直接连续 write_text；正式 Runner 使用有收据的 `timeline_delivery_store.record_timeline_delivery`。不能把前者问题误报为 Runner 已失去收据保护。

**要求**：统一正式保存入口，或清楚标注直接导出仅供临时验证，修正误导注释；文档区分正式交付与 validation artifact。

**验收**：正式流程无法绕过收据；直接导出不会更新项目 completed；中断后的行为可解释且保留旧交付。

### R10 · P2 · Skill 发布与 CI 证据完整

**证据**：安装器已有逐文件比对和备份，当前安装副本一致；CI 存在但不能据此推断分支保护已经强制要求检查。官方 quick validator 在未安装时会 skip。

**修改位置**：安装脚本及其说明、README、CI 配置、Skill 测试。

**要求**：记录发布代码版本和 Skill manifest；保留已有备份机制；补充仓库自包含的规范验证，不依赖开发者家目录；明确 skipped 的项目和影响；是否设置 required checks 单独作为仓库设置动作处理。不得将只运行检查表述为已强制阻止合并。

**验收**：全新环境能检查 Skill 引用与入口；安装失败可找回前版本；发布报告可定位运行代码与 Skill。修订代码应通过 `uv run pytest -q` 和 `git diff --check`，预览功能另需真实案例证据。

### R11 · P2 · 配置错误、性能与依赖维护

**证据**：音效库支持环境变量与配置文件，但配置异常存在静默回退；生成时间线会重新构建整个音频目录。当前三条警告来自 librosa 间接依赖 audioread，项目限定 Python 3.12。

**要求**：显式配置错误必须可见；评估复用已有目录缓存并保留冻结前重新校验；报告扫描/观察/音频分析耗时。依赖警告列为维护项，不直接删包或全局屏蔽；Python 升级前分别验证 WAV/MP3/M4A 与解码回退。

**验收**：错误配置不偷偷换库；缓存失效与文件变化测试通过；相同输入重试不重复无关昂贵阶段。当前警告不列为方案交付阻塞。

### R12 · P3 · 后续能力分批推进

- 精确片段观察：仅对不确定的已选槽位追加观察，继续保留证据与 abstention；不要为了“慢速模式”默认重看全部素材。
- 编辑工程导出：在一版真实粗剪人工验收后，单独评估目标剪辑软件版本、轨道/裁剪/音量参数和实机导入结果。
- 环境音：根据实际选中镜头与创意需要触发；“航拍”不等于应该听见无人机；音源应区分现场原声与后期设计。
- 槽位反馈：提供 keep/reject/替换区间反馈，后续修改进入新修订，不改写旧观察。

## 4. 推荐执行顺序与停止点

1. **批次 A：规范与可见性收口（R01–R03）**。交付一致的入口说明、可验证工作区解析和可解释音效降级。通过聚焦测试与回归后暂停。
2. **批次 B：修订与音效可追踪（R04–R05）**。用 Fireflies 做同音乐新版本，检查父版不变及新版本可复现。完成即暂停。
3. **批次 C：真实预览最小闭环（R06–R07）**。只处理现有万岁山案例：placements、低清 MP4、混音验证、用户反馈。先核对适配设计，再开发；不同时加入工程导出。
4. **批次 D：质量与维护（R08–R11）**。按真实预览反馈取舍；与当前交付直接相关的发布验证随对应批次完成。
5. **批次 E：扩展（R12）**。单独评估并实施，不能将该列表视为整包开发授权。

## 5. 下一轮真实验收标准

- 保持已确认的素材、Brief、Fireflies 选择和 60 秒竖屏目标。
- 先验证输入文件仍存在、证据哈希完整；不要删除项目状态以强制重跑。
- 旧正式版 17 槽位、改进验证版 23 槽位、新修订版分别标记；具体新版数量以实跑为准。
- 新版 Hook 正序/倒序结果一致，音效内容可追踪；高潮切分与局部能量来自本次算法输出。
- 方案验收：JSON/Markdown 一致、0–60 秒无空隙重叠、缺口可见、收据完整。
- 预览验收：真实素材区间合法、竖屏主体可见、高潮节奏与尾部听感经观看/试听反馈确认；外部服务调用仍为 0。
- 交付包清楚标注完成等级、版本、未完成项和下一步，不能仅凭 completed 或测试数宣布成片交付。

## 6. 本轮范围

本轮完成复盘及本修改清单；未改运行代码、Skill 安装内容、项目状态或媒体产物，未合并 PR、未运行真实渲染。后续每批先细化对应实施计划，完成并验证后备份阶段总结。
