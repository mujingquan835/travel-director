# Local Media Scanner V0.1 暂停检查点

暂停时间：2026-08-27（Asia/Shanghai）

> 状态：已恢复开发。本文件作为当时的历史检查点保留；Detector 的当前进展以后续 Git 提交和 `EXPERIMENTS.md` 为准。

## 安全恢复位置

- 主项目：`/Users/meimaodawang/Documents/旅行导演`
- 隔离 worktree：`/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1`
- 开发分支：`feature/local-media-scanner-v0.1`
- 已完成检查点：`1721042 feat: freeze 30-video ground truth set`
- 主分支未被合并，实现仍只在隔离 worktree 中。

## 已完成

1. 严格 Scanner Schema 与开发者 CLI。
2. 272 条真实视频的 FFprobe 元数据盘点。
3. `temporal3` / `adaptive5` 稀疏代表帧，支持显式 VideoToolbox 模式。
4. 未校准的清晰度、曝光、光流和运动原始证据。
5. 从 272 条中确定 30 条测试集，并在任何检测器/SigLIP 运行前冻结 Ground Truth。
6. Ground Truth 验证通过：30 个唯一文件，与 manifest 完全对应；根目录和 benchmark 副本字节一致。
7. 在开始 Detector 任务前，全套 30 项测试通过。

## 已知证据与问题

- 272 条素材：46.8523 分钟，20,330,842,680 字节。
- 30 条冻结集：7.94 分钟，2,983,893,228 字节。
- 30 条人工审阅抽帧共 111 张，累计解码/提取 238.08 秒。
- 一条竖拍马术素材在当前抽帧路径仍侧置，旋转处理缺陷未修。
- 两条近黑/严重遮挡素材已标为 `unusable` 并主动弃权内容字段。
- 即梦 CLI 已安装，但 Scanner V0.1 没有调用；未登录、未生成、未消耗积分。

## 当前故意未完成的状态

- 已新建 `local-media-scanner/tests/test_detector.py`，用于锁定人物计数、低分过滤和物体聚合契约。
- 该测试当前应失败：`ModuleNotFoundError: No module named 'scanner.detector'`。这是 TDD 的预期红灯，不是回归缺陷。
- 尚未执行 `uv sync --extra dev --extra vision`；Torch、Torchvision 和 SigLIP2 模型尚未因本阶段下载。

## 恢复后的下一步

1. 进入 `.../.worktrees/local-media-scanner-v0.1/local-media-scanner`。
2. 实现 `scanner/detector.py` 的数据契约和纯聚合逻辑，先让 `tests/test_detector.py` 通过。
3. 再安装 vision 依赖，记录确切版本、下载体积和缓存路径。
4. 实现 Torchvision SSDLite 适配器，在冻结的前 5 条上做 CPU 本地 smoke test，不修改 Ground Truth。

## 恢复核验命令

```bash
cd "/Users/meimaodawang/Documents/旅行导演/.worktrees/local-media-scanner-v0.1/local-media-scanner"
git status --short
git log --oneline -6
uv run pytest -q
uv run pytest tests/test_detector.py -q
```

`uv run pytest -q` 在 detector 模块实现前会因新增的红灯测试失败；恢复时应先按上述顺序完成 Task 6。
