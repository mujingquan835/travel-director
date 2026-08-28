# Local Media Scanner V0.1 Benchmark Conclusion

结论日期：2026-08-28
结论：**Continue with constraints（继续，但必须保留弃权和字段边界）**

Local Media Scanner 的本地处理路线可继续：在 M1 Pro 上，稀疏抽帧、传统 CV、SSDLite、SigLIP2、证据融合、不可变运行记录、字段级评估、静态报告和资源遥测均已跑通。它目前适合生成“可审计的素材证据”，不适合把大多数语义字段当作确定事实，更不能直接承担 AI Director、时间线、音乐或剪辑决策。

本结论只基于冻结的 30 条 Ground Truth、已保存的 30 条分阶段实验和两次三视频端到端运行。没有执行新的 30 条组合矩阵或 100 条全管线运行；所有 100 条结果都明确标为外推。

## 1. 数据与运行边界

- 原始盘点：272 条视频，46.85 分钟，20.33 GB。
- 冻结评估集：30 条视频，7.94 分钟，2.98 GB，平均每条 15.88 秒。
- 环境：MacBook Pro 2021、M1 Pro 10 核、16 GB 统一内存、macOS 26.6.2 arm64、Python 3.12.13、FFmpeg 8.1.1。
- 本地模型：Torchvision SSDLite COCO V1；SigLIP2 固定 revision `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`。
- 隐私边界：视频不上传；运行结果使用相对素材路径；缩略图和完整运行目录默认不进入 Git；Scanner 未调用或登录 Dreamina，也未消耗积分。
- 统计边界：30 条只能给出可行性信号；同一数据集没有被反复调参后包装成独立泛化结果。

## 2. Q1 — 100 条 10–30 秒视频需要多久

**建议规划区间：约 10–20 分钟，另加约 4–6 秒暖缓存模型加载。该数字是外推，不是 100 条实测。**

| 已测运行 | 视频/素材时长 | 扫描时间 | 折算 |
|---|---:|---:|---:|
| 30 条 Detector | 30 / 476.33 秒 | 180.57 秒 | 6.02 秒/条；22.75 秒/素材分钟 |
| 30 条 SigLIP2 MPS | 30 / 476.33 秒 | 170.86 秒 | 5.70 秒/条；21.52 秒/素材分钟 |
| 端到端共享抽帧热运行 | 3 / 27.19 秒 | 23.08 秒 | 7.69 秒/条；样本过小，仅作保守上界证据 |

推导方式：

- 按 30 条测试集的平均长度 15.88 秒和每文件速率外推，100 条约 9.5–12.8 分钟。
- 如果 100 条都接近 30 秒，按 30 条运行的素材分钟速率外推约 17.9–19.0 分钟。
- 因此对 10–30 秒混合素材给出取整后的 10–20 分钟规划区间。
- 模型首次下载不计入扫描耗时；SigLIP2 权重约 1.50 GB，首次安装/下载必须单列。

影响总耗时的首要因素是 4K HEVC 稀疏 seek 和 FFmpeg 进程启动，不是模型推理。最长 117.76 秒素材即使使用 VideoToolbox 仍明显慢于普通短片，因此不能把每条耗时视为常数。

## 3. Q2 — CPU、MPS 和独立 GPU

- **M1 Pro MPS：可接受。** 30 条 SigLIP2 运行总计 170.86 秒，模型推理只有 6.16 秒；完整流程受解码限制。
- **M1 Pro CPU：也可接受。** 五视频对照中，CPU/MPS 总耗时分别为 30.32/30.73 秒；MPS 推理更快（1.89 秒对 2.73 秒），但没有形成端到端优势。
- **独立 GPU：V0.1 不必需。** 当前瓶颈不是视觉模型算力。若未来改成密集帧、检测更大模型或多视频并行，再重新评估 GPU。
- **内存：可接受但需要约束并发。** Task 12 三视频运行的进程树峰值 RSS 为 1.347 GB；MPS 当前分配 1.501 GB、驱动分配 2.683 GB。统一内存下这些值存在重叠，不能简单相加成“总显存”。
- CUDA 接口虽保留，但本轮未验证，不应声称可用性或性能。

## 4. Q3 — 固定三帧与自适应 3–5 帧

固定三帧稳定保留 20%/50%/80% 时间锚点。自适应方案在此基础上加入高光流和场景变化候选，并去除近重复帧；真实 smoke 中它能补充运动或场景变化证据。

但是，本轮没有完成 temporal3 与 adaptive5 的同模型 30 条端到端准确率 A/B，因此：

- 可以确认自适应方案提供更丰富、带原因的审阅帧；
- 不能确认额外 1–2 帧提高了任何语义字段的准确率；
- 不应为了证明已有设计而重新跑同一批模型矩阵；
- 现阶段保留 `adaptive5` 作为证据采集配置，但不能把它描述成已验证优于 `temporal3`。

## 5. Q4 — 字段级可靠性与失败模式

这里的 `reliable` 只表示 V0.1 的测量/结构门槛，不是产品级泛化保证。

| Schema 字段或字段组 | 来源 | 支持/覆盖 | V0.1 结论 | 主要失败模式 |
|---|---|---:|---|---|
| 文件大小、mtime、duration、width、height、fps、codec | 文件系统 + ffprobe | 272/272 可读视频 | `reliable` | 源文件变化会使缓存失效，属于正确行为 |
| orientation、rotation、creation_time | ffprobe 元数据 | 272 条；值可空 | `candidate` | 一条马术素材的 Display Matrix 与视觉方向冲突；creation time 依赖容器元数据 |
| 代表帧时间、原因、缩略图相对路径 | FFmpeg + 规则 | 30 条/111 帧审阅 | `reliable`（过程） | 不代表语义覆盖已充分；极短片可能只有一帧 |
| Laplacian、亮度、暗/亮像素比 | 传统 CV | 30/30 原始值 | `reliable`（原始测量） | 不能直接等价为主观画质 |
| `exposure_status` | 传统 CV 阈值 | 30/30；准确率 0.667 | `candidate` | 混合光、欠曝常被判为 normal |
| `blur_score`、`quality_score`、quality 等级 | 传统 CV 映射 | 无独立校准 | `not_reliable_for_v0_1` | 原始锐度不能直接映射可用性；阈值未验证 |
| 光流、方向比、luma change 原始值 | 传统 CV | 除单帧外有证据 | `reliable`（原始测量） | 同时受主体、相机、时间间隔和切镜影响 |
| `motion_level`、`static_or_dynamic` | 光流映射 | 30 条 pilot | `not_reliable_for_v0_1` | 人工 high/medium/low 与原始光流不单调 |
| `people_present` | SSDLite | 28/30；F1 0.813，accuracy 0.786 | `candidate` | 远景人群、舞台、手部漏检；建筑画面偶发误检 |
| `people_count_estimate` | SSDLite | 28/30；MAE 6.14 | `not_reliable_for_v0_1` | 遮挡、远景和密集人群系统性少计；只能作下界证据 |
| `people_type` | SigLIP2 | 17 条有效；16/17 top-1 命中标签集 | `candidate` / child `insufficient_coverage` | adult 17、child 仅 3；child recall 0.333 |
| `scene_type` / candidates | SigLIP2 | 28 条；ungated accuracy 0.464；门控覆盖 0 | `not_reliable_for_v0_1` | 过度输出 other；0.08 margin 与分数分布不匹配 |
| `shot_scale` | SigLIP2 + 人物几何 | 28 条；融合覆盖 15/28；端到端 accuracy 0.286 | `not_reliable_for_v0_1` | 无人物画面、远景小人物、close_up、aerial 结构性失败 |
| `simple_action` | SigLIP2 固定提示词 | 27 条；exact 0/27 | `not_reliable_for_v0_1` | 提示词缺少舞台表演、驾车、登乘、烹饪、运镜等真实动作 |
| `main_objects` | SSDLite + SigLIP2 | 30 条；Detector micro recall 0.125 | `not_reliable_for_v0_1` | COCO/九类提示词不覆盖建筑、标牌、服装、舞台和旅游语义 |
| `material_role_candidates` | 可解释规则 | 依赖上游字段 | `candidate` | 上游 scene/action/shot/object 弃权会传播；不是独立模型准确率 |
| confidence、field_status、timings、errors | 管线结构 | 自动化测试 + 三视频 E2E | `reliable`（结构） | confidence 只代表证据强弱，不代表跨数据集可靠性 |

没有“整体 Scanner Accuracy”。不同字段任务、覆盖和失败成本不同，必须独立消费。

## 6. Q5 — 各组件负责什么

| 组件 | 保留职责 | 不允许承担的职责 |
|---|---|---|
| ffprobe / 文件系统 | 技术元数据、来源身份、缓存失效依据 | 判断画面语义或视觉方向冲突 |
| FFmpeg 稀疏采样 | 本地解码、代表帧、时间与选择原因 | 保证已经捕获所有关键时刻 |
| 传统 CV | 原始锐度、亮度、裁切比例、光流和变化证据 | 直接给出可靠画质或运动等级 |
| SSDLite | 人物存在候选、粗略人数下界、常见 COCO 物体、人物几何 | 精确人数、完整旅游物体、场景理解 |
| SigLIP2 | 固定 revision 的原始零样本分数和候选证据 | 当前直接填充 Scene、Shot Scale、Action、Objects |
| 融合与 Material Role 规则 | 保守聚合、置信度传播、触发规则可追溯 | 把弱证据升级为确定事实；产生 opening/climax/ending |
| 评估与静态报告 | null-aware 指标、覆盖、错例和本地审阅 | 用三条 smoke 声称字段可靠性 |

## 7. Q6 — 明确不可靠的字段与替代方向

- 人数：改为区间或 `none/single/few/crowd`，并用独立数据验证，不再输出伪精确整数。
- Scene/Object/Action：重新设计旅游领域分层 taxonomy；先验证标签覆盖，再评估更适配的本地模型或裁剪策略。
- Shot Scale：区分“有人物”和“无人物”路线；加入主体定位、构图与焦点证据，单独补足 close_up/aerial 样本。
- Motion：分离相机运动、主体运动、抖动与切镜；不能用一个稀疏光流阈值概括。
- Quality：把技术缺陷与编辑可用性分开，使用独立标注集校准。
- Material Role：等上游字段可靠后再做独立标注和评估；当前只允许候选，不进入确定时间线。

## 8. 验收矩阵

| 验收项 | 状态 | 证据/限制 |
|---|---|---|
| 本地只读媒体盘点 | 通过 | 272/272 可读视频，结果与独立盘点一致 |
| 稀疏抽帧与显式 VideoToolbox | 通过 | bounded probes、代表帧原因和真实长短片 smoke 均有记录 |
| 冻结 Ground Truth | 通过 | 30 个唯一文件；模型运行前冻结；两份 JSON 字节一致 |
| CPU 与 MPS 本地模型路径 | 通过 | 同帧 top-1 一致，最大分数差 `4.33e-7` |
| 单文件失败隔离 | 通过 | failed/partial 卡片、阶段错误和 prior evidence 保留均有测试 |
| 缓存、revision、不可变 run | 通过 | 配置 hash、模型 revision、cache-link、resume 契约有测试 |
| 字段级 null-aware 评估 | 通过 | 11 类字段指标，不生成误导性的总体准确率 |
| 静态 HTML 审阅 | 通过 | 三视频实浏览器检查；10/10 图像加载，无脚本、无溢出 |
| 环境与资源遥测 | 通过 | 100 ms 汇总采样；不支持的 I/O 明确为 `null` |
| 30 条组合管线 A/B | 未完成 | 已有 30 条分阶段结果，但没有 temporal3/adaptive5 组合矩阵 |
| 100 条全管线吞吐 | 未执行 | 当前 10–20 分钟为证据外推，不是实测 |
| 语义字段作为确定事实 | 不通过 | 除技术/原始证据外，多数字段仅 candidate 或 not reliable |
| AI Director、音乐/SFX、时间线导出 | 不在范围 | Scanner V0.1 未实现，也未调用 Dreamina |

## 9. Q7 — 是否继续与最小下一步

继续开发，但下一步不应扩大功能面，也不应继续在同一 30 条上调阈值。最小有效下一步是：

1. 只保留技术元数据、原始 CV、代表帧和 `people_present` 候选进入上层实验。
2. 已冻结一组与原30条零重叠的30条候选集；下一步按 `benchmark/PEOPLE_VALIDATION_GUIDE.md` 完整观看并标注“人物存在”和粗粒度人数，不同时追全部语义字段。
3. 用保存的静态报告进行人工纠错，先找 taxonomy 和证据缺口，再决定是否替换模型。
4. 只有当候选字段在独立数据达到门槛后，才进入 Director、音乐、时间线或导出阶段。

## 10. 证据索引

- 完整实验流水：[`EXPERIMENTS.md`](EXPERIMENTS.md)
- 冻结清单：[`benchmark/test_manifest.json`](benchmark/test_manifest.json)
- Ground Truth：[`benchmark/ground_truth.json`](benchmark/ground_truth.json)
- Task 9 三视频验证报告：`benchmark/runs/exp09-pipeline-e2e-3-v2/validation_report.html`（本地忽略产物）
- Task 12 遥测：`benchmark/runs/exp12-telemetry-warm-3/telemetry.json`（本地忽略产物）

本报告没有把未执行的 30 条组合矩阵、100 条吞吐或独立泛化验证写成已完成。
