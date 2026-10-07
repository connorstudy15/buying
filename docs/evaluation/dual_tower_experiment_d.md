# Dual-Tower Experiment D（待确认设计）

## 1. 现状与实验边界

当前知识链路使用 `knowledge/*.md`，由 `TextParser` 与 `ApproxTokenChunker(chunk_size=512, overlap=50)` 切块，当前 Embedding 写入 Qdrant collection `globex_category_kb`。商品向量 collection 是另一套 `globex_products`。

Experiment D 不改线上 `KnowledgeBase`、Candidate B、RRF、reranker、Top-K 或 QueryProcessor。双塔索引固定使用新 collection：`knowledge_dual_tower_exp`。Stage 1 只产出独立排名 JSONL，再由 `evaluate_dual_tower_retriever.py` 比较；没有通过 Stage 1 门禁就停止。

## 2. 双塔最小侵入结构

```text
冻结 query / subquery
 ├─ 当前 query embedding → globex_category_kb → baseline ranking.jsonl
 └─ Query Tower embedding → knowledge_dual_tower_exp → dual ranking.jsonl

两路排名 → Retriever-only evaluator（不进入 Candidate B）
```

Document Tower 对同一批冻结 chunk 离线编码。实验 collection payload 必须保留：`candidate_id`、`document_id`、`source`、`chunk_index`、`content_sha256`、chunk 正文和实验模型版本。不得覆盖或 alias 到 production collection。

Stage 2 才允许把 Dual Tower 作为 `_retrieve_candidates` 的实验实现注入，并保持 DIRECT final selection 与 DECOMPOSE 后处理完全不变。

## 3. 数据分层

### Train

每条是 `(query, positive evidence, hard negatives[])`。优先从非 benchmark 文档、经人工审批的线上失败查询、或独立生成的非冻结问题构造。hard negative 从当前 embedding Top-N 中挖掘，优先：同商品错误需求、同文档错误 section、跨领域表面相似、重复模板。

### Validation

与 Train 的 query、`group_id`、样本 ID 分离，用于 early stopping、温度和 batch 参数选择。不能拿 frozen test 调参。

### Frozen test / holdout

只用于最终 Retriever-only 报告。正式 benchmark、blind、human case 均在这里。默认泄漏检查还禁止 Train/Validation positive 使用 frozen gold evidence；如未来确有充分理由放宽，必须显式传参并在报告披露。

DECOMPOSE 子查询必须冻结成独立 query instance。它们应来自一次批准的 Candidate B QueryProcessor 计划并人工映射到 information need；训练时不得读取这些子查询。

## 4. 文件契约

- 训练格式：`eval/dual_tower/contracts/train.example.jsonl`
- 验证格式：`eval/dual_tower/contracts/validation.example.jsonl`
- 冻结查询格式：`eval/dual_tower/contracts/frozen_queries.example.jsonl`
- Retriever 排名格式：`eval/dual_tower/contracts/ranking.example.jsonl`

稳定 evidence ID 继续使用 `source + section + quote hash`；实验 candidate ID 使用 chunk 内容与元数据的稳定 hash。

## 5. Stage 1 指标与门禁

Evaluator 输出 Recall@5/10/24/50、MRR、Gold Mean/Median Rank（Top-50 未命中按 51 计）、两种 Retrieval Loss 数量、hard-negative outrank-positive rate、要求的各分桶、简单题退化和逐 evidence rank movement。

建议进入 Stage 2 的最低条件：

1. Recall@24 提升且 Retrieval Loss 下降；
2. `single_evidence` 的既有容易题没有明显退化；
3. hard-negative outrank-positive rate 不恶化；
4. Rank 15–50 的 gold 有可复现的前移，不是只修一个 `v4-006`；
5. blind-008、human-mh-001 即使前移，也仍记为 Trigger 漏拆，不能宣传成 QueryProcessor 已修复。

## 6. 模型与训练建议

当前机器是 8GB 显存、D 盘剩余空间约 13GB，项目也未安装 PyTorch/Transformers/Sentence-Transformers。适合先运行现成小型 encoder 的推理 PoC；不适合直接在主环境开展大批量训练。

建议顺序：

1. 先用现成 sentence-transformer/embedding encoder 生成双塔 baseline；
2. Stage 1 有信号后，在隔离环境或云端 GPU 使用 contrastive loss、in-batch negatives 与当前 Top-N hard negatives 微调；
3. 导出固定模型版本，在本地仅做推理与离线建库；
4. 未提升则保留当前 embedding + domain supplemental recall，停止双塔投入。

## 7. 运行命令（当前只做契约验证与离线评分）

```powershell
.venv-eval\Scripts\python.exe scripts/eval/validate_dual_tower_splits.py `
  --train eval/dual_tower/train.jsonl `
  --validation eval/dual_tower/validation.jsonl `
  --frozen eval/dual_tower/frozen_queries.jsonl

.venv-eval\Scripts\python.exe scripts/eval/evaluate_dual_tower_retriever.py `
  --queries eval/dual_tower/frozen_queries.jsonl `
  --baseline eval/runs/dual-tower-d/baseline-ranking.jsonl `
  --dual-tower eval/runs/dual-tower-d/dual-ranking.jsonl `
  --output-dir eval/runs/dual-tower-d/retriever-only
```

当前尚未创建 `knowledge_dual_tower_exp`、下载模型、生成训练数据或执行真实评测；这些操作等方案确认后进行。
