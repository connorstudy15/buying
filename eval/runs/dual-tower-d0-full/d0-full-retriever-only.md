# Dual-Tower Experiment D0-full

本实验只把 role-aware encoder 从 Flash 换成 Full；Query Plan、151 个 chunk、角色、Top-50 和 evaluator 均冻结。

| Metric | Flash role | Full role | Delta |
|---|---:|---:|---:|
| Recall@5 | 0.7958 | 0.5423 | -0.2535 |
| Recall@10 | 0.8310 | 0.7042 | -0.1268 |
| Recall@24 | 0.8732 | 0.7887 | -0.0845 |
| Recall@50 | 0.9437 | 0.9296 | -0.0141 |
| MRR | 0.7819 | 0.4984 | -0.2835 |
| Retrieval Loss gold | 6 | 8 | +2 |
| Hard-negative outrank-positive | 0.0833 | 0.2708 | +0.1875 |

## Buckets

- `DECOMPOSE_SUBQUERY`：Recall@24 0.8750 → 0.7625；MRR 0.7765 → 0.5210。
- `DIRECT`：Recall@24 0.8710 → 0.8226；MRR 0.7888 → 0.4692。
- `domain_rule`：Recall@24 0.7955 → 0.7727；MRR 0.7482 → 0.4611。
- `implicit_cross_domain`：Recall@24 0.8636 → 0.7727；MRR 0.7741 → 0.5227。
- `multi_evidence`：Recall@24 0.8800 → 0.8000；MRR 0.7912 → 0.5256。
- `single_evidence`：Recall@24 0.8571 → 0.7619；MRR 0.7597 → 0.4337。

## Rank movement

```json
{
  "gold_rank_improved": 15,
  "gold_rank_unchanged": 29,
  "gold_rank_worsened": 49,
  "query_level_win": 3,
  "query_level_tie": 59,
  "query_level_loss": 9,
  "query_level_ids": {
    "win": [
      "human-mh-001::original",
      "v4-006::original",
      "v4-030::subquery_3"
    ],
    "tie": [
      "blind-001::original",
      "blind-002::original",
      "blind-005::original",
      "blind-006::original",
      "blind-007::original",
      "blind-008::original",
      "blind-012::original",
      "blind-013::original",
      "blind-016::original",
      "blind-017::original",
      "blind-018::original",
      "blind-021::subquery_1",
      "blind-021::subquery_2",
      "blind-025::subquery_1",
      "blind-025::subquery_2",
      "blind-030::original",
      "human-mh-002::subquery_1",
      "human-mh-002::subquery_2",
      "v4-002::original",
      "v4-005::original",
      "v4-017::original",
      "v4-020::original",
      "v4-021::original",
      "v4-022::original",
      "v4-024::subquery_1",
      "v4-024::subquery_2",
      "v4-026::subquery_1",
      "v4-027::original",
      "v4-028::subquery_1",
      "v4-028::subquery_2",
      "v4-029::subquery_1",
      "v4-029::subquery_2",
      "v4-030::subquery_1",
      "v4-030::subquery_2",
      "v4-031::subquery_1",
      "v4-031::subquery_2",
      "v4-034::subquery_1",
      "v4-034::subquery_2",
      "v4-035::original",
      "v4-037::subquery_1",
      "v4-038::subquery_1",
      "v4-038::subquery_2",
      "v4-040::subquery_1",
      "v4-040::subquery_2",
      "v4-041::subquery_1",
      "v4-041::subquery_2",
      "v4-041::subquery_3",
      "v4-043::subquery_2",
      "v4-046::subquery_1",
      "v4-046::subquery_2",
      "v4-048::subquery_1",
      "v4-048::subquery_2",
      "v4-049::original",
      "v4-051::subquery_2",
      "v4-r002::original",
      "v4-r006::original",
      "v4-r008::original",
      "v4-r010::original",
      "v4-060::original"
    ],
    "loss": [
      "blind-010::original",
      "blind-014::original",
      "blind-019::subquery_1",
      "blind-019::subquery_2",
      "v4-026::subquery_2",
      "v4-037::subquery_2",
      "v4-043::subquery_1",
      "v4-051::subquery_1",
      "v4-r007::original"
    ]
  }
}
```
