# Travel Director 参考片与声画规划改造 — 暂停续接点

暂停原因：用户明确要求“先暂停项目，保存进度，我要离开电脑”。停止开发，不安排后台继续或自动恢复。本文件是阶段进度备份，不是实现完成声明。

## 权威位置与边界

- 工作目录：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner`
- 工作树：`feature/local-media-scanner-v0.1`，HEAD `7b0e946`。所有本轮修改尚未提交，已经保存到磁盘。不要重新开发、reset 或覆盖已有改动。
- 需求：用户对话中的“续接计划：完成参考片与声画规划改造”、`/Users/meimaodawang/Downloads/PLAN.md`，实施分解见 `docs/superpowers/plans/2026-09-05-reference-av-direction.md`。
- 当前对话实施，不接入音乐生成/额外模型，不新增试听页面，不渲染，不剪辑。音乐审美由用户外部选定。明确交付剪辑的单首音频直接导入；失败、参考、复盘音频不导入；多首未选定只问对象。
- 四例默认参考，案例二仅 0–180 秒。用户当前要求优先，不自动改变地点、片长或画幅。参考声学语义未知，不伪称听辨。

## 已实现并验证的部分

1. `director/creative_schema.py`、`director/references/defaults.json`：四例参考库、项目关联哈希、素材引用、参考范围、段落覆盖、三条 <=200 字提示词校验。新增 custom alias 不能扩大默认参考范围的测试与校验。
2. `director/creative_direction.py`：会话创作请求、独立内容寻址修订、摘要及当前索引。重复提交复用；追加新修订不覆盖旧记录；旧库哈希过期不再阻断有效新提交。普通续跑遇到完整但过期方案，返回新创作请求；损坏记录仍阻断。
3. `director/runner.py`、`director/cli.py`：`needs_creative_direction`、`--creative-response`；新流程不再自动生成旧音乐模板和旧 final_summary。
4. 音乐恢复：Runner 允许已有不可变 asset、分析失败后以同一 `--music` 重试；仍校验原文件与冻结文件哈希。
5. `director/music_version.py`、`--new-music-version`：必须携带父项目及新音乐；创建同级内容寻址独立版本，复制既有视觉证据、不重扫，不复制原冻结音频和后续剪辑输出，返回新项目路径。同一父项目/同一新文件重试复用版本；父项目字节保持不变的测试已通过。
6. 旧提示词出口：`music_prompt_recommender.py` 固定模板已退役；旧 CLI 明确引导 `run --creative-response`，不创建/覆盖输出。`visual_schema.py` 删除强制免责声明/固定人声措辞，历史制品仍可读取。历史摘要测试使用测试专用制品。
7. 仓库 Skill 已修改：`skills/travel-director/SKILL.md`、`references/workflow.md`，新增 `references/creative-direction.md`。包含新状态、展示顺序、音频用途及换曲。**尚未同步安装版**。

## 最新证据

- 最新完整回归：`.venv/bin/pytest -q` → **384 passed，3 条既有 audioread 依赖弃用警告，13.84 秒**。
- 创作模块与 Runner 定向合同：41 passed（此前 376 的阶段已被此轮最新结果取代）。
- 两个修复遵循先失败再修复：旧参考哈希阻断新方案、音频冻结后分析失败无法重试。换曲显式参数及版本测试也已先红后绿。
- Skill 基线独立试用确认：安装旧版缺 `needs_creative_direction` 及换曲协议；单首正式音频路径可用。仓库新版已针对缺口修改。新版 forward-test 因用户暂停已中断，不能声称通过。
- 独立代码审查结论：**尚不可交付，发现一项 P2，见下节**。审查未修改仓库。
- 没有外部/付费服务调用，没有导入两首拒绝音乐。

## 必须先修复的独立审查问题

**P2：新创作路径绕过既有 external_calls 台账完整性检查。**

复现：在临时项目达到 `waiting_for_music` 后删除 `external_calls.json`，再次 `run` 及 `inspect_travel_director` 均仍返回 `waiting_for_music`；CreativeSummary 仍硬编码 `external_call_count=0`。

涉及：`director/creative_direction.py::_context` 只检查视觉阶段；`runner.py::_advance_creative` 冻结恢复也绕过旧 `build_skill_run_summary` 检查。旧验证函数 `director/skill_summary.py::_external_call_payload` 检查台账存在/哈希/结构，旧摘要还将非空台账作为完成阻断条件。

下一步：先补缺失、漂移、非空台账的失败测试，覆盖创作提交/续跑、已冻结创作恢复、换曲版本创建；集中恢复 ledger 校验，保证 local-only 契约真实。不要只让摘要报 0。考虑同时让 `_context` 验证原始 Brief 哈希（Runner 已验证，但模块直接调用应自洽）。修复后再请原独立审查者复核。

## 尚未完成的交付项

1. 上述 P2 修复及复核。
2. 补强旧项目兼容的明确测试：未冻结旧项目增补不覆盖、不扫描；已冻结旧项目在参考库更新后按原合同恢复。当前仅新创作+音乐版本主要路径通过。
3. 新版 Skill forward-test、`quick_validate.py`、安装版同步及逐文件一致性检查。安装入口仍旧文档，不要声称正式入口已切换。
4. 参考库目前有视觉证据与音频未知说明；如需要补音频技术信息，从已保存各 case analysis.md 摘取经核实的技术值及测量出处，不能当听辨或照抄混音目标。案例二全片/三分钟外分析不得进入参考结论。
5. 使用真实开封项目已有分析的隔离验收：本轮**尚未创建/运行**隔离副本。以会话实际阅读素材证据后写出适配 60 秒竖屏方案（不能用测试生成器冒充创作）。验证参考选择、段落表、三提示词、重复提交、测试音频导入和换曲；收集原项目不变的前后哈希证据。
6. 最终完整回归、`git diff --check`、必要打包资源检查、独立审查通过，再保存完成阶段总结。不要在这些之前宣布实现完成。

## 真实项目与证据保护

- 原项目：`prototype/runs/travel-project-3d14b9a84b`，约 156 MB。
- 暂停前只读核对：state `status=completed,current_stage=visual_review` 是旧内部视觉状态；`music_asset=null,creative_current=null`。真实项目未绑定音乐、未写入新创作方案。
- 输入：`/Users/meimaodawang/Desktop/万岁山素材`。
- brief 原文：`制作一条 60 秒竖屏开封旅行短片，有进入、探索、高潮和收束，纪实风格，兼顾城市氛围与同行体验。`
- 已有 270 素材；treatment 提示 `missing_director_function:climax` 和 `missing_director_function:ending`。不得把高潮和收束镜头描述为已经具备。
- 参考研究素材：`/Users/meimaodawang/Documents/旅行导演/outputs/reference-review-20260905/`。其中早期 Skill融合方案/阶段总结含已被用户推翻的“必须先听辨/候选试听”想法，不能沿用。
- 两首拒绝音乐仍不导入：Downloads 中 `jimeng-2026-09-05-1334-边界回声.wav` 与 `jimeng-2026-09-05-1948-暖光漫行.wav`。不从拒绝记录推导乐器或流派禁用。

## 文件与协作状态

- 核心新测试：`tests/director/test_creative_runner.py`、`test_creative_schema.py`。
- 修改过既有测试：`test_runner.py`、`test_music_prompt_recommender.py`、`test_skill_summary.py`。
- 无关既有未跟踪文档保持原状：2026-08-31 kdenlive context、2026-09-04 visual supplement context、2026-08-31 visual plan。
- 子任务 `legacy_cleanup` 已完成；`skill_baseline` 已完成；`implementation_review` 已完成并报告 P2；`skill_forward` 已因暂停中断。没有安排后台续跑。
- 恢复顺序：读本文件 → git status/diff 确认现场 → 修复审查 P2 的 TDD → 旧合同补测 → Skill 验证同步 → 隔离验收 → 最终回归与审查。现有实现继续修改，不重做四例研究、不重扫素材。
