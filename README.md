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

已实现本地音频库索引、带缓存的候选推荐、用户选曲后的冻结分析，以及快速占位时间线 JSON/Markdown 交付和完整性校验。

`completed` 表示快速时间线方案已验证，素材槽位仍待填充。正式流程尚未接入真实素材预览、完整混音、慢速可视化填槽或编辑工程导出。万岁山案例已完成用户选曲和方案验证；剪辑点收尾听感仍需真实预览验收。

原始视频、音乐库、模型缓存、虚拟环境及运行产物保留本地，不随代码仓库上传。音频根目录可通过 `TRAVEL_DIRECTOR_AUDIO_ROOT` 配置，目录支持“音乐/音效”及旧版 BGM/SFX 布局。克隆到其他位置后，可用 `TRAVEL_DIRECTOR_WORKSPACE` 指定 `local-media-scanner` 的绝对路径。

## Git 分支

通过开发分支和 Pull Request 更新 main。使用前核对实际 checkout 和提交；功能分支上的改动只有合并后才进入 main。设置 `TRAVEL_DIRECTOR_WORKSPACE` 时应指向要运行的包目录。
