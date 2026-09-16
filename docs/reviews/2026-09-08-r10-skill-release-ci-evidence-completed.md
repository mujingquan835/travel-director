# R10 Skill 发布与 CI 证据完成记录

日期：2026-09-08
范围：补齐 Skill 安装、发布收据、仓库校验与 GitHub Actions 证据；不修改时间线、音乐分析、音频包装建议或素材。

## 结论

R10 已完成。仓库现在可以在不依赖开发者家目录的环境中校验和隔离安装 Skill，并留下可下载的发布收据。GitHub Actions 已对实现提交实际运行成功，但当前私有仓库的 GitHub 计划不支持分支保护，因此这些检查尚未成为 GitHub 强制的合并门禁。

## 发布与安装

- 新增 `skills/travel-director/scripts/validate.py`，仅用 Python 标准库检查 frontmatter、Skill 名称、必需文件、CLI 入口、本地 Markdown 引用、越界链接和符号链接。
- 安装成功后原子写入 `${CODEX_HOME}/skill-receipts/travel-director.json`，记录 Git checkout、`git_dirty`、运行包版本、`pyproject.toml` SHA-256、逐文件 SHA-256、manifest SHA-256 和备份路径。
- 替换安装继续把旧副本保存在 `${CODEX_HOME}/skill-backups/`；发布或收据写入失败会恢复旧副本。
- `__pycache__`、`.pyc` 和 `.pyo` 不进入校验文件数、安装副本或发布 manifest，避免本地运行缓存改变发布身份。
- 当前发布集合固定为 7 个文件，仓库 validator 校验 6 个本地引用。

## quick validator 语义

- 仓库自包含 validator 是 CI 必须通过的步骤，失败会使工作流失败。
- 官方 Codex `quick_validate.py` 是补充检查。本机文件存在并实际返回 `Skill is valid!`。
- GitHub runner 没有安装官方 validator，CI 明确输出 `Optional Codex validator skipped` notice；这表示该补充检查没有执行，不等于官方校验通过。
- 测试汇总中的 1 个 skipped 就是上述环境缺失。它不会替代或跳过仓库 validator。

## GitHub Actions 证据

实现提交 `7213b04dc731e85fe7b2601bfe96f1aec048b57f` 的 [CI run 34200493747](https://github.com/mujingquan835/travel-director/actions/runs/34200493747) 成功：

- PR diff 检查通过。
- 仓库 validator 通过：7 个文件、6 个本地引用。
- 隔离 CI home 安装通过。
- 全量测试：`537 passed, 1 skipped, 3 warnings`；与本机 `538 passed, 3 warnings` 的差异仅为 runner 缺少官方 quick validator。
- 发布收据 artifact `travel-director-release-1103ddd0d8d367716c812e380aa9f6307728d8ba` 上传成功，artifact ID `10045698143`。artifact 名称和收据中的 Git 提交是 PR 测试 checkout 的临时合并提交；对应功能分支头为 `7213b04dc731e85fe7b2601bfe96f1aec048b57f`。
- 下载核对的收据为 `git_dirty=false`、运行包版本 `0.1.0`、7 个文件，manifest SHA-256 为 `f68de8a3ac4dd9135cc8dfc05600dac7b32c46cfb0071bc1d85a4af24433c811`。
- 收据上传动作已固定到官方 `actions/upload-artifact v7.0.1` 提交 `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`，该版使用 Node 24；成功运行中不再出现旧版 Node 20 警告。

## 失败运行保留

R10 首次两次远端运行没有通过，不能从记录中省略：

- [run 34198631852](https://github.com/mujingquan835/travel-director/actions/runs/34198631852)：PR diff 检查发现两份既有阶段文档的行尾空格；后续步骤未执行。
- [run 34198913448](https://github.com/mujingquan835/travel-director/actions/runs/34198913448)：仓库 validator、隔离安装和 diff 检查通过；全量测试因 Rich 在 Linux 终端宽度下折行，导致 CLI 帮助文本断言失败。断言已改为读取 Typer 参数元数据，不再依赖终端渲染宽度。

这两次失败用于证明门禁确实能发现问题，最终通过证据以 run 34200493747 为准。

## 分支保护限制

对 `main` 和 `feature/local-media-scanner-v0.1` 查询 GitHub branch protection API 均返回 HTTP 403：当前私有仓库需要升级 GitHub Pro 或改为公开仓库才能启用该功能。因此本轮没有启用 required checks，也不把“工作流运行成功”表述为“GitHub 已禁止未通过检查的合并”。

## 本地验证

- 仓库 validator：`status=valid`，7 个文件，6 个本地引用。
- 官方 Codex quick validator：`Skill is valid!`。
- R10 Skill 测试：`15 passed`。
- 全量回归：`538 passed, 3 warnings`。
- 3 条警告仍来自 `audioread` 在 Python 3.12 导入已弃用的 `aifc`、`audioop`、`sunau`；R10 未新增测试警告。
- `python3 -m py_compile` 与 `git diff --check` 通过。

## 下一项

R11：配置错误、性能与依赖维护。先处理显式音效库配置错误的可见性，再评估目录缓存复用和各阶段耗时证据；不在同一轮顺带升级 Python 或删除音频依赖。
