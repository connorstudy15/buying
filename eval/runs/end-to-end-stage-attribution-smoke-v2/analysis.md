# 端到端分阶段评测：Smoke V2 结论

## 状态

这是一轮 61 题 smoke test，不是三轮正式结论。质量对比使用共享候选池，延迟使用独立无缓存探针，两类数据不再互相污染。

计划中的三轮正式运行在第一轮无缓存 embedding 阶段被服务端 `403 AccessDenied.Unpurchased` 中止。当前 `.env` 配置的 embedding 模型为 `qwen3.7-text-embedding-flash`。恢复该模型权限或额度后，需要重新执行三轮正式评测。

## 暂定效果

- Legacy Evidence Recall@3：65.67%。
- 实验 A（DECOMPOSE + RRF）：75.83%。
- 实验 B（DECOMPOSE + per-need reranker + RRF）：81.83%。
- Legacy All-Evidence Recall@3：54.00%。
- 实验 A All-Evidence Recall@3：70.00%。
- 实验 B All-Evidence Recall@3：76.00%。
- 实验 B 相比 Legacy 没有 strict regression；相比实验 A 也没有 strict regression。

单轮结果显示实验 B 有收益，但必须用三轮中位数确认模型波动后才能作为候选发布结论。

## Gold evidence 首次丢失阶段

- Retrieval Loss：8/87，9.20%。
- Reranker Loss：0/87，0%。
- Fusion Loss：0/87，0%。
- Top-K Truncation Loss：6/87，6.90%。

这说明当前 reranker 没有删除候选，RRF 的去重也没有直接删除 gold evidence。剩余失败主要来自两处：原始召回根本没找到证据，以及证据虽然在融合候选池中、但没有进入最终 Top-3。

旧的 `Fusion information-need loss` 把最终截断也算在融合之后，不能再单独用它判断 RRF 的责任。

## 无缓存延迟

- 全部请求 End-to-End P50/P95：1.33/3.13 秒。
- DIRECT End-to-End P50/P95：1.14/2.14 秒。
- DECOMPOSE End-to-End P50/P95：1.84/5.19 秒。
- DECOMPOSE reranker P50/P95：0.41/0.51 秒。
- Raw Retrieval P50/P95：0.11/0.23 秒。
- RRF/Fusion P95：约 1.2 毫秒。

主要长尾不是 RRF，也通常不是向量检索。`human-mh-002` 和 `blind-010` 由 QueryProcessor 长尾主导；`v4-041` 由 reranker 超时重试主导。对应 Langfuse trace ID 已写入主报告。

## 估算成本

- 实验 B 约 ¥0.005094/Query（闲时原价，不含 embedding 公共成本）。
- Legacy → B：本轮新增 11 个完整正确 case，估算每新增一个完整正确 case 约 ¥0.028249。
- A → B 的 reranker 增量：新增 3 个完整正确 case，约 ¥0.088944/新增完整正确 case。

价格依据为阿里云百炼华北2公开原价，未计免费额度、缓存折扣或活动优惠。

## 下一步

1. 恢复 `qwen3.7-text-embedding-flash` 的调用权限或余额。
2. 重跑 61 题 × 3 轮正式评测。
3. 若结果稳定，优先处理 8 个 Retrieval Loss case；Top-K 截断再作为第二优先级。
4. 利用 Langfuse 分别治理 QueryProcessor 长尾和 `v4-041` 的 reranker 重试长尾。
