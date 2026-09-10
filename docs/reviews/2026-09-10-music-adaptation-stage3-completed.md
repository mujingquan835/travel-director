# 第三项：音乐乐句适配与修订记录

2026-09-10。阶段完成：乐句/听审合同、原曲到项目映射、独立修订差异、镜头内部动作引用、FCPXML导出接入、本地测试与安装。未完成实际音乐听审、成片审美验收或新包剪映客户端验收。未继续下一项音效设计，也未提交Git、推送或运行本轮CI。

## 已实现的变化

以前自动节拍/能量结果容易承担过多创意含义。新流程把三种信息分别保存：

1. 自动候选：BPM、节拍、候选重拍、能量段落和原曲结尾行为，以 `unconfirmed_candidates` 保存，不能当已确认乐句。
2. 听审记录：原曲区间、审听人、方法、带时区的时间和具体记录；与冻结音乐哈希绑定。已确认乐句必须有覆盖区间的听审记录。程序只能验证来源字段与覆盖，不能证明人或模型真的听过。
3. 编辑选择：原曲区间→项目区间对应表、转折/停顿/恢复/重音/结束节点、结束处理、画面如何响应音乐。

音乐片段允许有理由地重排、跳转或重复，保持原速。映射必须连续覆盖项目；留白用明确的music silence段表示，而不是遗漏。该停顿只停止音乐轨，原声和SFX可继续。

`cut`记录明确截断；`source_end`要求真正到达原曲末尾但不等于确认终止感；`silence`要求末尾有音乐留白段；`fade`目前保存为`needs_audio_processing`，不生成可导出的EDL。音量包络尚未实现，不把淡出文字当成已物化音效。

## 画面无需按BPM切镜

- `hold`：保持镜头，不自动增加切点。
- `internal_action`：音乐节点引用一个镜头内部已经精看过的动作起始/重音/结束时刻。保存源时间、项目时间、原误差和证据帧，报告音乐节点是否处于动作观察窗口内。未知动作不得绑定，偏差不会自动修成同步。
- `local_fast_cut`：明确引用至少两个连续、按顺序的局部镜头，并给出理由。程序不据BPM推导快切，也不能靠这个标签证明镜头真适合快切。

本轮保持输入画面EDL不变。若实际乐句需要修改画面，应先建立一个新的、经过第二项校验的镜头组，再作为适配修订的基准；差异记录会保留基准文件变化，不直接改冻结叙事历史。

## 版本与导出

初版和修订都生成独立目录。`--parent`保存父版路径、哈希及字段级before/after差异；重试同版本可复用，不同内容不能覆盖原目录。同一适配链沿用同一冻结音乐项目；换音乐仍走原有new-music-version流程。

派生EDL携带`music_adaptation`绑定并保留`shot_group`绑定。export-fcpxml现在复核冻结音乐、原分析、基准EDL、父版、画面与音乐片段映射。导出包新增music_adaptation.json快照；receipt包含映射、事件、结束方式、听审状态和修订差异。追加SFX仍可使用既有机制，不能篡改已绑定画面和音乐。

听审状态分别为`not_listened`、`partial_source_review`、`source_ranges_reviewed`；成品混音的`mix_listening_status`独立保持`not_reviewed`。结构校验通过、记录了源片段听审或FCPXML生成成功，都不等于重组后混音好听。

## 文件与调用

源码根：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner`。

- [实现](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/director/music_adaptation.py)
- [合同](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/director/music_adaptation_schema.py)
- [Skill使用规则](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/skills/travel-director/references/music-adaptation.md)
- 安装版：`/Users/meimaodawang/.codex/skills/travel-director/SKILL.md`；调用名`$travel-director`。源码Skill在上述根目录的`skills/travel-director/`。

从源码根执行：

```bash
uv run travel-director build-music-adaptation --plan <plan.json绝对路径> --output <新版本目录>
uv run travel-director build-music-adaptation --plan <修订plan.json> --parent <前版adaptation.json> --output <新修订目录>
uv run travel-director inspect-music-adaptation --adaptation <adaptation.json>
uv run travel-director export-fcpxml --decision <返回的edit_decision.json> --output <新交付目录>
```

对话执行时必须如实填写听审记录，不能仅根据声音测量、元数据或音乐名称虚构乐句判断。无听审时可以生成明确标注的技术试版，不能称为音乐审美已验收。

## 验证

完整测试：**624 passed，3个既有依赖弃用警告，45.08秒**。本轮新增21项测试，覆盖候选/确认听审规则、部分听审覆盖、音乐映射与明确停顿、区间/事件越界、禁止未经支持的变速、重排、原曲结尾误用、未知动作、镜头内部动作误差、局部快切约束、父版不可覆盖、字段差异、父版漂移和导出音乐改动拒绝。

仓库Skill validator通过，20个本地链接有效；官方quick_validate通过，git diff --check通过。安装后resolver与真实修订inspect通过。

[测试日志](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/validation/music-adaptation-20260910/tests.log)

## 真实数据功能验证

本轮用第二项约2.13秒的画面组和已有万岁山历史项目中冻结的106秒音乐做技术验证；不是重新确认该音乐适合当前成片，也没有更换原项目选曲。音乐源来自`travel-project-70811bf416`，画面组沿用第二项`travel-project-7b639731d7`的观察。本流程允许明确引用已冻结音乐项目与独立画面基准，两者来源各自保存。

第二版映射：

| 原曲区间 | 项目区间 | 用途 |
| --- | --- | --- |
| 0–1秒 | 0–1秒 | 开头候选片段，未听审 |
| 无音乐源 | 1–1.3秒 | 明确暂停音乐，原声保持 |
| 20–20.833333秒 | 1.3–2.133333秒 | 后部候选区间，未听审 |

第一版停顿为1–1.2秒。第二版延长0.1秒后保存6处字段变化，包含修订原因、停顿终点、后段映射及事件位置等。源音乐字节不变，原project_state、music_structure、music_asset与第二项基准EDL哈希均未改变。

车辆遮挡动作约在局部时间线1.466667秒，继承第一项约±0.133335秒误差。该动作位于第二镜头内部，音乐节点只是拟议响应，不宣称已经听到原曲该处有重音，也没有因此增加切镜。

生成FCPXML含2段画面和2段音乐，保留原视频原声。独立读取XML反算音乐源入点与项目起点，确认0.3秒音乐空段及映射一致。输出状态`fcpxml_generated`，源听审`not_listened`，混音听审`not_reviewed`；新包未在剪映验收。

[修订前](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/validation/music-adaptation-20260910/v1/adaptation.json)

[修订后及差异](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/validation/music-adaptation-20260910/v2/adaptation.json)

[导出收据](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/validation/music-adaptation-20260910/package/receipt.json)

[历史文件哈希检查](/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner/validation/music-adaptation-20260910/history-check.json)

本轮完成的是具备证据与版本约束的音乐适配能力。真实乐句判断、顺滑音乐拼接和成片情绪仍需实际听看。后续音效设计应使用这份映射与留白空间安排声音，不能靠增加音效掩盖未经听审的音乐接缝。
