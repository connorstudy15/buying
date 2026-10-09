# Resource Governance causal-smoke replay

- Eligible traces: `2/2`
- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Future information used: `false`

## Old vs first informed revision

| Metric | Revision 0 | First informed revision |
|---|---:|---:|
| MAE | 83204.5 | 18451.5 |
| MAPE | 0.5145205755557507 | 0.12115179056812449 |
| Underprediction rate | 1.0 | 0.5 |
| Underprediction P95 ratio | 0.7858474528393946 | 0.07359880935095106 |
| Overprediction rate | 0.0 | 0.5 |
| Operation-count MAE | 17.0 | 100.5 |
| Planned-budget exceed rate | 1.0 | 1.0 |

## Operation catalog

| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |
|---|---:|---:|---:|---|---|---:|
| `embedding.product_query` | 21 | 31.0 | 35.0 | False | True | 19 |
| `reranker.product` | 21 | 1205.0 | 1257.0 | False | True | 19 |
| `main.plan` | 8 | 12751.0 | 22495.0 | False | True | 6 |
| `reranker.knowledge.need` | 3 | 3433.0 | 3469.0 | False | True | 2 |
| `search.plan` | 3 | 15168.0 | 30147.0 | False | True | 2 |
| `main.final` | 2 | 21747.0 | 25608.0 | True | True | 0 |
| `query_processor.decompose` | 1 | 1248.0 | 1248.0 | False | True | 0 |
| `query_processor.direct` | 1 | 1564.0 | 1564.0 | False | True | 0 |
| `search.final` | 1 | 40370.0 | 40370.0 | False | True | 0 |
