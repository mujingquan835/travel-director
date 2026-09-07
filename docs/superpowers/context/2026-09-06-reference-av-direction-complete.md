# Travel Director 参考片与声画规划改造：完成阶段记录

日期：2026-09-06。本记录取代 2026-09-05 paused.md 的待办状态；历史暂停记录保留，不覆盖。

## 已完成范围

流程现为：已有素材与 Brief → 会话选择参考并展示声画联合段落表 → 三条音乐提示词 → 用户外部生成或选曲 → 发回正式配乐 → 本地冻结分析 → waiting_for_timeline。

- `needs_creative_direction` 返回来源哈希、参考库、素材/导演制品、Schema 与响应路径；`--creative-response` 校验并保存独立内容寻址修订，重试幂等，变更追加。
- 参考范围、素材 ID、Brief 地点/时长/画幅、段落连续覆盖、恰好三条且各不超过 200 字均受合同约束。案例二限 0–180 秒；同源 custom 别名不能扩大范围。
- 废弃固定三组流派/配器/强高潮的自动提示词出口；旧命令明确引导会话创作，历史制品仍可读取；移除强制问题尾句和固定人声措辞。
- 单首明确用于剪辑的音乐按已选定导入；参考、复盘、拒绝音频不调用 --music；多首正式音乐未选对象时仅澄清文件。
- 冻结音频后分析失败，可同曲重试。--new-music-version 创建独立换曲项目并返回新路径，保留父项目。旧视觉证据不重扫、不覆盖，旧冻结项目不受参考库升级影响。
- 仓库和已安装 Skill 已同步，包括新状态、输出顺序、用途分流、换曲协议、冻结项目兼容。未新增音乐服务、试听页面、听觉模型、剪辑或渲染。

## 审查修复与测试证据

独立审查发现并以先红后绿方式修复三项完整性问题：

1. 新创作路径遗漏 external_calls 台账验证：现在检查存在、哈希、结构及 local-only 空台账条件，写入前校验；12 个组合用例覆盖提交、恢复、冻结、换曲及缺失/漂移/非空。
2. 复用已存在换曲子项目只查 lineage：现在先校验其台账、Brief、全部记录的视觉制品及创作/旧合同，再允许返回和写入。
3. 分析失败重试先写分析再检查损坏创作记录：现在创作完整性验证前置，损坏时保持项目字节不变。

- 最终完整回归：`.venv/bin/pytest -q`，**402 passed，3 条既有 audioread 依赖弃用警告，18.40 秒**。
- 独立最终复核：**59 passed**；额外临时项目复现证实损坏换曲子项目返回 blocked 且字节不变；未发现剩余已确认代码阻断项。
- `git diff --check` 通过。
- Skill 独立只读 forward-test：八类真实使用场景可由文档正确执行。失败音频不导入；实质听感复盘不属于本轮新增功能。已明确所有冻结项目不因参考库升级重规划。
- 仓库及安装版 `quick_validate.py` 均通过；`diff -qr` 无差异。
- 安装版 resolver 实际返回当前权威包目录；`uv run --offline --no-sync travel-director status` 实测隔离项目为 waiting_for_timeline、external_call_count=0。

## 开封隔离验收

成功制品目录：
`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/outputs/reference-av-acceptance/kaifeng-a6lvjxvh/`

- `acceptance.json`：全部原项目文件前置哈希、最终不变断言、视觉证据不变、重复提交/换曲复用结果。
- `方案.md`：参考选择 → 声画联合表 → 音乐要求 → 三条提示词，完整可读。
- `session-authored-plan.json`：会话依据已查看素材接触表及参考片接触表实际撰写，不是测试 fixture 冒充方案。
- `01-request.json` 至 `06-version-repeat.json`：正式 CLI 的请求、提交、重复提交、导入、换曲、重复换曲结果。
- 测试音频仅为脚本合成的 440/660 Hz 60 秒测试信号，**不是可用审美配乐**。三条提示词长度为 **87、90、89** 字。两首用户拒绝音乐均未导入。
- 所有原项目文件哈希保持不变；隔离副本的旧 visual 制品也保持不变；换曲父项目保持不变。导入和换曲都停在 waiting_for_timeline。
- 复现脚本：`local-media-scanner/scripts/accept_reference_av.py`，每次新建隔离目录，不写真实项目，不调用扫描或外部服务。
- 首次尝试 `kaifeng-8oacv37e` 因验收脚本在比较中重复计算整树哈希而被主动中断；优化为一次计算后新目录重跑成功。首次目录保留为未完成尝试，不作为完成证据。

## 参考与素材的实际边界

四例已核实视觉观察、适用区间、证据路径和适用条件进入默认库；已知音频格式与测量值带来源写入 audio_notes，且明确不是听辨或推荐响度。

本轮实际复查案例四接触表发现：62 秒为蓝色海水礁石，64 秒采样已黑场。默认库 ending 观察时间已修正为 62 秒，旧研究文字未被覆盖。

验收保持开封 60 秒竖屏。采用案例二标题与人物环境交替、案例四细节与地景收束的方法；未自动把开封改成风光旅拍或横屏。已看素材支持夜间街口、城门、入口、牌楼、灯笼、人群行进和水面灯影。高潮、同行身份/近景、可靠结尾及部分段落净时长仍有缺口，表中明示；这些创作规划不等于可直接渲染的完整剪辑。

## 真实项目与版本控制状态

真实项目：`local-media-scanner/prototype/runs/travel-project-3d14b9a84b`。其旧内部 status=completed/current_stage=visual_review 只表示视觉阶段；`music_asset` 和 `creative_current` 均仍为空。未给真实项目绑定音乐或新创作方案。

权威工作树：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`，分支 `feature/local-media-scanner-v0.1`，基线 HEAD `7b0e946`。本轮代码、测试、Skill、验收脚本与阶段记录已落盘，**尚未 Git 提交、合并或推送**，未删除工作树及用户其他文档。安装版 Skill 路径为 `/Users/meimaodawang/.codex/skills/travel-director`。

下一次真正制作时，按用户交付用途继续正式项目；本验收目录不能冒充真实项目。当前阶段完成不意味着生成了音乐或视频，也不承诺音乐平台审核通过。
