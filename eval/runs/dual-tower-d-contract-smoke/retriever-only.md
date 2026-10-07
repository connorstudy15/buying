# Dual-Tower Experiment D — Retriever-only

## Overall

| Metric | Baseline | Dual Tower | Delta |
|---|---:|---:|---:|
| Recall@5 | 1.0000 | 1.0000 | +0.0000 |
| Recall@10 | 1.0000 | 1.0000 | +0.0000 |
| Recall@24 | 1.0000 | 1.0000 | +0.0000 |
| Recall@50 | 1.0000 | 1.0000 | +0.0000 |
| MRR | 1.0000 | 1.0000 | +0.0000 |
| Gold Mean Rank (miss=51) | 1 | 1 | n/a |
| Gold Median Rank (miss=51) | 1.0 | 1.0 | n/a |
| Retrieval Loss gold count | 0 | 0 | n/a |
| Hard-negative outrank positive | 0.0 | 0.0 | n/a |

## Buckets

- `DECOMPOSE_SUBQUERY`：Recall@24 1.0000 → 1.0000；MRR 1.0000 → 1.0000。
- `DIRECT`：Recall@24 1.0000 → 1.0000；MRR 1.0000 → 1.0000。
- `domain_rule`：Recall@24 1.0000 → 1.0000；MRR 1.0000 → 1.0000。
- `implicit_cross_domain`：Recall@24 1.0000 → 1.0000；MRR 1.0000 → 1.0000。
- `multi_evidence`：Recall@24 1.0000 → 1.0000；MRR 1.0000 → 1.0000。
- `single_evidence`：Recall@24 1.0000 → 1.0000；MRR 1.0000 → 1.0000。

## Rank movement

| Case | Evidence | Old | Dual | Delta | Old score | New score |
|---|---|---:|---:|---:|---:|---:|
| frozen-demo-direct | frozen.md#answer#demo | 1 | 1 | +0 | 0.9 | 0.9 |
| frozen-demo-parent | frozen-rule.md#answer#demo | 1 | 1 | +0 | 0.88 | 0.88 |

## Regression

- Strict regression @24：`none`
- Easy single-evidence regression @5：`none`
