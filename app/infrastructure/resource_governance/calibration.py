"""Pure statistics for Phase 2.5 calibration reports.

These functions intentionally contain no policy decisions and no network or
business-content access. They consume normalized numeric observations only.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Iterable


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * q) - 1))]


def error_metrics(
    rows: Iterable[dict[str, Any]], *, predicted_key: str, actual_key: str,
) -> dict[str, Any]:
    pairs = [
        (float(row[predicted_key]), float(row[actual_key]))
        for row in rows
        if row.get(predicted_key) is not None and row.get(actual_key) is not None
    ]
    signed = [predicted - actual for predicted, actual in pairs]
    absolute = [abs(value) for value in signed]
    percentage = [abs(error) / max(actual, 1.0) for error, (_, actual) in zip(signed, pairs)]
    under = [actual - predicted for predicted, actual in pairs if predicted < actual]
    under_ratio = [
        (actual - predicted) / max(actual, 1.0)
        for predicted, actual in pairs if predicted < actual
    ]
    over = [predicted - actual for predicted, actual in pairs if predicted > actual]
    actuals = [actual for _, actual in pairs]
    predicted = [value for value, _ in pairs]
    return {
        "n": len(pairs),
        "actual_p50": percentile(actuals, .50),
        "actual_p80": percentile(actuals, .80),
        "actual_p95": percentile(actuals, .95),
        "predicted_p50": percentile(predicted, .50),
        "predicted_p80": percentile(predicted, .80),
        "predicted_p95": percentile(predicted, .95),
        "mae": statistics.fmean(absolute) if absolute else None,
        "mape": statistics.fmean(percentage) if percentage else None,
        "absolute_error_p50": percentile(absolute, .50),
        "absolute_error_p95": percentile(absolute, .95),
        "underprediction_count": len(under),
        "underprediction_rate": len(under) / len(pairs) if pairs else None,
        # No underpredicted sample is a measured zero-risk tail, not missing
        # data.  Keep None only when there are no comparable samples at all.
        "underprediction_p50": percentile(under, .50) if under else 0.0 if pairs else None,
        "underprediction_p80": percentile(under, .80) if under else 0.0 if pairs else None,
        "underprediction_p95": percentile(under, .95) if under else 0.0 if pairs else None,
        "underprediction_max": max(under) if under else 0.0 if pairs else None,
        "underprediction_ratio_p50": percentile(under_ratio, .50) if under else 0.0 if pairs else None,
        "underprediction_ratio_p80": percentile(under_ratio, .80) if under else 0.0 if pairs else None,
        "underprediction_ratio_p95": percentile(under_ratio, .95) if under else 0.0 if pairs else None,
        "overprediction_count": len(over),
        "overprediction_rate": len(over) / len(pairs) if pairs else None,
        "overprediction_p50": percentile(over, .50),
        "overprediction_p95": percentile(over, .95),
    }


def estimator_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "legacy": error_metrics(
            rows, predicted_key="old_estimated_prompt_tokens",
            actual_key="actual_prompt_tokens",
        ),
        "deepseek_v41": error_metrics(
            rows, predicted_key="deepseek_estimated_prompt_tokens",
            actual_key="actual_prompt_tokens",
        ),
        "actual_over_local_ratio": {
            name: {
                "p50": percentile(values, .50),
                "p80": percentile(values, .80),
                "p95": percentile(values, .95),
                "p99": percentile(values, .99),
            }
            for name, values in {
                "legacy": [
                    row["actual_prompt_tokens"] / row["old_estimated_prompt_tokens"]
                    for row in rows if row.get("old_estimated_prompt_tokens", 0) > 0
                    and row.get("actual_prompt_tokens") is not None
                ],
                "deepseek_v41": [
                    row["actual_prompt_tokens"] / row["deepseek_estimated_prompt_tokens"]
                    for row in rows if row.get("deepseek_estimated_prompt_tokens", 0) > 0
                    and row.get("actual_prompt_tokens") is not None
                ],
            }.items()
        },
    }


def bucket_metrics(
    rows: list[dict[str, Any]], key: str, *,
    predicted_key: str = "predicted_request_tokens",
    actual_key: str = "actual_request_tokens",
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is not None:
                groups[str(item)].append(row)
    result = {}
    for bucket, items in sorted(groups.items()):
        metrics = error_metrics(items, predicted_key=predicted_key, actual_key=actual_key)
        latencies = [float(item["latency_ms"]) for item in items if item.get("latency_ms") is not None]
        metrics.update(
            latency_p50=percentile(latencies, .50),
            latency_p95=percentile(latencies, .95),
        )
        result[bucket] = metrics
    return result


def phase3_gate(report: dict[str, Any]) -> dict[str, Any]:
    accounting = report.get("accounting", {})
    request = report.get("request_prediction", {})
    conditions = {
        "benchmark_trace_count_gte_134": int(report.get("trace_count") or 0) >= 134,
        "benchmark_unique_cases_gte_67": int(report.get("unique_case_count") or 0) >= 67,
        "benchmark_repetitions_gte_2": int(report.get("minimum_case_repetitions") or 0) >= 2,
        "golden_tokenizer_parity_passed": report.get("golden_tokenizer_parity_passed") is True,
        "retrieval_quality_regression_passed": report.get("retrieval_quality_regression_passed") is True,
        "accounting_reconciliation_error_zero": accounting.get("error_count") == 0,
        "reservation_leak_zero": accounting.get("reservation_leak_count") == 0,
        "duplicate_accounting_zero": accounting.get("duplicate_attempt_count") == 0,
        "stale_plan_execution_zero": accounting.get("stale_plan_execution_count") == 0,
        "overall_underprediction_rate_lt_10pct": (
            request.get("underprediction_rate") is not None
            and request["underprediction_rate"] < .10
        ),
        "overall_underprediction_p95_ratio_lte_10pct": (
            request.get("underprediction_ratio_p95") is not None
            and request["underprediction_ratio_p95"] <= .10
        ),
        "main_final_underprediction_p95_ratio_lte_10pct": (
            int((report.get("main_final_prediction") or {}).get("n") or 0) > 0
            and (report.get("main_final_prediction") or {}).get("underprediction_ratio_p95") is not None
            and report["main_final_prediction"]["underprediction_ratio_p95"] <= .10
        ),
        "planned_budget_exceed_rate_lte_10pct": (
            report.get("planned_budget_exceed_rate") is not None
            and report["planned_budget_exceed_rate"] <= .10
        ),
        "mandatory_erroneous_rejection_zero": report.get("mandatory_erroneous_rejection_count") == 0,
        "main_final_protection_failure_zero": report.get("main_final_protection_failure_count") == 0,
    }
    return {
        "decision": "GO" if all(conditions.values()) else "NO_GO",
        "conditions": conditions,
        "allowed_first_action_if_go": "optional_or_speculative_only",
        "mandatory_operations_remain_protected": True,
    }
