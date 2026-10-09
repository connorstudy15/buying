# Resource Governance causal-smoke replay

- Eligible traces: `12/12`
- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Future information used: `false`

## Old vs first informed revision

| Metric | Revision 0 | First informed revision |
|---|---:|---:|
| MAE | 50729.416666666664 | 37025.5 |
| MAPE | 0.5464560663566984 | 0.5623276977222245 |
| Underprediction rate | 0.5833333333333334 | 0.5 |
| Underprediction P95 ratio | 0.8352424717778103 | 0.7998822511369877 |
| Overprediction rate | 0.4166666666666667 | 0.5 |
| Operation-count MAE | 9.75 | 6.0 |
| Planned-budget exceed rate | 0.5 | 0.5 |

## Operation catalog

| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |
|---|---:|---:|---:|---|---|---:|
| `embedding.product_query` | 68 | 30.0 | 37.0 | False | True | 57 |
| `reranker.product` | 68 | 1180.0 | 1248.0 | False | True | 57 |
| `main.plan` | 34 | 12976.0 | 24527.0 | False | True | 22 |
| `reranker.knowledge.need` | 14 | 3493.0 | 3661.0 | False | True | 8 |
| `main.final` | 12 | 18402.0 | 37586.0 | True | True | 0 |
| `search.plan` | 10 | 7802.0 | 33606.0 | False | True | 7 |
| `query_processor.decompose` | 7 | 1051.0 | 1432.0 | False | True | 1 |
| `query_processor.direct` | 6 | 859.0 | 1268.0 | False | True | 1 |
| `search.final` | 3 | 30595.0 | 47000.0 | False | True | 0 |
