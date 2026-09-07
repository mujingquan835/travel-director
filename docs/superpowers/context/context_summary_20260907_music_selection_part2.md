# 第二部分：本地选曲流程接通

日期：2026-09-07。按用户要求分段实施，停止在音乐选择与冻结分析范围。

## 已完成

- 权威目录：`.worktrees/local-media-scanner-v0.1/local-media-scanner`。保留上一部分未提交修改，没有重置或混入其他任务。
- Runner 的 waiting_for_music 输出 `artifact_paths.music_recommendations`，指向项目 `music_selection/recommendations.json`。候选含标题、版本、实测时长、理由、绝对路径。最多 5 首；不足时不凑数。
- 用户选择后由 Skill 用现有 `--music <version_path>` 入口导入，复用冻结与分析机制；不自动选择第一首，也不自动 build-timeline。
- 库不可用或无匹配时返回明确状态，保留本地上传与外部生成音乐的既有流程。
- 推荐仅接受时长大于等于目标且不超过 600 秒的版本；优先 +10 秒以内预制版本，否则取最短合格版本。
- 新增 audio_catalog_cache.py。缓存位于 `~/.cache/travel-director/audio`，可通过 TRAVEL_DIRECTOR_AUDIO_CACHE 覆盖；文件路径、目录、大小、mtime_ns、ctime_ns 形成清单签名，增删改后刷新；坏缓存重建，扫描期间变动则提示重试。缓存不替代选定音频的内容哈希冻结。
- 相同候选内容不重写项目推荐文件，原子替换缓存与推荐 JSON。
- 仓库 SKILL.md / references/workflow.md 已更新，同步至全局 `/Users/meimaodawang/.codex/skills/travel-director`，字节一致及 skill-creator quick_validate 验证通过。

## 验证

- 全量回归：438 passed, 3 warnings in 18.34s。警告为原有 Python 音频模块弃用警告。
- 新增真实 WAV/ffprobe 缓存复用、增改删失效、坏缓存重建测试；推荐短曲及超长曲排除测试；Runner 选曲冻结重跑与库不可用备用导入测试。
- 集成测试使用模拟视觉项目和真实生成音频，模拟用户通过 --music 选择后，达到 waiting_for_timeline；原音频内容不变，重跑项目内容不变，external_call_count=0。
- 真实用户音乐库扫描：385 音乐条目，37 音效。首次约 61.85 秒，缓存命中约 0.08 秒，缓存数据相同。
- “旅行，古城，轻松”/60 秒真实推荐返回 5 首；全部文件存在，全部满足 60–600 秒时长条件。
- 证据：`outputs/audio-catalog-audit-20260907/part2_cache_recommendations.json`（外层目录）。
- git diff --check 通过。所有功能修改仍未提交 Git，包含第一部分遗留修改。

## 未完成与下一步边界

- 本轮异步询问真实项目，尚未收到选择；未替用户绑定音乐。真实项目中由用户选曲的完整验收仍待实际使用，不应将模拟集成测试称为真实项目验收。
- 未修改 Outro 时点、混音、时间线完整性验证或剪映导出。
- 此缓存只接入推荐阶段；旧时间线构建仍直接全库扫描，留待该阶段单独处理。
- 推荐仍为关键词/分类匹配，不代表试听质量判断或独立歌曲去重。目录修改会触发全量重建，尚非单文件增量索引。
- 下一轮优先真实项目选曲验收；后续再修复收尾时点与交付恢复校验。
