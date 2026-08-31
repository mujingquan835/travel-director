# Task 4 本地 VLM 制品审计与下载授权门

日期：2026-08-31

状态：`executed_not_qualified`

结论：用户已批准并完成一次受控下载；冷加载后触发 swap 硬停止，0 条进入推理，候选不合格。实测见 `2026-08-31-qwen3-vl-4b-mlx-smoke-result.md`。

## 唯一候选

| 项目 | 锁定值 |
|---|---|
| 模型 | `mlx-community/Qwen3-VL-4B-Instruct-4bit` |
| 模型 URL | <https://huggingface.co/mlx-community/Qwen3-VL-4B-Instruct-4bit> |
| revision | `2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b` |
| 许可证 | Apache-2.0 |
| 仓库精确体积 | `3,109,732,071 bytes`，约 `3.110 GB / 2.896 GiB` |
| 权重 | `model.safetensors`，`3,093,767,283 bytes` |
| 量化 | MLX affine 4-bit，group size 64 |
| 原模型 | `Qwen/Qwen3-VL-4B-Instruct`，Apache-2.0 |
| 转换声明 | 模型卡声明由原模型使用 `mlx-vlm 0.3.4` 转换；未给出原模型精确 revision，因此能力验证必须把该 MLX revision 自身视为被测制品 |
| 运行时 | `mlx-vlm==0.6.17`，MIT，<https://pypi.org/project/mlx-vlm/0.6.17/> |
| 运行时 wheel | `mlx_vlm-0.6.17-py3-none-any.whl`，`2,590,205 bytes`，SHA-256 `d24723244ef89b2a6140bec45e38c078689ea89450edfc0e348ad149f5af3b1c` |
| 兼容状态 | `not_verified`；模型转换版本与当前运行时不同，必须以 2 条本机 smoke 为准 |

官方依据：Hugging Face 模型 API/文件树、候选模型卡、Qwen 原模型卡、MLX-VLM 官方仓库与 PyPI 元数据。审计只读取页面、JSON 和小型配置文件，没有下载权重。

## 下载与隔离预算

- 机器：Apple M1 Pro，16 GB 统一内存；审计时数据卷约 315 GiB 可用。
- 当前 Hugging Face 公共缓存约 530 MiB，不修改、不清理。
- 独立运行环境：`local-media-scanner/.cache/task4-vlm/venv`。
- 独立模型缓存：`local-media-scanner/.cache/task4-vlm/huggingface`。
- 实验结果：`local-media-scanner/benchmark/runs/task4-local-vlm/`，当前规则已 gitignore。
- `uv --dry-run --no-cache` 在空 Python 3.12 环境解析为 52 个包；尚未下载这些 wheel。
- 授权预算：网络传输最多 3.5 GB，新增磁盘占用最多 5 GB。任一预计值或实际值超限，停止，不继续下载。
- 只允许一次模型下载；失败后不换第二个模型、不并行拉取原始 8.89 GB 模型。

拟执行安装与下载方式（尚未执行）：

```bash
uv venv .cache/task4-vlm/venv --python 3.12 --no-python-downloads
uv pip install --python .cache/task4-vlm/venv/bin/python 'mlx-vlm==0.6.17'
HF_HOME="$PWD/.cache/task4-vlm/huggingface" .cache/task4-vlm/venv/bin/python <受控下载脚本>
```

可恢复卸载方式：先确认目录为当前项目内的 `.cache/task4-vlm`，再删除该单一目录；不会触碰公共 `~/.cache/huggingface`、原始视频或其他项目环境。

## 两条 smoke 清单

两条均来自已冻结开发集，不接触盲测答案；每条仅输入 4 张已保存 probe 图，长边最多 768 px，temperature 0，输出最多 384 tokens。

1. `2026_02_06_18_26_40_IMG_0229.MOV`：横屏，12.631667 秒，4 张 probe。
2. `2026_02_07_14_08_15_IMG_0406.MOV`：竖屏，37.318333 秒，4 张 probe。

每条记录：加载/推理 wall time、进程树峰值 RSS、运行前后 swap、JSON 解析结果、必需字段覆盖、弃权字段、禁区字段检查和错误。

## 硬停止条件

- 进程树 RSS 达到 11 GiB。
- 相对运行前新增 swap 达到 512 MiB，或系统出现持续内存压力。
- 任一 smoke 导致 OOM、进程崩溃或无法恢复的 Metal 错误。
- 同一响应严格解析失败后，最多一次格式修复仍失败。
- 输出无法弃权，或确定性声称具体地点、人物身份、事件、导演职责、素材优先级、`source_in/source_out`。
- 任何下载或落盘预计超过上述授权预算。

触发后将候选标记为 `not_qualified`，回退 `scanner_only + assisted`，不尝试第二模型。

## 授权问题

是否批准按以上锁定值安装隔离运行时并下载一次约 3.110 GB 的模型制品，在网络传输 3.5 GB、落盘 5 GB、RSS 11 GiB 的上限内执行两条 smoke？在收到明确“批准下载并运行 smoke”之前，Task 4 停在此门。
