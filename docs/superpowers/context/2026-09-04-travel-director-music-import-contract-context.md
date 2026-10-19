# Travel Director 用户音乐导入与本地分析合同交接

## 完成范围

- 权威 worktree：`<checkout>`
- 分支：`feature/local-media-scanner-v0.1`
- 正式 `travel-director run` 新增 `--music <local-audio>`，只允许在原项目已经进入 `waiting_for_music` 后使用。
- 新增独立 `director/audio_import.py`，负责音乐校验、不可变冻结、项目证据绑定和现有分析器接续；没有重写 `music_analysis.py`。
- 接受 WAV、MP3、M4A；使用本地 `ffprobe` 校验可解码性、时长、采样率和声道，首版拒绝超过 10 分钟的音乐。
- 音乐复制到项目 `generation/assets/`，复制过程使用同目录临时文件、`fsync`、复制中 SHA-256 复核和原子替换；不修改或覆盖用户原文件。
- `generation/music_asset.json` 记录原始绝对路径、本地冻结相对路径、SHA-256、大小、时长、采样率、声道、MIME、`user_provided` 来源和 `license_status=unverified`。
- `music_structure.json` 复用现有本地分析器，记录实际 BPM、beat、downbeat、能量曲线、段落候选、结尾行为、置信度和源 SHA-256。
- 相同音乐重复运行复用冻结资产和分析结果，不重新分析、不改写项目证据；不同音乐、哈希漂移、错误阶段、超时长或同时导入确认文件时返回 `blocked`。
- 音乐冻结和分析完成后公开状态为 `waiting_for_timeline`，`current_stage=music_analysis`；`completed` 继续保留给未来真正创建剪辑草稿的阶段。
- 本开发包不生成时间线、不选镜头、不创建粗剪或剪映草稿。

## 验收证据

- TDD 首轮失败：Runner 不接受 `music` 参数，3 个合同测试按预期失败。
- 音乐合同聚焦测试：`42 passed, 3 warnings in 6.24s`。
- 独立代码审查发现并修复两个 Important：伪装扩展名未核验真实容器，以及文件系统 `OSError` 可能泄漏出 Runner 合同。新增相应回归测试。
- 提交前完整回归：`341 passed, 3 warnings in 12.90s`。
- 3 条警告仍来自既有 `audioread` 对 `aifc`、`audioop`、`sunau` 的弃用引用。
- `travel-director run --help` 已显示 `--music`。
- Skill 官方快速校验通过：`Skill is valid!`。
- 仓库 Skill 与 `$CODEX_HOME/skills/travel-director` 安装目录一致。
- `git diff --check` 通过。

## 真实项目状态

- 真实项目 `prototype/runs/travel-project-3d14b9a84b` 仍为 `run_state=waiting_for_music`、`current_stage=visual_review`。
- 本阶段未向真实项目导入音乐，未调用本地视觉模型、曲多多、即梦、Codex API 或任何外部、付费服务，`external_call_count=0`。

## 后续停止点

下一独立开发包是“根据已冻结的 `MusicStructure` 生成鼓点、高潮与抽帧图片占位时间线”。开始前需单独冻结其 Runner 状态和图片占位适配合同；不得直接套用旧视频片段选择或 FFmpeg 粗剪流程。
