# 旅行导演 V0.2 画面理解标注指南

日期：2026-08-31

状态：Task 2 冻结版；尚未填写人工标签，尚未运行新视觉模型

## 目的

这套标注只回答“画面中能够确认什么”，不能提前替 Director 判断核心、高潮、开场或淘汰，也不选择剪辑起止区间。

固定数据拆分：

- 开发集 12 条：允许用于合同、提示词和阈值调试。
- 盲测集 12 条：开发期间不根据模型结果修改规则，只在里程碑末运行一次。
- 保留集 6 条：本阶段不使用。

具体 membership、seed 和 SHA-256 记录在 `director_visual_split.json`。开发集、盲测集和保留集不得互换素材。

## 标注顺序

1. 打开本地 `director_visual_review.html`，只看已有代表帧和技术信息。
2. 不查看任何新模型输出，先完成 24 条事实标注。
3. 对每个需要确认的字段选择“确认/修订”或“仍然未知”。
4. “确认/修订”必须填写合法 JSON，例如 `"outdoor"`、`true` 或 `["culture_architecture"]`。
5. 填写简短理由，然后下载 `visual_confirmation.json`。
6. 用 CLI 校验，校验通过后才能导入为 assisted observation；原始 draft 不覆盖。
7. Director 桶位和职责在后续 `director_review.json` 中单独修改，不混入本表。

## 字段定义

### technical_usability

- `usable`：代表帧和技术信息未显示明确不可用问题。
- `unusable`：存在不可解码、全黑、严重损坏等硬证据。
- `review_required`：稀疏帧无法确定整条素材是否可用。

不得仅因为内容普通、构图不喜欢或与当前 Brief 不符而标为不可用。

### content_families

允许多选：

`urban | nature | culture_architecture | food | transport | lodging | attraction_activity | performance_event | people | detail | other | unknown`

只标能从代表帧确认的粗粒度内容，不猜测具体景点、人物身份或事件名称。

### setting

`indoor | outdoor | mixed | unknown`

### lighting

`daylight | night | artificial | mixed | unknown`

### people_presence / people_count_band

- presence：`present | absent | unknown`
- count band：`none | single | few | crowd | unknown`

遮挡、远景或只见局部时允许 `unknown`。人数只标粗粒度，不推断同行者、演员、游客或主角身份。

### subject_candidates / activity_candidates

使用短词描述直接可见的主体和动作。无法确认时留空，不使用故事性语言。

合格示例：

- 主体：`建筑外立面`、`人群`、`餐桌`。
- 动作：`行走`、`观看表演`、`乘车`。

不合格示例：

- `主人公第一次来到开封`
- `一家人度过温馨时光`
- `适合作为高潮`

这些都超出了可见事实。

## Director 人工修改

`director_review.json` 只允许：

- 修改 `core/candidate/redundant/reject_suggestion/review_required`。
- 修改导演职责。
- 强制保留或排除。
- 填写修改理由。

它不允许填写 `source_in/source_out` 或 preferred range。时间区间只在后续音乐时间线阶段产生。

## 盲测纪律

- 盲测人工答案默认保存为 `benchmark/*.local.json`，不提交到仓库。
- 模型、规则或阈值不能读取盲测答案。
- 盲测运行后不得继续基于盲测结果调参；需要修复时开启下一版本评估。
- 未完成人工标签时，模板保持 `completed: false`，不能把空白模板报告成 Ground Truth。

## CLI

从 `local-media-scanner/` 执行：

```bash
uv run travel-director render-visual-review \
  --observations benchmark/director_visual_observations.template.json \
  --ground-truth-template benchmark/director_visual_ground_truth.template.json \
  --output benchmark/director_visual_review.html

uv run travel-director validate-visual-confirmation \
  --observations benchmark/director_visual_observations.template.json \
  --confirmation benchmark/visual_confirmation.local.json

uv run travel-director import-visual-confirmation \
  --observations benchmark/director_visual_observations.template.json \
  --confirmation benchmark/visual_confirmation.local.json \
  --output benchmark/director_visual_confirmed.json
```

生成和校验过程不访问网络、不运行模型、不解码新视频。
