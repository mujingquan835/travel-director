# 旅行导演 Task 4 本地 VLM 结束上下文

日期：2026-08-31

权威工作区：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`

分支：`feature/local-media-scanner-v0.1`

## 阶段结论

- 唯一候选 `mlx-community/Qwen3-VL-4B-Instruct-4bit@2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b` 已完成一次受控下载和制品核验。
- 冷加载 `2.4554s` 后，首条推理前 swap 增量约 `1324.68 MiB`，超过 `512 MiB` 硬停止门。
- 推理数为 0；JSON质量和“100条不超过120秒”均未测，不得补写估算结论。
- 候选状态为 `not_qualified`；不补 `jinja2` 重跑、不试第二本地模型，默认回退 `scanner_only + assisted`。

## 已实现合同

- 本地 Provider 的严格响应解析、禁区字段拒绝、低置信度人工复核保持有效，可供未来云端 Provider 复用。
- 新增热态吞吐投影合同：输入实测单条时间，判断 100 条是否不超过 120 秒；该合同已通过单元测试，但本候选没有可输入的真实推理时间。

## 本地状态

- 模型与隔离运行时保留在 `local-media-scanner/.cache/task4-vlm`，约 `3.5 GB`，已忽略，不提交。
- 实验原始结果保留在 `local-media-scanner/benchmark/runs/task4-local-vlm/`，已忽略，不提交。
- 详细报告：`docs/superpowers/audits/2026-08-31-qwen3-vl-4b-mlx-smoke-result.md`。
- 下一实施任务：Task 5 用户描述规范化与确认；不依赖本地 VLM。

## 后续模型策略决定

- 用户决定后续 Skill 不绑定任何具体模型：由哪个智能体调用，就使用该智能体的默认模型和视觉能力。
- 项目不新增 Codex API、固定模型名或供应商配置；调用方智能体输出仍受严格 JSON、候选状态、弃权和人工确认约束。
- 批量画面理解采用每条一张联系图、每批最多 10 条、逐批 JSON 检查点；调用方不能读图时回退 `scanner_only + assisted`。
