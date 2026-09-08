# R04 阶段总结：同音乐时间线修订

对应 2026-09-08 修改清单 R04。

## 实现

- Runner/CLI 新增 `--new-timeline-revision`，要求已完成父项目及相同 input/brief；自动构建时间线，不允许同时导入音乐或响应。
- 新增 `director/timeline_revision.py`。子项目以父来源、算法源文件哈希、版本与默认配置确定身份；不重新扫描素材或分析音乐。
- `timeline_revision.json` 记录父路径、父状态/收据哈希、继承文件哈希、算法版本和默认配置；独立收据绑定该修订记录。
- 父版保持不变；重复相同请求复用同一个子项目；已完成修订不因音效库更新重新选音效。
- 创建时 staging 复制并校验，父源中存在软链接或发生变化则阻塞；仅清理本次创建的 staging。
- 生成失败保留子项目重试；未完成修订遇算法文件变化时阻塞，需从父项目发起新请求。
- 收据中断继续遵循现有保护策略：保留现场并阻塞，不自动覆盖修复。
- 支持恢复时校验继承文件与修订来源，必需音效约束在子项目重试中保留。
- 换曲版本不沿用旧时间线修订记录；Skill 和 README 已更新并同步安装副本，目录比较一致。

## 验证

- 修改前新增 3 项测试失败；最终修订聚焦测试 8 passed。
- 全量回归 484 passed、3 条原有 audioread 警告；随后仅新增收据中断和参数冲突两项测试，修订聚焦 8 项再次全部通过。
- git diff --check 通过。
- 真实案例经正式 CLI 执行两次：均 completed，返回同一项目，external_call_count=0。
- 原项目 5764 个文件逐文件哈希不变；重复请求后子项目 5763 个文件逐文件哈希不变。
- 新版 23 槽位，末端 60 秒；Hook 为 风声/CZG_Whoosh_007.wav + 上升音效/CZG_Hit_004.wav；Outro 保留截点未分析的 deferred 状态。

## 真实产物

- 父项目：`local-media-scanner/prototype/runs/travel-project-3d14b9a84b`。
- 新项目：`local-media-scanner/prototype/runs/travel-project-3d14b9a84b-timeline-e888731fc325da95`。
- 修订来源：新项目下 `timeline_revision.json`。
- 交付：新项目下 `delivery/fast_mode_timeline.json`、`delivery/timeline_delivery.md`、`delivery/receipt.json`。

## 边界

证据采用独立文件副本，会增加磁盘占用。绝对证据引用保留原来源。SFX 字节冻结、Outro 确定性与真实混音预览不在本项实现范围。目录库变化本身不改变同一父版/算法/配置请求的身份。新的 GitHub Actions 尚未执行，本次未推送或合并。

## 下一项 R05

音效字节可追踪与 Outro 确定性：稳定排序选择收尾音效，记录或冻结所选音效字节哈希，渲染前验证，避免同路径替换音效悄悄改变结果。R05 未实施。
