# 旅行导演 / Travel Director

本地优先的旅行素材分析与剪辑方案工具，通过 Codex Skill 和 Python Runner 使用。

## 代码入口

- `local-media-scanner/`：Python 项目、Scanner、Director 和测试。
- `local-media-scanner/skills/travel-director/`：Skill 入口与工作流说明。
- `docs/superpowers/`：设计、实施计划与阶段记录。

运行环境、安装步骤见 [项目说明](local-media-scanner/README.md)。安装 uv 后，在 Python 项目目录执行：

```bash
cd local-media-scanner
uv sync
uv run travel-director --help
uv run pytest -q
```

## 当前能力与边界

已实现本地音频库索引、带缓存的候选推荐、用户选曲后的冻结分析，以及占位时间线 JSON/Markdown 交付和完整性校验。最近完整回归为 449 项通过、3 条弃用警告（2026-09-07）。

时间线完成状态表示剪辑方案交付，不表示视频渲染或混音完成。真实项目用户选曲验收、剪辑点收尾分析及剪映草稿导出仍待后续阶段。

原始视频、音乐库、模型缓存、虚拟环境及运行产物保留本地，不随代码仓库上传。音频根目录可通过 `TRAVEL_DIRECTOR_AUDIO_ROOT` 配置，目录支持“音乐/音效”及旧版 BGM/SFX 布局。克隆到其他位置后，可用 `TRAVEL_DIRECTOR_WORKSPACE` 指定 `local-media-scanner` 的绝对路径。

## Git 分支

GitHub 的 `main` 保存本次完整代码；`feature/local-media-scanner-v0.1` 保留当前开发分支。后续可通过开发分支和 Pull Request 更新 main。
