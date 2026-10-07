# Dual-Tower Experiment D0-full 结论

## 实验边界

唯一主要变量：

- Flash role：`qwen3.7-text-embedding-flash`
- Full role：`qwen3.7-text-embedding`

两组都使用 DashScope native API、`text_type=query/document`、同一冻结 Query Plan、同一 151 个 chunk、1024 官方默认维度和同一 Retriever-only evaluator。没有 instruct、QueryProcessor 重跑、reranker、RRF、selector、答案生成或 chunk 修改。

新 collection 为 `knowledge_dual_tower_full_exp`；生产 collection 和 `knowledge_dual_tower_exp` 未覆盖。

## 权限、维度和语料一致性

- Full query/document 冒烟均一次成功，无 403、无 fallback。
- 官方默认维度和实际返回维度均为 1024；未 padding、truncate 或调维度刷分。
- Full collection 共 151 个 point。
- Corpus Manifest SHA-256：`c0473ab320aca136281cc719559ef930bd371b0722f867826c282b8c41a4171b`
- Query Plan SHA-256：`4fd24d67ed9c903df3ff5970e06efdeaf032f69b79fa85be89e3dc853ad38403`

## 总体结果

| 指标 | Flash role | Full role | 变化 |
|---|---:|---:|---:|
| Recall@5 | 79.58% | 54.23% | -25.35pp |
| Recall@10 | 83.10% | 70.42% | -12.68pp |
| Recall@24 | 87.32% | 78.87% | -8.45pp |
| Recall@50 | 94.37% | 92.96% | -1.41pp |
| MRR | 0.7819 | 0.4984 | -0.2835 |
| Gold mean rank，miss=51 | 7.87 | 12.57 | 变差 4.70 名 |
| Gold median rank | 1 | 5 | 变差 4 名 |
| Retrieval Loss gold/query | 6 / 6 | 8 / 8 | 增加 2 / 2 |
| Hard-negative outrank-positive | 8.33% | 27.08% | 恶化 18.75pp |

Primary gate 排除 Trigger 漏拆诊断和争议标签后：

| 指标 | Flash role | Full role |
|---|---:|---:|
| Recall@5 | 82.84% | 57.46% |
| Recall@10 | 86.57% | 73.88% |
| Recall@24 | 89.55% | 81.34% |
| Recall@50 | 94.78% | 94.78% |
| MRR | 0.8052 | 0.5254 |
| Retrieval Loss | 5 | 6 |
| Hard-negative outrank-positive | 4.55% | 22.73% |

排除特殊 case 后，结论没有改变。

## 分桶

| Bucket | Recall@24 Flash → Full | MRR Flash → Full | Retrieval Loss Flash → Full |
|---|---:|---:|---:|
| DIRECT | 87.10% → 82.26% | 0.7888 → 0.4692 | 1 → 2 |
| DECOMPOSE subquery | 87.50% → 76.25% | 0.7765 → 0.5210 | 5 → 6 |
| Single evidence | 85.71% → 76.19% | 0.7597 → 0.4337 | 0 → 1 |
| Multi evidence | 88.00% → 80.00% | 0.7912 → 0.5256 | 6 → 7 |
| Implicit / cross-domain | 86.36% → 77.27% | 0.7741 → 0.5227 | 6 → 7 |
| Domain rule | 79.55% → 77.27% | 0.7482 → 0.4611 | 6 → 8 |

Full 在所有关键 bucket 都退化，没有保留 Flash role 在复杂检索上的优势。

## Paired rank movement

- Gold improved：15
- unchanged：29
- worsened：49
- Query-level Recall@24：3 win / 59 tie / 9 loss
- Easy-case regression@5：7 条

严格 Recall@24 回归包括 `blind-010`、`blind-019` 两个 subquery、`v4-026::subquery_2`、`v4-037::subquery_2`、`v4-043::subquery_1`、`v4-051::subquery_1`、`v4-r007`；`blind-014` 为争议 case。

## v4-006

| Arm | Gold rank |
|---|---:|
| B0-compatible | 16 |
| B0-native-symmetric | 38 |
| Flash role | 35 |
| Full role | 16 |

Full 确实把 `v4-006` 从 35 拉回 16，改善 19 名。但仍未进入 Top-10/Top-5，而且 gold 前面仍有 15 个候选；其中绝大多数是 `eval-travel-gear-*` 或 `eval-home-living-*` 合成模板。它改善了这个单点，却没有解决重复模板竞争。

因此 `v4-006` 的改善不能抵消全局退化，也不能证明 Full 具有更好的普遍 evidence discrimination。

## 上一轮改善 case 是否保留

- `v4-051::subquery_1`：13 → 25，丢失 Recall@24，收益未保留。
- `v4-048::subquery_2`：运费证据 2 → 1，但另一条 home-living 证据 27 → Top-50 外，部分退化。
- `blind-019::subquery_1`：一条证据 1 → 2，另一条 10 → Top-50 外，明显退化。
- `blind-019::subquery_2`：两条证据 2/1 → 30/38，明显退化。

Full 为救 `v4-006` 牺牲了上一轮已经改善的复杂检索 case。

## Trigger 漏拆诊断

- `blind-008`：跨境证据从 Top-50 外进入 Rank 17，但商品证据从 Rank 2 掉出 Top-50。
- `human-mh-001`：跨境证据 42 → 16，但商品证据 1 → 10。

这只能说明 Full 改变了错误 DIRECT route 下的偏好，不能说它解决了 QueryProcessor Trigger False Negative。

## Hard-negative 类型

| 类型 | Flash | Full |
|---|---:|---:|
| generic vs specific | 7.41% | 37.04% |
| repeated template competition | 14.29% | 57.14% |
| same domain wrong rule | 10.00% | 30.00% |
| keyword overlap wrong answer | 66.67% | 66.67% |
| same product / wrong need | 8.33% | 8.33% |

Full 最严重的问题恰好是本轮希望改善的细粒度区分：泛化知识和重复模板更容易排到真正证据前面。

## 延迟与成本

官方北京区实时调用单价：

- Full：¥0.0005 / 千输入 Token
- Flash：¥0.000125 / 千输入 Token

| 项目 | Flash | Full | 变化 |
|---|---:|---:|---:|
| 151 chunk 建库时间 | 2.75 s | 5.87 s | 约 2.13× |
| 一次建库 Token | 63,604 | 63,604 | 相同 |
| 一次建库成本 | ¥0.00795 | ¥0.03180 | 4× |
| Batch query 时间 | 1.01 s | 1.59 s | 约 1.57× |
| 单 Query P50 | 223.61 ms | 249.70 ms | +11.7% |
| 单 Query P95 | 246.29 ms | 319.46 ms | +29.7% |
| 平均 Query 成本 | 约 ¥0.00000338 | 约 ¥0.00001353 | 4× |
| 错误率 / 重试率 | 0 / 0 | 0 / 0 | 相同 |

## 最终问题回答

1. **Full 是否优于 Flash role？** 否，整体显著更差。
2. **Recall@24？** 87.32% → 78.87%，下降 8.45pp。
3. **Recall@50？** 94.37% → 92.96%，下降 1.41pp。
4. **Retrieval Loss？** 6 → 8，增加 2。
5. **MRR / Gold Rank？** MRR 下降 0.2835，平均 rank 变差 4.70 名。
6. **Hard negative？** 8.33% → 27.08%，明显恶化。
7. **v4-006？** 35 → 16，有改善，但仍被 15 个候选压制。
8. **复杂 case 收益？** 没有完整保留，多项明显回归。
9. **DIRECT / single-evidence regression？** 有，且规模明显；easy regression@5 为 7。
10. **延迟 / 成本？** P50 +11.7%，P95 +29.7%，单价和估算调用成本均为 4×。
11. **是否进入 Stage 2？** 不进入。
12. **是否继续 D0-instruct？** 当前不继续；先处理语料中重复 synthetic fixture 的竞争和评测/生产知识隔离问题。
13. **是否启动 Chunk Experiment E？** 没有新证据。问题表现为排序与语料竞争，而不是知识点被切断。

## 决策

`D0-full = rejected for Stage 2`。

保留 Flash role 的实验结论，但不修改正式 Candidate B。Full collection 仅作为可复现实验 artifact，不接入正式链路。
