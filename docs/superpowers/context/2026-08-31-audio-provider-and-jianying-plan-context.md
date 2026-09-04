# 旅行导演音乐/音效 Provider 与剪映交接规划上下文

> **历史记录／不是当前实施入口：** 本文保留 2026-08-31 的调研结论，但本地生成模型、曲库、SFX 和 FFmpeg 粗剪不再属于当前 Skill 主线。
>
> 当前唯一基线：[`2026-09-04-travel-director-two-stage-project-contract-context.md`](2026-09-04-travel-director-two-stage-project-contract-context.md)。

日期：2026-08-31
历史阶段：方案调研与当时可执行计划完成
工作区：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`
分支：`feature/local-media-scanner-v0.1`
基线：`9f1616590baedbeab0f301d60ad9a4447d2a7afd`

## 用户最新决定

- 即梦 CLI 不能用于音乐/SFX，但用户能手工使用即梦网页；应把即梦路径改为提示词交付。
- 需要评估本地开源音乐与音效模型。
- 需要评估是否能把结果直接交给剪映，及相关开源项目。
- 网易云音乐、QQ 音乐可考虑作为找参考音乐的入口。
- 曲多多网站已可打开，需设计更快的使用流程。

## 已核验工作区

- 权威 worktree 正确，Git 状态干净。
- 当前 Director 已有提示词、实际音频分析、音乐时间线、镜头选择、SFX 计划、项目编排和本地 FFmpeg 渲染。
- 已安装 Dreamina CLI 的历史只读检查仅显示图像/视频生成，音乐能力不支持。
- 曲多多 parser 已存在，但真实快速会话协调器未形成稳定产品接口。
- 当前本机为 Apple Silicon M1 Pro、16 GB；没有运行或下载任何新模型。
- 标准 `/Applications` 目录未检测到剪映应用，剪映版本和草稿路径仍需用户后续确认。

## 规划结论

1. 默认路径改为 `PromptPackage -> 用户网页生成/本地生成 -> ImportAudio -> 本地 Director`。
2. 本地音乐首选 ACE-Step 1.5；本地 SFX 首选 MOSS-SoundEffect v2.0；两者均需单独的大模型下载与单次烟测授权。
3. Stable Audio Open、MusicGen/AudioGen、TangoFlux、AudioLDM 因商业许可或研究边界不作为默认产品路径。
4. 剪映/CapCut 的 UI 具备 AI 音乐与 AI 音效，但没有核实到可公开直接调用的对应 API；第一阶段只做手动导入，第二阶段实验 `pyJianYingDraft` 新草稿导出。
5. 网易云/QQ 音乐只保存人工参考意图，不下载、不抓流、不作为默认可商用音频。
6. 曲多多原型采用 `search-packet -> 当前可见页最多 5 条 -> 本地 3 方向`；正式产品路径为 HIFIVE 官方 API/SDK。

## 交付文件

- `docs/superpowers/plans/2026-08-31-audio-provider-and-jianying-handoff.md`

## 外部服务状态

- 即梦：`not_executed`
- 曲多多/HIFIVE：`not_executed`
- ACE-Step：`not_installed`
- MOSS-SoundEffect：`not_installed`
- 剪映 AI：`not_executed`
- 网易云/QQ 音乐：`not_executed`
- 付费、充值、下载与模型生成：均为 0

## 继续条件

用户先复核计划。建议优先批准 Tasks 1–5；ACE-Step、MOSS 和剪映草稿导出分别设置新的确认点，不打包授权。
