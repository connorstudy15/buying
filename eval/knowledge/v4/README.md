# Knowledge benchmark v4（扩充候选，待人工审批）

## 目标

在不修改已冻结 `knowledge-eval-v1` 22 条 Core 的前提下，新增 60 条专项候选；全部批准后总规模为 82 条。

计划分布（旧 Core + 新增候选）：

| 主桶 | 旧 Core | 新增候选 | 目标合计 |
|---|---:|---:|---:|
| single evidence | 12 | 22 | 34 |
| cross / multi evidence | 4 | 20 | 24 |
| implicit constraint | 2 | 10 | 12 |
| unanswerable | 3 | 7 | 10 |
| policy boundary | 1 | 1 | 2 |
| 总计 | 22 | 60 | 82 |

`hard negative` 是可与上述主桶重叠的专项标签，阶段 B 目标保留 15～20 条高质量样本，不应为了凑数把普通负例强行标成 hard negative。

## 数据隔离

1. `blind_increment_queries.jsonl` 只根据 `v3/query_generation_index.json` 生成；模型未看到知识正文。
2. `candidate_pool.jsonl` 在 Query 冻结后，由 BM25、向量和标题路由共同建立。
3. 阶段 B 才能读取候选正文并提出 grade、evidence 和 hard negative。
4. 阶段 B 结果一律先标记 `pending_human_review`。人工审批前不得合并进冻结 Core，也不得用于正式上线结论。

## 当前状态

- 60 条盲 Query：已生成并完成结构自检。
- 候选池：已生成，平均每题 14.38 个候选来源。
- 阶段 B 标签：等待用户明确授权把候选知识正文发送给配置的阿里云百炼模型。
- 人工审批：尚未开始。

## 文件

- `blind_increment_queries.jsonl`：无答案的新 Query。
- `blind_increment_queries.manifest.json`：生成模型、Prompt 与输出哈希。
- `candidate_pool.jsonl`：多路候选池。
- `candidate_pool.manifest.json`：候选池参数与哈希。
- `stage_b_proposed_labels.jsonl`：阶段 B 成功后生成，仍是待审候选。
- `human_review_increment.csv`：给人工审批使用。

旧 22 条 Core 始终保留在 `eval/knowledge/v3/knowledge_eval_candidates.jsonl`，不会被本目录覆盖。
