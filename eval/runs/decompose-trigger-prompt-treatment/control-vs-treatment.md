# DECOMPOSE Trigger Prompt 单变量实验

## 实验设计

- 数据集：Knowledge V5 Core 61。
- Control：原 QueryProcessor Prompt。
- Treatment：只增加 DECOMPOSE 独立证据判定条件和抽象正反例。
- 两组均运行 3 轮；K、RRF、reranker、延迟预算、模型与代码一致。
- 正式 Trigger 指标只统计 31 道具有显式人工 `expected_query_strategy` 的可回答题。

## Trigger 指标

| 指标 | Control（三轮中位数） | Treatment（三轮中位数） |
|---|---:|---:|
| Trigger Precision | 78.95% | 100% |
| Trigger Recall | 93.75% | 100% |
| False Trigger Rate | 26.67% | 0% |

Treatment 三轮 Precision 均为 100%；Recall 分别为 100%、93.75%、100%。

- Control 每轮稳定误拆：`v4-002`、`v4-049`、`v4-r008`、`v4-r010`。
- Treatment 三轮均消除了以上误拆。
- Control 中 `v4-051` 的结果为 DIRECT、REWRITE、DECOMPOSE；Treatment 三轮均为 DECOMPOSE。
- Treatment 第 2 轮漏拆 `v4-027`，但该题即使走 DIRECT 仍完整召回证据，未造成该题召回退化。

## 检索质量

| 指标（实验 B，三轮中位数） | Control | Treatment | 变化 |
|---|---:|---:|---:|
| Evidence Recall@3 | 76.33% | 76.33% | 0pp |
| All-Evidence Recall@3 | 70.00% | 68.00% | -2pp |
| Single Evidence Recall | 74.00% | 76.00% | +2pp |
| Single All-Evidence | 72.00% | 72.00% | 0pp |
| Cross Evidence Recall | 93.75% | 93.75% | 0pp |
| Cross All-Evidence | 87.50% | 87.50% | 0pp |
| Implicit Constraint Recall | 63.33% | 63.33% | 0pp |
| Implicit Multi-hop Recall | 75.00% | 50.00% | -25pp |
| Implicit Multi-hop All-Evidence | 50.00% | 0.00% | -50pp |

## 为什么 Trigger 更准但 All-Evidence 略降

`v4-002`、`v4-049` 被正确改为 DIRECT 后，分别只能召回 1/2、0/2 gold evidence；
而 Control 的错误 DECOMPOSE 会生成多路查询，偶然拿全证据。

这不是应该保留误拆的理由，而是暴露了 DIRECT 路径的召回短板：

- 一个 information need 仍可能需要同一文档的两个 section/chunk 支持；
- 当前 `_legacy_finalize` 按 document ID 去重，每篇文档只保留第一个 chunk；
- 因此“单一证据主题”被错误限制成“只能返回一个 chunk”。

`v4-r008`、`v4-r010` 改为 DIRECT 后仍保持完整召回，说明不是所有 DIRECT 都退化。

Implicit multi-hop 的下降主要来自旧 Core 的 `human-mh-001/002` 尚无显式策略标签：

- `human-mh-001` 两组都稳定输出 REWRITE，始终只能召回一半证据；
- `human-mh-002` Treatment 有两轮因“任意”约束在子查询中丢失，被 validator 判为 `query_processor_constraint_drift` 并回退 legacy，第三轮才正确 DECOMPOSE。

这两题必须先补人工 `expected_query_strategy`，否则显式 Trigger 指标看不到该退化。

## 延迟、调用与成本

| 指标 | Control | Treatment |
|---|---:|---:|
| 总 P50 | 1.280s | 1.108s |
| 总 P95 | 2.136s | 2.010s |
| QueryProcessor 输入 token/题 | 356.58 | 568.94 |
| 3 轮 reranker 调用数 | 165 | 131 |
| 估算费用/题（闲时） | ¥0.006082 | ¥0.005140 |
| reranker 降级率 | 0% | 0% |

Prompt 虽增加约 212 个输入 token/题，但因误拆减少，reranker 调用下降约 20.6%，总估算费用反而下降约 15.5%，P50/P95 也下降。

## 结论

Prompt 对 Trigger 分类达到预设目标，可保留为候选；但暂不直接冻结成正式线上版本。

下一步应拆成两个独立动作：

1. 给旧 Core（尤其 `human-mh-001/002`）补显式 DIRECT/DECOMPOSE 标签。
2. 单独优化 DIRECT 的 section/chunk 选择，使一个 information need 可以返回同文档多个必要 chunk；不能继续用错误 DECOMPOSE 代偿 DIRECT 召回缺陷。
