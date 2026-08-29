# 音乐驱动旅行混剪实施计划阶段上下文

首次计划日期：2026-08-28（Asia/Shanghai）  
离线基础实施更新：2026-08-29（Asia/Shanghai）

## 权威工作区

- 工作树：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`
- 分支：`feature/local-media-scanner-v0.1`
- 计划编写前 HEAD：`1578d8f docs: define music-driven montage prototype`
- 主工作区 `main` 仅有 Scanner 设计和旧计划，不含 Scanner 源码；后续开发不得在 `main` 直接开始。

## 本轮完成

- 完整阅读 `docs/superpowers/specs/2026-08-28-music-driven-travel-montage-prototype-design.md`。
- 检查 Scanner 源码、测试、基准结论、Git 分支和 worktree 状态。
- 本地运行 `uv run pytest -q`，结果为 `72 passed in 7.16s`。
- 生成可执行计划 `docs/superpowers/plans/2026-08-28-music-driven-travel-montage-prototype.md`。

## Scanner 可复用与不可越界结论

- 可复用：技术元数据、稀疏代表帧、原始画质/运动证据、本地缓存、分阶段错误、遥测和结果 Schema。
- 必须降权：`people_present` 仅候选；人数估计、场景、景别、动作、对象不能作为确定事实。
- 禁止推断：不能由“检测到很多人”推出人物主线、A-roll/B-roll 或编辑角色。
- 当前独立 30 条人物验证包尚待人工标注，不能把它写成已经完成的泛化验证。

## 本轮外部服务状态

- 未打开或调用曲多多。
- 未登录或调用即梦。
- 未调用任何付费服务，未消耗积分。
- 未开发业务代码；仅新增计划和本阶段上下文 Markdown。

## 2026-08-29 离线基础实施检查点

- 用户选择 Inline Execution，按 `executing-plans` 与 TDD 执行。
- Task 1 完成并提交：`053e058 feat: freeze travel director contracts`。
- Task 2 完成并提交：`7ddb200 feat: bridge scanner evidence into material library`。
- Task 3 完成并提交：`fdfa989 feat: derive auditable music search briefs`。
- Task 4 完成并提交：`40d947e feat: add offline music catalog provider boundary`。
- 当前完整测试：`95 passed`。
- 真实本地 smoke 使用有证据记录的三视频 Scanner 运行 `exp09-pipeline-e2e-3-v2`；没有根目录 `scanner_result.json`，未伪造 canonical 产物。
- 已实现：严格 Director 契约、本地 CLI、Scanner 保守桥接、近重复候选、稀疏音频证据、搜索方案、离线 Catalog Provider、三方向可解释排序。
- 仍未实现或执行：曲多多页面适配、即梦能力检查/生成、音乐分析、时间线、镜头选择、SFX 计划、渲染与端到端验收。
- 本检查点未打开或调用曲多多，未检查、登录或调用即梦，未调用付费服务，未消耗积分。
- 下一门：Task 5 需要用户单独授权后才可进行一次曲多多当前可见结果页 smoke；授权前可以只实现离线解析器测试，但按当前计划先停下复核。

## 待用户复核的四个门

1. 新增 `director` 同级包、保持 Scanner Schema 不变。
2. 先离线契约，再曲多多单页、即梦只读能力检查、单次生成授权的顺序。
3. 本地音乐分析使用 librosa/soundfile，预览渲染仅使用 FFmpeg。
4. 首次验收最多一次曲多多页面捕获、一次音乐生成尝试、不生成 SFX、一次代表性混剪渲染。

## 2026-08-30 恢复与 Task 5 离线检查点

- 恢复后确认 worktree clean、前四个功能提交存在，重新运行 `95 passed`。
- 已提交计划与上下文：`fc20152 docs: record director implementation plan and checkpoint`。
- Task 5 离线可见页面解析器已按 TDD 完成并提交：`13f1c98 feat: parse bounded visible catalog results`。
- 当前完整测试：`100 passed`。
- 解析器只接收单个当前可见页面的规范化 JSON；最多保留5条，只保留允许字段，不包含浏览器控制或 DOM 选择器。
- `login_required`、`captcha`、`waf`、多页面或异常卡片结构均返回 `blocked` 和空候选，不猜测或绕过。
- 截至本检查点仍未打开曲多多、未捕获真实页面、未下载试听音频，未检查或调用即梦，付费调用和积分消耗均为0。
- 当前停止点：等待用户明确授权一次曲多多当前可见搜索结果页 smoke；若未授权，Task 5 保持“离线解析完成、真实网页未执行”。

## 2026-08-30 曲多多真实 smoke 结果

- 用户明确回复“继续”，授权一次当前可见结果页 smoke。
- 官方产品页的“立即前往”目标为 `https://agm.haifanwu.com/`。
- 应用内浏览器访问产品页和曲库目标均在导航阶段超时；切换到已连接 Chrome 后访问同一官方曲库目标仍超时。
- 页面内容、登录框、验证码、WAF提示和结果卡片均未出现；按停止规则未继续猜域名、构造搜索URL或重试。
- 结果：`blocked/navigation_timeout`，可见候选0、下载0、登录尝试0、验证码/WAF处理0、费用0。
- 忽略的本地证据：`local-media-scanner/prototype/runs/quduoduo-smoke-20260830/`。
- Task 5 的离线代码完成，真实曲库价值未验证；后续仅可用fixture继续技术链路，不得声称曲多多闭环已完成。

## 2026-08-30 Task 6–7 检查点

- Task 6 按 TDD 完成参考安全的 60 秒音乐蓝图与原创约束 prompt，提交：`a69d51c feat: build reference-safe music blueprints`。
- Task 7 新增可替换生成 Provider 协议、单次用户授权契约、即梦帮助文本能力解析与 fail-closed 门禁。
- 离线门禁证明：未授权时返回 `blocked/not_authorized`；授权但无音乐命令时返回 `blocked/unsupported_capability`；两种情况均不触发 runner。
- 只读检查安装位置 `/Users/meimaodawang/.local/bin/dreamina`，仅执行 `dreamina --version` 与 `dreamina --help`。
- 当前构建为 `673dd28-dirty`（commit `673dd28`，build time `2026-08-17T16:06:28Z`）；帮助只暴露图像/视频生成，没有 music/audio 生成命令，结论为 `music_generation=false`。
- 按停止规则未检查登录态、未查询积分、未请求生成授权、未运行生成；外部调用数0，费用0。
- 脱敏运行证据位于被忽略的 `local-media-scanner/prototype/runs/dreamina-capability-20260830/dreamina/capabilities.json`。

## 2026-08-30 Task 8 本地音乐分析检查点

- 新增 `librosa>=0.11,<1` 与 `soundfile>=0.13,<1`，并更新 `uv.lock`；仅下载本地 Python wheels/缓存，未调用外部业务或付费服务。
- `analyze_music` 只从本地 WAV/MP3/M4A 解码样本测量 22.05 kHz 单声道数据，输出源 SHA-256、BPM、beat、四拍 downbeat 候选、1秒能量曲线、分段置信度和结尾行为。
- 合成回归音频为 60 秒/120 BPM，24–31 秒低能段，59.5 秒末次冲击；聚焦测试 3 passed。
- 新增非私有合成媒体脚本，可生成同款 click track 和5个纯色本地视频；本检查点仅做语法检查，未执行视频生成。
- 完整回归：`110 passed in 9.66s`；另有3条来自上游 `audioread` 的 Python 3.13 弃用预警，当前运行时为 Python 3.12。
- `travel-director version` 仍输出 `0.1.0`，音频分析栈改为仅在 `analyze-music` 命令中懒加载。
- 本阶段曲多多/即梦调用数均为0，费用0。

## 2026-08-30 Task 9 时间线骨架检查点

- 新增 `build_timeline_slots(structure, brief, config)`，只消费实测音乐结构和用户 brief，不选择任何素材文件。
- 0–60 秒时间线连续、无重叠；内部槽位边界吸附到实测 beat/downbeat，并记录对应 beat 索引。
- 默认目标均值：intro 3.5秒、rise 2.2秒、breath 4.5秒、climax 1.4秒、outro 3.5秒；同时受最短/最长槽位预算约束。
- 开场需求为 `establishing_environment`，高潮为 `high_visual_impact`，结尾为 `resolved_ending`；未知段保留 `unknown` 并记录 `continuity_fallback`。
- 聚焦测试 `5 passed`，完整回归 `115 passed in 9.60s`；仍仅3条上游 `audioread` 弃用预警。
- 本阶段曲多多/即梦调用数0，费用0。

## 2026-08-30 Task 10 镜头选择检查点

- 新增两遍式 `place_clips`：先保留有视觉冲击/运动证据的顶部候选给高潮，再填充开场、上升、呼吸和结尾槽位。
- 评分分项包含时长匹配、原始运动证据、画质证据、候选场景多样性和视觉冲击；每个 placement 保留 `score_components` 和 `relaxed_constraints`。
- 相邻槽位优先排除同一 `duplicate_group_id`，唯一素材耗尽后才允许复用，并显式记录 `reused_after_unique_exhausted`。
- 所有 in/out 位于技术时长及推荐区间内；`analysis_status=failed` 的素材不可用，无法填充时返回 `partial/insufficient_material`。
- `people_present`/人数候选不参与人物主线推断，评分中不存在 `human_story`。
- 聚焦测试 `6 passed`，完整回归 `121 passed in 9.66s`；本阶段外部服务调用0，费用0。

## 2026-08-30 Task 11 原声/SFX 计划检查点

- `collect_sfx_candidates` 只保留白名单标签，要求候选 `file` 与所属素材一致，按来源去重并保留置信度。
- `build_sfx_plan` 只处理已放置且事件时刻位于裁切区间内的候选；输出 `keep_original|enhance_original|generate_sfx|silence`，不调用生成器。
- 呼吸段的本地音频证据优先 `keep_original`；纯视觉事件可记录一次选择性 `generate_sfx` 建议，相邻镜头不会连续建议生成。
- 时间线事件时刻按传入 placement 顺序累加镜头时长，因此要求该列表为连续时间线顺序；候选时刻减去 `source_in` 后映射到对应镜头。
- 聚焦测试 `6 passed`，完整回归 `127 passed in 9.55s`；曲多多、即梦和 SFX 生成调用数均为0，费用0。
