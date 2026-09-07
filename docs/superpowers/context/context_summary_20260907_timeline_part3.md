# 第三部分：收尾时点与交付完整性修复

日期：2026-09-07。用户要求逐部分继续，本轮到此停止。

## 范围选择

- 先只读查找真实项目，找到 prototype/runs/travel-project-3d14b9a84b，输入为桌面“万岁山素材”，Brief 为 60 秒竖屏开封旅行片。
- `uv run travel-director status` 实测 needs_creative_direction / external_call_count=0，视觉分析已完成，但没有已保存的新创意方案可直接选曲。
- 异步询问用户选真实项目验收或先修时间线，尚未收到回复；已声明按后者继续。未推进或修改真实项目创意、音乐与素材。

## 完成

- Outro 允许传入 target_duration_seconds，按成片边界安排触发时间。60 秒原曲用于 30 秒时间线时，触发位置为 29 秒，不再为 59 秒。
- 截短时不使用原曲 ending 推断剪辑点行为，返回明确的未分析原因并暂不选额外 Outro SFX；Markdown 同样展示原因。
- 新增 director/timeline_delivery_store.py，生成 delivery/receipt.json，记录 JSON 与 Markdown 的 SHA-256，并将 receipt 哈希写入项目状态。
- 新交付完成、恢复运行、status 检查均验证交付 JSON、Markdown 和 receipt。缺失、修改、写入中断均不能报告 completed。
- 交付写入保留已有不同内容，使用原子文件写入。文件之间不是全事务；中断可能留下部分文件，但状态检查会阻塞，绝不自动宣称完成或覆盖旧文件。
- 旧交付没有 receipt 时明确 blocked，未实施旧交付迁移/修复命令。
- 换曲版本不继承旧 timeline_delivery_receipt，保留父项目；completed 的推荐时长改为实际目标时长，文案说明是占位方案。
- 更新 workflow.md 并同步全局 Skill，校验通过。

## 验证

- 全量：449 passed, 3 warnings in 23.94s；git diff --check 通过。
- 新测试覆盖截短和完整原曲、JSON/Markdown/receipt 缺失与漂移、旧版本无凭据、凭据写入中断、换曲隔离。
- 合成回归证据：外层 outputs/timeline-repair-audit-20260907/synthetic_30s_timeline.json 和 .md。路径和音效为测试样本，不代表真实音频混音或真实成片。
- 保留前两部分所有未提交修改，本轮新增修改也未提交 Git。

## 未做

真实项目创意与用户选曲验收、实际混音、剪辑点音频重新分析、SFX 冻结与路径完善、时间线阶段索引缓存接入、剪映导出、慢速可视化均未实施。候选推荐缓存已在上一部分完成。后续工作仍需分段；不要把当前 completed 当成最终视频完成。
