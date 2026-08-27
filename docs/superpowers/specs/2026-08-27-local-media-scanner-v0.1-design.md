# Travel Edit Engine V0.1 — Local Media Scanner 设计

日期：2026-08-27  
状态：已完成会话设计确认，待书面复核后进入实施计划

## 1. 目标与结论边界

本阶段验证普通电脑能否在完整视频不离开本机的前提下，用稀疏代表帧、传统计算机视觉和本地轻量视觉编码器，把几十分钟旅游视频压缩成可供后续 AI Director 使用的结构化素材地图。

Scanner 只回答素材的客观或近客观属性：它大概是什么、技术质量如何、运动程度如何、可能属于哪些素材角色。Scanner 不决定时间线位置、音乐结构、开场、高潮、结尾或其他 Editorial Role。

V0.1 的最终结论必须逐字段给出以下三种结果之一：

- `reliable`：在本轮 Ground Truth 上达到保留标准，且未发现明显系统性失败。
- `candidate`：有价值，但准确率、样本覆盖或稳定性不足以作为确定字段。
- `not_reliable_for_v0_1`：当前本地轻量路线不够可靠，不应伪造确定输出。

30 条素材只能提供可行性信号，不能支持产品级泛化声明。缺少样本的类别必须报告 `insufficient_coverage`。

## 2. 明确不做

V0.1 不开发正式 GUI、Web App、账号系统、云数据库、视频上传、自动剪辑、AI Director、Editing Grammar、音乐生成、音乐分析、SFX、剪映/FCPXML 导出、真实素材 Timeline、自动转场、调色、字幕或精确 Moment Detection。

即梦 CLI 已作为未来音乐与音效阶段的优先提供方安装，但不属于 Scanner V0.1 的运行依赖。V0.1 不登录即梦、不调用生成任务、不消耗积分。后续接入前必须从实际 CLI 验证音乐和独立 SFX 能力，不能根据产品设想推断命令已经存在。

## 3. 当前验证环境与数据

开发机：

- MacBook Pro 2021，Apple M1 Pro，10 核 CPU，16 GB 统一内存。
- macOS 26.6.2，arm64。
- FFmpeg/ffprobe 8.1.1，启用 VideoToolbox。
- 系统 Python 3.14.4；项目使用 `uv` 管理 Python 3.12，不修改系统 Python。
- PyTorch 推理后端：`auto` 优先 MPS，失败时显式记录原因并回退 CPU；也可强制 `cpu` 或 `mps`。

真实素材目录只读使用：`/Users/meimaodawang/Desktop/万岁山素材/`。

只读盘点结果：

- 272 条视频、1 张 JPG。
- 视频总时长约 2811.14 秒（46.85 分钟）。
- 视频总大小约 20.33 GB（`du` 约 19 GiB）。
- 269 MOV、3 MP4；270 条 HEVC、2 条 H.264。
- 260 条 3840×2160、10 条 1920×1080、1 条 1280×720、1 条 720×1280。
- 时长中位数约 6.07 秒；24 条短于 3 秒，19 条长于 30 秒；最长约 117.76 秒。

原素材不得移动、重命名、修改、转码覆盖或上传。所有缓存、缩略图和结果写入项目目录下的可忽略运行目录。

## 4. 总体数据流

```text
只读视频目录
  -> ffprobe metadata
  -> 低分辨率 probe-frame 扫描
       -> 亮度/曝光/模糊候选
       -> 光流运动候选
       -> 颜色直方图场景变化候选
  -> 稀疏代表帧选择（通常 3–5 张）
  -> 传统 CV 指标
  -> 轻量 COCO 检测器
  -> SigLIP2 零样本分类/相似度
  -> 视频级融合与不确定性
  -> Material Role 候选规则
  -> scanner_result.json
  -> Ground Truth 逐字段评估
  -> validation_report.html / BENCHMARK.md
```

模块之间只传递有版本的结构化对象。任何模型失败均不得用默认标签填充。

## 5. 项目结构

```text
local-media-scanner/
  README.md
  pyproject.toml
  uv.lock
  scanner/
    __init__.py
    cli.py
    config.py
    schema.py
    cache.py
    metadata.py
    sampling.py
    cv_metrics.py
    selection.py
    detector.py
    vision.py
    fusion.py
    roles.py
    pipeline.py
    telemetry.py
    evaluation.py
    report.py
  tests/
    test_metadata.py
    test_sampling.py
    test_cv_metrics.py
    test_fusion.py
    test_roles.py
    test_schema.py
    test_report.py
  benchmark/
    annotation_guide.md
    test_manifest.json
    ground_truth.json
    runs/
  ground_truth.json
  scanner_result.json
  validation_report.html
  EXPERIMENTS.md
  BENCHMARK.md
```

根目录的三个结果文件是最新已验证运行的便捷副本；带参数、环境和完整遥测的不可变运行记录保存在 `benchmark/runs/<run-id>/`。代表帧和缓存默认不提交 Git，以避免把私人素材画面纳入版本历史。

## 6. CLI 边界

首版只提供开发者 CLI：

```bash
uv run travel-scanner inspect --input /absolute/video/folder
uv run travel-scanner select-testset --input /absolute/video/folder --count 30
uv run travel-scanner scan --manifest benchmark/test_manifest.json --device auto
uv run travel-scanner evaluate --ground-truth ground_truth.json --result scanner_result.json
uv run travel-scanner report --ground-truth ground_truth.json --result scanner_result.json
uv run travel-scanner benchmark --manifest benchmark/test_manifest.json --device auto
```

`scan` 接受目录或 manifest，但真实准确率实验必须使用冻结的 manifest。`--device auto|cpu|mps|cuda` 为稳定公共参数；V0.1 在当前 Mac 上只验证 CPU 与 MPS，CUDA 仅保留设备选择接口和清晰的未验证状态。

## 7. 代表帧算法

### 7.1 Probe frames

每条视频先用 FFmpeg 解码最长边 320 px 的低分辨率 probe frames。短片最多取 16 张，长片最多取 24 张，按全时长均匀分布。它们只用于便宜的 CV 统计，不进入大型视觉模型。

抽样数量使用：

```text
probe_count = clamp(ceil(duration_seconds * 2), 6, 24)
```

不足 1 秒的视频按可解码帧数降级，不强制得到 6 个不同时间点。

### 7.2 Candidate selection

基础候选固定为时长的 20%、50%、80%。额外候选来自：

- 相邻 probe frame 的稠密光流强度峰值：`motion`。
- HSV 颜色直方图距离峰值：`scene_change`。

候选按时间接近程度和缩略图感知哈希去重。最小时间间隔为 `max(0.25 秒, duration * 0.08)`。正常视频保留 3–5 张；极短视频允许 1–2 张。候选合并时将原 Schema 的单值 `reason` 改为 `reasons` 数组，以保留同一帧同时满足 temporal、motion 或 scene_change 的证据。

Experiment 02 必须比较：

- 三张固定 temporal baseline。
- temporal + motion。
- temporal + motion + scene change。

仅当自适应方案对字段准确率或失败案例有实际改善时保留其复杂度。

## 8. 传统 CV 字段

### 8.1 画质

- `laplacian_variance_raw`：灰度图 Laplacian 方差，保留原始量供校准。
- `blur_score`：0 表示清晰、1 表示严重模糊；只能在 Ground Truth 上确定映射后输出，否则为 `null`。
- `brightness_score`：线性化近似后的平均亮度，归一化到 0–1。
- `dark_pixel_ratio`、`bright_pixel_ratio`：暗部和高光裁切比例。
- `exposure_status`：`underexposed|normal|overexposed|mixed|unknown`。
- `quality_score`：高分表示整体更可用；本轮未验证组合权重前为 `null`，不能随意平均几个指标。

### 8.2 运动

probe frames 在相邻时间间隔上计算 Farneback 光流，按图像对角线和时间归一化。保留中位数与高分位原始量，随后在 Ground Truth 上确定 `low|medium|high` 阈值。

运动表示画面变化强度，不区分主体运动、相机移动或抖动。V0.1 不把高运动自动解释成有价值动作。

## 9. 本地模型

### 9.1 人物与基础物体检测

首个基线使用 Torchvision `ssdlite320_mobilenet_v3_large` 的 COCO 预训练权重：

- 负责 `people_present`、`people_count_estimate` 和有限的 `main_objects`。
- 默认在 CPU 上运行，避免检测 NMS 等算子在 MPS 上的兼容性干扰主实验。
- 人数按每张代表帧检测结果聚合，同时保留 `min/median/max` 证据；Experiment 04 比较最大值、中位数和高置信单帧策略。
- COCO 只有 `person`，不能直接判断 child/adult。年龄类型由人物裁剪后的 SigLIP2 实验提供，默认视为候选字段。

如果 SSDLite 在真实素材上漏检明显，Experiment 04 可以加入一个更强但许可清晰的检测器作为对照；替换模型必须记录体量、许可、耗时和收益，不能静默改变基线。

### 9.2 SigLIP2

首个基线模型为 `google/siglip2-base-patch16-224`：

- 用于 `scene_type`、非 COCO 语义对象、人物年龄候选、Shot Scale 候选和视觉 embedding。
- 使用英文模板集合而不是单一提示词；同类提示分数先聚合，再跨帧聚合。
- 保留 top-k 分数、第一二名 margin、使用的 prompts 和模型版本。
- 模型相似度不是校准后的概率。Schema 中的 `confidence` 必须附带 `source`，报告不得把 0.8 相似度写成“80% 正确概率”。

首轮只下载这一套视觉模型。MobileCLIP2 仅在 SigLIP2 性能不可接受或需要轻量对照时进入后续实验。

## 10. Scene Type 与对象

`scene_type` 固定为：

```text
nature, city, building, indoor, theme_park,
food_dining, transportation, night_scene, other
```

具体建筑、游乐设施、食物、招牌、车辆或纪念品进入 `main_objects`，不扩张 Scene Type。

零样本分类必须包含负面和近邻提示，避免把“古建筑景区”仅因存在建筑误归为普通 building。若一条视频跨场景且代表帧无法形成稳定多数，输出 top candidates 和低置信状态，而不是强制单标签。

## 11. Shot Scale 重点实验

输出类保持：`wide|medium|close|close_up|aerial`。

人工标注指南使用视觉占比和叙事主体定义：

- `wide`：环境明显主导，人物或核心物体较小。
- `medium`：主体清晰且仍保留充分环境上下文；人物通常约半身到全身。
- `close`：主体占画面主要区域；人物通常是胸部以上或等价物体近景。
- `close_up`：脸、手、食物、票据或其他局部细节主导画面。
- `aerial`：明显的高空俯瞰视角；不能仅凭 wide 推断。

Experiment 05 对比三种方法：

1. SigLIP2 纯零样本。
2. 人物检测框高度/面积与环境占比启发式；只适用于人物主导画面。
3. 两者融合；无人物画面回退 SigLIP2 并降低证据等级。

`close` 与 `close_up`、无人物景别和 `aerial` 是预期高风险项。某一类在 30 条中少于 5 个有效样本时，不给出该类可靠性结论。

## 12. Video-level Fusion

每个字段聚合时保留：

- 每帧预测与原始分数。
- 跨帧一致率。
- top-1/top-2 margin。
- 使用的证据源。
- 冲突原因。

融合原则：

- 技术字段不经过模型。
- 人物存在优先检测器；SigLIP2 只能补充候选，不覆盖高置信检测结果。
- Scene Type 使用跨帧稳健聚合；单张异常帧不能支配视频标签。
- Shot Scale 在人物画面优先使用几何证据和视觉语义融合。
- 低一致率、低 margin 或输入帧不足时降低 `confidence`，必要时输出 `null`。

## 13. Material Role 候选

六类保持：`human_story|environment|experience|detail|transition|atmosphere`。

它们由可解释规则生成，不训练新的“编辑决策模型”：

- `human_story`：稳定人物证据，加人物主导景别、互动或行动候选。
- `environment`：wide 或环境主导，并有有效场景类型。
- `experience`：人物/交通/餐饮/游乐等实际行为证据；单有场景名不足以确认。
- `detail`：close/close_up 与可识别局部物体证据。
- `transition`：只输出 candidate；需要明显遮挡、甩镜、推门或 POV 等运动模式证据。
- `atmosphere`：环境主导、低至中运动、自然/夜景/灯光等氛围证据。

每条候选必须列出触发规则和输入字段。Material Role 可以多选；不得映射成 opening、climax、ending 等 Editorial Role。

## 14. Schema V0.1

```json
{
  "schema_version": "0.1.0",
  "file": "IMG_038.MOV",
  "source": {
    "relative_path": "IMG_038.MOV",
    "size_bytes": 123456789,
    "mtime_ns": 0
  },
  "analysis_status": "complete",
  "technical": {
    "duration": 8.2,
    "width": 3840,
    "height": 2160,
    "fps": 30.0,
    "orientation": "landscape",
    "codec": "hevc",
    "creation_time": "2026-02-07T03:10:05Z"
  },
  "quality": {
    "laplacian_variance_raw": 120.5,
    "blur_score": null,
    "brightness_score": 0.72,
    "dark_pixel_ratio": 0.02,
    "bright_pixel_ratio": 0.01,
    "exposure_status": "normal",
    "quality_score": null
  },
  "motion": {
    "motion_intensity_raw": 0.031,
    "motion_intensity": 0.78,
    "motion_level": "high",
    "static_or_dynamic": "dynamic"
  },
  "content": {
    "people_present": true,
    "people_count_estimate": 2,
    "people_type": ["child", "adult"],
    "scene_type": "theme_park",
    "scene_type_candidates": [],
    "main_objects": ["person", "building"],
    "simple_action": "walking"
  },
  "shot_scale": "wide",
  "material_role_candidates": ["human_story", "environment"],
  "material_role_evidence": {
    "human_story": {
      "score": 0.81,
      "rules": ["people_present", "people_dominant_scale"],
      "inputs": ["content.people_present", "shot_scale"]
    },
    "environment": {
      "score": 0.76,
      "rules": ["wide_environment"],
      "inputs": ["content.scene_type", "shot_scale"]
    }
  },
  "representative_frames": [
    {
      "timestamp": 1.6,
      "reasons": ["temporal"],
      "thumbnail_relpath": "frames/IMG_038/001600.jpg"
    }
  ],
  "confidence": {
    "people_present": {"score": 0.92, "source": "detector"},
    "shot_scale": {"score": 0.55, "source": "fusion"}
  },
  "field_status": {
    "people_present": "predicted",
    "shot_scale": "candidate"
  },
  "timings_ms": {
    "metadata": 21,
    "frame_scan": 340,
    "cv": 84,
    "detector": 190,
    "vision_model": 490,
    "fusion": 8,
    "total": 1133
  },
  "errors": []
}
```

### 14.1 Schema 修改记录

- 增加 `schema_version`，便于实验间比较。
- 增加 `source`，支持缓存失效和输入审计；不暴露绝对路径到可分享结果。
- 增加 `analysis_status` 与 `errors`，避免失败文件消失。
- `representative_frames.reason` 改为 `reasons` 数组，保留合并候选的多重依据。
- 增加原始 CV 指标，防止归一化分数掩盖阈值变化。
- 增加字段级 `confidence`、`field_status` 和 `timings_ms`。单条视频的 `field_status` 只表示 `predicted|candidate|abstained|unavailable`，不能冒充跨测试集可靠性。
- 保留字符串形式的 `material_role_candidates` 供 Director 简单消费，同时增加 `material_role_evidence`，使每个候选可追溯到规则和输入字段。
- `reliable|candidate|not_reliable_for_v0_1|insufficient_coverage` 属于 Ground Truth 评估后的全局字段结论，只写入评估汇总、HTML 顶部和 `BENCHMARK.md`，不重复写进原始 Scanner 素材卡片。
- 不可靠字段允许 `null`；示例值不代表本轮模型已经达到对应准确率。

## 15. 30 条测试集与 Ground Truth

### 15.1 选择

先为 272 条视频生成一张本地联系表，仅用于人工选样。选择兼顾：

- 三个拍摄日期与不同时间段。
- 竖屏/横屏、1080p/4K、极短/常规/长视频。
- 元数据与 CV 预扫描提示的低光、高光、模糊、静态和高运动。
- 人物有无、人数、儿童/成人、不同场景、不同景别和候选素材角色。
- 明显重复或相邻拍摄片段。

不能保证素材池包含航拍、食物或全部角色；未发现的类别保持缺失，不用网络视频或合成画面冒充真实测试准确率。

### 15.2 标注隔离

Ground Truth 必须在运行视觉模型前冻结并提交。人工标注可以观看整条短视频，而 Scanner 仍只看稀疏帧。争议项使用 `uncertain`，评估时单独统计或排除，不强制选择。

Ground Truth 包含字段值、标注置信度、可选备注和标注时间，不包含模型输出。

## 16. 逐字段指标

- `people_present`：Precision、Recall、F1、Accuracy。
- `people_count_estimate`：精确命中率、±1 命中率、MAE。
- `people_type`：每标签 Precision/Recall/F1 与 Micro/Macro F1。
- `scene_type`：Accuracy、Macro F1、混淆矩阵、coverage。
- `shot_scale`：Accuracy、Macro F1、逐类召回、混淆矩阵。
- `motion_level`、`exposure_status`：Accuracy、Macro F1、混淆矩阵；同时保留连续原始分数分布。
- `quality`：人工等级与原始分数的排序一致性、阈值分类结果。
- `main_objects`、`material_role_candidates`：Micro/Macro F1、Jaccard、每标签 coverage。
- `simple_action`：只在标签样本足够时评估；否则 `insufficient_coverage`。

保留标准不是单一总体 Accuracy：字段 Macro F1/任务适配指标达到 0.80、关键类至少 5 个有效样本、并且无明显系统性失败时可标为 `reliable`；0.65–0.79 或覆盖不足时为 `candidate`；低于 0.65、跨参数不稳定或语义不成立时为 `not_reliable_for_v0_1`。阈值是 V0.1 决策门槛，不是统计学上的产品保证。

## 17. 性能与资源遥测

每次 benchmark 记录：

- 视频数量、总时长、总字节数。
- Metadata、probe scan、抽帧、CV、检测器、视觉模型、融合、报告和总耗时。
- 平均每条视频耗时、平均每分钟原始素材耗时。
- 冷启动模型加载和预热后推理分开记录。
- 进程 CPU 时间、系统/进程 CPU 采样、峰值 RSS、系统 RAM。
- 设备型号、Chip、总内存、操作系统、Python、FFmpeg、PyTorch、模型版本。
- MPS 是否请求、是否可用、是否实际使用及回退原因。

Apple Silicon 为统一内存架构，`VRAM` 输出 `not_applicable_shared_memory`。PyTorch 能提供的 MPS 分配内存单独记录。无 root 权限无法可靠取得 GPU 利用率时输出 `unavailable`，不估算伪值。

100 条耗时先由 30 条 warm benchmark 按素材分钟与文件数双变量外推；路线稳定后，可从同一素材池选择 100 条做一次无人工标注的真实吞吐验证。模型下载时间作为安装成本单列，不计入本地扫描耗时。

## 18. HTML Validation Report

报告为静态 HTML，无服务器、无复杂前端。每条卡片展示：

- 文件名、代表帧缩略图和时间点。
- Duration、People、Scene、Shot Scale、Motion、Material Role、Quality。
- 字段置信度、证据来源和单条预测状态；页面顶部另列 Benchmark 得出的全局字段可靠性。
- Ground Truth、预测值、匹配/不匹配/不评估标记。
- 错误或回退信息。

页面顶部展示逐字段指标、运行环境、耗时拆分和失败文件数。缩略图使用相对路径；不嵌入完整视频或 base64 大文件。

## 19. 错误与缓存

- 单文件 ffprobe、解码或模型失败不终止整批运行。
- 失败项输出 `analysis_status: failed|partial`、阶段、错误码和简短信息。
- MPS 回退必须写入结果和 BENCHMARK，不允许静默发生。
- 缓存键包含相对路径、文件大小、mtime ns、采样配置、模型 ID、模型 revision 和 Schema 版本。
- 配置或模型变化后生成新运行目录，不覆盖历史 benchmark。
- 输入绝对路径只保留在本机运行 manifest；可分享 JSON 使用相对路径。

## 20. 测试策略

实施使用测试驱动开发：

- 使用 FFmpeg 在测试临时目录生成极短、横屏、竖屏、黑场、白场、静止和运动合成视频，验证元数据、抽帧、异常处理与分数方向。
- 使用合成图像验证 blur、exposure 和 motion 的单调性，不用合成数据声称真实准确率。
- detector/vision 使用小型固定图片夹具或 mock 验证接口、聚合与失败回退；真实模型准确率只由 30 条 benchmark 给出。
- Schema 使用 JSON Schema/Pydantic 验证 nullability、枚举和版本。
- HTML 测试验证所有素材卡片、转义、相对缩略图和错误状态。
- 每个 Experiment 在前一阶段留下可复现结果后再进入下一阶段。

## 21. 实验门禁

1. **Experiment 01 — Metadata**：所有可读文件元数据正确；坏文件能隔离失败。
2. **Experiment 02 — Sparse Sampling**：三帧基线与自适应方案均可复现，并统计额外成本。
3. **Experiment 03 — Blur/Exposure/Motion**：合成单调性通过，真实样本阈值有人工对照。
4. **Experiment 04 — Detection/SigLIP2**：CPU/MPS 路径、模型缓存、逐帧原始输出和耗时可审计。
5. **Experiment 05 — Shot Scale**：完成三种方案逐类比较；不足类别明确退出结论。
6. **Experiment 06 — Material Role**：每条候选可追溯到输入证据，不能包含 Editorial Role。
7. **Experiment 07 — 30-video Benchmark**：Ground Truth 冻结，逐字段指标和 HTML 可复现。
8. **Experiment 08 — 100-video Estimate**：提供线性外推，并在成本允许时用 100 条真实吞吐运行校验。

每个实验在 `EXPERIMENTS.md` 记录方法、模型、参数、耗时、准确情况、失败案例、保留结论和下一步。

## 22. 最终验收回答

`BENCHMARK.md` 必须明确回答：

1. 100 条 10–30 秒旅游视频的本地扫描耗时区间及推导依据。
2. M1 Pro MPS、M1 Pro CPU 是否可接受；独立 GPU 是否必需。
3. 三张固定帧和自适应 3–5 张对“这条视频大概是什么”的差异。
4. 每个 Schema 字段的独立可靠性、样本覆盖与失败模式。
5. 哪些字段由传统 CV、检测器、SigLIP2 或规则完成。
6. 哪些字段明确不够可靠，原因和未来替代方向。
7. Local Media Scanner 路线是否值得继续，以及继续的最小下一步。

完成标准是得到证据支持的可行/不可行结论，不是把所有字段填满。

## 23. 参考实现来源

- FFmpeg/ffprobe：https://ffmpeg.org/documentation.html
- PyTorch MPS：https://docs.pytorch.org/docs/stable/notes/mps.html
- Torchvision SSDLite：https://pytorch.org/vision/stable/models/ssdlite.html
- Hugging Face SigLIP2：https://huggingface.co/docs/transformers/model_doc/siglip2
- Apple MobileCLIP2（候选对照）：https://github.com/apple/ml-mobileclip
