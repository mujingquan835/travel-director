# 第二项：局部镜头组与导出证据接入

2026-09-10。状态：第二项程序与 Skill 调整完成，已安装本机；未提交 Git、推送或执行本轮 GitHub CI。真实两镜头 FCPXML 已生成，未在剪映验收新包，也未评价最终观感。

## 已实现

- 独立 2–4 镜头组合同，记录镜头顺序、源区间、叙事职能及理由。
- 每个相邻连接必须引用左右两侧的精看 request、candidate 和帧证据；程序核验素材、精看结果、源区间与邻接关系。
- 动作锚点直接继承原动作时刻与误差，不能在组合计划里另填更小误差。普通边界帧保留对应样本窗口。源窗口转换到局部时间线后仍保留双侧误差；精确执行切点不冒充精确观察时刻。
- `supported`、`intentional_cut`、`needs_review` 分别表示有依据的连接、有意硬切/反差、待精看。待精看组合可保存，但不产生可导出的 EDL。未知运动不能变成已支持的运动匹配。
- 程序生成连续时间位置、总时长及绑定后的 `edit_decision.json`。生成过程不重扫素材、不重新调用模型、不改变音乐或音效。
- FCPXML 导出器真正消费 `shot_group` 绑定：重新验证镜头组和双侧精看证据，检查视频顺序、源路径、区间、增益、时间位置和画布是否一致。校验失败时不创建新交付包。
- 交付包增加 `shot_group.json`；receipt 保存快照哈希、精看哈希和连接的双侧时间窗口。额外音频仍可按原流程添加，但不能篡改已绑定的视频决策和总时长。
- 旧无绑定决策保持兼容，不会获得镜头组校验声明。此轮不改 Runner 状态图和八字段粗看合同。

## 文件及调用

源码根：`<checkout>/local-media-scanner`。

- [镜头组实现](<checkout>/local-media-scanner/director/shot_group.py)
- [镜头组合同](<checkout>/local-media-scanner/director/shot_group_schema.py)
- [Skill 使用说明](<checkout>/local-media-scanner/skills/travel-director/references/shot-group.md)
- [导出器](<checkout>/local-media-scanner/director/fcpxml_delivery.py)
- 安装入口：`$CODEX_HOME/skills/travel-director/SKILL.md`，调用名 `$travel-director`；安装回执绑定当前工作树运行文件哈希，resolver 核验通过。

从源码根运行：

```bash
uv run travel-director build-shot-group --plan <局部组合计划.json> --output <新目录>
uv run travel-director inspect-shot-group --group <返回的group.json>
uv run travel-director export-fcpxml --decision <返回的edit_decision.json> --output <新交付目录>
```

计划结构详见 Skill 说明。新组必须引用已提交的精看结果。修改原镜头组时用新输出目录保留历史，不通过删除绑定绕过导出校验。

## 验证

完整测试：**603 passed，3 个既有依赖弃用警告，39.92 秒**。较第一项增加 23 项测试，覆盖2/3/4镜头、邻接完整性、双侧锚点、继承误差、未知运动、未解决连接、EDL换序/改区间/改时间/改画布、源证据破坏、不可覆盖组、追加音频与真实FCPXML物化。

仓库 Skill validator 通过，16 个本地链接有效；官方 quick_validate 使用项目 uv Python 运行通过（系统 Python 缺 yaml，未安装额外依赖）；`git diff --check`通过。安装后再次核验 resolver 与真实镜头组。

[完整测试日志](<checkout>/local-media-scanner/validation/shot-group-20260910/tests.log)

## 真实两镜头验证

沿用万岁山项目 `travel-project-7b639731d7`，没有重扫 270 段素材。

1. 读取原粗看并新增 IMG_0229.MOV 的 4.8–6.2 秒局部精看：道路、车流、标线构成环境，动作起止未明确，保留未知。
2. 复用第一项 IMG_0230.MOV 的 2.8–3.9 秒精看结果：前景白色车辆遮挡。
3. 组合为环境→侧向车辆细节，使用 **intentional_cut / hard_cut**。没有充分证据证明两侧运动匹配，因此不声明无缝连接或真实事件因果。
4. 第一镜头选择4.8–6.0秒，第二镜头2.935–3.868333秒；组合总长 **2.133333秒**，切点位于1.2秒。
5. 左侧边界证据5.866667–6.133333秒、右侧2.801667–3.068333秒，约±0.133秒的采样窗口分别保留。组与导出收据都含这些信息。
6. 直接从绑定EDL生成FCPXML，独立读取XML核对2段视频的源入点、时长、顺序及时间位置。保留原声gain=1，没有新加音乐或音效；原声听感未审。

[局部组合计划](<checkout>/local-media-scanner/validation/shot-group-20260910/plan.json)

[已验证镜头组](<checkout>/local-media-scanner/validation/shot-group-20260910/group/group.json)

[真实FCPXML](<checkout>/local-media-scanner/validation/shot-group-20260910/package/project.fcpxml)

[导出收据](<checkout>/local-media-scanner/validation/shot-group-20260910/package/receipt.json)

以上是功能验证素材，不是替换用户原草稿的新成片。`fcpxml_generated` 与 `shot_group_validated` 都不等于实际剪映客户端验收或审美合格。

## 边界与后续

镜头组合由会话撰写，程序校验不能证明故事或连接一定好看。当前可结构化验证运动、动作、景别/主体位置等依据；颜色/形状匹配尚无独立精看字段，不应编造为已验证条件。没有新增转场、变速或帧网格吸附，源时间保持显式的秒/微秒表示。新的剪映包仍需实际导入、播放、修改、保存重开验证。

下一项音乐适配可以使用已明确的镜头组职能和连接窗口，提出“保留组内动作、允许哪些边界在窗口内移动”的修订；不能让自动节拍覆盖动作证据或把采样误差当任意剪辑空间。本轮不继续修改第三项。
