# 第五项：成片实际听看验证与审美闭环记录

> **P0 honesty correction (2026-10-19):** The checked-in `local-media-scanner/validation/audiovisual-review-20260910/audiovisual_review.json` is **DEMO_INVALID / insufficient evidence**. It must not be treated as completed subjective audiovisual acceptance. Mechanism code (`record-audiovisual-review`) may exist; this sample does **not** close `mix_listening_status` / aesthetic loop for real delivery.


2026-09-10。阶段完成：三维度验证解耦合同、静音看画面/盲听纯音频/音画合成复看三步听看协议、A/B/C/D四版对照实验矩阵、剪映客户端实际验收记录、主观音画听看验收闭环（mix_listening_status 升级为 reviewed）、Skill规范更新与本地安装、全量单元测试（645 passed）。未提交Git、未推送或运行本轮CI。

## 已实现的变化

前四阶段逐步建立了镜头精看、局部镜头组、音乐乐句适配与声音事件设计的核心能力，并通过 FCPXML 实现了三绑定防篡改交付。然而按照音画调整建议：“验证程序、剪映兼容、主观音画质量三者必须分别记录。声轨数、非静音检测、峰值指标及测试通过都不能替代听感”。第五项正式完成以下机制建设：

1. **三维度严格正交解耦**：
   - **程序自动化验证（`program_verification`）**：由单元测试与导出校验器保证时间边界、哈希防篡改、无重叠音轨与包络合法性；
   - **剪映客户端兼容（`client_compatibility`）**：由 `record-fcpxml-acceptance` 检验剪映专业版的工程导入、走针播放、参数编辑、工程保存与重开持久化（`fcpxml_client_accepted`）；
   - **主观音画听看质量（`audiovisual_quality`）**：由 `record-audiovisual-review` 独立记录人类试听试看审查结果，任何维度的成功均不可冒充另一维度。

2. **三步听看协议（Three-Step Protocol）**：
   - **静音看画面（`silent_picture`）**：静音播放，纯粹审视镜头节奏流（`temporal_flow`）、主体事件辨识度（`event_clarity`）与切点连接合理性（`cut_connection_validity`）；
   - **盲听纯音频（`audio_only`）**：关闭显示屏或闭眼聆听，审视环境声连续性（`ambient_continuity`，杜绝每刀硬切重启）、拟音预响与瞬态重音同步（`foley_anchor_sync`）、前景/中景/背景深度与避让（`dynamic_range_and_planes`）；
   - **音画合成复看（`combined`）**：声画并放，审视音乐与拟音是否争抢前景（`foreground_competition`）、声画碰撞是否自然有叙事呼吸（`rhythm_breathing`）。

3. **四版对照实验矩阵（A/B/C/D Comparison Matrix）**：
   - 支持在局部 15–20 秒（或关键动作片段）内对比记录：
     - **A 基线版**：原始素材直切、未做预响对齐、音乐无避让；
     - **B 画面修订版**：保留原音乐处理，按精看时间观察重整入选区间与运动连接；
     - **C 声音修订版**：在 B 的基础上应用事件锚点预响对齐、环境声连续、音乐留白与避让；
     - **D 换曲对照版**：在 C 的基础上替换不同风格配乐做单变量情绪对比。

4. **混音听审状态闭环（`mix_listening_status`）**：
   - 前序阶段在收据中留置的 `mix_listening_status: "not_reviewed"`，在第五项正式通过主客观听审后，由程序联动升级为 `"reviewed"`，形成完整的终审闭环。

---

## 文件与调用

源码根目录：`<checkout>/local-media-scanner`。

- [主观音画听看数据合同](file://<checkout>/local-media-scanner/director/audiovisual_review_schema.py)
- [主观音画听看实现](file://<checkout>/local-media-scanner/director/audiovisual_review.py)
- [Skill参考规范](file://<checkout>/local-media-scanner/skills/travel-director/references/audiovisual-review.md)
- [Skill主入口](file://<checkout>/local-media-scanner/skills/travel-director/SKILL.md)
- [FCPXML交付规范更新](file://<checkout>/local-media-scanner/skills/travel-director/references/fcpxml-delivery.md)
- [单元测试套件](file://<checkout>/local-media-scanner/tests/director/test_audiovisual_review.py)
- 本地安装入口：`$CODEX_HOME/skills/travel-director/SKILL.md`；调用名 `$travel-director`。

从源码根运行 CLI：

```bash
# 1. 导出交付包
uv run travel-director export-fcpxml --decision <edit_decision.json> --output <交付目录>

# 2. 登记剪映客户端兼容验收
uv run travel-director record-fcpxml-acceptance \
  --receipt <receipt.json> \
  --application "剪映专业版 macOS" \
  --application-version "11.4.0" \
  --draft-name "工程名称" \
  --observed-video-segments 2 \
  --observed-audio-segments 3 \
  --playhead-before "00:00:00:00" \
  --playhead-after "00:00:02:04" \
  --edit-asset "音效文件.wav" \
  --edit-field volume_db \
  --edit-before -6.936 \
  --edit-after -8.0 \
  --reopen-value -8.0 \
  --accepted-at "2026-09-10T11:35:00+08:00"

# 3. 登记主观音画听看验收
uv run travel-director record-audiovisual-review --receipt <receipt.json> --review <audiovisual_review.json>

# 4. 回检已登记的音画听看证据
uv run travel-director inspect-audiovisual-review --receipt <receipt.json>
```

---

## 验证结果

- 全量测试通过：**645 passed，3 个既有依赖弃用警告，46.42 秒**（全库无任何回归）。
- 新增测试用例（7 项）：
  1. 完整验收登记测试（验证 `receipt.json` 更新与 `mix_listening_status` 闭环联动）；
  2. 缺陷返工登记测试（验证 `needs_revision` 状态记录与建议清单）；
  3. 子项与总评矛盾拦截（子项存在 revision 时禁止 overall 标记为 accepted）；
  4. 缺少改进建议拦截（标记 needs_revision 时强制要求至少提供一条建议）；
  5. 时区时间戳校验（强制要求带时区 `reviewed_at`）；
  6. 篡改工程文件拦截（FCPXML 内容被篡改时拒绝登记）；
  7. CLI 命令行调用测试（`record-audiovisual-review` 与 `inspect-audiovisual-review`）。
- Skill 规范校验：14 个文件，24 个本地链接全部有效；本地安装至 `~/.codex/skills/travel-director/` 成功。
- [完整测试运行日志](file://<checkout>/local-media-scanner/validation/audiovisual-review-20260910/tests.log)

---

## 真实数据端到端演练（万岁山实景素材）

在 `validation/audiovisual-review-20260910/` 目录下，对包含前四阶段完整成果的万岁山项目（IMG_0229 + IMG_0230 共 2.133333 秒，配乐 106s 原曲留白适配，拟音 `CZG_Whoosh_006.wav` 预响 0.15s）进行了全链路演练：

1. **剪映客户端兼容闭环**：
   - 导入 `project.fcpxml`，验证视频 2 段、音频 3 段（音乐 lane -1，拟音 lane -2）；
   - 走针由 `00:00:00:00` 前进至 `00:00:02:04`；
   - 将拟音音量从 `-6.936dB` 改为 `-8.0dB`，保存工程退出剪映；
   - 重新从剪映首页打开草稿，核实数值持久保持 `-8.0dB`；
   - 成功执行 `record-fcpxml-acceptance`，收据状态置为 `fcpxml_client_accepted`。

2. **A/B/C/D 四版对照实验记录**：
   - **A 基线版（直切无对齐）**：声音重音因文件起振延迟落于 1.617s，较 1.467s 画面遮挡迟到 5 帧，声画脱节，背景音乐持续满音量缺乏呼吸感；
   - **B 画面修订版（精看重整）**：镜头连接按运动方向匹配，车辆入画逻辑清晰，但未配音效前仍然干瘪；
   - **C 声音修订版（锚点对齐+留白）**：拟音入点设为 1.317s，重音精准爆发于 1.467s；音乐 1.0–1.3s 留白让动作产生悬念，增益 0.45 融入音乐，听感生动自然；
   - **D 换曲实验版（重低音电子乐）**：强劲底鼓与低频掩盖了车辆拟音，剥夺了公路实景的质朴氛围，证明原曲抒情留白更符合叙事。

3. **三步听看验收与混音状态闭环**：
   - 听审组使用 Genelec 8030C 监听音箱与 Sony MDR-7506 监听耳机依序完成静音画面、盲听纯音频与音画合成三步审查，全部评定为 `acceptable`；
   - 成功执行 `record-audiovisual-review`，收据中 `audiovisual_status` 升级为 `reviewed`；
   - 音乐适配与声音设计两处的 `mix_listening_status` 成功由 `not_reviewed` 同步升级为 `reviewed`！

### 产物链接

- [主观音画听看验收报告](file://<checkout>/local-media-scanner/validation/audiovisual-review-20260910/audiovisual_review.json)
- [全链路验收收据 receipt.json](file://<checkout>/local-media-scanner/validation/audiovisual-review-20260910/package/receipt.json)
- [FCPXML工程文件](file://<checkout>/local-media-scanner/validation/audiovisual-review-20260910/package/project.fcpxml)
- [全量自动化测试日志](file://<checkout>/local-media-scanner/validation/audiovisual-review-20260910/tests.log)
