# 旅行导演 / Travel Director

本地优先的旅行素材分析与剪辑方案工具，通过 Codex Skill 和 Python Runner 使用。

## 代码入口

- `local-media-scanner/`：Python 项目、Scanner、Director 和测试。
- `local-media-scanner/skills/travel-director/`：Skill 入口与工作流说明。
- `docs/superpowers/`：设计、实施计划与阶段记录。

运行环境、安装步骤见 [项目说明](local-media-scanner/README.md)。安装 uv 后，在 Python 项目目录执行：

```bash
cd local-media-scanner
uv sync --locked
uv run travel-director run --help
```

## 当前能力与边界

完整测试使用 `uv sync --locked --extra dev --extra vision` 安装依赖，再运行 `uv run pytest -q` 和 `git diff --check`。运行与测试均需要 Python 3.12、FFmpeg/ffprobe；正常 Skill 流程不启用模型。

**主 Runner 流程（规划交付）已实现：** 本地素材稀疏观察、创意方案、本地音频库索引与候选推荐、用户选曲后的冻结分析、快速占位时间线 JSON/Markdown（`delivery/` + `receipt.json`）、以及 `--build-guide` 音乐/画面与音频包装建议。

**精剪侧车与 FCPXML（在有简洁剪辑决策后）：** Skill 另支持镜头精看、局部镜头组、音乐乐句适配、声音事件设计，以及 `export-fcpxml` / `record-fcpxml-acceptance` 生成可导入剪映的 FCPXML 包并分别记录程序生成与客户端兼容。详见 `local-media-scanner/skills/travel-director/SKILL.md` 与 `references/fcpxml-delivery.md`。

**明确未宣称 / 未完成：**

- `completed` 只表示规划时间线方案已校验，不是成片、不是自动剪辑完成。
- 主观音画听看机制（`record-audiovisual-review`）存在，但仓库内 validation 样例为 **DEMO_INVALID**，不能当作审美闭环已完成。
- 音量包络 / fade 等音频处理导出（`needs_audio_processing`）尚未实现（P1）。
- 自动选镜主路径增强、clip_worthiness / 六镜头角色、1–2 帧 stinger 等不在当前 P0。
- 不生成成片 MP4；不以鼠标在剪映里手搭时间线作为正式交付。

原始视频、音乐库、模型缓存、虚拟环境及运行产物保留本地，不随代码仓库上传。音频根目录通过环境变量 **`TRAVEL_DIRECTOR_AUDIO_ROOT`** 配置（可选：`~/.config/travel-director/audio.toml` 的 `audio_root`）；**无个人家目录硬编码回退**。目录支持“音乐/音效”及旧版 BGM/SFX 布局。克隆到其他位置后，可用 `TRAVEL_DIRECTOR_WORKSPACE` 指定 `local-media-scanner` 的绝对路径。

## Git 分支

通过开发分支和 Pull Request 更新 main。使用前核对实际 checkout 和提交；功能分支上的改动只有合并后才进入 main。设置 `TRAVEL_DIRECTOR_WORKSPACE` 时应指向要运行的包目录。
