# B0-native-symmetric vs D0-role

两组共用同一批 DashScope native `text_type=document` 文档向量；唯一变量是 Query 的 `text_type`。

| Metric | Native symmetric (query=document) | D0-role (query=query) | Delta |
|---|---:|---:|---:|
| Recall@5 | 0.8099 | 0.7958 | -0.0141 |
| Recall@10 | 0.8099 | 0.8310 | +0.0211 |
| Recall@24 | 0.8451 | 0.8732 | +0.0282 |
| Recall@50 | 0.9507 | 0.9437 | -0.0070 |
| MRR | 0.7201 | 0.7819 | +0.0618 |
| Retrieval Loss gold | 6 | 6 | +0 |
| Hard-negative outrank positive | 0.1667 | 0.0833 | -0.0833 |

## Buckets

- `DECOMPOSE_SUBQUERY`：Recall@24 0.8500 → 0.8750；MRR 0.7460 → 0.7765。
- `DIRECT`：Recall@24 0.8387 → 0.8710；MRR 0.6867 → 0.7888。
- `domain_rule`：Recall@24 0.7727 → 0.7955；MRR 0.6995 → 0.7482。
- `implicit_cross_domain`：Recall@24 0.8409 → 0.8636；MRR 0.7463 → 0.7741。
- `multi_evidence`：Recall@24 0.8600 → 0.8800；MRR 0.7568 → 0.7912。
- `single_evidence`：Recall@24 0.8095 → 0.8571；MRR 0.6327 → 0.7597。

## Paired movement

{
  "gold_rank_improved": 22,
  "gold_rank_unchanged": 60,
  "gold_rank_worsened": 11,
  "query_level_win": 2,
  "query_level_tie": 69,
  "query_level_loss": 0,
  "query_level_ids": {
    "win": [
      "blind-014::original",
      "v4-051::subquery_1"
    ],
    "tie": [
      "blind-001::original",
      "blind-002::original",
      "blind-005::original",
      "blind-006::original",
      "blind-007::original",
      "blind-008::original",
      "blind-010::original",
      "blind-012::original",
      "blind-013::original",
      "blind-016::original",
      "blind-017::original",
      "blind-018::original",
      "blind-019::subquery_1",
      "blind-019::subquery_2",
      "blind-021::subquery_1",
      "blind-021::subquery_2",
      "blind-025::subquery_1",
      "blind-025::subquery_2",
      "blind-030::original",
      "human-mh-001::original",
      "human-mh-002::subquery_1",
      "human-mh-002::subquery_2",
      "v4-002::original",
      "v4-005::original",
      "v4-006::original",
      "v4-017::original",
      "v4-020::original",
      "v4-021::original",
      "v4-022::original",
      "v4-024::subquery_1",
      "v4-024::subquery_2",
      "v4-026::subquery_1",
      "v4-026::subquery_2",
      "v4-027::original",
      "v4-028::subquery_1",
      "v4-028::subquery_2",
      "v4-029::subquery_1",
      "v4-029::subquery_2",
      "v4-030::subquery_1",
      "v4-030::subquery_2",
      "v4-030::subquery_3",
      "v4-031::subquery_1",
      "v4-031::subquery_2",
      "v4-034::subquery_1",
      "v4-034::subquery_2",
      "v4-035::original",
      "v4-037::subquery_1",
      "v4-037::subquery_2",
      "v4-038::subquery_1",
      "v4-038::subquery_2",
      "v4-040::subquery_1",
      "v4-040::subquery_2",
      "v4-041::subquery_1",
      "v4-041::subquery_2",
      "v4-041::subquery_3",
      "v4-043::subquery_1",
      "v4-043::subquery_2",
      "v4-046::subquery_1",
      "v4-046::subquery_2",
      "v4-048::subquery_1",
      "v4-048::subquery_2",
      "v4-049::original",
      "v4-051::subquery_2",
      "v4-r002::original",
      "v4-r006::original",
      "v4-r007::original",
      "v4-r008::original",
      "v4-r010::original",
      "v4-060::original"
    ],
    "loss": []
  }
}
