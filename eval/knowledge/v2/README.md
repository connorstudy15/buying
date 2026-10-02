# 知识召回 v2：答案条件化草稿（不得晋级）

> **状态：废弃草稿。** 本批 Query 是在生成器看过正文证据后反推得到，存在答案泄漏和题目过于贴合语料的问题。保留仅用于审计，不得并入正式 dev/release，也不再要求人工审核。

本目录是新评测集的候选区，不会自动并入正式 dev/release。旧的 50 条文档级用例继续作为 regression subset。

## 本批构成

- 30 条候选：18 条单文档证据题、8 条跨文档证据题、3 条不可回答题、1 条政策边界题。
- 每条由 GPT Sol 草拟 `query`、`evidence`、`graded_relevance`、hard negative、理由和置信度。
- `evidence.quote` 已自动检查，均能在当前冻结语料中逐字找到。
- 当前统一标记为 `split=candidate`、`label_status=pending_human_review`。

## 相关性等级

- `3`：直接、完整回答 Query 的核心证据，应当进入最终上下文。
- `2`：提供必要辅助证据，但不能独立完整回答。
- `1`：主题相近或有少量背景价值，不应挤掉 3 级证据。
- `0`：不回答该 Query；若词面或主题很像，可作为 hard negative。

## 人工审核方法（目标不超过 2 小时）

打开 `human_review.csv`，每条只做以下判断：

1. `query` 是否像真实用户会问的问题。
2. `evidence` 是否真的足以支持问题答案。
3. `relevant` 和 `graded_relevance` 是否合理。
4. hard negative 是否确实“看起来相关但不能回答”。
5. 在 `decision` 填 `approve`、`edit` 或 `reject`。

如果选择 `edit`，只填写需要修改的 `corrected_*` 列；补充说明写到 `reviewer_notes`。建议先审核低于 0.98 置信度的条目，再审核跨文档和政策边界题。

## 晋级规则

- 只有 `decision=approve`，或 `decision=edit` 且修改内容完整的条目，才能成为正式金标。
- 晋级时再按题族分组切分 dev/release，避免同一事实的改写版本跨 split 泄漏。
- 正式评测同时保留文档级 Recall/MRR/nDCG，并增加 evidence hit、graded nDCG、hard-negative intrusion、拒答准确率和 latency。
- 父子块实验使用相同 Query 和证据金标；检索使用 child，评分同时检查命中的 evidence 与返回的 parent。
