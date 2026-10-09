# Phase 2.5 Execution Graph Audit

- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Traces: `134`
- Route error finding: `report_bug`
- Replay: `BLOCKED_MISSING_CAUSAL_EVENTS`

## Old predictor

- MAE: `20744.783582089553`
- MAPE: `0.6378214763588578`
- Underprediction rate: `0.291044776119403`
- Underprediction P95 ratio: `0.8247767528838275`

## Most frequently missing operations

| Operation | Missing count |
|---|---:|
| `unclassified_observed_resource_operation` | 295 |
| `main.plan` | 132 |
| `query_processor.direct` | 80 |
| `query_processor.decompose` | 57 |
| `search.plan` | 21 |
| `query_processor.rewrite` | 6 |
| `search.final` | 6 |

## Long tail

- >80K: `8`
- >150K: `5`
- product_search traces: `5`

## Replay constraint

The legacy aggregate report has no event timestamps or revision snapshots; using final route/subquery count at revision zero would leak future state.

The collector now records bounded FutureWorkPlan revision history for future causal replay. No final route is backfilled into revision zero.
