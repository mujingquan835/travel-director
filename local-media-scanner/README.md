# Travel Director — 本地素材分析与时间线方案

本目录包含 Scanner、Director Runner 和 Codex Skill。当前正式流程支持本地素材观察、创意方案、音乐候选推荐、用户选曲后的冻结分析，以及快速时间线 JSON/Markdown 交付。

## 安装与使用

先安装 uv，并确保 FFmpeg、ffprobe 在 PATH 上可用。项目要求 Python `>=3.12,<3.13`。以下命令在当前 checkout 的 `local-media-scanner` 目录运行：

```bash
uv sync --locked
ffmpeg -version
ffprobe -version
uv run travel-director run --help
```

将当前 checkout 的 Skill 安装到 Codex（已有不同副本时安装器会拒绝覆盖）：

```bash
uv run python skills/travel-director/scripts/install.py --codex-home "${CODEX_HOME:-$HOME/.codex}"
```

更新已有副本时，在安装命令末尾增加 `--replace`；安装器会先备份旧副本。设置 `TRAVEL_DIRECTOR_WORKSPACE` 为当前包目录的绝对路径，避免在多个 checkout 间误用版本。

在 Codex 中使用 `$travel-director`，提供素材文件夹绝对路径和自然语言创意要求。Skill 通过唯一的 `run` 入口推进：

```bash
uv run travel-director run --input <absolute-folder> --brief <description>
```

根据返回状态完成观察、必要确认和创意提交；后续调用保持 input/brief 不变，并带上返回的 `--project <project_path>`。用户选定音乐后使用 `--music <local-audio>`；到达 `waiting_for_timeline` 后使用 `--build-timeline` 生成快速方案。详细状态处理见 [Skill](skills/travel-director/SKILL.md) 和 [workflow](skills/travel-director/references/workflow.md)。单独运行 CLI 不会自动代替当前会话完成视觉观察或创意编写。

## 交付能力

| 交付类型 | 当前正式 Runner 支持 | 内容 |
| --- | --- | --- |
| 快速时间线方案 | 支持 | 节拍对齐占位槽位、叙事/运镜提示，以及实际生成的音频包装计划；JSON、Markdown 和完整性收据 |
| 真实素材预览 | 已接入 R06 | `--place-footage` 产出填槽报告；`--build-preview` 生成低清 BGM-only MP4，完整混音留待 R07 |
| 编辑工程 | 尚未接入 | 剪映等软件的可编辑工程 |

默认 `completed` 表示占位时间线方案已通过完整性校验。使用 `--place-footage` / `--build-preview` 时，根据 `current_stage` 和实际返回路径交付填槽报告或预览；有空槽时报告内为 `partial`，Runner 为 `blocked`，停止渲染并保留完整时间轴。产物独立保存于 `previews/<内容指纹>/`，旧时间线和收据不变。预览只含 BGM，完整画面缩放加黑边；Hook/Outro/原声混音、编辑工程和慢速可视化填槽尚未交付。

## 完整测试环境

完整测试会导入 Scanner 的可选视觉模块，因此需要同时安装 dev 与 vision extras，与 GitHub Actions 保持一致：

```bash
uv sync --locked --extra dev --extra vision
uv run pytest -q
git diff --check
```

vision 是完整测试的依赖要求，不表示正常 Skill 流程会加载模型。正常 Scanner 流程保持 `--no-models`，外部服务调用次数为 `external_call_count=0`。官方 Codex Skill 校验器未安装时，对应测试会标记 skipped，不能称该项已通过。

## 证据与使用边界

保留稀疏帧观察的不确定性，不把未经支持的语义判断当成确定事实。Scanner 的历史实验与评估见 `BENCHMARK.md`；这些指标不等于真实剪辑质量验收。

本地流程不上传素材、不调用外部音乐/模型服务。音乐可由用户在外部取得后通过本地文件导入。原始素材、冻结音乐和历史交付保持可追踪。同音乐方案更新使用 `run --project <completed-parent> --new-timeline-revision`，并保留相同 input/brief；返回独立项目、修订记录与收据，复用原观察和音乐分析。不能通过删除状态或覆盖旧文件重新生成。
