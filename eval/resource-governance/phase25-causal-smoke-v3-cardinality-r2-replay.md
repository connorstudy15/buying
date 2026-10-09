# Resource Governance causal-smoke replay

- Eligible traces: `10/10`
- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Future information used: `false`

## Old vs first informed revision

| Metric | Revision 0 | First informed revision |
|---|---:|---:|
| MAE | 175258.5 | 113875.6 |
| MAPE | 0.7840277570688354 | 0.47484067717771355 |
| Underprediction rate | 0.6 | 0.8 |
| Underprediction P95 ratio | 0.9093641995435279 | 0.9245821106401478 |
| Overprediction rate | 0.4 | 0.2 |
| Operation-count MAE | 44.6 | 38.2 |
| Planned-budget exceed rate | 0.6 | 0.8 |
| Future-operation precision | 1.0 | 1.0 |
| Future-operation recall | 0.1449159720153635 | 0.2515792264759548 |
| Cost-weighted future recall | 0.3438391719420037 | 0.46932914882654153 |
| Cost-weighted future precision | 1.0 | 1.0 |
| Mandatory future recall | 0.6502675148433735 | 0.9429672803527925 |
| High-cost future recall | 0.5367154544496411 | 0.5622289093406562 |
| Main Final recall | 1.0 | 1.0 |
| Search Final recall | 0.0 | 0.8333333333333334 |
| Missing remaining cost (mean) | 193549.7 | 147074.7 |
| Unexpected predicted cost (mean) | 0.0 | 0.0 |

## Planning transitions

```json
{
  "target_transition_counts": {
    "main.plan": {
      "request_start": 10,
      "query_processor.rewrite": 1,
      "reranker.product": 21,
      "search.final": 6,
      "main.plan": 2,
      "reranker.knowledge.need": 1,
      "query_processor.direct": 1
    },
    "search.plan": {
      "main.plan": 6,
      "search.plan": 24,
      "reranker.product": 20,
      "embedding.product_query": 6,
      "reranker.knowledge.need": 2
    }
  },
  "potential_repeated_execution_counts": {
    "main.plan": 32,
    "embedding.product_query": 151,
    "reranker.product": 151,
    "search.plan": 52,
    "query_processor.direct": 9,
    "query_processor.decompose": 3
  }
}
```

## Operation catalog

| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |
|---|---:|---:|---:|---|---|---:|
| `embedding.product_query` | 159 | 31.0 | 41.0 | False | True | 151 |
| `reranker.product` | 159 | 1194.0 | 1288.0 | False | True | 151 |
| `search.plan` | 58 | 6772.0 | 17484.0 | False | True | 52 |
| `main.plan` | 42 | 16209.0 | 49106.0 | False | True | 32 |
| `reranker.knowledge.need` | 21 | 3493.0 | 3685.0 | False | True | 15 |
| `search.final` | 17 | 19436.0 | 31350.0 | False | True | 11 |
| `query_processor.direct` | 16 | 923.0 | 1332.0 | False | True | 9 |
| `main.final` | 10 | 31261.0 | 55732.0 | True | True | 0 |
| `query_processor.decompose` | 9 | 1372.0 | 1647.0 | False | True | 3 |
| `query_processor.rewrite` | 2 | 1068.0 | 1280.0 | False | True | 0 |

## Lifecycle and budget diagnostics

```json
{
  "future_operation_lifecycle": {
    "transition_count": 1325,
    "new_state_distribution": {
      "planned": 506,
      "completed": 434,
      "superseded": 29,
      "started": 339,
      "cancelled": 17
    },
    "transition_reason_distribution": {
      "MANDATORY_FINAL_PROTECTION": 27,
      "BOOTSTRAP_SPECULATIVE": 10,
      "QUERY_PROCESSOR_TYPE_UNKNOWN": 29,
      "observed_completed": 434,
      "UNRESOLVED_REQUIRED_NEED": 21,
      "placeholder_replaced_by_decompose": 8,
      "observed_upstream_started": 339,
      "placeholder_replaced_by_direct": 20,
      "placeholder_replaced_by_rewrite": 1,
      "PRODUCT_RETRIEVAL_EMITTED": 344,
      "SEARCH_RETURN_CONTINUATION": 75,
      "search_flow_finalized": 17
    },
    "obsolete_node_removal_count": 480,
    "query_processor_placeholder_replace_count": 29
  },
  "planned_budget_revision_response": {
    "plan_changed_revision_count": 562,
    "budget_recomputed_revision_count": 562,
    "budget_recomputation_rate": 1.0,
    "stale_not_recomputed_count": 0,
    "unchanged_budget_reason_distribution": {
      "SAME_ESTIMATED_COST": 378
    }
  },
  "prediction_reason_precision": {
    "MANDATORY_FINAL_PROTECTION": {
      "predicted": 27,
      "matched_later": 27,
      "precision": 1.0
    },
    "BOOTSTRAP_SPECULATIVE": {
      "predicted": 10,
      "matched_later": 10,
      "precision": 1.0
    },
    "QUERY_PROCESSOR_TYPE_UNKNOWN": {
      "predicted": 29,
      "matched_later": 0,
      "precision": 0.0
    },
    "UNRESOLVED_REQUIRED_NEED": {
      "predicted": 21,
      "matched_later": 21,
      "precision": 1.0
    },
    "PRODUCT_RETRIEVAL_EMITTED": {
      "predicted": 344,
      "matched_later": 336,
      "precision": 0.9767441860465116
    },
    "SEARCH_RETURN_CONTINUATION": {
      "predicted": 75,
      "matched_later": 62,
      "precision": 0.8266666666666667
    }
  },
  "product_retrieval_totals": {
    "initial_search": 8,
    "same_need_refinement": 114,
    "different_need": 21,
    "same_need_evidence_insufficient": 28,
    "exact_duplicate": 1
  }
}
```

Revision 0 vs first informed revision compares two causal checkpoints in the same execution; it is not a controlled comparison of two software versions.
Prediction-reason precision currently matches later operation names and is diagnostic only; concurrent logical-call identity requires a separate gate.
