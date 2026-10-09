# Token Budget × Context Governance Phase 2.5 最终报告

Governor mode: **shadow-only**

## 1. Golden Prompt/Token parity 结果

- Gate: **FAIL/BLOCKED**
- Official comparable cases: 0/14
- PRIMARY: `False`

## 2. DeepSeek V4.1 tokenizer vs fallback vs Provider actual

- Official tokenizer: `False`
- Fallback MAE: 577.1429
- Fallback MAPE: 1.0496
- Fallback P95 delta ratio: 7.6667

## 3. Tokenizer calibration sample/confidence

- Distribution: `{"medium": 202, "bootstrap": 93}`
- HIGH requires >=100 observations *and* an approved parity/residual gate.

## 4. Accounting reconciliation

- Errors: 0
- Reservation leaks: 0
- Duplicate attempts: 0
- Stale executions: 0

## 5. 67×2 总体结果

- Traces: 132
- Unique cases: 67
- Minimum repetitions: 1
| Metric | Value |
|---|---:|
| n | 132 |
| actual_p50 | 8560.0000 |
| actual_p80 | 21319.0000 |
| actual_p95 | 63970.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 30555.8939 |
| mape | 2.8775 |
| underprediction_rate | 0.1212 |
| underprediction_p50 | 13461.0000 |
| underprediction_p80 | 47234.0000 |
| underprediction_p95 | 248021.0000 |
| underprediction_max | 248021.0000 |
| overprediction_rate | 0.8788 |
| overprediction_p50 | 33139.0000 |
| overprediction_p95 | 33186.0000 |
| latency_p50 | n/a |
| latency_p95 | n/a |

## 6. Single Evidence

| Metric | Value |
|---|---:|
| n | 74 |
| actual_p50 | 8547.0000 |
| actual_p80 | 20308.0000 |
| actual_p95 | 48587.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 28077.1892 |
| mape | 2.8304 |
| underprediction_rate | 0.0811 |
| underprediction_p50 | 6890.0000 |
| underprediction_p80 | 19171.0000 |
| underprediction_p95 | 55613.0000 |
| underprediction_max | 55613.0000 |
| overprediction_rate | 0.9189 |
| overprediction_p50 | 33150.0000 |
| overprediction_p95 | 33186.0000 |
| latency_p50 | 1463.0330 |
| latency_p95 | 60627.9190 |

## 7. Cross Evidence

| Metric | Value |
|---|---:|
| n | 58 |
| actual_p50 | 8571.0000 |
| actual_p80 | 36146.0000 |
| actual_p95 | 88931.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 33718.3793 |
| mape | 2.9376 |
| underprediction_rate | 0.1724 |
| underprediction_p50 | 22273.0000 |
| underprediction_p80 | 47234.0000 |
| underprediction_p95 | 248021.0000 |
| underprediction_max | 248021.0000 |
| overprediction_rate | 0.8276 |
| overprediction_p50 | 33132.0000 |
| overprediction_p95 | 33165.0000 |
| latency_p50 | 1476.6280 |
| latency_p95 | 72821.4890 |

## 8. Multi-hop

| Metric | Value |
|---|---:|
| n | 48 |
| actual_p50 | 8568.0000 |
| actual_p80 | 39852.0000 |
| actual_p95 | 88931.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 35575.5208 |
| mape | 3.0736 |
| underprediction_rate | 0.1875 |
| underprediction_p50 | 29394.0000 |
| underprediction_p80 | 57980.0000 |
| underprediction_p95 | 248021.0000 |
| underprediction_max | 248021.0000 |
| overprediction_rate | 0.8125 |
| overprediction_p50 | 33135.0000 |
| overprediction_p95 | 33165.0000 |
| latency_p50 | 1476.6280 |
| latency_p95 | 72821.4890 |

## 9. DIRECT / REWRITE / DECOMPOSE

### DIRECT
| Metric | Value |
|---|---:|
| n | 76 |
| actual_p50 | 8554.0000 |
| actual_p80 | 21319.0000 |
| actual_p95 | 54407.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 27109.9079 |
| mape | 2.6468 |
| underprediction_rate | 0.0921 |
| underprediction_p50 | 12710.0000 |
| underprediction_p80 | 19171.0000 |
| underprediction_p95 | 55613.0000 |
| underprediction_max | 55613.0000 |
| overprediction_rate | 0.9079 |
| overprediction_p50 | 33148.0000 |
| overprediction_p95 | 33186.0000 |
| latency_p50 | 1490.7930 |
| latency_p95 | 61560.4960 |
### REWRITE
| Metric | Value |
|---|---:|
| n | n/a |
| actual_p50 | n/a |
| actual_p80 | n/a |
| actual_p95 | n/a |
| predicted_p50 | n/a |
| predicted_p80 | n/a |
| predicted_p95 | n/a |
| mae | n/a |
| mape | n/a |
| underprediction_rate | n/a |
| underprediction_p50 | n/a |
| underprediction_p80 | n/a |
| underprediction_p95 | n/a |
| underprediction_max | n/a |
| overprediction_rate | n/a |
| overprediction_p50 | n/a |
| overprediction_p95 | n/a |
| latency_p50 | n/a |
| latency_p95 | n/a |
### DECOMPOSE
| Metric | Value |
|---|---:|
| n | 42 |
| actual_p50 | 8571.0000 |
| actual_p80 | 44091.0000 |
| actual_p95 | 88931.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 35922.7857 |
| mape | 2.9591 |
| underprediction_rate | 0.2143 |
| underprediction_p50 | 29394.0000 |
| underprediction_p80 | 57980.0000 |
| underprediction_p95 | 248021.0000 |
| underprediction_max | 248021.0000 |
| overprediction_rate | 0.7857 |
| overprediction_p50 | 33132.0000 |
| overprediction_p95 | 33156.0000 |
| latency_p50 | 1473.3710 |
| latency_p95 | 72821.4890 |

## 10. Operation-level prediction error

```json
{
  "context_growth_observed": {
    "n": 132,
    "mean": 466.4015151515151,
    "p50": 0.0,
    "p95": 3585.0
  },
  "main_final_estimation_error": {
    "n": 132,
    "mean": 14055.166666666666,
    "p50": 16728.0,
    "p95": 16776.0
  },
  "main_plan_estimation_error": {
    "n": 132,
    "mean": 7119.075757575758,
    "p50": 0.0,
    "p95": 35859.0
  },
  "missing_operation_count": {
    "n": 132,
    "mean": 1.7954545454545454,
    "p50": 0.0,
    "p95": 10.0
  },
  "missing_or_extra_future_operation_proxy": {
    "n": 132,
    "mean": 1.106060606060606,
    "p50": -1.0,
    "p95": 10.0
  },
  "operation_count_error": {
    "n": 132,
    "mean": 1.106060606060606,
    "p50": -1.0,
    "p95": 10.0
  },
  "output_length_error": {
    "n": 132,
    "mean": 13940.674242424242,
    "p50": 8192.0,
    "p95": 36678.0
  },
  "retry_or_timeout_count": {
    "n": 132,
    "mean": 0.0,
    "p50": 0.0,
    "p95": 0.0
  },
  "route_selection_error": {
    "n": 132,
    "mean": 1.0,
    "p50": 1.0,
    "p95": 1.0
  },
  "single_call_tokenizer_error": {
    "n": 132,
    "mean": 10161.401515151516,
    "p50": 9495.0,
    "p95": 16660.0
  },
  "unexpected_operation_count": {
    "n": 132,
    "mean": 0.6893939393939394,
    "p50": 1.0,
    "p95": 1.0
  }
}
```

## 11. Main Plan error

| Metric | Value |
|---|---:|
| n | 101 |
| actual_p50 | 10190.0000 |
| actual_p80 | 15380.0000 |
| actual_p95 | 23656.0000 |
| predicted_p50 | 20123.0000 |
| predicted_p80 | 24496.0000 |
| predicted_p95 | 32197.0000 |
| mae | 9304.1386 |
| mape | 0.9037 |
| underprediction_rate | 0.0000 |
| underprediction_p50 | n/a |
| underprediction_p80 | n/a |
| underprediction_p95 | n/a |
| underprediction_max | n/a |
| overprediction_rate | 1.0000 |
| overprediction_p50 | 9295.0000 |
| overprediction_p95 | 9933.0000 |
| latency_p50 | n/a |
| latency_p95 | n/a |

## 12. Main Final error

| Metric | Value |
|---|---:|
| n | 131 |
| actual_p50 | 0.0000 |
| actual_p80 | 11976.0000 |
| actual_p95 | 19955.0000 |
| predicted_p50 | 16752.0000 |
| predicted_p80 | 20362.0000 |
| predicted_p95 | 27851.0000 |
| mae | 14162.4580 |
| mape | 11629.2253 |
| underprediction_rate | 0.0000 |
| underprediction_p50 | n/a |
| underprediction_p80 | n/a |
| underprediction_p95 | n/a |
| underprediction_max | n/a |
| overprediction_rate | 1.0000 |
| overprediction_p50 | 16728.0000 |
| overprediction_p95 | 16776.0000 |
| latency_p50 | n/a |
| latency_p95 | n/a |

## 13. Context growth error

```json
{
  "deepseek_v41_input": {
    "n": 295,
    "actual_p50": 631.0,
    "actual_p80": 11099.0,
    "actual_p95": 18123.0,
    "predicted_p50": 9507.0,
    "predicted_p80": 14651.0,
    "predicted_p95": 22064.0,
    "mae": 4546.796610169492,
    "mape": 2930.0425583470446,
    "absolute_error_p50": 3314.0,
    "absolute_error_p95": 9522.0,
    "underprediction_rate": 0.0,
    "underprediction_p50": null,
    "underprediction_p80": null,
    "underprediction_p95": null,
    "underprediction_max": null,
    "underprediction_ratio_p50": null,
    "underprediction_ratio_p80": null,
    "underprediction_ratio_p95": null,
    "overprediction_rate": 1.0,
    "overprediction_p50": 3314.0,
    "overprediction_p95": 9522.0
  }
}
```

## 14. Route / operation-count error

- route_selection_error: `{"n": 132, "mean": 1.0, "p50": 1.0, "p95": 1.0}`
- operation_count_error: `{"n": 132, "mean": 1.106060606060606, "p50": -1.0, "p95": 10.0}`
- missing_operation_count: `{"n": 132, "mean": 1.7954545454545454, "p50": 0.0, "p95": 10.0}`
- unexpected_operation_count: `{"n": 132, "mean": 0.6893939393939394, "p50": 1.0, "p95": 1.0}`

## 15. Underprediction rate

- 0.1212

## 16. P95 underprediction shortfall

- Overall tokens: 248021.0000
- Overall ratio: 0.8561
- Main Final ratio: n/a

## 17. Planned Budget exceed rate

- 0.0833

## 18. 80K hard-cap shadow exceed rate

- 0.0303

## 19. Retrieval Quality Regression

- Gate: **FAIL/NOT_RUN**
```json
{
  "runs": []
}
```

## 20. Profile confidence distribution

```json
{
  "medium": 202,
  "bootstrap": 93
}
```

## 21. 哪些 Profile 已可 action-driving

- 只有 parity/residual Gate 通过且标记 HIGH 的 profile；本轮 Phase 3 未开启。

## 22. 哪些必须继续 shadow

- BOOTSTRAP/LOW 全部；MEDIUM 仅可用于未来 optional/speculative reservation；Main Final 与 mandatory 始终保护。

## 23. DEEPSEEK_V41_TOKENIZER_PRIMARY 是否可以 0 → 1

- **NO**

## 24. Phase 3：GO / NO_GO

- **NO_GO**
```json
{
  "benchmark_trace_count_gte_134": false,
  "benchmark_unique_cases_gte_67": true,
  "benchmark_repetitions_gte_2": false,
  "golden_tokenizer_parity_passed": false,
  "retrieval_quality_regression_passed": false,
  "accounting_reconciliation_error_zero": true,
  "reservation_leak_zero": true,
  "duplicate_accounting_zero": true,
  "stale_plan_execution_zero": true,
  "overall_underprediction_rate_lt_10pct": false,
  "overall_underprediction_p95_ratio_lte_10pct": false,
  "main_final_underprediction_p95_ratio_lte_10pct": false,
  "planned_budget_exceed_rate_lte_10pct": true,
  "mandatory_erroneous_rejection_zero": true,
  "main_final_protection_failure_zero": true
}
```
- 即使未来 GO，第一阶段也只允许影响 optional/speculative，不控制 mandatory flow。
