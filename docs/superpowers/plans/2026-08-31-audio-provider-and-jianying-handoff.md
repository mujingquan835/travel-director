# 旅行导演：音乐/音效 Provider 与剪映交接修订实施计划

> **历史记录／不得直接执行：** 本文中的本地生成模型、曲库、SFX 和 FFmpeg 粗剪路线已退出当前 Skill 主线。当前只保留“用户手工生成或取得音乐后导回本地项目”的后续方向。
>
> 当前唯一基线：[`../context/2026-09-04-travel-director-two-stage-project-contract-context.md`](../context/2026-09-04-travel-director-two-stage-project-contract-context.md)。

日期：2026-08-31
历史状态：待用户复核，未开始开发
权威工作区：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`
分支：`feature/local-media-scanner-v0.1`
编写基线：`9f1616590baedbeab0f301d60ad9a4447d2a7afd`

> 本计划替代原设计中“由即梦 CLI 直接生成音乐/SFX”的单一路径。实施时必须逐任务执行；每个模型下载、浏览器真实检索、账号登录、付费、授权或外部生成动作都需要新的、明确的用户授权。本计划本身不授权这些动作。

## 目标

把当前已经验证的本地 Director 链路改造成以下形态：

1. 默认输出可复制到即梦网页、剪映/CapCut 或其他生成器的音乐与音效提示词包。
2. 用户可把网页生成或已合法取得的本地音频导回 Director，继续节拍分析、时间线、选镜、SFX 和渲染。
3. 可选接入本地开源生成器：ACE-Step 1.5 负责音乐，MOSS-SoundEffect v2.0 负责音效。
4. 曲多多使用“快速、少量、当前可见页”的浏览器辅助路径；正式产品化则预留 HIFIVE 官方 API/SDK。
5. 网易云音乐和 QQ 音乐只作为人工发现参考方向的平台，不作为可下载、可抓取或默认可商用的生产音频源。
6. 剪映第一阶段只接收本地音频/视频与可选草稿，不把产品建立在未公开验证的剪映 AI API 上。

## 当前事实基线

- Git 工作区干净，HEAD 为 `9f16165`。
- Scanner 与 Director 已分包；Scanner Schema 不需要为本计划改动。
- 当前本地链路已包含：素材画像、音乐搜索 brief、离线曲库、音乐蓝图与参考安全提示词、实际音频分析、音乐槽位、镜头选择、SFX 计划、可恢复项目编排和 FFmpeg 预览渲染。
- 当前接受记录已验证一个 60 秒、720×1280、H.264/AAC 的本地合成预览；Provider-real 音乐价值和真实旅行素材的导演质量仍未验证。
- `DreaminaMusicProvider` 已 fail-closed；已安装即梦 CLI 的只读帮助只暴露图像/视频，不暴露音乐生成。
- 曲多多可访问，但现有代码只有“当前可见页 payload 解析器”，还没有可靠的搜索页浏览器协调器。
- 本机为 Apple Silicon M1 Pro、16 GB 统一内存；适合先做小模型/短时长烟测，不允许直接假设长音乐和 SFX 都能稳定生产。

## 产品与版权决策

### 1. 即梦改为提示词交付，不再是必需 Provider

默认主线改为：

```text
MusicBlueprint / SfxPlan
        ↓
PromptPackage
        ├─ music-prompt.txt       # 供即梦网页、剪映或其他生成器复制
        ├─ music-prompt.json      # 结构化参数与版权安全约束
        └─ sfx-prompts.json       # 只为入选镜头生成
        ↓
用户在任意工具生成或取得音频
        ↓
travel-director import-music / import-sfx
        ↓
现有本地分析、时间线和渲染链路
```

提示词只能引用 BPM、拍号、流派、乐器、情绪、能量曲线、段落与结尾方式；不得含参考曲名、作者、歌词、旋律片段或“模仿某艺人”等身份指令。

### 2. 开源生成器选型

| 用途 | 结论 | 理由 | 当前门禁 |
|---|---|---|---|
| 本地音乐 | 首选 ACE-Step 1.5 | MIT；10 秒至 10 分钟；支持 BPM、时长、纯音乐；官方提供 macOS Apple Silicon MPS/MLX 启动脚本和本地 REST API | 先做隔离环境与 30 秒烟测；模型下载需单独批准 |
| 本地 SFX | 首选 MOSS-SoundEffect v2.0 | Apache-2.0；中英文文本；1.3B；最长 30 秒；官方模型页给出 MPS 用法 | Mac 安装文档仍偏 CUDA；先做 3–5 秒单音效烟测 |
| 音乐/SFX 备选 | Stable Audio Open 1.0 | 可生成最长 47 秒的音乐和音效 | 模型为 Stability AI Community License，商业使用需单独核实，不作为默认产品路径 |
| 研究备选 | MusicGen / AudioGen | 成熟、资料多 | 权重为 CC-BY-NC 4.0，不进入商用产品路径 |
| 研究备选 | TangoFlux / AudioLDM | 文本音效能力可用 | TangoFlux 明确非商业研究；AudioLDM 数据/发布声明以研究例外为主，不进入商用路径 |

ACE-Step 的 reference audio、cover、remix 功能默认禁用。第一版只接受高层蓝图文本，避免参考音频带来的旋律与编曲相似风险。

官方依据：

- ACE-Step 1.5：[仓库与 Mac/API 能力](https://github.com/ACE-Step/ACE-Step-1.5)、[MIT 模型页](https://huggingface.co/ACE-Step/Ace-Step1.5)、[REST API](https://github.com/ACE-Step/ACE-Step-1.5/blob/main/docs/en/API.md)
- MOSS-SoundEffect v2.0：[官方模型页](https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0)、[官方仓库](https://github.com/OpenMOSS/MOSS-TTS)
- Stable Audio Open：[模型卡与许可](https://huggingface.co/stabilityai/stable-audio-open-1.0)
- AudioCraft：[MusicGen 模型卡](https://github.com/facebookresearch/audiocraft/blob/main/model_cards/MUSICGEN_MODEL_CARD.md)、[AudioGen 模型卡](https://github.com/facebookresearch/audiocraft/blob/main/model_cards/AUDIOGEN_MODEL_CARD.md)
- TangoFlux：[官方模型卡](https://huggingface.co/declare-lab/TangoFlux)

### 3. 剪映接入边界

剪映/CapCut 官方页面确认存在界面内的 [AI 音乐生成](https://www.capcut.com/tools/ai-music-generator) 和 [AI 音效生成](https://www.capcut.com/tools/ai-sound-effects-generator)。但截至本计划调研，没有找到可公开验证、可由本项目直接调用的 AI 音乐/SFX API 文档。`open.capcut.cn` 可见开发者后台入口，但公开页面当前不能提供可核验的相关接口合同。

因此分三层：

1. **正式基线**：输出本地 MP4、音乐、SFX 和结构化时间线 JSON，用户在剪映手动导入。
2. **实验导出**：评估开源 [`pyJianYingDraft`](https://github.com/you4728/pyjianyingdraft)，只生成一个全新的剪映草稿，不修改已有草稿，不自动导出。
3. **暂不采用**：未授权的逆向 API、加密草稿解密、GUI 批量导出、非官方云渲染和对剪映内部 AI 功能的自动点击。

`pyJianYingDraft` 能添加本地视频/音频、淡入淡出和轨道，但其 README 明确提示剪映 6+ 模板草稿加密、7+ 导出控件变化等版本风险。它只能是可替换的 `TimelineExporter`，不能成为 Director 的核心数据模型。

### 4. 网易云/QQ 音乐边界

网易云音乐与 QQ 音乐只能做“用户人工找参考曲”的入口：

- 用户可提交曲名、分享链接和自己总结的情绪/风格。
- Director 只保存参考意图和链接，不抓取、下载、缓存或解析受保护音频。
- 若用户要把原曲用于成片，必须另行提供明确授权证据和合法本地文件。
- 会员可听/可离线不等于可用于商业视频。

腾讯音乐的官方服务协议明确要求内容使用取得相关权利人的许可：[TME 服务协议](https://www.tencentmusic.com/zh-cn/protocol.html)。

### 5. 曲多多快速路径

原型快速路径：

```text
MusicSearchBrief
  -> search-packet.json（最多 3 组有序关键词/筛选建议）
  -> 打开曲多多当前搜索页
  -> 用户手动处理登录、验证码和授权购买
  -> 每次只读当前可见卡片，最多 5 条
  -> 本地排名 3 个方向
  -> 用户选择
  -> 仅保存元数据、详情/试听入口和捕获时间
```

禁止分页爬取、批量试听、试听音频下载和绕过风控。需要获得正式生产能力时，走 [HIFIVE 音加加开放平台](https://open.haifanwu.com/) 的搜索与授权 API/SDK；官方说明 API/SDK 需申请授权并按使用量或包年计费，不能把网页 DOM 适配器当成长期产品接口。

## 架构调整

```text
ReferenceDiscoveryProvider
  ├─ FixtureCatalogProvider
  ├─ QuduoduoVisiblePageProvider
  └─ ManualReferenceProvider      # 网易云/QQ/其他链接，仅意图元数据

PromptPackageBuilder              # 默认、零外部调用

MusicAssetProvider
  ├─ ManualImportedMusicProvider  # 网页生成/已授权本地文件
  └─ LocalAceStepProvider         # 可选 localhost API

SfxAssetProvider
  ├─ OriginalSoundProvider
  ├─ ManualImportedSfxProvider
  └─ LocalMossSfxProvider         # 可选 localhost API

TimelineExporter
  ├─ FfmpegPreviewExporter        # 已验证正式基线
  └─ JianyingDraftExporter        # 实验功能
```

Provider 返回本地文件和证据对象；Director 其他阶段不认识 Dreamina、ACE-Step、MOSS、曲多多或剪映 DOM。

## 文件地图

计划新增：

- `local-media-scanner/director/prompt_package.py`
- `local-media-scanner/director/audio_import.py`
- `local-media-scanner/director/reference/manual.py`
- `local-media-scanner/director/generation/ace_step.py`
- `local-media-scanner/director/sfx_generation/base.py`
- `local-media-scanner/director/sfx_generation/moss.py`
- `local-media-scanner/director/export/base.py`
- `local-media-scanner/director/export/jianying.py`
- `local-media-scanner/tests/director/test_prompt_package.py`
- `local-media-scanner/tests/director/test_audio_import.py`
- `local-media-scanner/tests/director/test_manual_reference.py`
- `local-media-scanner/tests/director/test_ace_step_provider.py`
- `local-media-scanner/tests/director/test_moss_sfx_provider.py`
- `local-media-scanner/tests/director/test_jianying_export.py`
- `local-media-scanner/prototype/fixtures/provider/ace-step-success.json`
- `local-media-scanner/prototype/fixtures/provider/moss-sfx-success.json`

计划修改：

- `docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md`
- `local-media-scanner/director/schema.py`
- `local-media-scanner/director/music_blueprint.py`
- `local-media-scanner/director/project.py`
- `local-media-scanner/director/cli.py`
- `local-media-scanner/director/catalog/quduoduo.py`
- `local-media-scanner/PROTOTYPE.md`
- `local-media-scanner/prototype/ACCEPTANCE.md`

不修改：

- `local-media-scanner/scanner/schema.py`
- Scanner 模型、阈值、Ground Truth 与既有运行产物
- 任何已有剪映草稿目录

## 可执行任务

### Task 1：把设计稿从“即梦直连”修订为“提示词交付 + 可替换 Provider”

**文件：**

- 修改设计稿第 2、6、8、9、10 节。
- 新增本计划对应的 ADR/决策说明（如需要）。

**步骤：**

1. 将流程中的“即梦 CLI 生成”改为 `PromptPackage -> 手工网页/本地 Provider -> ImportedMusicAsset`。
2. 保留现有 `MusicBlueprint`，不删除 `DreaminaMusicProvider`；把它标记为不支持且非默认。
3. 把 ACE-Step、MOSS、剪映、曲多多、网易云/QQ 的边界写入规范。
4. 文档检查：所有外部行为必须有 `not_executed / blocked / completed` 明确状态。
5. 提交：`docs: revise audio provider and editor handoff design`。

**验收：**设计稿不再暗示即梦 CLI 已具备音乐/SFX 能力；默认流程在没有任何外部生成器时仍能完成提示词交付和本地音频导回。

### Task 2：冻结 PromptPackage 契约并输出可复制文件

**文件：**

- 修改 `director/schema.py`、`director/music_blueprint.py`、`director/project.py`、`director/cli.py`。
- 新增 `director/prompt_package.py` 和 `tests/director/test_prompt_package.py`。

**步骤：**

1. 先写失败测试，覆盖：60 秒音乐提示词、五段能量结构、无人声、明确落点、SFX 时刻/时长、中文与英文版本。
2. 加入泄漏测试：参考曲名、作者、链接、旋律/歌词不得进入提示词。
3. 定义 `PromptPackage`、`MusicGenerationPrompt`、`SfxGenerationPrompt`；保持严格版本化和 `extra="forbid"`。
4. 新增 `travel-director build-prompts --project ...`。
5. 原子写入：`generation/prompt-package.json`、`generation/music-prompt.txt`、`generation/sfx-prompts.json`，并记录 SHA-256。
6. 运行：`uv run pytest -q tests/director/test_prompt_package.py tests/director/test_music_blueprint.py`。
7. 提交：`feat: emit provider-neutral audio prompt packages`。

**验收：**用户不安装任何生成 CLI 也能拿到可直接复制的音乐和音效提示词；执行该命令不联网。

### Task 3：实现合法本地音频导回与证据冻结

**文件：**

- 新增 `director/audio_import.py`、`tests/director/test_audio_import.py`。
- 修改 `director/schema.py`、`director/project.py`、`director/cli.py`。

**步骤：**

1. 先写失败测试：不存在文件、非音频、超时长、哈希漂移、重复导入和源文件覆盖。
2. 定义 `ImportedAudioAsset`：来源类型、原始绝对路径仅保存在本地证据、冻结相对路径、SHA-256、时长、采样率、声道、许可备注、用户确认状态。
3. 新增：
   - `travel-director import-music --project ... --audio ... --source manual_web|licensed_library|local_generation`
   - `travel-director import-sfx --project ... --audio ... --timeline-time ...`
4. 使用 ffprobe 验证，复制到项目 `generation/assets/`；从不覆盖输入。
5. 没有许可备注时允许本地试剪，但把可发布状态标记为 `license_unverified`。
6. 让 `analyze-music`、渲染和后续阶段读取冻结资产。
7. 运行：`uv run pytest -q tests/director/test_audio_import.py tests/director/test_project.py tests/director/test_render.py`。
8. 提交：`feat: import and freeze user-provided audio assets`。

**验收：**即梦网页、剪映、ACE-Step 或曲库取得的合法本地音频都能走同一入口；没有授权证据时不会被标记为可发布。

### Task 4：把曲多多使用收敛成一次三方向快速会话

**文件：**

- 修改 `director/catalog/quduoduo.py`、`director/cli.py`。
- 新增/修改 `tests/director/test_quduoduo.py`。

**步骤：**

1. 基于 `MusicSearchBrief` 输出 `search-packet.json`：最多 3 组搜索组合，每组包含关键词、BPM 区间、情绪、乐器、无人声偏好和目标时长。
2. 浏览器只在用户明确点击“去曲多多找音乐”后打开。
3. 用户自行完成登录、验证码和购买；Agent 不处理验证码、不绕过风控。
4. 只抓当前可见页，最多 5 张卡片；复用现有 `parse_visible_results`。
5. 本地排名最多 3 个方向；保存捕获 URL、时间和字段缺失状态，不缓存试听音频。
6. 任一页面结构异常时返回 `blocked/unsupported_structure`，不猜 DOM。
7. 离线测试使用 fixture；浏览器 smoke 另行授权且最多一次。
8. 提交：`feat: package one-shot quduoduo search sessions`。

**验收：**从本地 brief 到三方向的人工操作不超过一次打开、最多三次关键词尝试、一次当前页读取；无音频下载、无分页爬取。

### Task 5：加入网易云/QQ 的人工参考意图入口

**文件：**

- 新增 `director/reference/manual.py`、`tests/director/test_manual_reference.py`。
- 修改 `director/schema.py`、`director/cli.py`。

**步骤：**

1. 定义 `ManualReferenceIntent`：平台、曲名、作者（可选）、用户提供链接、用户描述、`audio_available=false`、`usage_rights=reference_only`。
2. 新增 `travel-director add-reference`，只接受用户提供的字段。
3. 禁止命令从网易云/QQ 下载、抓流地址、歌词或音频指纹。
4. 参考意图只能补充风格搜索 brief；不能直接生成 `GeneratedMusicAsset`。
5. 若用户之后提供合法本地文件，必须通过 Task 3 的导入与许可证据。
6. 运行：`uv run pytest -q tests/director/test_manual_reference.py tests/director/test_music_blueprint.py`。
7. 提交：`feat: add reference-only consumer music intents`。

**验收：**QQ/网易云能帮助表达“想要什么感觉”，但系统不能把它们误当作可用于成片的素材库。

### Task 6：在隔离环境评估 ACE-Step 1.5，本任务不默认安装

**门禁：**开始前单独向用户报告预计模型大小、缓存目录、磁盘空间和一次烟测时长；得到授权后才能下载。

**文件：**

- 新增 `director/generation/ace_step.py`、`tests/director/test_ace_step_provider.py`。
- 新增离线 API fixture。

**步骤：**

1. 先用 fixture 实现 localhost 客户端合同；业务测试不得依赖真实模型。
2. 只允许 `127.0.0.1`，拒绝任意远端 URL。
3. 映射 `MusicBlueprint` 到 duration、BPM、time signature、instrumental、caption；禁用 reference audio、cover、remix、lyrics。
4. 在独立目录/虚拟环境固定 ACE-Step 版本、模型 revision 和许可证摘要，避免污染 Scanner 的 uv 环境。
5. 经授权后只生成 1 条 30 秒、无人声的旅行器乐；记录耗时、峰值内存、输出格式、SHA-256 和失败原因。
6. 本地导回走 Task 3；不直接修改时间线。
7. 通过后才把它列为可选 Provider；失败则保留 PromptPackage 主线。
8. 运行离线测试：`uv run pytest -q tests/director/test_ace_step_provider.py tests/director/test_generation_gate.py`。
9. 提交：`feat: add gated localhost ace-step provider`。

**验收：**没有服务/模型时明确 `blocked/local_provider_unavailable`；真实烟测最多一次且不使用任何参考音频。

### Task 7：在隔离环境评估 MOSS-SoundEffect v2.0，本任务不默认安装

**门禁：**和 ACE-Step 分开授权；先报告下载量、依赖与 Mac 兼容风险。

**文件：**

- 新增 `director/sfx_generation/base.py`、`director/sfx_generation/moss.py`、`tests/director/test_moss_sfx_provider.py`。
- 修改 `director/schema.py`、`director/project.py`。

**步骤：**

1. 用 fixture 定义 `SfxGenerationProvider` 与 localhost 合同。
2. 每次只处理 `SfxPlan` 中 decision 为 `generate_sfx` 的项目；原声优先规则不变。
3. 默认 3–5 秒，最长不超过 10 秒；输出 48 kHz WAV，记录 seed、prompt、模型 revision 与 SHA-256。
4. 先尝试 MPS；不允许因失败自动切换云服务。
5. 经授权后只生成一个明确事件（如脚步或掠过），做峰值、静音、削波和时长检查。
6. 失败时输出 `sfx-prompts.json` 供用户手工生成。
7. 运行：`uv run pytest -q tests/director/test_moss_sfx_provider.py tests/director/test_sfx.py`。
8. 提交：`feat: add gated localhost moss sfx provider`。

**验收：**不开模型也不阻断成片；只在片段入选后生成，且一次 smoke 不扩张成批量任务。

### Task 8：实验性导出新的剪映草稿

**门禁：**先确认本机剪映专业版版本、草稿根目录和用户是否允许创建一个全新测试草稿；当前未在标准 `/Applications` 目录检测到剪映应用，不能假设已安装。

**文件：**

- 新增 `director/export/base.py`、`director/export/jianying.py`、`tests/director/test_jianying_export.py`。
- 修改 `director/cli.py`、`director/project.py`。

**步骤：**

1. 定义 Provider-neutral `TimelineExportResult`；现有 FFmpeg 渲染保持正式基线。
2. 先测试纯中间模型：视频片段、source in/out、音乐轨、原声/SFX 轨、淡入淡出、画幅。
3. 对 `pyJianYingDraft` 做版本固定和许可证核验；只写临时测试目录。
4. 新增 `travel-director export-jianying --project ... --draft-root ... --name ...`。
5. 强制创建新草稿目录；目标已存在则失败，不覆盖、不修改、不解密任何用户草稿。
6. 先在临时目录验证 JSON/素材引用完整，再经用户确认写入真实草稿根目录。
7. 用户手动打开剪映检查：镜头顺序、in/out、音乐位置、原声/SFX、横竖屏。
8. macOS 不做自动导出，不点击剪映 AI，不使用第三方云渲染。
9. 提交：`feat: add experimental jianying draft export`。

**验收：**至少一个新测试草稿能被当前剪映版本打开；失败不影响 MP4 基线，也不触碰已有草稿。

### Task 9：做一次受限真实旅行素材验收

**前置：**Tasks 1–5 已完成；Tasks 6–8 可按用户选择跳过。所有输入被冻结，外部调用逐项授权。

**步骤：**

1. 运行完整离线测试一次：`uv run pytest -q`。
2. 选一个代表性旅行项目；只运行一次 Scanner 缓存链，不重复视觉模型实验。
3. 选择一种音乐来源：用户导入、曲多多合法授权文件或经批准的 ACE-Step 单次生成。
4. 分析实际音乐，生成时间线、镜头选择与 SFX 计划。
5. 音效来源按优先级：原声 > 用户导入 > 经批准的单次 MOSS 生成 > 静音。
6. 生成 FFmpeg MP4；若 Task 8 已通过，再生成一个新剪映草稿。
7. 记录：音乐许可状态、外部调用数、模型/Provider 状态、素材留存率、重复镜头、音画落点、人工修改项和输出哈希。
8. 更新 `PROTOTYPE.md`、`prototype/ACCEPTANCE.md` 和阶段上下文。
9. 提交：`docs: record revised audio-provider acceptance`。

**验收：**不能用提示词、fixture、网站标题或模型安装成功替代真实音频与真实成片证据；最终结论必须是 `continue / revise / stop` 之一并列出约束。

## 有界测试协议

- 每个实现任务：目标测试一次；失败后最多一次修复重试；全量测试一次。
- ACE-Step：最多一次 30 秒生成；不使用参考音频。
- MOSS：最多一次 3–5 秒单音效生成。
- 曲多多：一次用户触发会话、最多 3 组搜索、读取 1 个当前可见页、最多 5 个候选。
- 剪映：只创建 1 个全新测试草稿；不自动导出。
- 不重复运行 Scanner 大模型或已有 30 条视觉验证集。

## 停止条件

出现任一情况立即停止对应分支，不影响 PromptPackage 与本地 MP4 基线：

- 模型/依赖需要大下载但未获授权。
- 开源代码与权重许可不一致或不允许目标商业用途。
- M1 Pro 16 GB 无法稳定运行，或会导致明显系统资源风险。
- 曲多多出现登录、验证码、WAF、页面结构不支持或授权范围不明。
- 网易云/QQ 来源没有独立商用授权。
- 剪映草稿版本不兼容、需要解密/逆向、或可能覆盖用户草稿。
- 任一外部服务要求付费、充值或授权确认而用户未在当下明确批准。

## 推荐执行顺序

建议先批准 **Tasks 1–5**：它们让即梦网页、曲多多、网易云/QQ 参考和任意本地音频都能进入同一条安全链路，不需要下载大模型。

之后分开复核：

1. **Task 6（ACE-Step）**：优先于其他本地音乐模型。
2. **Task 8（剪映草稿）**：在用户确认已安装版本和草稿路径后单独做。
3. **Task 7（MOSS SFX）**：最后做，因为现有原声/SFX 计划已能降级，且 Mac 兼容性不如 ACE-Step 明确。

## 本轮未执行

- 未修改业务代码。
- 未运行测试或模型。
- 未安装或下载 ACE-Step、MOSS、Stable Audio、MusicGen、AudioGen、TangoFlux、AudioLDM 或剪映相关依赖。
- 未调用即梦、曲多多、HIFIVE、剪映 AI、网易云、QQ 音乐或任何付费服务。
- 未登录、试听、下载、购买或生成任何音乐/音效。
