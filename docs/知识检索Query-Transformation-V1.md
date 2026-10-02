# 知识检索 Query Transformation V1

## 在线链路

```text
unsupported_fact_reason
  -> QueryProcessor（一次 LLM 调用）
  -> original + rewrite + 0..N subqueries
  -> 每路沿用 vector + title/region scoped candidate retrieval
  -> chunk 级普通 RRF
  -> 每篇文档保留一个片段
  -> Top-K
```

`unsupported_fact_reason` 在模型调用前执行。QueryProcessor 超时、网关失败、JSON
不合法或关键数字/约束漂移时，执行与关闭功能时相同的 legacy 路径。

## 配置

默认关闭，避免未经成对评测和 Prompt Registry 发布就改变线上主链：

```dotenv
KNOWLEDGE_QUERY_TRANSFORM_ENABLED=0
QUERY_PROCESSOR_MAX_SUBQUERIES=3
# 阿里云混合推理模型建议设为 1，防止只返回 ThinkingBlock 而没有 JSON。
QUERY_PROCESSOR_DISABLE_THINKING=1
KNOWLEDGE_RRF_K=60
```

QueryProcessor 默认复用 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，无需新 Key。
只有需要独立网关或模型时才配置：

```dotenv
QUERY_PROCESSOR_BASE_URL=
QUERY_PROCESSOR_API_KEY=
QUERY_PROCESSOR_MODEL=
```

评测通过并发布绑定新工具契约的 Prompt 版本后，才把
`KNOWLEDGE_QUERY_TRANSFORM_ENABLED` 改为 `1`，随后重启 API 和 worker。

## 成对评测

同一 Git 版本、数据集、K 和 embedding 索引下分别运行：

```powershell
.\.venv-eval\Scripts\python.exe scripts/eval/run_category_recall.py --dataset eval/knowledge/v3/knowledge_eval_candidates.jsonl --strategy legacy --top-k 3
.\.venv-eval\Scripts\python.exe scripts/eval/run_category_recall.py --dataset eval/knowledge/v3/knowledge_eval_candidates.jsonl --strategy query-transform --rrf-k 60 --top-k 3
```

除 Recall/MRR/nDCG、证据和 hard-negative 指标外，报告增加：

- Pre-fusion information-need coverage
- Post-fusion information-need coverage
- Fusion information-need loss
- 每题 Query variants、候选数、processor fallback 原因和 provenance

前三项按冻结集的 gold evidence/hop 计算，不把普通向量近邻当作正确证据。线上 trace
另记 `pre/post_fusion_query_route_coverage`，它只回答各子查询通道是否有候选进入/保留，
不能替代质量指标。

V1 不加入知识 reranker，也不做 coverage-aware selection。先用冻结评测集验证 Query
Transformation 的独立收益，再决定是否引入下一变量。
