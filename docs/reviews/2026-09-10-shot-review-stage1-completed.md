# 第一项：候选镜头精看完成记录

日期：2026-09-10。状态：代码、Skill 接入、本地测试、真实素材精看与本机安装完成；未提交 Git、未推送、未运行本轮 GitHub CI，未生成新剪映草稿。

## 已完成行为

- 保留现有每素材 3–5 帧粗看、八字段合同和 compact JSON 展开机制。
- 新增独立精看：明确选择候选素材的源时间短区间，局部解码，生成带源时间戳的密集帧与联系表，当前版本不生成连续播放代理。
- 上限：10 个区间/请求，单区间 8 秒，总共 40 秒。默认至少间隔 0.125 秒取真实解码帧，约 8 fps；源帧率可能使实际密度略低。单图长边至多 640 像素，每张表至多 12 帧。
- 保存建议 source_in/out、景别、主体位置、镜头/主体运动方向、主要动作起始/重音/结束的候选时刻、时间误差、置信度、理由和帧证据。
- 动作时刻必须由密集相邻帧约束，保留时间区间误差。看不见的动作和无法分辨的运动留空。置信度不等于时间精度。
- 同一请求缓存复用；已有精看结果不可覆盖；源文件、上游观察、样本或结果哈希改变时显式拒绝复用。只读取/校验选中素材，不重扫全素材库，不调用额外模型或外部服务。

## 文件与安装

运行源码根目录：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner`。

- [精看实现](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/director/shot_review.py)
- [独立精看合同](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/director/shot_review_schema.py)
- [使用与证据规则](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/skills/travel-director/references/shot-review.md)
- [新增测试](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/tests/director/test_shot_review.py)
- 源 Skill：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/skills/travel-director`。
- 安装入口：[SKILL.md](/Users/meimaodawang/.codex/skills/travel-director/SKILL.md)。调用名：`$travel-director`。
- 安装回执：`/Users/meimaodawang/.codex/skill-receipts/travel-director.json`，绑定 77 个运行时 Python 文件。resolver 当轮通过。
- 原安装备份：`/Users/meimaodawang/.codex/skill-backups/travel-director.backup-20260910-093958`。
- 当前 HEAD 仍为 `7a150d9`，本次安装绑定的是含未提交修改的实际源码哈希，不能将新功能说成已发布到该提交。此前用户的 Skill/compact 脚本修改完整保留。

## 最小使用方式

正常对话可要求 `$travel-director` 对已选镜头局部精看；Skill 会先粗选、生成 selection、检查时间样本，再提交 compact 观察。新流程是独立附属步骤，不改 Runner 原有状态图。

从上面的运行源码根目录执行：

```bash
uv run travel-director prepare-shot-review --project <现有项目绝对路径> --selection <selection.json绝对路径>
uv run travel-director submit-shot-review --request <返回的request.json> --observations <填写后的compact.json>
uv run travel-director inspect-shot-review --request <返回的request.json>
```

`needs_shot_observation` 表示等待本会话阅读样本并判断；`shot_review_validated` 只表示合同、来源和证据校验通过，不是 Ground Truth 或最终剪辑验收。精看结果由当前会话填写，本地程序不自动判断画面内容。

## 验证结果

- 新增测试 24 项通过：时间区间边界、真实 PTS、非帧对齐 seek、VFR、缓存不重复解码、错误解码不发布半成品、上下游/源文件/图像/结果篡改、密集运动证据、动作误差范围、候选覆盖、旧八字段合同隔离。
- 第一次扩展 VFR 测试暴露了 trim duration 相对首帧计算导致末尾超界的问题，改为 post-seek 时间域内明确 start/end。修复后重跑完整测试。
- 完整测试：**580 passed，3 个既有依赖弃用警告，34.91 秒**。
- 仓库 Skill 验证通过，11 个本地链接有效；`git diff --check` 通过；本机安装后 resolver、Skill validator、真实结果 CLI inspect 均通过。
- [完整测试日志](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/validation/shot-review-20260910/tests.log)

## 真实素材验证

使用已有万岁山项目 `travel-project-7b639731d7`。先阅读原粗看图，选择 `2026_02_06_18_30_11_IMG_0230.MOV` 中 2.8–3.9 秒，检验前景白色车辆遮挡是否能作为后续连接候选。该选择是功能验证，不是重新决定整片采用该镜头。

- 1.1 秒窗口生成 9 个实际时间样本，未重新扫描 270 段素材。
- 独立 ffprobe 源帧时间对照：本次 9 帧的时间戳误差均为 0 秒（按保存的微秒精度）；这证明时间映射，不证明动作语义正确。
- 本会话观察：前景白色车辆向画面右侧移动；遮挡开始候选约 **2.868 ± 0.067 秒**，视觉遮挡重音候选约 **3.202 ± 0.133 秒**。
- 无法可靠拆分拍摄端运动与车辆相对运动，因此 camera_motion 留空；完整动作结束时刻未确认，action_end 留空。
- 建议可用区间约 2.802–3.868 秒，是观察支持的剪辑候选范围，不是已输出 EDL。
- 第二次同请求 cache_hit=true，实测 0.1066 秒；测试另通过阻止解码函数验证缓存不重解码。该耗时仅代表本机这一个区间，不推广为全项目性能保证。

[查看时间样本图](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/prototype/runs/travel-project-7b639731d7/visual/shot_reviews/d6d7195868a7085d281c4060b9c5852f546d8ee09b03af2a5f397c7d0bebda46/shot-000-sheet-00.jpg)

[查看保存的精看结果](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/prototype/runs/travel-project-7b639731d7/visual/shot_reviews/d6d7195868a7085d281c4060b9c5852f546d8ee09b03af2a5f397c7d0bebda46/results/observations.json)

附加证据位于 `validation/shot-review-20260910/`：selection、compact 观察、prepare/submit 返回、源 PTS 对照、缓存计时、安装后 inspect 返回与测试日志。该目录是功能验证材料，不是正式剪映交付。

## 对第二项的调整建议

第一项现在能回答“这个局部动作/构图是否有证据、精确到什么程度”，但仅有一个镜头的遮挡重音，不能推断它与任意下一镜头都能连接。

下一阶段建议新增独立“镜头组与连接决策”合同，输入应引用已验证的精看 request/result、candidate_id 和具体帧段：

1. 先用 2–4 个候选镜头构成局部序列，并说明各镜头的叙事职能。
2. 每个连接同时引用前镜头的离开区间和后镜头的进入区间，解释动作、注意点、方向、形状/颜色、内容或有意反差。
3. 支持 `supported`、`needs_review` 和有理由的普通硬切；未知运动不自动变成匹配依据。
4. 输出切点允许范围与理由，继承精看的时间误差，不把候选中点升级为帧级精确切点。
5. 验证时只补看相关边界，不重新读取全部粗看/素材库。先做一组局部剪辑比较，再决定是否接入全片。

当前导出器仍不自动消费或强制校验精看结果；本轮通过 Skill 把精看放在精确剪辑决策前。这一程序连接应在第二项的镜头组决策到 EDL 接入时补充。音乐、SFX 匹配、包络、变速均未在本轮修改。
