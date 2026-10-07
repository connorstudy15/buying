# Native symmetric 控制实验结论

## 这次真正控制住了什么

两组使用完全相同的：

- `qwen3.7-text-embedding-flash`
- DashScope native API
- 151 个 document vectors
- `knowledge_dual_tower_exp` collection
- 512 tokens + overlap 50 chunks
- 71 条冻结 query/subquery

唯一变量：

- B0-native-symmetric：Query 使用 `text_type=document`
- D0-role：Query 使用 `text_type=query`

没有重新建库，没有重新调用 QueryProcessor，没有 instruct、reranker、RRF 或 final selector。

## 总体结果

| 指标 | Query=document | Query=query | 变化 |
|---|---:|---:|---:|
| Recall@5 | 80.99% | 79.58% | -1.41pp |
| Recall@10 | 80.99% | 83.10% | +2.11pp |
| Recall@24 | 84.51% | 87.32% | +2.82pp |
| Recall@50 | 95.07% | 94.37% | -0.70pp |
| MRR | 0.7201 | 0.7819 | +0.0618 |
| Gold mean rank，miss=51 | 8.70 | 7.87 | 改善 0.83 名 |
| Retrieval Loss gold count | 6 | 6 | 不变 |
| Hard negative outrank positive | 16.67% | 8.33% | 减半 |

Primary gate 排除 Trigger 诊断 case 和争议标签后：

| 指标 | Query=document | Query=query |
|---|---:|---:|
| Recall@24 | 88.06% | 89.55% |
| MRR | 0.7399 | 0.8052 |
| Retrieval Loss | 5 | 5 |
| Hard negative outrank positive | 13.64% | 4.55% |

## 分桶

| Bucket | Recall@5 | Recall@24 | MRR |
|---|---:|---:|---:|
| DECOMPOSE subquery | 78.75% → 76.25% | 85.00% → 87.50% | 0.7460 → 0.7765 |
| DIRECT | 83.87% → 83.87% | 83.87% → 87.10% | 0.6867 → 0.7888 |
| Single evidence | 80.95% → 80.95% | 80.95% → 85.71% | 0.6327 → 0.7597 |
| Multi evidence | 81.00% → 79.00% | 86.00% → 88.00% | 0.7568 → 0.7912 |
| Implicit / cross-domain | 78.41% → 76.14% | 84.09% → 86.36% | 0.7463 → 0.7741 |
| Domain rule | 76.14% → 73.86% | 77.27% → 79.55% | 0.6995 → 0.7482 |

信号很一致：`text_type=query` 主要改善中段排序和第一条正例的位置，因此 MRR、Recall@10、Recall@24 上升；但 Top-5 与 Top-50 并非全面占优。

## Paired movement

- Gold rank improved：22
- unchanged：60
- worsened：11
- Query-level Recall@24：2 win / 69 tie / 0 loss
- Easy single-evidence regression@5：0

唯一的整体 Recall@5 下降来自 `v4-030::subquery_2`：两条位于同一个 chunk 的 gold 从 Rank 5 变成 Rank 6。它属于边界移动，不是正确证据完全消失。

Recall@50 的净下降来自两组相反变化：

- 变差：`blind-025::subquery_1` 一条 gold Rank 47 → Top-50 外；`v4-030::subquery_3` Rank 38 → Top-50 外。
- 改善：`blind-021::subquery_2` 和 `v4-048::subquery_2` 各有一条 gold 从 Top-50 外进入 Rank 27。

因此 Retrieval Loss 总数保持 6，但具体丢失/找回的 evidence 发生了交换。

## v4-006 三组对照

| Arm | Gold rank |
|---|---:|
| B0-compatible | 16 |
| B0-native-symmetric | 38 |
| D0-role | 35 |

这说明：

1. `v4-006` 的 Rank 16 → 35 不能归因于 `text_type=query`。
2. 主要退化发生在 document vectors 从 compatible 变成 native-document 时：16 → 38。
3. Query role 实际把它从 38 小幅拉回 35，但力度不足以抵消 document/endpoint 变化。
4. 三组 Top-20 都被同领域的合成旅行/家居评测模板占据；这些 chunk 主题相似，但不支持当前 gold evidence。问题更像细粒度 evidence discrimination 和重复模板竞争。

所以继续给 Query 加 instruct 可能进一步强化宽泛的“旅行用品检索意图”，不保证能解决这种细粒度区分，当前不应直接进入 D0-instruct。

## 最终判断

这次可以比上一轮更准确地说：

> 在固定 native document vectors 后，`text_type=query` 本身是有价值的：它明显改善 MRR、Recall@10、Recall@24 和 hard-negative 排序，并且没有 Recall@24 query regression。

但同时：

> 这份收益还不足以让整套 native D0-role 进入 Candidate B。它没有减少 Retrieval Loss，Recall@5/50 有小幅交换，而且 native document representation 对 `v4-006` 的伤害远大于 Query role 带来的补偿。

当前决策：

- 不否定 role-aware encoding；“角色区分无效”的结论应撤回。
- D0-role 仍不进入正式 Candidate B。
- 暂不做 D0-instruct。
- 不启动 Chunk Strategy Experiment E。
- 下一步若继续，应优先分析 native document encoding 为什么放大重复合成模板，以及是否需要在评测语料中隔离/降低 synthetic fixture 对正式知识的竞争；这比继续调 Query instruct 更有针对性。
