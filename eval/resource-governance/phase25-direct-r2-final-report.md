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

- Distribution: `{"medium": 394, "bootstrap": 173}`
- HIGH requires >=100 observations *and* an approved parity/residual gate.

## 4. Accounting reconciliation

- Errors: 0
- Reservation leaks: 0
- Duplicate attempts: 0
- Stale executions: 0

## 5. 67×2 总体结果

- Traces: 134
- Unique cases: 67
- Minimum repetitions: 2
| Metric | Value |
|---|---:|
| n | 134 |
| actual_p50 | 33740.0000 |
| actual_p80 | 47069.0000 |
| actual_p95 | 91594.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 20744.7836 |
| mape | 0.6378 |
| underprediction_rate | 0.2910 |
| underprediction_p50 | 15486.0000 |
| underprediction_p80 | 45526.0000 |
| underprediction_p95 | 196268.0000 |
| underprediction_max | 207068.0000 |
| overprediction_rate | 0.7090 |
| overprediction_p50 | 17496.0000 |
| overprediction_p95 | 26366.0000 |
| latency_p50 | n/a |
| latency_p95 | n/a |

## 6. Single Evidence

| Metric | Value |
|---|---:|
| n | 74 |
| actual_p50 | 23763.0000 |
| actual_p80 | 39102.0000 |
| actual_p95 | 50859.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 15347.2162 |
| mape | 0.8000 |
| underprediction_rate | 0.1486 |
| underprediction_p50 | 5315.0000 |
| underprediction_p80 | 12605.0000 |
| underprediction_p95 | 35127.0000 |
| underprediction_max | 35127.0000 |
| overprediction_rate | 0.8514 |
| overprediction_p50 | 20221.0000 |
| overprediction_p95 | 26548.0000 |
| latency_p50 | 17205.6320 |
| latency_p95 | 28754.9210 |

## 7. Cross Evidence

| Metric | Value |
|---|---:|
| n | 60 |
| actual_p50 | 38094.0000 |
| actual_p80 | 61401.0000 |
| actual_p95 | 205228.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 27401.7833 |
| mape | 0.4378 |
| underprediction_rate | 0.4667 |
| underprediction_p50 | 16669.0000 |
| underprediction_p80 | 62502.0000 |
| underprediction_p95 | 196268.0000 |
| underprediction_max | 207068.0000 |
| overprediction_rate | 0.5333 |
| overprediction_p50 | 8747.0000 |
| overprediction_p95 | 22130.0000 |
| latency_p50 | 28050.8730 |
| latency_p95 | 73897.3740 |

## 8. Multi-hop

| Metric | Value |
|---|---:|
| n | 50 |
| actual_p50 | 44403.0000 |
| actual_p80 | 65707.0000 |
| actual_p95 | 210363.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 30294.3000 |
| mape | 0.4208 |
| underprediction_rate | 0.5400 |
| underprediction_p50 | 19644.0000 |
| underprediction_p80 | 62502.0000 |
| underprediction_p95 | 196268.0000 |
| underprediction_max | 207068.0000 |
| overprediction_rate | 0.4600 |
| overprediction_p50 | 11737.0000 |
| overprediction_p95 | 21174.0000 |
| latency_p50 | 29850.1440 |
| latency_p95 | 79529.6850 |

## 9. DIRECT / REWRITE / DECOMPOSE

### DIRECT
| Metric | Value |
|---|---:|
| n | 76 |
| actual_p50 | 27336.0000 |
| actual_p80 | 38163.0000 |
| actual_p95 | 58366.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 14977.5000 |
| mape | 0.6918 |
| underprediction_rate | 0.1579 |
| underprediction_p50 | 7029.0000 |
| underprediction_p80 | 19704.0000 |
| underprediction_p95 | 35127.0000 |
| underprediction_max | 35127.0000 |
| overprediction_rate | 0.8421 |
| overprediction_p50 | 20094.0000 |
| overprediction_p95 | 25021.0000 |
| latency_p50 | 18208.4960 |
| latency_p95 | 29742.4070 |
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
| n | 44 |
| actual_p50 | 44832.0000 |
| actual_p80 | 67075.0000 |
| actual_p95 | 210363.0000 |
| predicted_p50 | 41697.0000 |
| predicted_p80 | 41697.0000 |
| predicted_p95 | 41697.0000 |
| mae | 32607.8864 |
| mape | 0.4071 |
| underprediction_rate | 0.5682 |
| underprediction_p50 | 19644.0000 |
| underprediction_p80 | 62502.0000 |
| underprediction_p95 | 196268.0000 |
| underprediction_max | 207068.0000 |
| overprediction_rate | 0.4318 |
| overprediction_p50 | 11737.0000 |
| overprediction_p95 | 21174.0000 |
| latency_p50 | 30724.8760 |
| latency_p95 | 79529.6850 |

## 10. Operation-level prediction error

```json
{
  "context_growth_observed": {
    "n": 134,
    "mean": 3111.3880597014927,
    "p50": 3054.0,
    "p95": 6074.0
  },
  "main_final_estimation_error": {
    "n": 134,
    "mean": 7529.298507462687,
    "p50": 7620.0,
    "p95": 9112.0
  },
  "main_plan_estimation_error": {
    "n": 134,
    "mean": 17283.67910447761,
    "p50": 17603.0,
    "p95": 34995.0
  },
  "missing_operation_count": {
    "n": 134,
    "mean": 4.32089552238806,
    "p50": 3.0,
    "p95": 11.0
  },
  "missing_or_extra_future_operation_proxy": {
    "n": 134,
    "mean": 4.298507462686567,
    "p50": 3.0,
    "p95": 11.0
  },
  "operation_count_error": {
    "n": 134,
    "mean": 4.298507462686567,
    "p50": 3.0,
    "p95": 11.0
  },
  "output_length_error": {
    "n": 134,
    "mean": 23530.261194029852,
    "p50": 21928.0,
    "p95": 37901.0
  },
  "retry_or_timeout_count": {
    "n": 134,
    "mean": 0.0,
    "p50": 0.0,
    "p95": 0.0
  },
  "route_selection_error": {
    "n": 134,
    "mean": 1.0,
    "p50": 1.0,
    "p95": 1.0
  },
  "single_call_tokenizer_error": {
    "n": 134,
    "mean": 8097.888059701492,
    "p50": 7385.0,
    "p95": 14837.0
  },
  "unexpected_operation_count": {
    "n": 134,
    "mean": 0.022388059701492536,
    "p50": 0.0,
    "p95": 0.0
  }
}
```

## 11. Main Plan error

| Metric | Value |
|---|---:|
| n | 263 |
| actual_p50 | 8272.0000 |
| actual_p80 | 13530.0000 |
| actual_p95 | 19352.0000 |
| predicted_p50 | 16874.0000 |
| predicted_p80 | 22456.0000 |
| predicted_p95 | 27377.0000 |
| mae | 8806.1331 |
| mape | 0.9285 |
| underprediction_rate | 0.0000 |
| underprediction_p50 | n/a |
| underprediction_p80 | n/a |
| underprediction_p95 | n/a |
| underprediction_max | n/a |
| overprediction_rate | 1.0000 |
| overprediction_p50 | 8931.0000 |
| overprediction_p95 | 9415.0000 |
| latency_p50 | n/a |
| latency_p95 | n/a |

## 12. Main Final error

| Metric | Value |
|---|---:|
| n | 134 |
| actual_p50 | 14419.0000 |
| actual_p80 | 19669.0000 |
| actual_p95 | 23441.0000 |
| predicted_p50 | 22090.0000 |
| predicted_p80 | 25976.0000 |
| predicted_p95 | 29876.0000 |
| mae | 7529.2985 |
| mape | 0.5591 |
| underprediction_rate | 0.0000 |
| underprediction_p50 | n/a |
| underprediction_p80 | n/a |
| underprediction_p95 | n/a |
| underprediction_max | n/a |
| overprediction_rate | 1.0000 |
| overprediction_p50 | 7620.0000 |
| overprediction_p95 | 9112.0000 |
| latency_p50 | n/a |
| latency_p95 | n/a |

## 13. Context growth error

```json
{
  "deepseek_v41_input": {
    "n": 567,
    "actual_p50": 7113.0,
    "actual_p80": 14042.0,
    "actual_p95": 20163.0,
    "predicted_p50": 9551.0,
    "predicted_p80": 16431.0,
    "predicted_p95": 22554.0,
    "mae": 1918.3121693121693,
    "mape": 0.33279946908266705,
    "absolute_error_p50": 2417.0,
    "absolute_error_p95": 3079.0,
    "underprediction_rate": 0.003527336860670194,
    "underprediction_p50": 383.0,
    "underprediction_p80": 900.0,
    "underprediction_p95": 900.0,
    "underprediction_max": 900.0,
    "underprediction_ratio_p50": 0.015044386833215493,
    "underprediction_ratio_p80": 0.025278058645096056,
    "underprediction_ratio_p95": 0.025278058645096056,
    "overprediction_rate": 0.9964726631393298,
    "overprediction_p50": 2418.0,
    "overprediction_p95": 3079.0
  }
}
```

## 14. Route / operation-count error

- route_selection_error: `{"n": 134, "mean": 1.0, "p50": 1.0, "p95": 1.0}`
- operation_count_error: `{"n": 134, "mean": 4.298507462686567, "p50": 3.0, "p95": 11.0}`
- missing_operation_count: `{"n": 134, "mean": 4.32089552238806, "p50": 3.0, "p95": 11.0}`
- unexpected_operation_count: `{"n": 134, "mean": 0.022388059701492536, "p50": 0.0, "p95": 0.0}`

## 15. Underprediction rate

- 0.2910

## 16. P95 underprediction shortfall

- Overall tokens: 196268.0000
- Overall ratio: 0.8248
- Main Final ratio: n/a

## 17. Planned Budget exceed rate

- 0.1791

## 18. 80K hard-cap shadow exceed rate

- 0.0597

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
  "medium": 394,
  "bootstrap": 173
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
  "benchmark_trace_count_gte_134": true,
  "benchmark_unique_cases_gte_67": true,
  "benchmark_repetitions_gte_2": true,
  "golden_tokenizer_parity_passed": false,
  "retrieval_quality_regression_passed": false,
  "accounting_reconciliation_error_zero": true,
  "reservation_leak_zero": true,
  "duplicate_accounting_zero": true,
  "stale_plan_execution_zero": true,
  "overall_underprediction_rate_lt_10pct": false,
  "overall_underprediction_p95_ratio_lte_10pct": false,
  "main_final_underprediction_p95_ratio_lte_10pct": false,
  "planned_budget_exceed_rate_lte_10pct": false,
  "mandatory_erroneous_rejection_zero": true,
  "main_final_protection_failure_zero": true
}
```
- 即使未来 GO，第一阶段也只允许影响 optional/speculative，不控制 mandatory flow。
