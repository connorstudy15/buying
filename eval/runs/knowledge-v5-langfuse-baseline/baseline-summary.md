# Knowledge Retrieval V5 Baseline 总结

## 实验口径

- 数据集：`knowledge_eval_core_61.jsonl`，61 题，Top-K=3，单轮 paired evaluation。
- Legacy：旧知识检索链路。
- 实验 A：DIRECT / DECOMPOSE + RRF，不执行 REWRITE。
- 实验 B：实验 A + 每个 information need 独立调用 Qwen3.7 Text Rerank，再进行 RRF。
- 同一轮复用 QueryProcessor 计划和候选池，减少模型波动与重复调用造成的实验污染。
- Langfuse 仅发送题号、策略、模型用量、延迟和数值指标；不发送 query、知识正文或候选文本。

## 核心结果

| 指标 | Legacy | 实验 A | 实验 B | B - Legacy |
|---|---:|---:|---:|---:|
| Evidence Recall@3 | 67.67% | 75.67% | 77.33% | +9.66pp |
| All-Evidence Recall@3 | 56.00% | 66.00% | 72.00% | +16.00pp |
| Hard-negative hit rate | 34.29% | 25.71% | 22.86% | -11.43pp（更好） |
| Fusion information-need loss | 26.00% | 17.00% | 13.00% | -13.00pp（更好） |
| Unanswerable accuracy | 36.36% | 36.36% | 36.36% | 无变化 |
| P50 latency | 104 ms | 1,281 ms | 1,447 ms | +1,343 ms |
| P95 latency | 160 ms | 1,914 ms | 2,249 ms | +2,089 ms |

实验 B 相对实验 A 的纯 reranker 增益为：Evidence Recall +1.66pp、All-Evidence Recall +6.00pp、
hard-negative hit rate -2.85pp、fusion need loss -4.00pp；没有出现“旧链路正确、新链路错误”的严格退化 case。

## 分桶结论

- single evidence：实验 B 相比 Legacy，Evidence Recall 76% → 78%，All-Evidence 72% → 76%，简单题没有总体退化。
- cross evidence：Evidence Recall 80.21% → 93.75%，All-Evidence 56.25% → 87.50%，是最明确的收益桶。
- implicit constraint multi-hop：Evidence Recall 50% → 75%，All-Evidence 0% → 50%。
- 普通 implicit constraint：实验 B 的 Evidence Recall 为 53.33%，低于实验 A 的 63.33%；该桶只有 5 题，需逐题排查，不可只看总体收益。
- unanswerable：11 题只通过 4 题。Query Transformation 和 reranker 不解决拒答边界，仍是上线阻断项。

## DECOMPOSE 触发

- 仅统计有显式人工策略标签的 31 题：Trigger Precision 78.95%，Trigger Recall 93.75%。
- 显式标签误拆：`v4-002`、`v4-049`、`v4-r008`、`v4-r010`。
- 显式标签漏拆：`v4-051`。
- 其余 19 个可回答旧 Core 观测仍按题型推导策略真值，因此混合口径不能作为正式门禁。

## 延迟与估算成本

- 实验 B 共触发 27 个 Query、55 次 reranker 调用，平均每个触发 Query 2.04 次。
- QueryProcessor P50/P95：1.19s / 1.76s。
- 触发重排的 Query，reranker 并发墙钟 P50/P95：0.44s / 15.90s。
- `v4-029`、`v4-049` 各出现约 22 秒 reranker 长尾，是当前 P95 风险来源。
- 实验 B 估算为每题 ¥0.00608～¥0.00659；61 题约 ¥0.371～¥0.402。
- 费用估算只含 QueryProcessor 和 reranker，不含 embedding、免费额度、缓存折扣或 Langfuse 套餐费用。
- Langfuse tracing 本身没有增加任何模型 token。

## Partial Coverage 专项

- `v4-044`：已有证据 Recall=100%，全部必要 need 覆盖=33.33%。说明内部已有知识能找到，但外部权威信息仍缺失。
- `v4-047`：已有证据 Recall=0%，全部必要 need 覆盖=0%。这是明确的检索/知识覆盖 bad case。
- 该裸检索 runner 无法测 Missing Need Detection、False Complete Answer 和 Correct Escalation；这些必须在端到端 Agent 回答评测中验证。

## Langfuse 验收

- Core 本地结果中的 183 条“题目 × 策略”观测全部生成有效 trace ID。
- 通过 Langfuse 只读 API 抽查 1 条 Core trace 和 1 条 Partial trace：均已入库、已结束、无错误。
- 当前仅完成抽查，不声称已逐条远端读取验证全部 185 条 trace。

## 决策

实验 B 的多证据收益足够大，适合保留为 V3 Candidate；但本轮只有一次重复，不能直接冻结为上线版本。
下一步优先级：

1. 修复 unanswerable 判定（当前 36.36%）。
2. 限制 reranker 长尾，并分析 `v4-029`、`v4-049`。
3. 补齐旧 Core 的显式 DIRECT/DECOMPOSE 标签，再把 Trigger Precision 变成正式门禁。
4. 对固定版本再跑 3 次重复，报告中位数与最差值。
