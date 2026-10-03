# Langfuse 分步骤 Trace 与 reranker 长尾分析

## 已增加的子 span

每道评测题现在形成以下父子结构：

```text
eval.knowledge.retrieval
├── knowledge.query_processor
├── knowledge.candidate_retrieval × query variant
├── knowledge.reranker.need × information need
│   └── knowledge.reranker.attempt × retry attempt
└── knowledge.rrf_fusion
```

仅记录固定步骤名、case ID、information need ID、文档数、候选数、token、attempt、耗时和错误类型；
不发送 query、子查询正文、知识片段或候选文档正文。

Langfuse 只读验收：`b21a08c2130e8fe7f2e5323d4cfaec02` 共 10 个 observation，1 个根节点、9 条有效父子连接、0 个缺失父节点、0 个错误。

## 长尾定位

旧诊断中 `v4-029`、`v4-049` 曾出现约 22 秒的单路 reranker 调用。
补充子 span 后的新诊断轮中：

- `v4-049` 总耗时 2.113s：QueryProcessor 1.676s；两路 reranker 0.434s / 0.404s；RRF 低于 1ms。
- 优化前诊断轮最慢题为 `v4-035`，总耗时 6.699s，其中 QueryProcessor 6.698s；它没有调用 reranker。
- 优化后最慢的 `v4-029` 总耗时 3.567s，其中 QueryProcessor 3.059s；两路 reranker 0.506s / 0.494s；RRF 低于 1ms。

结论：22 秒是远程 reranker 偶发长尾，不是 RRF；当前常态下端到端长尾更多来自 QueryProcessor。

## reranker 延迟预算

- 单次 attempt 超时：3 秒。
- 最多 attempt：2 次。
- 重试退避：0.25 秒。
- 两次均失败：保留原候选顺序并标记 `degraded=true`，不让整条检索链路失败。
- 理论上单个 information need 的最坏等待约 6.25 秒；多个 need 并发，不按路数串行相加。
- 所有 attempt、错误类型、降级次数都会进入 Langfuse 和本地报告。

本轮 53 次 reranker 调用没有发生降级。优化后：

- 单次 reranker P50/P95：0.407s / 0.494s。
- 仅触发 DECOMPOSE 的 Query，其 reranker 并发墙钟 P50/P95：0.422s / 0.503s。
- 实验 B 相对同轮实验 A：Evidence Recall +3pp、All-Evidence Recall +6pp。

不同轮的绝对 Recall 不宜直接归因于超时改动，因为 QueryProcessor 每轮重新推理，DIRECT/DECOMPOSE 计划会波动；
本轮没有触发超时降级，因此质量变化不是降级造成的。

## DECOMPOSE 误拆与漏拆诊断

只按显式人工标签统计，本轮：

- Trigger Precision：83.33%。
- Trigger Recall：93.75%。
- 误拆：`v4-002`、`v4-r008`、`v4-r010`。
- 漏拆：`v4-051`。

误拆的共同模式：模型把同一个最终判断中的“属性维度”当成了可独立失败的 information need。

- `v4-002` 被拆成重量与携带负担。
- `v4-r008` 被拆成手工属性与外观差异。
- `v4-r010` 被拆成材质与耐用性。

这些通常属于同一证据主题，不应仅因为能列出两个方面就 DECOMPOSE。

漏拆 `v4-051` 表明模型没有稳定执行当前口径：即使只有一个最终判断目标，只要必须组合两个可独立检索、可独立失败的 gold evidence needs，也应 DECOMPOSE。

下一步讨论重点应是 QueryProcessor 的决策契约与负例，而不是继续调整 RRF 或 reranker。
