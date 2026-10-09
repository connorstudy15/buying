# Resource Governance causal-smoke replay

- Eligible traces: `11/11`
- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Future information used: `false`

## Old vs first informed revision

| Metric | Revision 0 | First informed revision |
|---|---:|---:|
| MAE | 96963.72727272728 | 65701.27272727272 |
| MAPE | 0.6890875842633348 | 0.47721070623382844 |
| Underprediction rate | 0.6363636363636364 | 0.6363636363636364 |
| Underprediction P95 ratio | 0.8634662423010049 | 0.870436592348998 |
| Overprediction rate | 0.36363636363636365 | 0.36363636363636365 |
| Operation-count MAE | 25.0 | 19.90909090909091 |
| Planned-budget exceed rate | 0.45454545454545453 | 0.6363636363636364 |
| Future-operation precision | 1.0 | 0.8205922865013775 |
| Future-operation recall | 0.25052226166515434 | 0.3487199745960291 |
| Cost-weighted future recall | 0.47205937488455624 | 0.5119190018136011 |
| Cost-weighted future precision | 1.0 | 1.0 |
| Mandatory future recall | 0.8432202620048245 | 1.0 |
| High-cost future recall | 0.6407898604964168 | 0.5748682149385327 |
| Main Final recall | 1.0 | 1.0 |
| Search Final recall | 0.0 | 1.0 |
| Missing remaining cost (mean) | 106975.54545454546 | 82183.81818181818 |
| Unexpected predicted cost (mean) | 0.0 | 0.0 |

## Planning transitions

```json
{
  "target_transition_counts": {
    "main.plan": {
      "request_start": 11,
      "reranker.product": 22,
      "main.plan": 2,
      "search.final": 3,
      "reranker.knowledge.need": 2
    },
    "search.plan": {
      "main.plan": 3,
      "search.plan": 10,
      "reranker.product": 6,
      "search.final": 1,
      "embedding.product_query": 4
    }
  },
  "potential_repeated_execution_counts": {
    "main.plan": 29,
    "embedding.product_query": 95,
    "reranker.product": 95,
    "search.plan": 21,
    "query_processor.direct": 2
  }
}
```

## Operation catalog

| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |
|---|---:|---:|---:|---|---|---:|
| `embedding.product_query` | 104 | 32.0 | 39.0 | False | True | 95 |
| `reranker.product` | 104 | 1203.0 | 1285.0 | False | True | 95 |
| `main.plan` | 40 | 13431.0 | 39349.0 | False | True | 29 |
| `search.plan` | 24 | 7005.0 | 17178.0 | False | True | 21 |
| `main.final` | 11 | 18557.0 | 44034.0 | True | True | 0 |
| `query_processor.direct` | 8 | 941.0 | 1080.0 | False | True | 2 |
| `search.final` | 8 | 20051.0 | 32674.0 | False | True | 5 |
| `reranker.knowledge.need` | 6 | 3541.0 | 3625.0 | False | True | 4 |
| `query_processor.decompose` | 2 | 1357.0 | 1598.0 | False | True | 0 |
| `query_processor.rewrite` | 2 | 1317.0 | 1518.0 | False | True | 0 |

## Lifecycle and budget diagnostics

```json
{
  "future_operation_lifecycle": {
    "transition_count": 806,
    "new_state_distribution": {
      "planned": 304,
      "completed": 268,
      "started": 214,
      "superseded": 12,
      "cancelled": 8
    },
    "transition_reason_distribution": {
      "BOOTSTRAP_SPECULATIVE": 11,
      "MANDATORY_FINAL_PROTECTION": 19,
      "observed_completed": 54,
      "QUERY_PROCESSOR_TYPE_UNKNOWN": 18,
      "PRODUCT_RETRIEVAL_EMITTED": 218,
      "observed_upstream_started": 214,
      "exact_observed_completed": 214,
      "placeholder_replaced_by_direct": 8,
      "placeholder_replaced_by_rewrite": 2,
      "SEARCH_RETURN_CONTINUATION": 32,
      "child_flow_finalized": 8,
      "UNRESOLVED_REQUIRED_NEED": 6,
      "placeholder_replaced_by_decompose": 2
    },
    "obsolete_node_removal_count": 288,
    "query_processor_placeholder_replace_count": 12
  },
  "planned_budget_revision_response": {
    "plan_changed_revision_count": 346,
    "budget_recomputed_revision_count": 346,
    "budget_recomputation_rate": 1.0,
    "stale_not_recomputed_count": 0,
    "unchanged_budget_reason_distribution": {
      "SAME_ESTIMATED_COST": 246
    }
  },
  "prediction_reason_precision": {
    "BOOTSTRAP_SPECULATIVE": {
      "predicted": 11,
      "matched_later": 11,
      "precision": 1.0
    },
    "MANDATORY_FINAL_PROTECTION": {
      "predicted": 19,
      "matched_later": 19,
      "precision": 1.0
    },
    "QUERY_PROCESSOR_TYPE_UNKNOWN": {
      "predicted": 18,
      "matched_later": 0,
      "precision": 0.0
    },
    "PRODUCT_RETRIEVAL_EMITTED": {
      "predicted": 218,
      "matched_later": 212,
      "precision": 0.9724770642201835
    },
    "SEARCH_RETURN_CONTINUATION": {
      "predicted": 32,
      "matched_later": 27,
      "precision": 0.84375
    },
    "UNRESOLVED_REQUIRED_NEED": {
      "predicted": 6,
      "matched_later": 6,
      "precision": 1.0
    }
  },
  "product_retrieval_totals": {
    "initial_search": 9,
    "same_need_refinement": 60,
    "different_need": 15,
    "same_need_duplicate_candidate": 2,
    "same_need_evidence_insufficient": 23
  }
}
```

Revision 0 vs first informed revision compares two causal checkpoints in the same execution; it is not a controlled comparison of two software versions.
Prediction-reason precision currently matches later operation names and is diagnostic only; concurrent logical-call identity requires a separate gate.
