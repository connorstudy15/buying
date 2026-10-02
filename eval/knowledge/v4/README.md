# Knowledge benchmark v4（扩充候选，阶段 B 已审核、尚未冻结）

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

- 60 条盲 Query：已生成并完成结构自检；阶段 A 文件与 manifest 哈希保持冻结。
- 候选池：已生成，平均每题 14.38 个候选来源。
- 阶段 B 标签：独立审核已完成，45 条保留、15 条拒绝。
- 合并候选集：旧 Core 22 条 + 本轮保留 45 条，共 67 条；仍未冻结为正式 benchmark。
- Query 策略：8 条 implicit case 经用户终审从 DIRECT 改为 DECOMPOSE，详见 `QUERY_STRATEGY_ADJUDICATION.md`。

## DIRECT / DECOMPOSE 终审口径

即使用户只有一个最终判断目标，如果该判断必须组合两个可独立检索、可独立失败的 gold evidence needs，也应标为 `DECOMPOSE`。

这条口径判断的是证据需求结构，不是句子里出现了几个商品，也不是最终答案只有几个结论。

## 文件

- `blind_increment_queries.jsonl`：无答案的新 Query。
- `blind_increment_queries.manifest.json`：生成模型、Prompt 与输出哈希。
- `candidate_pool.jsonl`：多路候选池。
- `candidate_pool.manifest.json`：候选池参数与哈希。
- `stage_b_proposed_labels.jsonl`：阶段 B 成功后生成，仍是待审候选。
- `human_review_increment.csv`：给人工审批使用。
- `stage_b_reviewed_labels.jsonl`：阶段 B 全部 60 条的审核结果，包含拒绝项。
- `knowledge_eval_candidates.reviewed.jsonl`：旧 Core 与本轮 45 条保留项的合并候选集。
- `query_strategy_adjudication.jsonl`：机器可读的阶段 B 后策略裁决记录。
- `QUERY_STRATEGY_ADJUDICATION.md`：人工可读的策略裁决说明。

旧 22 条 Core 始终保留在 `eval/knowledge/v3/knowledge_eval_candidates.jsonl`，不会被本目录覆盖。
