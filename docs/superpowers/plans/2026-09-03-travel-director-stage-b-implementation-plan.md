# Travel Director 阶段 B 薄封装实施方案

> **历史记录／部分过期：** 本文的薄封装方向仍有效；四状态、`completed` 终点和阶段 C 复用结论已被两段式项目合同取代。
>
> 当前唯一基线：[`../context/2026-09-04-travel-director-two-stage-project-contract-context.md`](../context/2026-09-04-travel-director-two-stage-project-contract-context.md)。

> 日期：2026-09-03
>
> 历史状态：已实施并通过当时回归；后续验收结论见上方更正
>
> 权威工作树：`<checkout>`

## 1. 目标

把阶段 A 已实现的幂等 `travel-director run` 接入正式 `$travel-director`，使用户只需提供本地素材目录和自然语言创作描述。

本阶段是薄封装，不重写 Director，不新建 Skill，不重构底层 CLI。

## 2. 实施范围

1. 正式 Skill 只调用 `travel-director run`，`status` 仅用于诊断恢复状态。
2. Skill 根据四种状态续跑：
   - `needs_visual_observation`
   - `needs_user_confirmation`
   - `completed`
   - `blocked`
3. 视觉观察契约只在需要读取联系表时加载。
4. 少量聊天确认只写简单答案，Runner 负责生成带 hash 的现有严格确认产物并调用现有校验器。
5. 超过 5 个字段或 3 条素材时，仍使用现有本地确认页。
6. 最终结果继续以 `final_summary.json` 为机器真相，不新增 Markdown 输出层。

## 3. 简单答复契约

Brief 聊天答复：

```json
{
  "kind": "brief",
  "answers": {
    "style": "纪实",
    "mood": "探索",
    "rhythm": "medium"
  }
}
```

视觉字段答复：

```json
{
  "kind": "visual",
  "answers": [
    {
      "material_id": "sha256:<material-id>",
      "field": "lighting",
      "value": "daylight"
    }
  ]
}
```

用户拒绝必要确认时，将 `status` 写为 `declined`；下一次 `run` 返回 `blocked`，不生成提示词。

## 4. 实际修改

- `local-media-scanner/director/runner.py`
  - `RunAction` 新增 `response_path` 和按素材分组的 `review_questions`。
  - 新增 Brief 和视觉简单答复模型。
  - 简单答复转换为现有 `BriefConfirmation` 或 `VisualConfirmation`。
  - 继续使用现有 hash 和严格校验函数。
- `local-media-scanner/skills/travel-director/SKILL.md`
  - 删除十步内部编排，只保留单入口、四状态、边界和最终输出。
- `local-media-scanner/skills/travel-director/references/workflow.md`
  - 从逐命令手册收缩为恢复和简单答复参考。
- `local-media-scanner/tests/director/test_runner.py`
  - 覆盖 Brief 答复转换、视觉答复转换和拒绝后阻断。
- `local-media-scanner/tests/director/test_travel_director_skill.py`
  - 改为行为契约测试，不再校验旧十步文案。

## 5. 未修改内容

- Director 规则、角色分配、项目覆盖和提示词推荐逻辑。
- Ground Truth、blind annotation、Task 1 评估器和 Task 3。
- 现有底层 CLI 命令及旧原型实现。
- 本地视觉推理路线、曲多多、即梦、Codex API 或任何外部服务。

## 6. 验证记录

- 定向回归：`17 passed`。
- 全量回归：`312 passed, 3 warnings`。
- 3 条 warning 均为现有 `aifc` / `audioop` / `sunau` 弃用警告。
- Skill 结构校验：`Skill is valid!`。
- 临时安装目录与仓库 Skill 源文件一致。
- 正式 Skill 已安装到 `$CODEX_HOME/skills/travel-director`，旧版由安装器备份。
- 未运行真实视频，未调用独立模型或外部服务。

## 7. 下一停止点

阶段 B 完成后未进入底层 CLI 分层或旧代码清理。阶段 C 已复用现有 12 条真实素材 Director 项目完成两次恢复调用，没有重新扫描；当前无必做后续阶段。
