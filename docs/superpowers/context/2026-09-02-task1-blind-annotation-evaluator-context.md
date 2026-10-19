# V0.3 Task 1：Ground Truth 恢复与正式盲测评估器

日期：2026-09-02

状态：完成

权威工作区：`<checkout>`

分支：`feature/local-media-scanner-v0.1`

实施基线：`d044526 feat: add independent blind annotation review`

## 完成范围

- 从用户确认的可靠派生文件 `/tmp/blind_annotation_summary.json` 恢复 blind-v1 评估所需 Ground Truth。
- 恢复制品保存于 Git 忽略目录：`local-media-scanner/benchmark/manual_review/travel-director-skill-blind-v1/blind_annotation.local.json`。
- 恢复制品通过 `validate-blind-annotation`。
- 新增正式 CLI：`travel-director evaluate-blind-annotation`。
- 新增版本化 `0.3.0` JSON 报告，固定记录 split、Brief、annotation、raw observations、assisted observations 和 intent decisions 的 SHA-256。
- raw 与 assisted 视觉指标分开计算；枚举字段报告 coverage、covered accuracy、end-to-end accuracy 和具体未覆盖/不匹配素材。
- `content_families` 报告固定标签全集、zero-division=0、逐标签指标、micro/macro F1 和 exact-set accuracy。
- Director 报告 bucket accuracy、完整 confusion matrix、逐职责 precision/recall/F1、micro F1 和 exact-set accuracy。
- membership、Brief 哈希、Ground Truth 完成状态、assisted 完成状态和 intent decisions 完成状态均为硬门。

## Ground Truth 恢复血缘

- 删除前原附件路径：`<downloads>/blind_annotation.json`
- 记录的原附件 SHA-256：`dda2c751aba3de2fa5a718a3c6861b694c20ff527ed2a4367f5c192c74693f1b`
- 派生恢复源 SHA-256：`0104d97dd7067c3e64b838cfbb92f33d4baeb3d9bd8707120db07a76df2ff7c5`
- 当前恢复制品 SHA-256：`4fbc9536a3be610f4451ac9d98f8e6ffbe6b9c4492c683c41a10dde3f2584749`
- 恢复了 12 条素材的六个正式视觉评估字段，以及 12 条 Director bucket/function 标签。
- 未恢复视觉主体/动作短词、视觉备注和原始 JSON 字节排版；当前制品不宣称与删除前附件字节相同。

详细恢复说明：`local-media-scanner/benchmark/manual_review/travel-director-skill-blind-v1/RECOVERY.md`。

## 正式命令

```bash
uv run travel-director evaluate-blind-annotation \
  --split benchmark/director_visual_split.json \
  --brief-confirmation benchmark/runs/travel-director-skill-blind-v1/visual/brief_confirmation.json \
  --annotation benchmark/manual_review/travel-director-skill-blind-v1/blind_annotation.local.json \
  --raw-observations benchmark/runs/travel-director-skill-blind-v1/visual/drafts/clip_observations.merged.json \
  --assisted-observations benchmark/runs/travel-director-skill-blind-v1/visual/clip_observations.json \
  --intent-decisions benchmark/runs/travel-director-skill-blind-v1/visual/intent_decisions.json \
  --output benchmark/manual_review/travel-director-skill-blind-v1/evaluation_report.json
```

## 冻结基线结果

- 正式报告 SHA-256：`f3eda5b542120d4c71977dd38c2ecf8c94cdb9b07db0c5445cad01d1e0368b08`
- 样本数：12
- raw `content_families` micro F1：`0.42105263157894735`
- assisted `content_families` micro F1：`0.47619047619047616`
- raw `people_presence` end-to-end accuracy：`0.8333333333333334`
- assisted `people_count_band` end-to-end accuracy：`0.25`
- Director bucket accuracy：`0.5`
- Director function micro F1：`0.5833333333333334`
- Director function exact-set accuracy：`0.0`
- `external_call_count=0`

同一输入重复运行的两份报告字节完全一致。

## 验证

- 定向测试：`2 passed`
- 完整测试：`301 passed, 3 warnings`
- 既有 `intent_matcher.py` 工作区哈希与 HEAD 一致。

## 明确未做

- 未修改 Director 规则或预测制品。
- 未使用 blind-v1 标签调参。
- 未运行模型或重新解码视频。
- 未调用曲多多、即梦、Codex API、网络或任何付费服务。
- 未开始 V0.3 Task 2。
