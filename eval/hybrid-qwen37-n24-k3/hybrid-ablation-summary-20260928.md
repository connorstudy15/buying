# 商品 Hybrid/RRF 消融评测（N=24，K=3）

## 结论

`BM25 + Embedding + RRF + Qwen3.7 Reranker` 在当前 67 条回归集上优于
`Embedding + Qwen3.7 Reranker`：Final Recall@3、MRR@3、nDCG@3 均提升，
成对比较改善 2 条、退化 0 条，且精排成本没有增加。

但正式 Hybrid 门禁目前仍应判定 **BLOCK**：过滤准确率为 0.8333，存在一条
“金标商品同时被业务硬约束过滤”的标注/规则冲突。解决该冲突并复验前，不打开
线上 `HYBRID_RECALL_ENABLED`。

## 固定实验条件

- 数据集：`eval/product_recall.jsonl`，67 条 Query。
- 每路候选深度：24。
- RRF：等权，`k=60`。
- RRF 后严格截断：24。
- 最终结果：K=3。
- Reranker：`qwen3.7-text-rerank`。
- 五档均使用真实项目链路；各档独立进程运行，避免嵌入式 Qdrant 文件锁。

## 五档消融结果

| 策略 | Candidate Recall@24 | Final Recall@3 | Precision@3 | MRR@3 | nDCG@3 | Filter accuracy | P95 | Rerank tokens | Rerank 费用 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.9339 | 0.8371 | 0.4552 | 0.8408 | 0.8190 | 0.8333 | 8.9ms | 0 | ¥0 |
| Embedding | 0.9627 | 0.9092 | 0.4179 | 0.9154 | 0.8909 | 1.0000 | 345.5ms | 0 | ¥0 |
| Embedding + Qwen | 0.9627 | 0.9515 | 0.4478 | 0.9552 | 0.9437 | 0.8333 | 703.9ms | 228,490 | ¥0.114245 |
| BM25 + Embedding + RRF | 0.9739 | 0.9042 | 0.4129 | 0.8955 | 0.8771 | 0.8333 | 356.5ms | 0 | ¥0 |
| **BM25 + Embedding + RRF + Qwen** | **0.9739** | **0.9664** | **0.4577** | **0.9851** | **0.9664** | **0.8333** | **756.5ms** | **224,835** | **¥0.112418** |

Rerank 费用按 ¥0.5/百万输入 Token 计算。Hybrid 精排平均处理 23.93 个文档、
最大 24 个，证明 RRF 后的 N=24 截断真实生效。

## 相对当前主链的变化

以 `Embedding + Qwen` 为基线，最终 Hybrid：

- Candidate Recall@24：0.9627 → 0.9739（+1.12 个百分点）。
- Final Recall@3：0.9515 → 0.9664（+1.49 个百分点）。
- MRR@3：0.9552 → 0.9851（+2.99 个百分点）。
- nDCG@3：0.9437 → 0.9664（+2.27 个百分点）。
- P95：703.9ms → 756.5ms（+52.6ms，约 +7.5%）。
- Reranker 成本：¥0.114245 → ¥0.112418（本轮没有增加）。
- Recall、nDCG、Top-1 成对比较均为：改善 2 条、退化 0 条、持平 65 条。

改善的两条 Query：

1. `300元以内抗造又不含塑料的旅行装备`：Final Recall@3 +0.5。
2. `预算100元以内的收纳用品`：Final Recall@3 +0.5。

## 两路召回贡献

- BM25 分支 Recall@24：0.8781。
- Embedding 分支 Recall@24：0.9552。
- 两路并集 Oracle Recall：0.9925。
- RRF 截断后的 Candidate Recall@24：0.9739。
- BM25 独有相关实体：7 个；Embedding 独有相关实体：12 个。

两路具有真实互补性；同时 Oracle 0.9925 高于 RRF 0.9739，说明未来仍可优化
RRF 参数或融合方式，但不应在同一 67 条全集上反复调参后再宣称泛化提升。

## 为什么 RRF 后仍需 Reranker

单独 `Hybrid RRF` 的 Candidate Recall 提升到了 0.9739，但 Final Recall@3 只有
0.9042，低于纯向量加精排的 0.9515。RRF 适合扩大和融合候选，不足以承担最终
Top-3 语义排序；Qwen3.7 精排把 Final Recall@3 提升到 0.9664。

## 当前阻断项

`300元以内抗造又不含塑料的旅行装备` 中，一条现有金标商品被结构化硬约束判定
为不合格，导致过滤准确率为 0.8333。需要人工确认：

- 如果商品确实含排除材质，应修正 `relevant`/graded relevance；
- 如果商品不应被排除，应修正商品 `material_tags` 或过滤规则。

修正后必须重跑 `hybrid-experimental` 正式门禁；通过前不启用线上开关。
