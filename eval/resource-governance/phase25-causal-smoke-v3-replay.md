# Resource Governance causal-smoke replay

- Eligible traces: `14/14`
- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Future information used: `false`

## Old vs first informed revision

| Metric | Revision 0 | First informed revision |
|---|---:|---:|
| MAE | 164712.64285714287 | 152514.2142857143 |
| MAPE | 0.6999853354490304 | 0.5865271684840841 |
| Underprediction rate | 0.6428571428571429 | 0.7857142857142857 |
| Underprediction P95 ratio | 0.9303302450312868 | 0.934271545469505 |
| Overprediction rate | 0.35714285714285715 | 0.21428571428571427 |
| Operation-count MAE | 37.5 | 33.214285714285715 |
| Planned-budget exceed rate | 0.5714285714285714 | 0.8571428571428571 |
| Future-operation precision | 1.0 | 1.0 |
| Future-operation recall | 0.17232019656249678 | 0.2724369198697101 |
| Cost-weighted future recall | 0.3874510790625439 | 0.4116233740407185 |
| Cost-weighted future precision | 1.0 | 1.0 |
| Mandatory future recall | 0.7678357685186796 | 0.8466405980778495 |
| High-cost future recall | 0.588958300978418 | 0.3632716634708708 |
| Main Final recall | 1.0 | 1.0 |
| Search Final recall | 0.0 | 0.3333333333333333 |
| Missing remaining cost (mean) | 180102.92857142858 | 161376.7857142857 |
| Unexpected predicted cost (mean) | 0.0 | 0.0 |

## Planning transitions

```json
{
  "target_transition_counts": {
    "main.plan": {
      "request_start": 14,
      "query_processor.rewrite": 1,
      "query_processor.direct": 2,
      "reranker.knowledge.need": 3,
      "reranker.product": 30,
      "main.plan": 7,
      "search.final": 5
    },
    "search.plan": {
      "main.plan": 6,
      "search.plan": 24,
      "reranker.product": 23,
      "embedding.product_query": 3,
      "search.final": 1,
      "reranker.knowledge.need": 2
    }
  },
  "potential_repeated_execution_counts": {
    "main.plan": 48,
    "embedding.product_query": 175,
    "reranker.product": 175,
    "search.plan": 53,
    "query_processor.direct": 9,
    "query_processor.decompose": 4
  }
}
```

## Operation catalog

| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |
|---|---:|---:|---:|---|---|---:|
| `embedding.product_query` | 187 | 32.0 | 43.0 | False | True | 175 |
| `reranker.product` | 187 | 1208.0 | 1303.0 | False | True | 175 |
| `main.plan` | 62 | 15389.0 | 56557.0 | False | True | 48 |
| `search.plan` | 59 | 7165.0 | 18143.0 | False | True | 53 |
| `reranker.knowledge.need` | 28 | 3469.0 | 3661.0 | False | True | 21 |
| `query_processor.direct` | 18 | 929.0 | 1597.0 | False | True | 9 |
| `search.final` | 16 | 21402.0 | 27894.0 | False | True | 10 |
| `main.final` | 14 | 19768.0 | 78911.0 | True | True | 0 |
| `query_processor.decompose` | 11 | 1269.0 | 1613.0 | False | True | 4 |
| `query_processor.rewrite` | 2 | 1132.0 | 1141.0 | False | True | 0 |

## Lifecycle and budget diagnostics

```json
{
  "future_operation_lifecycle": {
    "transition_count": 787,
    "new_state_distribution": {
      "planned": 288,
      "completed": 256,
      "superseded": 30,
      "started": 213
    },
    "transition_reason_distribution": {
      "BOOTSTRAP_SPECULATIVE": 14,
      "MANDATORY_FINAL_PROTECTION": 20,
      "observed_completed": 256,
      "QUERY_PROCESSOR_TYPE_UNKNOWN": 30,
      "UNRESOLVED_REQUIRED_NEED": 28,
      "placeholder_replaced_by_decompose": 9,
      "observed_upstream_started": 213,
      "placeholder_replaced_by_direct": 19,
      "placeholder_replaced_by_rewrite": 2,
      "PRODUCT_RETRIEVAL_EMITTED": 190,
      "SEARCH_RETURN_CONTINUATION": 6
    },
    "obsolete_node_removal_count": 286,
    "query_processor_placeholder_replace_count": 30
  },
  "planned_budget_revision_response": {
    "plan_changed_revision_count": 416,
    "budget_recomputed_revision_count": 416,
    "budget_recomputation_rate": 1.0,
    "stale_not_recomputed_count": 0,
    "unchanged_budget_reason_distribution": {
      "SAME_ESTIMATED_COST": 321
    }
  },
  "prediction_reason_precision": {
    "BOOTSTRAP_SPECULATIVE": {
      "predicted": 14,
      "matched_later": 14,
      "precision": 1.0
    },
    "MANDATORY_FINAL_PROTECTION": {
      "predicted": 20,
      "matched_later": 20,
      "precision": 1.0
    },
    "QUERY_PROCESSOR_TYPE_UNKNOWN": {
      "predicted": 30,
      "matched_later": 0,
      "precision": 0.0
    },
    "UNRESOLVED_REQUIRED_NEED": {
      "predicted": 28,
      "matched_later": 28,
      "precision": 1.0
    },
    "PRODUCT_RETRIEVAL_EMITTED": {
      "predicted": 190,
      "matched_later": 188,
      "precision": 0.9894736842105263
    },
    "SEARCH_RETURN_CONTINUATION": {
      "predicted": 6,
      "matched_later": 6,
      "precision": 1.0
    }
  },
  "product_retrieval_totals": {
    "initial_search": 12,
    "same_need_refinement": 154,
    "different_need": 22,
    "exact_duplicate": 1
  }
}
```

Revision 0 vs first informed revision compares two causal checkpoints in the same execution; it is not a controlled comparison of two software versions.
Prediction-reason precision currently matches later operation names and is diagnostic only; concurrent logical-call identity requires a separate gate.
