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
2. **peak_cut**：`Ē` 相对 `E_p80`（含 5% 容差）且（M0 在 `onset_rate_from_beat_grid_proxy` 下能量门限即足够；否则还需 `onset_rate >=` 全曲区 P70，或 `musical_label in {chorus, drop}`，或进入该区前 4s 能量斜率显著为正）；或 M0 代理下该区为非 hook/outro 中均能最高且 ≥ `E_med`（主导中段高能）。
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


---

## 13. M0 实现说明（heuristic_v1）

- 产物：项目根 `music_edit_regions.json`（`ProjectPaths.music_edit_regions`），与 `music_structure.json` 并列；`MusicStructure` 仍为 0.1.0。状态键 `music_edit_regions` 记录在 `project_state.json`。
- 命令：`travel-director analyze-music-edit-regions --project <project_path> [--provider heuristic_v1] [--disable-hook-region] [--target-duration-seconds N]`。须先用 `--music` 冻结音乐；输出 JSON 含 `candidate_status=unconfirmed_candidates` 与 `external_call_count=0`。M0 只接受 `heuristic_v1`。
- 换曲：`--new-music-version` 生成的子项目不复制旧 `music_edit_regions.json`（作废），需在子项目重跑；同项目内再跑时结果变化则覆盖并标 `regenerated`，不变则字节不动。`source_sha256` 与冻结曲不符的文件读取时视为不存在。
- 边界：沿用现有能量 sections，各内部边界在 ±1 个能量窗内吸到最陡的能量阶跃；再切出开场 hook 窗 `[0, min(3, 0.08·duration)]` 与收尾窗（`duration ≥ 12s` 时末尾 `max(8s, 0.12·duration)`，整窗为一区）；中段短于 `min_region_seconds` 的区并入能量更接近的邻区，无法合并则标 `unknown` 并记 `short_region_unmerged`。
- `onset_rate`：M0 用 beat 网格密度（区内 beat 数 / 区长）作代理，`warnings` 恒含 `onset_rate_from_beat_grid_proxy`；真 onset 留给 M1。分位比较带 5% 相对容差。
- **CHANGE (peak_cut / beat-proxy)**：在 `onset_rate_from_beat_grid_proxy` 期间，中段（非 hook/outro）`Ē` 相对 `E_p80` 带与 onset 相同的 5% 相对容差即可单独标 `peak_cut`（不要求 beat 密度达 P70 或正进入斜率）；另将「非 hook/outro 中均能最高且 ≥ E_med」的主导高能段标为 `peak_cut`，避免点位 `E_p80` 被 outro 抬高时平坦高能中段被错标 `narrative_hold`。
- `peak_cut` 镜长均值 `max(0.5, 60/bpm)` 夹在 `[0.5, 1.4]` 内以满足不变量 4；`unknown` 的 `snap_policy` 取 `free`。
- `musical_label` 恒为 null。没有逐拍 onset 的结构（手写测试曲线）仍用 `downbeat_detector=every_fourth_beat`，并保留 `onset_rate_from_beat_grid_proxy`。`evidence_basis` 在分析器产物里为 `energy`，角色被改过则为 `manual`。全部区域只是未经听审的候选。

## 14. 镜头槽（建议，不改分区）

分析器在有真实 onset 时把 `onset_rate` 写成起音次数 / 区长，并不再写 `onset_rate_from_beat_grid_proxy`。拍点来自 librosa `beat_track(trim=False)`，并对照 `beat.plp` 的峰数。强拍默认用低频 onset 相位（`onset_phase_heuristic`）；置信度低于 0.10 时退回 `every_fourth_beat`，并写 `downbeat_phase_heuristic`。拍号按 4/4，警告 `meter_assumed_4_4`。

`shot_slots[]` 按角色模板、乐句和重音排不等长槽。每个槽有 `reason_code`、一句中文 `reason_zh`、建议镜头类型（远/细/动/脸/空/转/?）和证据引用。槽的起止就是分区的 `start` / `end`，段界上只有一条时间。

剪法存在 `shot_style`：`narrative`（叙事）、`travel`（旅拍快剪）、`event`（活动快剪）。新分析的命令行默认是 `travel`。不传风格时，规划函数仍走叙事，原来的字段保持不变，空的快剪字段不出现。镜头时间排完之后另补剪辑思路：`shot_size`、`motion`、`transition_in`、`transition_out`、`sound_cue`、`story_beat`、`content_hint`，不改 `start` / `end`，原来的 `transition` 仍留着。旅拍铺陈的常规镜按动、细、脸轮换，只改类型，不改切点。叙事槽 id 仍是 `rXX-sNN`。旅拍和活动用确定性规则 `fastcut-0.3`（`director/shot_track/fastcut.py`），时间只来自已经存下的拍点、强拍、乐句、分区边界和 onset。不调用 LLM。分区边界不动。活动铺陈的快闪比 0.2 原型少一半，所以铺陈刀/小节低于推进。可选字段：`style`、`pattern_role`、`flurry_group`、`ramp`、`transition`、`flash`、`cut_on`、`rules_version`、`beat_length`。`beat_length` 用拍（可以是半拍）；原来的整数 `beats` 不变。闪白、变速、转场是给剪辑的建议，不是素材里已经有这些画面。确认台用 `POST /api/regions-draft/shot-style` 换剪法：草稿就地保存，已确认版本只读并记下当时的剪法，从确认版切换会另开草稿。镜头块按时间贴齐，没有外边距和圆角；邻居之间是 1 像素内线，快闪是一条括号加内部发丝线。窄块上的字藏起来，悬停和局部细节条还能看到。确认台的「剪辑思路」默认收起。镜头轨标题旁边是「展开剪辑思路 / 收起」，选择记在浏览器本地。打开后在镜头轨下多出景别、转场、声音、故事四行，悬停或点镜头能看到 `content_hint`。最好的一镜标 ★，接缝要求写在该镜头上。本段怎么剪是一句动作，统计在悬停里。分区叫开场、铺陈、停留、推进、高潮、换气、收尾、待定；慢剪法叫慢叙事，不再用「叙事」同时指角色和剪法。待定角色显示「还有 N 段待定角色」，并可以直接去选角色。刀口嗒嗒声默认关。局部细节条有闪 / 变速 / 转场 / 快闪组图例。`shot-track stats` 打印每段刀数和「落点 N 刀 vs 进场前 N 刀」。

新分析先按原始分区定角色，再把存下来的 `start` / `end` 吸到格点上。不足 1 小节的移动不能把角色从 establish 改成 unknown。最近强拍在半小节（2 拍）以内就吸强拍；强拍置信度低于 0.10 且最近强拍超过半小节时，改吸 1 小节以内的最近拍点，并写 `boundary_snap_beat_low_confidence`。超过 1 小节不移动，记 `boundary_snap_beyond_bar`。相距不足半小节的强拍丢掉较晚的那个（`downbeat_cluster`），半小节或更远的保留。吸过的原始时间在 `start_raw_s` / `end_raw_s`。

确认台可以在标尺、音乐轨、分区、乐句、镜头轨上点或拖来移动播放头，空格播放或暂停。左右方向键跳到上一拍或下一拍，按住 Shift 则跳到镜头切点（没有镜头槽时跳强拍）。循环本段默认关闭。局部细节条跟随播放头，窗口大约前后 4 秒；对比旧版才显示按均长平分的那一行。

已经确认或已经存下的草稿不会被静默改写。确认时把分区、镜头轨（含 `shot_style`、`shot_rules_version`）和剪辑思路冻成快照：`shot_track_locked` 与 `guide_version`。打开已确认或历史版本只读这份快照，不再重算镜头轨。草稿仍按当前规则重算。规则版本和快照不一致时，页面只提示「有新规则，可另存新草稿」，不改确认版文件。没有快照的旧确认版保持原字节，页面提示另存新草稿；`migrate_unlocked_confirmed_regions` 会按当前规则另开草稿。确认台按当前边界重算建议，芯片写明距离和半小节阈值。采纳进新草稿；已确认文件只读。若已有打开的草稿，再从确认版采纳会 409。`export_fcpxml_for_confirmed_regions` 只读已确认快照，按 30fps 写出 FCPXML（音乐轨、每个镜头一个 gap，名字含镜头号和 `content_hint`、分区和落点 marker）和一份剪辑单。草稿不能导出。剪映 11.4.0 曾导入过带视频和音频的 FCPXML；marker、占位名和 gap 还没在剪映里验证，页面和文档都不写成已兼容。采纳或分析吸过之后，这些边界就是刀口。镜头类型仍是建议，不能拖。

确认台音乐页可以「导入 / 换音乐」：只接受本机上传的 mp3、m4a、wav（上限 100MB，时长仍不得超过 10 分钟；`--lan` 时这个接口也拒绝非本机）。它走 `create_music_version` 和 `freeze_and_analyze_music`，拍点用 `auto`（有 beat_this 且本地已有权重才用，否则 librosa），再按旅拍快剪做分区并打开新草稿。进度是建版本、拍点、分区、完成。旧项目留在磁盘上，配乐菜单可以切回去。只有 brief 和配乐、没有完整视觉阶段的项目会得到明确失败，不会另造一套版本目录。

可选依赖 `beat`（torch + beat-this，MIT）用 `File2Beats(..., dbn=False)` 出拍点和强拍。没装、没有本地权重，或运行失败时回退 librosa，并在 `beat_backend` / `beat_backend_note` 里写明。`auto` 不会为了分析去下载权重。显式 `--beat-backend beat_this` 第一次会下载 small0（约 8MB）或 final0（约 78MB）到 torch hub 缓存。不引入 madmom、Essentia、aubio、MERT、MuQ。
