# Knowledge Query Transformation V1 — Paired Baseline

- Code: `d237e30`
- Dataset: `eval/knowledge/v3/knowledge_eval_candidates.jsonl`（22 cases）
- K: 3
- Transform: original + rewrite/subqueries + RRF(k=60)
- Strict regression definition: legacy `All-Evidence Recall@3 = 1` but transform is not 1

## Overall

| Metric | Legacy | Transform | Delta |
|---|---:|---:|---:|
| Document Recall@3 | 0.7193 | 0.6579 | -0.0614 |
| Evidence Recall@3 | 0.6053 | 0.5526 | -0.0527 |
| All-Evidence Recall@3 | 0.4211 | 0.4211 | 0.0000 |
| Hard-negative hit rate | 0.5263 | 0.4211 | -0.1052（改善） |
| Unanswerable accuracy | 0.0000 | 0.0000 | 0.0000 |
| Fusion need loss | 0.3158 | 0.3684 | +0.0526（退化） |
| P50 latency | 102.219 ms | 1479.371 ms | +1377.152 ms |
| P95 latency | 304.320 ms | 2994.951 ms | +2690.631 ms |
| QueryProcessor fallback rate | n/a | 0/22 = 0% | — |

## Buckets

| Bucket / Metric | Legacy | Transform | Delta |
|---|---:|---:|---:|
| single: document Recall@3 | 0.8333 | 0.7500 | -0.0833 |
| single: Evidence Recall@3 | 0.7083 | 0.6250 | -0.0833 |
| single: All-Evidence Recall@3 | 0.6667 | 0.5833 | -0.0834 |
| single: hard-negative hit | 0.4167 | 0.4167 | 0.0000 |
| cross: document Recall@3 | 0.4583 | 0.4167 | -0.0416 |
| cross: Evidence Recall@3 | 0.5000 | 0.5000 | 0.0000 |
| cross: All-Evidence Recall@3 | 0.0000 | 0.2500 | +0.2500 |
| cross: hard-negative hit | 1.0000 | 0.5000 | -0.5000 |
| multi/constraint: document Recall@3 | 0.7500 | 0.7500 | 0.0000 |
| multi/constraint: Evidence Recall@3 | 0.5000 | 0.5000 | 0.0000 |
| multi/constraint: All-Evidence Recall@3 | 0.0000 | 0.0000 | 0.0000 |
| multi/constraint: Hop Recall | 0.0000 | 0.0000 | 0.0000 |

`Constraint Recall` 仍为 n/a：裸知识检索 runner 只能验证第一跳证据，不能证明约束已传给商品检索。

## Regression / Improvement

- Strict baseline-correct cases: 8
- Strict regressions: 1
- Regression Rate: `1 / 8 = 12.5%`
- Strict improvements: 1
- Net fully-correct cases: 8 → 8

### Legacy correct → Transform wrong

- `blind-005`：旅行三件套收纳效率。正确 evidence 已在 transform 候选池中，但原始查询与近同义 rewrite 对相似评测干扰文档重复投票，最终把 `travel-gear.md` 挤出 Top-3。

### Legacy wrong → Transform correct

- `blind-019`：20寸登机箱 + 移动电源航空运输。两个 subquery 分别覆盖尺寸与电池运输，Evidence Recall 0.5 → 1.0，All-Evidence 0 → 1。

### Partial evidence changes

- `blind-021`：粗陶茶具包装 + 体积重，Evidence Recall 0.5 → 0；两个正确 evidence 都在候选池，但融合后全部丢失。

## Fusion Loss Cases (Transform)

正确 evidence 已进入 pre-fusion candidate pool，但最终 Top-3 未完整保留：

- `blind-005`：1.0 → 0.0（新引入）
- `blind-006`：1.0 → 0.0
- `blind-010`：1.0 → 0.0
- `blind-012`：1.0 → 0.0（两个必要 evidence 最终只保留一个）
- `blind-014`：1.0 → 0.0
- `blind-021`：1.0 → 0.0（legacy 为 1.0 → 0.5，transform 进一步退化）
- `human-mh-002`：1.0 → 0.0（同一文档两个必要 section 被“每文档只留一个 chunk”规则压掉）

Transform 修复了 `blind-019` 的 legacy fusion loss，但新增 `blind-005`，并加重 `blind-021`。

## Unanswerable Failures

三题两档均错误返回知识近邻：

- `blind-027`：订单物流状态
- `blind-028`：实时库存与当天发货
- `blind-029`：未来国际运费及政策预测

说明当前 `unsupported_fact_reason` 未覆盖订单/物流、实时库存/履约、以及“下个月会不会”式预测表达。

## Conclusion

V1 暂不应上线。Subquery 对真正的双主题问题有效（`blind-019`），且 hard-negative hit rate 明显下降；但普通 RRF 对近同义 original/rewrite 重复计票，并且 Top-3 + 每文档一个 chunk 造成严重 fusion loss。下一轮应优先修融合与拒答 gate，而不是先调 RRF k 或增加 reranker。
