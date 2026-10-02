# 知识召回 v3：盲 Query → 检索标注 → 人工审批

## 状态

阶段 A、阶段 B 与口径审核已完成。`knowledge-eval-v1` 已于 2026-10-02 冻结；冻结范围和文件哈希见 `FROZEN_V1_MANIFEST.json`。`blind_queries*.jsonl` 只有问题和场景，不包含答案，不应直接交给召回评测器。

## 隔离规则

1. Query 生成请求只能读取 `query_generation_index.json`，不得读取 `knowledge/*.md`。
2. 目录索引只说明品类、对象范围和问题维度，不含具体结论、数字、证据句或文档标签。
3. Query 文件写入后，以 SHA-256 冻结；阶段 B 不得修改 Query，只能标记可回答、不可回答或淘汰。
4. 阶段 B 才允许检索正文，建立候选池并标注 evidence、graded relevance 和 hard negative。
5. 找不到充分证据时不得硬配相关文档：应改标为 unanswerable 或 reject，再由阶段 A 补生成新题。
6. 人工只审批阶段 B 的标注结果，不审批已经废弃的 v2 答案条件化草稿。

## 当前文件

- `query_generation_index.json`：无答案目录卡片。
- `blind_queries.jsonl`：第二轮盲生成的30条口语化问题。
- `blind_queries.manifest.json`：模型、索引、Prompt 与输出哈希；明确记录 `knowledge_body_exposed=false`。
- `blind_queries-index-too-coarse.*`：第一轮仅看 manifest 的失败实验，保留用于审计。它证明索引过粗会生成大量知识库范围外问题。
- `blind_multihop_queries.jsonl`：在原 30 条冻结集之外盲生成的 2 条顺序多跳增补题。
- `blind_multihop_queries.manifest.json`：多跳增补集的独立 Prompt、索引与输出哈希；仍记录 `knowledge_body_exposed=false`。
- `candidate_pool_multihop.jsonl`：两条多跳题的独立 BM25、向量与标题路由候选池。
- `stage_b_multihop_labels.jsonl`：逐跳依赖、证据、覆盖点与禁止推断标注。两题均为条件式可回答，不能在缺少具体航司、航线或 SKU 参数时给确定结论。
- `human_multihop_queries.jsonl`：用户只根据知识索引摘要亲自编写的 2 条隐式约束多跳题；正式审批使用这一版。
- `stage_b_human_multihop_labels.jsonl`：人工题的逐跳标注。第一题测试主动发现充电宝航空限制，第二题测试拒绝“任意航空公司均适用”的无依据保证。
- `blind_multihop_queries.*` 与 `stage_b_multihop_labels.jsonl`：被人工题替换的机器增补实验，仅保留审计，不再进入正式审批表。
- `human_review.csv`：合并原阶段 B 与多跳增补后的人工审批表；当前 32 个候选中 22 条进入审批，10 条被机器预标为 reject。
- `LABELING_CONTRACT.md`：统一 `grade=0..3`、hard negative 与各分桶指标的定义。
- `knowledge_eval_candidates.jsonl`：由保留题编译出的 evidence-level 可执行金标集；当前均为 `frozen_v1`。
- `evidence_mapping_review.csv`：原文、章节或等级契约无法自动确认时的异常清单；当前只有表头，表示机械映射没有发现冲突。
- `FROZEN_V1_MANIFEST.json`：冻结版本、唯一真值规则、样本分布与关键文件 SHA-256。后续新增题不得原地改写 v1，应进入新的增量集或升级版本。

当前 22 条候选的分布为：single evidence 12、cross evidence 4、unanswerable 3、policy boundary 1、implicit-constraint multi-hop 2。`blind-008` 经阶段 B 审核由 single evidence 修正为 cross evidence；盲生成原始文件不回写，保留初始分类供审计。它适合先跑开发基线，但尚未达到建议的正式集规模；尤其 semantic/paraphrase、hard-negative 专桶、context-dependent 和纯知识 true multi-hop 仍需后续补题。

## 阶段 B 输出要求

每条冻结 Query 应输出：`label_decision`、`answerability`、`relevant`、`evidence`、`graded_relevance`、`hard_negatives`、理由和置信度。顺序多跳题还必须输出 `hops`、`depends_on`、`must_cover` 与 `forbidden_inferences`。只有 `label_decision=keep` 的条目进入人工审核表。

重新生成 evidence-level 候选集：

```powershell
uv run python scripts/eval/enrich_knowledge_v3_labels.py
```

冻结后的 v1 可以作为基线输入。跨到商品检索的多跳题在 Query Planner/Agent trace 接入前，`Path Success` 与 `Constraint Recall` 必须保持 `n/a`。
