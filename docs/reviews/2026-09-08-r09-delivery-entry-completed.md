# R09 交付保存入口收敛完成记录

日期：2026-09-08  
范围：只调整时间线交付与验证导出的保存边界，不修改时间线算法、音乐分析、音频包装建议或素材。

## 结论

正式 Runner 原本已经使用带收据的 `timeline_delivery_store.record_timeline_delivery`，因此不存在正式流程普遍丢失收据的问题。R09 收敛的是另一个容易误用的无收据直写函数。

## 完成内容

- 将 `save_fast_mode_delivery` 改名为 `export_fast_mode_validation_artifacts`，删除“两文件原子保存”的错误说明。
- 正式项目时间线的唯一完成入口为 `record_timeline_delivery`。它继续绑定 JSON、Markdown、`receipt.json` 和项目状态哈希，并在返回完成前统一验证。
- 验证导出明确不生成 `receipt.json`、不更新项目状态，也不代表 completed。
- 验证导出拒绝写入名为 `delivery` 的目录；识别到项目根目录时，只允许写入该项目的 `validation/` 子目录。
- 验证文件采用单文件临时文件加 `os.replace`；单文件替换失败时保留已有目标文件并清理临时文件。JSON/Markdown 两文件不宣称为事务，发生中断后应检查或丢弃该验证目录。
- 尝试用不同内容替换已完成正式时间线时，在写入前阻塞，并保持项目全部旧字节不变。
- Skill、workflow、README 和历史验证命令已经使用新的命名并明确 formal delivery 与 validation artifact 的区别。

## 验证

- R09 相关测试：`56 passed`。
- 全量回归：`533 passed, 3 warnings`。
- 3 条警告仍来自 `audioread` 使用 Python 3.12 已弃用的 `aifc`、`audioop`、`sunau`，R09 未新增警告。
- `python3 -m py_compile` 与 `git diff --check` 通过。
- 全仓搜索不再存在 `save_fast_mode_delivery` 调用或文档示例。
- 仓库 Skill 与 `/Users/meimaodawang/.codex/skills/travel-director` 同步一致。

## 真实项目恢复验证

项目：`local-media-scanner/prototype/runs/travel-project-3d14b9a84b-timeline-e888731fc325da95`

- 在禁止 `subprocess.run` 的条件下恢复项目，返回 `completed` / `timeline_delivery`。
- 返回正式 `timeline_delivery`、`timeline_markdown` 与 `timeline_receipt` 路径。
- `external_call_count=0`。
- 恢复前后项目 5,794 个文件的 SHA-256 清单完全一致，没有重写交付、素材或历史建议。

## 下一项

R10：补齐 Skill 发布与 CI 证据。重点核对安装器验证、GitHub Actions 实际检查与 quick validator 的 skip 语义，不能把存在 CI 文件误报为分支保护已经启用。
