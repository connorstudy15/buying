# Resource Governance causal-smoke replay

- Eligible traces: `0/2`
- Governor: `shadow-only`
- Phase 3: `NO_GO`
- Future information used: `false`

## Old vs first informed revision

| Metric | Revision 0 | First informed revision |
|---|---:|---:|
| MAE | None | None |
| MAPE | None | None |
| Underprediction rate | None | None |
| Underprediction P95 ratio | None | None |
| Overprediction rate | None | None |
| Operation-count MAE | None | None |
| Planned-budget exceed rate | None | None |
| Future-operation precision | None | None |
| Future-operation recall | None | None |
| Cost-weighted future recall | None | None |
| Cost-weighted future precision | None | None |
| Mandatory future recall | None | None |
| High-cost future recall | None | None |
| Missing remaining cost (mean) | None | None |
| Unexpected predicted cost (mean) | None | None |

## Planning transitions

```json
{
  "target_transition_counts": {
    "main.plan": {},
    "search.plan": {}
  },
  "potential_repeated_execution_counts": {}
}
```

## Operation catalog

| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |
|---|---:|---:|---:|---|---|---:|
