# Gemini Phase 1 报告复核与落地建议

日期：2026-09-07。范围：只读代码审查、测试复跑、最小复现；未修改功能、未调用外部服务。本文件为阶段性审查完成后的上下文备份。

## 已确认

- 权威代码：`.worktrees/local-media-scanner-v0.1/local-media-scanner`，分支 `feature/local-media-scanner-v0.1`，提交 `2fca13e`，该工作树检查时干净。外层 main 有原有未跟踪文件，不能笼统称全工作区干净。
- 全局 `$CODEX_HOME/skills/travel-director` 与仓库技能目录 `diff -qr` 一致。
- `.venv/bin/pytest -q` 实跑：429 passed, 3 warnings in 19.14s。
- `--build-timeline` 已接入 Runner，交付 JSON 与 Markdown；当前 completed 仅指占位时间线方案完成，不代表真实画面匹配、混音或剪映工程完成。
- 真实库“音乐”下有 40 个分类，“音效”下有 37 个支持格式文件。369 首及 98.92% 未重新完成逐曲索引验证。

## 阻碍实际使用的发现

1. audio_catalog.py:341-342 固定扫描 BGM/SFX，实际素材在 音乐/音效。默认 build_audio_catalog() 实测 0 tracks / 0 sfx。BGM/SFX 空目录在检查前已存在。
2. music_recommender.py 自建另一套 CatalogVersion（path），实际索引使用 relative_path；真实 schema 对接 recommend_music 复现 AttributeError: 'CatalogVersion' object has no attribute 'path'。推荐函数尚未被 Runner 调用。
3. outro_builder.py:70 用原曲时长安排收尾。测试构造原曲 60 秒、成片 30 秒，收尾触发在 59 秒；还需要分析选用区间的结尾行为。
4. Runner 仅根据 timeline_delivery 哈希键存在返回 completed，恢复路径未重新检查交付 JSON/Markdown 存在及内容；Markdown 未纳入完整性记录。
5. 音效只写相对路径，未携带根目录或冻结副本/哈希。目录异常和 Hook/Outro 异常被宽泛捕获，可能静默缺失包装却报告完成。
6. Hook/Outro 是规划；filter 函数尚未接入真实混音。Markdown 要求 Riser/Hit 都在 0 秒，与代码 Hit 默认 1.8 秒矛盾。
7. creative_sections 的 narrative_task/visual_plan 已继承，但 desired_motion 仍来自音乐段落的 low/medium/high 默认值，不能声称已经理解并继承具体创意运镜。
8. 现有测试主要使用模拟数据，未覆盖真实目录与模块连接；429 passed 不等于真实使用验收。

## 推荐实施顺序与验收

1. Phase 1 修复：真实目录可配置且缺目录显式报错；统一索引 schema；缓存索引；推荐接入 waiting_for_music（展示候选与理由，由用户选定后冻结）；SFX 冻结；按成片边界规划收尾；明确降级状态；校验交付物与恢复幂等；统一 Markdown 与 JSON 时间参数。
2. 真实快速模式试点：同一项目、本地选定音频与真实素材，输出可读时间线和可试听混音；验证路径、时长、首尾、无素材修改、恢复与换曲隔离。媒体相关实现先按适用技能要求执行。
3. 可视化填充：复用已验证代表帧，每槽位记录 material_id、源片段 in/out、证据、匹配理由、置信度和缺口；低置信度留空。稀疏帧不足以证明整段可用，精确入出点需局部复核。
4. 剪映导出技术验证：先查当前库文档、安装版本及本机剪映版本；新建独立最小草稿测试双视频、BGM、Riser、Hit、Outro 和音量关键帧，在实际剪映打开并导出。兼容性未实测，不承诺 pyJianYingDraft 已可在本机使用。
5. 环境音：依据镜头证据与创意意图形成可关闭建议；航拍不自动等于应有无人机声，古城/戈壁不自动等于应有驼铃。区分现场声与后期设计音效。

保留 Skill + Runner 主入口。历史独立盲测标注缺失不在本轮恢复范围，不能把旧记忆中的阻塞状态当成当前已核实状态，也不能据单元测试宣称视觉语义准确率已过验收。
