"""Audit Phase 2.5 execution graphs without calling any model API.

This consumes the content-free Phase 2.5 report.  It intentionally refuses to
claim a causal replay when observation timestamps and plan revision snapshots
are absent: using the final route at revision zero would leak future state.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.infrastructure.resource_governance.calibration import error_metrics, percentile


BOOTSTRAP_OPERATIONS = Counter({"main.plan": 1, "main.final": 1})


def _graph_diff(
    request: dict[str, Any], operations: list[dict[str, Any]],
) -> dict[str, Any]:
    actual = Counter(str(row.get("operation") or "unknown") for row in operations)
    missing = actual - BOOTSTRAP_OPERATIONS
    unexpected = BOOTSTRAP_OPERATIONS - actual
    observed_count = int(request.get("actual_operation_count") or sum(actual.values()))
    unclassified_count = max(0, observed_count - sum(actual.values()))
    if unclassified_count:
        missing["unclassified_observed_resource_operation"] += unclassified_count
    predicted = float(request["predicted_request_tokens"])
    actual_tokens = float(request["actual_request_tokens"])
    shortfall = max(0.0, actual_tokens - predicted)
    return {
        "trace_id": request.get("trace_id"),
        "case_id": request.get("case_id"),
        "query_type": request.get("query_type"),
        "initial_route": request.get("initial_route"),
        "route_after_query_processor": request.get("route_after_query_processor"),
        "final_execution_route": request.get("final_execution_route") or request.get("route"),
        "route_revision_count": request.get("route_revision_count"),
        "route_mismatch_reason": (
            "initial_route_is_bootstrap_placeholder"
            if request.get("initial_route") in (None, "unknown", "unknown_one_plan_plus_final")
            else "not_recorded_in_legacy_report"
        ),
        "predicted_operations": dict(BOOTSTRAP_OPERATIONS),
        "actual_named_operations": dict(actual),
        "predicted_operation_count": int(request.get("predicted_operation_count") or 2),
        "actual_operation_count": observed_count,
        "missing_operations": dict(missing),
        "unexpected_operations": dict(unexpected),
        "predicted_request_tokens": predicted,
        "actual_request_tokens": actual_tokens,
        "signed_error": predicted - actual_tokens,
        "absolute_error": abs(predicted - actual_tokens),
        "underprediction_ratio": shortfall / max(actual_tokens, 1.0),
        # Legacy report counted candidate_retrieval spans under this name; it
        # is a branch/call proxy, not a trustworthy information-need count.
        "candidate_retrieval_count_proxy": int(request.get("subquery_count") or 0),
        "final_context_tokens": int(request.get("final_context_tokens") or 0),
    }


def _tail_classification(row: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    named = row["actual_named_operations"]
    if row["final_execution_route"] == "product_search":
        reasons.append("product_or_mixed_flow_requires_trace_review")
    if named.get("main.plan", 0) > 2:
        reasons.append("repeated_main_reasoning")
    if row["final_context_tokens"] > 48_000:
        reasons.append("context_inflation")
    if row["missing_operations"].get("unclassified_observed_resource_operation", 0) > 3:
        reasons.append("many_non_model_resource_operations")
    if row["final_execution_route"] == "knowledge_decompose" or row["candidate_retrieval_count_proxy"] > 1:
        reasons.append("legitimate_multi_branch_workload")
    if row["underprediction_ratio"] > .50:
        reasons.append("predictor_missing_future_work")
    primary = (
        "E_context_inflation" if "context_inflation" in reasons
        else "B_predictor_underprediction_repeated_reasoning_needs_review"
        if "repeated_main_reasoning" in reasons
        else "B_predictor_underprediction" if "predictor_missing_future_work" in reasons
        else "A_reasonably_complex_or_needs_manual_review"
    )
    return {**row, "root_cause_tags": reasons, "primary_root_cause": primary}


def analyze(report: dict[str, Any]) -> dict[str, Any]:
    operations_by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report.get("operation_rows") or []:
        operations_by_trace[str(row.get("trace_id") or "")].append(row)
    diffs = [
        _graph_diff(row, operations_by_trace.get(str(row.get("trace_id") or ""), []))
        for row in report.get("request_rows") or []
    ]
    missing = Counter()
    for row in diffs:
        missing.update(row["missing_operations"])
    above_80k = [_tail_classification(row) for row in diffs if row["actual_request_tokens"] > 80_000]
    above_150k = [row for row in above_80k if row["actual_request_tokens"] > 150_000]
    product = [row for row in diffs if row["final_execution_route"] == "product_search"]
    old_metrics = error_metrics(
        diffs, predicted_key="predicted_request_tokens", actual_key="actual_request_tokens",
    )
    route_diagnostic = {
        "legacy_route_selection_error_rate": 1.0,
        "finding": "report_bug",
        "reason": "bootstrap placeholder was compared with final execution route",
        "comparable_initial_route_count": sum(
            row["initial_route"] not in (None, "unknown", "unknown_one_plan_plus_final")
            for row in diffs
        ),
        "corrected_error_rate": None,
    }
    replay_ready = all(
        row.get("plan_revision_history") and row.get("operation_timeline")
        for row in report.get("request_rows") or []
    ) if diffs else False
    return {
        "schema_version": "resource-governance-execution-graph-audit-v1",
        "source_trace_count": len(diffs),
        "shadow_only": True,
        "phase3_decision": "NO_GO",
        "route_selection_diagnostic": route_diagnostic,
        "old_predictor_metrics": old_metrics,
        "operation_count_error": {
            "mean_missing": (
                sum(max(0, row["actual_operation_count"] - row["predicted_operation_count"]) for row in diffs)
                / len(diffs) if diffs else None
            ),
            "p50_missing": percentile([
                max(0, row["actual_operation_count"] - row["predicted_operation_count"])
                for row in diffs
            ], .50),
            "p95_missing": percentile([
                max(0, row["actual_operation_count"] - row["predicted_operation_count"])
                for row in diffs
            ], .95),
        },
        "most_frequently_missing_operations": [
            {"operation": name, "count": count} for name, count in missing.most_common()
        ],
        "long_tail": {
            "above_80k_count": len(above_80k),
            "above_150k_count": len(above_150k),
            "above_80k": above_80k,
            "above_150k": above_150k,
        },
        "product_search_audit": {
            "count": len(product),
            "actual_tokens_p50": percentile([row["actual_request_tokens"] for row in product], .50),
            "actual_tokens_p95": percentile([row["actual_request_tokens"] for row in product], .95),
            "rows": product,
        },
        "replay": {
            "status": "READY" if replay_ready else "BLOCKED_MISSING_CAUSAL_EVENTS",
            "new_predictor_metrics": None,
            "required_fields": ["operation_timeline", "plan_revision_history"],
            "reason": (
                None if replay_ready else
                "The legacy aggregate report has no event timestamps or revision snapshots; "
                "using final route/subquery count at revision zero would leak future state."
            ),
        },
        "execution_graph_rows": diffs,
    }


def _markdown(audit: dict[str, Any]) -> str:
    old = audit["old_predictor_metrics"]
    missing = audit["most_frequently_missing_operations"][:10]
    lines = [
        "# Phase 2.5 Execution Graph Audit",
        "",
        "- Governor: `shadow-only`",
        "- Phase 3: `NO_GO`",
        f"- Traces: `{audit['source_trace_count']}`",
        f"- Route error finding: `{audit['route_selection_diagnostic']['finding']}`",
        f"- Replay: `{audit['replay']['status']}`",
        "",
        "## Old predictor",
        "",
        f"- MAE: `{old['mae']}`",
        f"- MAPE: `{old['mape']}`",
        f"- Underprediction rate: `{old['underprediction_rate']}`",
        f"- Underprediction P95 ratio: `{old['underprediction_ratio_p95']}`",
        "",
        "## Most frequently missing operations",
        "",
        "| Operation | Missing count |",
        "|---|---:|",
        *[f"| `{row['operation']}` | {row['count']} |" for row in missing],
        "",
        "## Long tail",
        "",
        f"- >80K: `{audit['long_tail']['above_80k_count']}`",
        f"- >150K: `{audit['long_tail']['above_150k_count']}`",
        f"- product_search traces: `{audit['product_search_audit']['count']}`",
        "",
        "## Replay constraint",
        "",
        audit["replay"]["reason"] or "Causal replay fields are available.",
        "",
        "The collector now records bounded FutureWorkPlan revision history for future causal replay. "
        "No final route is backfilled into revision zero.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    audit = analyze(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(_markdown(audit), encoding="utf-8")
    print(json.dumps({
        "trace_count": audit["source_trace_count"],
        "above_80k": audit["long_tail"]["above_80k_count"],
        "above_150k": audit["long_tail"]["above_150k_count"],
        "replay": audit["replay"]["status"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
