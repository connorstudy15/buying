# Knowledge Eval v3 标注口径

## 相关性等级

- `grade=3`：答案必需或可直接支撑结论的证据；属于正例。
- `grade=2`：实质相关、可提供部分支持，但单独不足以回答完整问题。
- `grade=1`：主题或词面相近，但不能支撑答案。
- `grade=0`：无关、冲突或明显错误范围。

`relevant` 必须且只能列出本题的 `grade=3` 文档。证据级真值放在
`evidence_ground_truth`，其稳定 ID 由 `source + section + quote` 生成，不依赖 chunk 边界。

## Hard negative

`hard_negative` 是独立判断，不等于 `grade=1`。它表示该候选很容易被系统误召回或误用：

- 可以是 `grade=0`：词面相似但完全错误；
- 可以是 `grade=1`：同主题但不能支持答案；
- 可以是 `grade=2`：只支持局部结论，若被当成完整答案会误导；
- 不允许是 `grade=3`。

因此同时报告 hard-negative 命中率，以及 hard negative 是否排在首个正证据之前。

## 分桶与边界

- 普通单跳：报告 document Recall/MRR/nDCG 与 evidence Recall。
- Cross-evidence：额外报告 All-evidence Recall（所有必需证据是否同时找全）。
- Unanswerable：只报告拒答准确率，不混入普通 Recall。
- True multi-hop：报告知识检索可验证 hop 的 Hop Recall；只有所有 hop 都属于知识检索时才报告 Path Success。
- Implicit constraint：在 Query Planner/Agent trace 接入前，原始知识召回只能报告证据覆盖，`Constraint Recall` 为 `n/a`，不能据此声称隐含约束已被识别并传给商品检索。

所有自动映射异常写入 `evidence_mapping_review.csv`，经人工确认后才能把
`label_status` 从 `pending_human_review` 改为批准状态。
