# Dual-Tower Experiment D0-role 结论

## 实验边界

- 模型不变：`qwen3.7-text-embedding-flash`
- chunk 不变：生产库原有 151 个 chunk，仍为 `512 tokens + overlap 50`
- B0：OpenAI-compatible 对称编码 + `globex_category_kb`
- D0-role：DashScope native，query 使用 `text_type=query`，文档使用 `text_type=document`
- 未使用 instruct；未调用新的 QueryProcessor；未进入 reranker、RRF、selector 或答案生成。
- 冻结来源：`knowledge-v5-20261004205525-58dd98e5` 的第 1 次重复，避免事后挑选最好的一次。
- 61 个 case 中，4 个被 unsupported gate 拦截；7 个没有 gold evidence，不能计算 Retriever Recall；最终为 50 个 case、71 个 query/subquery 实例。

## 权限与数据一致性

- 原生 query/document 冒烟测试均一次成功，返回 1024 维，无 403，无 fallback。
- 新 collection：`knowledge_dual_tower_exp`，151 个 point，Cosine，1024 维。
- baseline 与实验组的 chunk ID 集合完全相同，文本来自生产 collection，没有重新切块。
- Query Plan SHA-256：`4fd24d67ed9c903df3ff5970e06efdeaf032f69b79fa85be89e3dc853ad38403`
- Corpus Manifest SHA-256：`c0473ab320aca136281cc719559ef930bd371b0722f867826c282b8c41a4171b`

## Endpoint A/A

同一批 20 个文档，在 compatible 与 native-document 两种方式下：

| 指标 | 结果 |
|---|---:|
| 配对向量 cosine 均值 | 0.9350 |
| 配对向量 cosine 最小值 | 0.8922 |
| 最近邻 Top-1 一致率 | 75.00% |
| 最近邻 Top-5 平均 Jaccard | 79.29% |

这不是“两个 endpoint 产生完全相同的文档向量”。因此 D0-role 同时包含了“接口路径差异”和“角色编码差异”，不能把全部变化严格归因于 `text_type`。该限制必须保留在结论中。

## Retriever-only 主结果

| 指标 | B0 | D0-role | 变化 |
|---|---:|---:|---:|
| Recall@5 | 79.58% | 79.58% | 0.00pp |
| Recall@10 | 83.10% | 83.10% | 0.00pp |
| Recall@24 | 86.62% | 87.32% | +0.70pp |
| Recall@50 | 92.25% | 94.37% | +2.11pp |
| MRR | 0.7489 | 0.7819 | +0.0329 |
| Gold mean rank，未命中按 51 | 8.96 | 7.87 | 改善 1.09 名 |
| Retrieval Loss gold 数 | 8 | 6 | 减少 2 |
| Hard negative 排在 positive 前 | 10.42% | 8.33% | 改善 2.09pp |

排除两个争议 case 和两个 Trigger 漏拆诊断 case 后，primary gate 的 Recall@24 为 88.81% → 89.55%，Retrieval Loss 为 7 → 5，结论方向不变。

## 分桶

| Bucket | Recall@24 B0 → D0 | MRR B0 → D0 | Retrieval Loss B0 → D0 |
|---|---:|---:|---:|
| DECOMPOSE subquery | 83.75% → 87.50% | 0.7399 → 0.7765 | 6 → 5 |
| DIRECT | 90.32% → 87.10% | 0.7606 → 0.7888 | 2 → 1 |
| Multi-evidence | 85.00% → 88.00% | 0.7619 → 0.7912 | 7 → 6 |
| Single-evidence | 90.48% → 85.71% | 0.7180 → 0.7597 | 1 → 0 |
| Implicit / cross-domain | 82.95% → 86.36% | 0.7408 → 0.7741 | 7 → 6 |
| Domain-rule | 78.41% → 79.55% | 0.6588 → 0.7482 | 8 → 6 |

DIRECT / single-evidence 的 Recall@24 下降来自同一个 primary case：`v4-006`。所以不能用总体均值掩盖这条回归。

## Paired rank movement

- Gold rank improved：17
- unchanged：66
- worsened：10
- Query-level @24：2 win / 68 tie / 1 loss
- 唯一 @24 loss：`v4-006::original`
- Easy-case regression@5：0

关键 case：

- `v4-006`：Rank 16 → 35，变差 19 名，并从 Recall@24 命中变为未命中。这与预设的核心语义排序验收目标相反。
- `blind-008`：商品相关证据 Rank 2 → 2；另一份跨境证据仍未进 Top-50。仍是 Trigger 漏拆，D0 没有修复。
- `human-mh-001`：商品相关证据 Rank 1 → 1；跨境证据 Rank 29 → 42。仍是 Trigger 漏拆，且原始 query 容错没有增强。
- `blind-014`：Rank 23 → 24；标签有争议，不参与主门槛。
- `v4-022`：Rank 44 → 50；标签有争议，不参与主门槛。
- 明显改善示例：`v4-051::subquery_1` Rank 38 → 13；`v4-048::subquery_2` 有一条 gold 从 Top-50 外进入 Rank 27；`blind-019::subquery_1` Rank 33 → 10。

不同编码方式的绝对 score 不直接比较；上述判断只依据 rank、hit@K 和成对移动。

## 延迟、请求与成本证据

- 151 个文档：8 批、63,604 input tokens、2.75 秒、0 retry。
- 71 个 query 批量编码：4 批、1,921 tokens、1.01 秒、0 retry。
- 71 次真实单请求探针：P50 223.61 ms，P95 246.29 ms，错误率 0，重试率 0。
- 没有在代码中注入经过核实的该业务空间模型单价，因此报告 token 用量，但不捏造人民币成本。

## A–H 回答

**A. 仅增加角色区分是否提升 Retriever？** 轻微提升总体深召回和 MRR，但不是稳定的全面提升。

**B. 提升发生在哪些桶？** 主要在 DECOMPOSE subquery、multi-evidence、implicit/cross-domain 和 domain-rule；DIRECT / single-evidence 的 Recall@24 下降。

**C. v4-006 是否提前？** 没有，Rank 16 → 35，明显退化。

**D. Retrieval Loss 是否减少？** 是，gold 级 8 → 6；primary gate 7 → 5。

**E. 是否有简单题退化？** Top-5 easy regression 为 0，但 `v4-006` 在 Top-24 发生严格回归，因此不能说“无退化”。

**F. Endpoint 是否影响归因？** 是。A/A 显示文档向量和邻居次序存在实质差异，结果不能完全归因于角色参数。

**G. 是否进入 D0-instruct？** 暂不进入。D0-role 未满足核心 case 不退化的门槛，且总体 Recall@24 只提升 0.70pp。

**H. 是否启动 Chunk Strategy Experiment E？** 当前没有证据。正确 chunk 大多已存在，D0 的变化来自 representation/ranking；本实验没有发现必须改 chunk 的新证据。

## 最终决策

`D0-role = diagnostic result, not accepted into Candidate B`。

正式 Candidate B、生产 collection、QueryProcessor、reranker、RRF、Top-K、selector 和 chunk 参数均保持不变。下一步若要继续研究，应先分析 `v4-006` 为什么被 role encoding 压低，以及 Endpoint A/A 的差异来源；未经确认不要直接做 D0-instruct。
