# Knowledge Corpus Isolation Report

## Corpus

- Production：12 docs / 12 chunks；collection `globex_category_kb` / 12 points。
- Evaluation：45 docs / 151 chunks；collection `globex_category_kb_eval` / 151 points。
- Production manifest SHA-256：`8c27d56eda7a2fd50a42bb66e626630ae049b91630897733fbef77b429236d5c`
- Evaluation source manifest SHA-256：`47b2e0c92c25d187be3b52f855e5c6675406b1ca18a045537a79c143368f0abf`
- Frozen evaluation corpus manifest SHA-256：`c0473ab320aca136281cc719559ef930bd371b0722f867826c282b8c41a4171b`

## Isolation regression

- Exact ranking match：`True`
- Metric match：`True`
- Query Plan SHA-256：`4fd24d67ed9c903df3ff5970e06efdeaf032f69b79fa85be89e3dc853ad38403`

## Production sanity

- evidence_recall_at_k: `1.0`
- all_required_needs_recall_at_k: `1`
- information_need_coverage_at_k: `1.0`
- unanswerable_abstention_accuracy: `0.14285714285714285`
- latency_p50_ms: `202.08394998917356`
- latency_p95_ms: `312.38604499521875`

## Recommendation

暂不把 role-aware Flash 接入正式 Candidate B。当前 24 题在现有 production retriever 上的 answerable Recall@3 已无提升空间，但不可回答拒答率明显不足；先人工抽查 sanity gold，扩大 production 查询与困难负例，再做 symmetric vs role-aware 的独立对照。
