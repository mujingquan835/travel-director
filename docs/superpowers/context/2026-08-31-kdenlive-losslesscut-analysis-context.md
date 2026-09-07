# Kdenlive / LosslessCut 对旅行导演的借鉴分析上下文

日期：2026-08-31（Asia/Shanghai）

## 本轮范围

- 只做公开资料核验、现有实现对照和产品架构判断。
- 未安装 Kdenlive 或 LosslessCut，未修改旅行导演实现，未运行新的素材、模型、外部或付费调用。
- “两个项目”按 Kdenlive 与 LosslessCut 理解。

## 结论

不应把“Codex + LosslessCut + FFmpeg + Kdenlive”复制成旅行导演的固定四段流水线。

- Kdenlive 适合作为可选的人工精剪与交付端。旅行导演应继续拥有 Scanner、音乐结构、时间线、选镜和快速预览的核心状态，并新增 OpenTimelineIO 导出适配器，把多轨剪辑、标记和素材引用交给 Kdenlive 复核。不要直接生成易随版本变化的 `.kdenlive` XML。
- LosslessCut 适合作为可选的单素材人工选段工具，不适合作为多素材 Vlog 时间线或音乐卡点引擎。可考虑导出每个源文件的 CSV 选段清单，并把人工修正后的区间和标签导回为 keep/reject/editorial override。
- FFmpeg 继续负责确定性的扫描、抽帧、预览和自动化渲染。Kdenlive 与 LosslessCut 都不应替代当前内部 JSON 证据链。

## 关键原因

- 当前 `ClipPlacement` 已包含源文件、source in/out、section role、评分分量与约束放宽记录，足以映射到 OTIO clip/marker。
- 当前 FFmpeg render 是有哈希和 ffprobe 验证的快速预览，不应该因为引入 GUI 编辑器而移除。
- Kdenlive 官方支持 OTIO 多轨与标记导入/导出、代理、字幕、调色和音视频示波器，正好补足人工精剪层。
- Kdenlive 原生 `.kdenlive` 是基于 MLT 的版本化 XML，官方明确提示格式会变化且可能不向后兼容，因此只把 OTIO 当交换协议。
- LosslessCut 官方说明不能在同一时间线编辑多个文件；无损切点通常受关键帧约束，Smart Cut 仍为实验能力。它更适合源素材清理和人工标注，不适合最终卡点。
- 现有真实素材以 HEVC 为主；LosslessCut 使用 Chromium 播放，官方记录 HEVC/10-bit 等场景可能需要硬件解码切换或 FFmpeg 辅助播放，因此不能把它设为必经依赖。

## 建议的后续验证（尚未执行）

1. 先完成当前已记录的“避免可避免的同文件相邻”本地门槛。
2. 新增只读导出器：`clip_placements.json + sfx_plan.json + music asset -> OTIO`。
3. 用合成素材验证一次 Kdenlive 打开、素材重连、标记、音乐轨和往返导出，不碰真实素材。
4. 只有在存在明显的长素材人工挑选痛点时，再做 LosslessCut CSV 单素材往返小实验；否则暂不引入依赖。

## 官方资料

- https://docs.kdenlive.org/en/user_interface/menu/file_menu.html
- https://docs.kdenlive.org/en/project_and_asset_management/file_management/project_files.html
- https://docs.kdenlive.org/en/getting_started/introduction.html
- https://docs.kdenlive.org/en/effects_and_filters/subtitles.html
- https://github.com/mifi/lossless-cut/blob/master/README.md
- https://github.com/mifi/lossless-cut/blob/master/docs/index.md
- https://github.com/mifi/lossless-cut/blob/master/docs/troubleshooting.md
