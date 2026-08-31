# Task 4 Qwen3-VL 4B MLX 实机结果

日期：2026-08-31

状态：`not_qualified`

## 结论

候选在 Apple M1 Pro 16 GB 上未进入首条推理即触发 swap 硬停止，不适合作为“旅行导演”的本地批量默认视觉模型。回退路径为 `scanner_only + assisted`；后续若接云端便宜大模型，应复用现有严格 JSON、弃权和人工复核合同。

## 制品与安装

- 模型：`mlx-community/Qwen3-VL-4B-Instruct-4bit`
- revision：`2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b`
- 权重：`3,093,767,283 bytes`，已跟随 snapshot 符号链接核验真实 blob。
- 运行时：项目内隔离的 `mlx-vlm==0.6.17`，52 个包。
- 隔离目录：约 `3.5 GB`，未触碰公共 Hugging Face 缓存。
- 普通 HTTP 单线程续传完成段耗时：`16m58s`。首次 Xet 请求持续出现 `IncompleteMessage`，已切换同一 revision 的普通 HTTP；未下载第二模型。

## 实机门结果

| 指标 | 实测 |
|---|---:|
| 冷加载 | `2.455409959s` |
| 运行前 swap | `1,343,162,941 bytes`（约 `1280.94 MiB`） |
| 观测 swap | `2,732,190,597 bytes`（约 `2605.62 MiB`） |
| swap 增量 | `1,389,027,656 bytes`（约 `1324.68 MiB`） |
| 硬停止上限 | `512 MiB` |
| 已完成推理 | `0` |
| JSON 成功率 | `not_measured` |
| 100 条投影 | `not_measured` |

冷加载后的 swap 增量达到硬门约 2.59 倍，因此立即停止。不能用冷加载时间代替推理速度，也不能据此声称“100 条需要多少时间”。

## 次要兼容问题

首条推理前，`apply_chat_template` 还暴露出 `jinja2` 未安装错误。由于 swap 硬门已经先失败，本轮没有补装依赖并重跑；否则会违反一次 smoke 的停止规则。

## 用户性能门

用户要求本地批量方案达到 100 条不超过 120 秒，即热态平均不超过 `1.2s/条`。代码已加入可测试的投影合同，但本候选未进入推理，无法参加该速度门。不能把缺失数据当作失败速度，也不能为了取得速度数字绕过资源硬门。

## 后续边界

1. Scanner 继续本地处理元数据、画质、运动和代表帧。
2. 画面语义理解保持可替换 Provider；当前默认 `scanner_only + assisted`。
3. 若采用云端便宜模型，先以同样的 2 条与 12 条固定集评估上传体积、单条成本、并发、严格 JSON 和禁区字段。
4. 模型缓存暂时保留在项目 `.cache/task4-vlm`，删除需要单独确认；权重、缓存和用户素材不进入 Git。

## 回归证据

- `uv run pytest tests/director/test_local_vlm_contract.py tests/director/test_visual_evaluation.py -q`：`14 passed`。
- `uv run pytest -q`：`175 passed, 3 warnings`。
- `git diff --check`：通过。
