# Resource Governance causal-smoke replay

- Eligible traces: `12/12`
- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Future information used: `false`

## Old vs first informed revision

| Metric | Revision 0 | First informed revision |
|---|---:|---:|
| MAE | 16852.583333333332 | 17834.083333333332 |
| MAPE | 0.4616091427830629 | 0.5924926875569322 |
| Underprediction rate | 0.5 | 0.3333333333333333 |
| Underprediction P95 ratio | 0.4782657657657658 | 0.2842436414196031 |
| Overprediction rate | 0.5 | 0.6666666666666666 |
| Operation-count MAE | 5.5 | 2.8333333333333335 |
| Planned-budget exceed rate | 0.4166666666666667 | 0.4166666666666667 |
| Future-operation precision | 1.0 | 0.7611111111111111 |
| Future-operation recall | 0.2890542328042328 | 0.6803418803418803 |
| Cost-weighted future recall | 0.5860602100570889 | 0.8433761685459794 |
| Cost-weighted future precision | 1.0 | 0.8386612117310229 |
| Mandatory future recall | 1.0 | 1.0 |
| High-cost future recall | 0.8845772831576889 | 0.9155186966161121 |
| Main Final recall | 1.0 | 1.0 |
| Search Final recall | None | None |
| Missing remaining cost (mean) | 27683.583333333332 | 9230.666666666666 |
| Unexpected predicted cost (mean) | 0.0 | 4684.75 |

## Planning transitions

```json
{
  "target_transition_counts": {
    "main.plan": {
      "request_start": 12,
      "reranker.product": 9,
      "query_processor.direct": 1,
      "reranker.knowledge.need": 4,
      "main.plan": 1
    },
    "search.plan": {}
  },
  "potential_repeated_execution_counts": {
    "main.plan": 15,
    "query_processor.direct": 1,
    "embedding.product_query": 24,
    "reranker.product": 24
  }
}
```

## Operation catalog

| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |
|---|---:|---:|---:|---|---|---:|
| `embedding.product_query` | 34 | 30.0 | 35.0 | False | True | 24 |
| `reranker.product` | 34 | 1197.0 | 1256.0 | False | True | 24 |
| `main.plan` | 27 | 10974.0 | 20183.0 | False | True | 15 |
| `reranker.knowledge.need` | 17 | 3469.0 | 3601.0 | False | True | 11 |
| `main.final` | 12 | 17212.0 | 26536.0 | True | True | 0 |
| `query_processor.decompose` | 6 | 1389.0 | 1602.0 | False | True | 0 |
| `query_processor.direct` | 4 | 941.0 | 1101.0 | False | True | 1 |
| `query_processor.rewrite` | 1 | 1162.0 | 1162.0 | False | True | 0 |
