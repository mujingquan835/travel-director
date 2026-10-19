# music_edit_regions 技能合同草案 v0.1

状态：草案 v0.1.1（已定 hook 默认开；交 M0 实现）。作者视角：短视频剪辑 + 对照 travel-director 现有 `MusicStructure` / `TimelineConfig`。
目标：给定冻结曲，产出「剪辑区域」候选；不自动改片、不替代听审确认。

---

## 1. 一句话

把一条音乐划成连续区域，每区带可测的 `edit_role`（快剪 / 叙事 / 收尾等）、镜长预算、贴拍策略与证据。下游时间线优先读本合同；没有本文件时回退现有 `MusicStructure.sections.role`。

---

## 2. 非目标

- 不选片、不填槽、不导出 FCPXML。
- 不声称已确认乐句或下拍（除非 `downbeat_detector` 为真检测器且 confidence 达标）。
- 不调用需付费或默认开启的外部 API；可选本地模型（all-in-one / beat_this）须显式 `provider` 且可关闭。
- 不伪造听审或 LUFS。

---

## 3. 与现有产物关系

| 现有 | 关系 |
|------|------|
| `MusicStructure`（schema 0.1.0） | 保留。其中 `role`（intro/rise/breath/climax/outro/unknown）视为 **musical_proxy**，由能量启发式产生。 |
| `downbeats_seconds = beat_times[::4]` | 本技能若启用 `beat_this` / `allin1`，写入新区文件的 `downbeats_seconds`，并标 `downbeat_detector`；旧字段行为不变直到迁移。 |
| `TimelineSlot.section_role` | 读新区时写入 **mapped** 旧角色（见 §7），或新增可选字段 `edit_role`（实现阶段再定，合同先要求映射表）。 |
| `music_adaptation.automatic_hints` | 追加 `edit_region_candidates`，一律标 `unconfirmed_candidates`。 |

新文件建议路径（项目内）：`paths.music_edit_regions` → `music_edit_regions.json`，与 `source_sha256` 绑定。

---

## 4. 输入

- `audio_path`：本地 WAV / MP3 / M4A（与现分析一致）
- `source_sha256`：冻结曲哈希（必须与项目音乐版本一致）
- `target_duration_seconds`（可选）：只分析 / 裁切到成片窗
- `provider`：`heuristic_v1`（默认，纯现有 librosa 能量）| `allin1` | `beat_this+heuristic` | `hybrid`（结构模型 + 启发式角色）
- `enable_hook_region`：bool，默认 **true**（所有片种默认开开场 hook；仅当用户/Brief 明确关闭时为 false）
- `min_region_seconds`：默认 4.0（短于则与邻区合并，除非 provider 给出 chorus/drop 边界）
- `energy_window_seconds`：默认 1.0（对齐现配置）

---

## 5. 输出 schema（逻辑字段）

```text
MusicEditRegions
  schema_version: "0.1.0"
  source_sha256: str
  duration_seconds: float > 0
  bpm: float | null
  provider: str
  beats_seconds: float[]
  downbeats_seconds: float[]
  downbeat_detector: "every_fourth_beat" | "beat_this" | "allin1" | "unknown"
  energy_curve: { time_seconds, value }[]   # value in [0,1]
  regions: MusicEditRegion[]                # 连续覆盖 [0, duration]
  ending: { last_onset_seconds, behavior }  # 复用 MusicEnding
  confidence: float in [0,1]                # 文档级
  warnings: str[]
  errors: []                                # 同现有 ProviderError 形状

MusicEditRegion
  region_id: str                            # 如 "r01"
  start: float >= 0
  end: float > start
  edit_role: EditRole
  musical_label: MusicalLabel | null        # 来自结构模型；启发式可为 null
  musical_proxy: "intro"|"rise"|"breath"|"climax"|"outro"|"unknown"  # 兼容旧时间线
  mean_energy: float in [0,1]
  onset_rate: float >= 0                    # onset 数 / 区长（每秒）
  energy_slope: float                       # 区后半均能 − 区前半均能（归一能量）
  suggested_shot_mean_s: float > 0
  shot_min_s: float > 0
  shot_max_s: float > shot_min_s
  snap_policy: "downbeat" | "beat" | "free"
  desired_motion: "low" | "medium" | "high"
  content_need: str                         # 短标签，见 §7
  confidence: float in [0,1]
  evidence_basis: "energy" | "structure_model" | "hybrid" | "manual"
```

### EditRole（剪辑意图，少而硬）

- `hook`：开场抢注意（默认开启）
- `establish`：立地 / 立人，信息可读
- `narrative_hold`：叙事 / 风光 / 情绪铺陈
- `build`：推进、加速感
- `peak_cut`：高潮快剪
- `breath`：喘息 / 留白
- `settle_outro`：收尾沉降
- `unknown`：证据不足

### MusicalLabel（可选，结构模型）

`intro` | `verse` | `chorus` | `bridge` | `drop` | `outro` | `other` | `unknown`

---

## 6. 区域不变量（程序校验必过）

1. `regions` 非空；`regions[0].start == 0`（容差 1 ms）。
2. 相邻区首尾相接（容差 1 ms）；最后一区 `end == duration_seconds`。
3. 区不重叠；无负长度。
4. 每区 `shot_min_s <= suggested_shot_mean_s <= shot_max_s`。
5. `peak_cut` 与 `breath` 不得时间重叠（边界冲突时：outro 窗优先 settle；否则能量高者取 peak，低者取 breath）。
6. 若 `duration >= 12s`，必须存在覆盖最后 `max(8s, 0.12 * duration)` 的区，且其中至少一区 `edit_role == settle_outro` 或 `musical_label == outro` 或 `musical_proxy == outro`（启发式失败则 `warnings` 含 `missing_settle_outro` 且该窗标 `unknown`，不得假装 settle）。
7. 同一 `source_sha256` + 同一 `provider` + 同一配置 → 两次运行区域边界与 `edit_role` 字节级稳定（浮点四舍五入到 1e-3 s）。

---

## 7. 默认镜长、运动、content_need、旧角色映射

单位：秒。实现可做成 `EditRegionConfig`，以下为合同默认。

- `hook`：mean 0.9，min 0.6，max 1.2；motion high；content_need `attention_hook`；proxy `intro`
- `establish`：mean 3.2，min 2.5，max 4.0；motion low；`orientation_detail`；proxy `intro`
- `narrative_hold`：mean 4.0，min 3.0，max 5.5；motion low；`scenic_or_story`；proxy `rise` 或 `unknown`（中段）
- `build`：mean 2.0，min 1.5，max 2.5；motion medium；`forward_motion`；proxy `rise`
- `peak_cut`：mean `max(0.5, 60/bpm)`（bpm 缺失则 1.0）；min 0.5，max 1.4；motion high；`high_visual_impact`；proxy `climax`
- `breath`：mean 4.5，min 3.5，max 6.0；motion low；`reflective_pause`；proxy `breath`
- `settle_outro`：mean 3.5，min 2.5，max 4.5；motion low；`closing_image`；proxy `outro`
- `unknown`：mean 3.0，min 1.5，max 5.0；motion medium；`unspecified`；proxy `unknown`

`snap_policy` 默认：

- `peak_cut` / `hook` / `build` → `beat`（若 downbeat_detector 非 every_fourth_beat 且 conf≥0.7 则 `downbeat`）
- `establish` / `narrative_hold` / `breath` / `settle_outro` → `free`（区边界仍建议吸到最近 beat，镜头内不强制）

---

## 8. 角色判定启发式（heuristic_v1 / hybrid 的角色层）

设全曲能量归一到 [0,1]；`E_med` / `E_p80` / `E_p20` 为全曲能量点的中位数与分位；区长 `L`；区均能 `Ē`；`onset_rate`；`slope` = 后半均能 − 前半均能。
outro 窗 = 末尾 `max(8s, 0.12 * duration)`。

判定顺序（先匹配先得，除非注明覆盖）：

1. **settle_outro**：落在 outro 窗，且（`Ē <= E_med` 或 `ending.behavior in {decay, fade}` 或 `musical_label == outro`）。覆盖同窗的 peak。
2. **peak_cut**：`Ē >= E_p80` 且（`onset_rate >=` 全曲区 onset_rate 的 P70，或 `musical_label in {chorus, drop}`，或进入该区前 4s 的能量斜率显著为正）。
3. **breath**：`Ē <= E_med * 0.45`（对齐现 `breath_energy_ratio`）且不在已判 settle 的窗。
4. **build**：`slope > 0.08` 且未判 peak；或 `musical_label` 暗示过渡（若有 pre-chorus 则用）。
5. **hook**（`enable_hook_region` 默认 true）：`[0, min(3, 0.08*duration)]`；若开场 onset 密或能量已高则 `edit_role=hook`，否则仍划出该窗但降为 `establish` 并 `warnings` 记 `hook_window_soft`。
6. **establish**：首个未判 hook 的稳定区，或 `start≈0` 的首区。
7. **narrative_hold**：其余中能量、`|slope|` 低、onset_rate ≤ 全曲 P50。
8. **unknown**：证据冲突或 `L < min_region_seconds` 合并失败。

`hybrid`：边界优先用结构模型；`edit_role` 仍跑以上规则，但 chorus/drop 强制至少 `build` 或 `peak_cut`（由 `Ē` 相对 E_med 决定）。

---

## 9. Runner / CLI 挂载（实现时）

- 命令建议：`travel-director analyze-music-edit-regions --project ... [--provider heuristic_v1]`
- 时机：音乐冻结并完成现有 `analyze_music` 之后；换曲（`--new-music-version`）必须重跑并作废旧 `music_edit_regions.json`。
- `build-timeline`：若存在有效新区文件且 sha 匹配，用 `musical_proxy`（或未来的 `edit_role`）驱动 `mean_for` / `desired_motion` / `content_need`；否则行为与今日完全一致。
- 精剪支线：`music_adaptation` 只把新区当 `unconfirmed_candidates`；`local_fast_cut` 仍要画面证据。

---

## 10. 验收（三类分开记）

### A. 程序校验（CI / pytest）

- 不变量 §6 全过。
- 固定夹具 wav + 固定 config：两次 JSON 在 round(1e-3) 后一致。
- 构造能量曲：高能量密 onset 区 → `peak_cut`；低能量区 → `breath`；尾窗衰减 → `settle_outro`。
- `peak_cut.suggested_shot_mean_s < narrative_hold.suggested_shot_mean_s`（同 bpm 夹具）。
- provider=`heuristic_v1` 时 `external_call_count == 0`。

### B. 剪映 / 工程兼容

本技能不直接导出；不测 FCPXML。若时间线消费新区，只测「槽位疏密变化可复现」，不测成片观感。

### C. 主观听看（人， downstream）

- 挑 1 首冻结旅行曲（30–60s 成片窗）：人先盲标区域角色（不看模型输出），再对比模型；记录一致率，不把人标写进 CI 绿勾。
- 禁止用演示 JSON 冒充已完成审美闭环。

---

## 11. 实现分期建议

- **M0（合同落地）**：本文件进 `skills/travel-director/references/music-edit-regions.md`；schema + 纯启发式从现有 sections 映射出 `edit_role`（可先规则翻译 intro→establish 等）+ 单测。
- **M1**：真 `onset_rate` / `energy_slope` 写入；timeline 可选读新区。
- **M2**：可选 `beat_this` downbeat；可选 `allin1` musical_label（默认关）。
- **M3**：与选片 `clip_worthiness` / 六类镜头职能对齐（另合同）。

---

## 12. 已定决策（2026-10-19）

1. **hook**：所有片种默认开启（`enable_hook_region=true`）。
2. **AGPL**：只学密度表与契约，禁止拷贝 BeatSync-Engine 代码。
3. **产物形态**：并列 `music_edit_regions.json`，不升 `MusicStructure` 大版本；旧 `sections.role` 仍作 fallback。
4. **实现**：M0 交骑兵1号（schema + references 文档 + 启发式映射 + 单测）；M1+ 另议。

