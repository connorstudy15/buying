"""Strict timestamp-ordered replay of revisioned FutureWorkPlan traces."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.resource_governance.runtime_progress_report import summarize_runtime_progress

from app.infrastructure.resource_governance.calibration import bucket_metrics, error_metrics, percentile

MANDATORY_OPERATIONS = {"main.final", "search.final", "trade.final"}
HIGH_COST_THRESHOLD = 10_000
MEDIUM_COST_THRESHOLD = 1_000


def _event_cost(event: dict[str, Any]) -> int:
    return (
        int(event.get("chat_tokens") or 0)
        + int(event.get("embedding_tokens") or 0)
        + int(event.get("rerank_tokens") or 0)
    )


def _cost_bucket(cost: int) -> str:
    if cost >= HIGH_COST_THRESHOLD:
        return "HIGH_COST"
    if cost >= MEDIUM_COST_THRESHOLD:
        return "MEDIUM_COST"
    return "LOW_COST"


def _remaining_actual(timeline: list[dict[str, Any]], timestamp: str) -> list[dict[str, Any]]:
    # Completion after checkpoint includes calls already in flight. Legacy
    # exports lacking endTime remain start-time proxies, not exact replay.
    return [row for row in timeline
            if str(row.get("end_timestamp") or row.get("timestamp") or "") > timestamp]


def _counter_delta(actual: list[str], predicted: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    actual_counter = Counter(actual)
    predicted_counter = Counter(predicted)
    return dict(actual_counter - predicted_counter), dict(predicted_counter - actual_counter)


def _future_overlap(
    actual_events: list[dict[str, Any]],
    predicted_operations: list[str],
    cost_profile: dict[str, float],
) -> dict[str, Any]:
    """Score future graph coverage by operation count and observed token cost."""
    queues: dict[str, list[int]] = defaultdict(list)
    for event in actual_events:
        queues[str(event.get("operation") or "unknown")].append(_event_cost(event))
    matched_cost = 0
    matched_count = 0
    predicted_cost = 0.0
    unexpected_cost = 0.0
    for operation in predicted_operations:
        name = str(operation)
        queue = queues.get(name) or []
        if queue:
            cost = queue.pop(0)
            matched_cost += cost
            matched_count += 1
            predicted_cost += cost
        else:
            cost = float(cost_profile.get(name, 0.0))
            predicted_cost += cost
            unexpected_cost += cost
    actual_cost = sum(_event_cost(event) for event in actual_events)
    actual_count = len(actual_events)
    predicted_counter = Counter(predicted_operations)
    mandatory_cost = sum(
        _event_cost(event) for event in actual_events
        if str(event.get("operation")) in MANDATORY_OPERATIONS
    )
    mandatory_matched = 0
    mandatory_available = predicted_counter.copy()
    for event in actual_events:
        name = str(event.get("operation"))
        if name in MANDATORY_OPERATIONS and mandatory_available[name] > 0:
            mandatory_matched += _event_cost(event)
            mandatory_available[name] -= 1
    high_events = [event for event in actual_events if _cost_bucket(_event_cost(event)) == "HIGH_COST"]
    high_cost = sum(_event_cost(event) for event in high_events)
    high_available = predicted_counter.copy()
    high_matched = 0
    for event in sorted(high_events, key=_event_cost, reverse=True):
        name = str(event.get("operation"))
        if high_available[name] > 0:
            high_matched += _event_cost(event)
            high_available[name] -= 1
    def operation_recall(operation: str) -> float | None:
        actual_count = sum(1 for event in actual_events if str(event.get("operation")) == operation)
        if not actual_count:
            return None
        return min(actual_count, predicted_counter.get(operation, 0)) / actual_count
    return {
        "future_operation_precision": matched_count / len(predicted_operations) if predicted_operations else None,
        "future_operation_recall": matched_count / actual_count if actual_count else None,
        "cost_weighted_future_recall": matched_cost / actual_cost if actual_cost else None,
        "cost_weighted_future_precision": matched_cost / predicted_cost if predicted_cost else None,
        "mandatory_future_recall": mandatory_matched / mandatory_cost if mandatory_cost else None,
        "high_cost_future_recall": high_matched / high_cost if high_cost else None,
        "predicted_remaining_cost": predicted_cost,
        "actual_remaining_cost": actual_cost,
        "missing_remaining_cost": max(0, actual_cost - matched_cost),
        "unexpected_predicted_cost": unexpected_cost,
        "high_cost_actual": high_cost,
        "high_cost_matched": high_matched,
        "main_final_recall": operation_recall("main.final"),
        "search_final_recall": operation_recall("search.final"),
        "actual_operation_cost_buckets": dict(Counter(_cost_bucket(_event_cost(event)) for event in actual_events)),
    }


def _checkpoint(history: list[dict[str, Any]]) -> dict[str, Any]:
    for trigger in ("query_processor_result", "tool_calls_emitted"):
        found = next((row for row in history if row.get("trigger") == trigger), None)
        if found is not None:
            return found
    return history[0]


def _prediction_row(
    request: dict[str, Any], revision: dict[str, Any], timeline: list[dict[str, Any]], *, label: str,
    cost_profile: dict[str, float] | None = None,
) -> dict[str, Any]:
    timestamp = str(revision.get("timestamp") or "")
    remaining = _remaining_actual(timeline, timestamp)
    predicted_operations = [str(value) for value in revision.get("operations") or []]
    actual_operations = [str(row.get("operation") or "unknown") for row in remaining]
    missing, unexpected = _counter_delta(actual_operations, predicted_operations)
    used = float(revision.get("used_chat_tokens") or 0)
    predicted_total = float(revision.get("projected_chat_tokens") or 0)
    actual_total = float(request.get("actual_request_tokens") or 0)
    known_count = int(revision.get("known_operation_count") or 0)
    predicted_count = known_count + len(predicted_operations)
    actual_count = int(request.get("actual_operation_count") or len(timeline))
    overlap = _future_overlap(remaining, predicted_operations, cost_profile or {})
    actual_main_plan_rounds = sum(1 for value in actual_operations if value == "main.plan")
    actual_search_plan_rounds = sum(1 for value in actual_operations if value == "search.plan")
    predicted_main_plan_rounds = sum(1 for value in predicted_operations if value == "main.plan")
    predicted_search_plan_rounds = sum(1 for value in predicted_operations if value == "search.plan")
    return {
        "trace_id": request.get("trace_id"),
        "case_id": request.get("case_id"),
        "route": request.get("route"),
        "query_type": request.get("query_type"),
        "benchmark_buckets": request.get("benchmark_buckets") or [],
        "latency_ms": request.get("latency_ms"),
        "checkpoint": label,
        "revision_sequence": int(revision.get("sequence") or 0),
        "trigger": revision.get("trigger"),
        "visible_route": revision.get("route"),
        "visible_query_mode": revision.get("query_mode"),
        "visible_information_need_count": revision.get("information_need_count"),
        "predicted_request_tokens": predicted_total,
        "actual_request_tokens": actual_total,
        "predicted_remaining_chat_tokens": max(0.0, predicted_total - used),
        # Ledger settlements at the checkpoint define consumed usage. Include
        # in-flight calls rather than silently dropping them by start timestamp.
        "actual_remaining_chat_tokens": max(0.0, actual_total - used),
        "plan_trace_integrity": request.get("plan_trace_integrity"),
        "predicted_operation_count": predicted_count,
        "actual_operation_count": actual_count,
        "predicted_operations": predicted_operations,
        "predicted_remaining_main_plan_rounds": predicted_main_plan_rounds,
        "actual_remaining_main_plan_rounds": actual_main_plan_rounds,
        "main_plan_remaining_count_error": predicted_main_plan_rounds - actual_main_plan_rounds,
        "predicted_remaining_search_plan_rounds": predicted_search_plan_rounds,
        "actual_remaining_search_plan_rounds": actual_search_plan_rounds,
        "search_plan_remaining_count_error": predicted_search_plan_rounds - actual_search_plan_rounds,
        "operation_count_error": predicted_count - actual_count,
        "remaining_operation_count_error": len(predicted_operations) - len(actual_operations),
        "missing_operations": missing,
        "unexpected_operations": unexpected,
        "planned_budget": float(revision.get("planned_budget_chat_tokens") or 0),
        "planned_budget_scope": revision.get("planned_budget_scope", "LEGACY_SCOPE_UNVERIFIED"),
        "planned_total_chat_budget": revision.get("planned_total_chat_budget"),
        "planned_remaining_chat_budget": revision.get("planned_remaining_chat_budget"),
        "planned_budget_exceeded": (
            actual_total > float(revision["planned_total_chat_budget"])
            if revision.get("planned_total_chat_budget") is not None else None
        ),
        "budget_recomputed": bool(revision.get("budget_recomputed")),
        "budget_unchanged_reason": revision.get("budget_unchanged_reason"),
        "main_plan_prediction_reasons": revision.get("main_plan_prediction_reasons") or [],
        **overlap,
    }


def _operation_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    routes: dict[str, Counter[str]] = defaultdict(Counter)
    traces: dict[str, Counter[str]] = defaultdict(Counter)
    for request in rows:
        trace_id = str(request.get("trace_id") or "")
        route = str(request.get("route") or "unknown")
        for event in request.get("operation_timeline") or []:
            operation = str(event.get("operation") or "unknown")
            grouped[operation].append(event)
            routes[operation][route] += 1
            traces[trace_id][operation] += 1
    duplicates = Counter()
    for counts in traces.values():
        for operation, count in counts.items():
            if count > 1:
                duplicates[operation] += count - 1
    catalog = []
    mandatory = {"main.final", "trade.final"}
    predictable = {
        "main.plan", "main.final", "query_processor.direct", "query_processor.rewrite",
        "query_processor.decompose", "search.plan", "search.final",
        "reranker.knowledge.need", "embedding.product_query", "reranker.product",
    }
    for operation, events in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        tokens = [
            int(event.get("chat_tokens") or 0) + int(event.get("embedding_tokens") or 0)
            + int(event.get("rerank_tokens") or 0) for event in events
        ]
        catalog.append({
            "operation_type": operation,
            "count": len(events),
            "token_p50": percentile(tokens, .50),
            "token_p95": percentile(tokens, .95),
            "route_distribution": dict(routes[operation]),
            "mandatory": operation in mandatory,
            "cancellable": operation not in mandatory,
            "predictable": operation in predictable,
            "repeated_execution_count": duplicates[operation],
        })
    return catalog


def _cost_profile(rows: list[dict[str, Any]]) -> dict[str, float]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for request in rows:
        for event in request.get("operation_timeline") or []:
            grouped[str(event.get("operation") or "unknown")].append(_event_cost(event))
    return {operation: float(percentile(values, .50) or 0) for operation, values in grouped.items()}


def _transition_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    targets: dict[str, Counter[str]] = {"main.plan": Counter(), "search.plan": Counter()}
    repeated: Counter[str] = Counter()
    for request in rows:
        events = sorted(
            request.get("operation_timeline") or [],
            key=lambda item: str(item.get("timestamp") or ""),
        )
        previous = "request_start"
        seen: Counter[str] = Counter()
        for event in events:
            operation = str(event.get("operation") or "unknown")
            if operation in targets:
                targets[operation][previous] += 1
            if seen[operation] > 0 and operation in {
                "main.plan", "search.plan", "query_processor.direct",
                "query_processor.decompose", "embedding.product_query", "reranker.product",
            }:
                repeated[operation] += 1
            seen[operation] += 1
            previous = operation
    return {
        "target_transition_counts": {target: dict(counts) for target, counts in targets.items()},
        "potential_repeated_execution_counts": dict(repeated),
    }


def _product_repeat_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counter()
    by_case: dict[str, dict[str, int]] = {}
    for request in rows:
        searches = [
            event for event in request.get("product_search_events") or []
            if event.get("operation") == "search"
        ]
        categories: Counter[str] = Counter()
        results = {
            int(event.get("search_iteration") or 0): event
            for event in request.get("product_search_events") or []
            if event.get("operation") == "result"
        }
        seen_exact: set[tuple[str, str, str]] = set()
        seen_need: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for event in searches:
            query_hash = str(event.get("query_hash") or "")
            constraint = str(event.get("constraints_signature") or "")
            need = str(event.get("information_need_id") or "overall")
            iteration = int(event.get("search_iteration") or 0)
            exact = (need, query_hash, constraint)
            prior_need = seen_need.get(need) or []
            if not seen_exact:
                categories["initial_search"] += 1
            elif exact in seen_exact and query_hash and constraint:
                categories["exact_duplicate"] += 1
            elif prior_need and prior_need[-1][2] == 0:
                categories["same_need_evidence_insufficient"] += 1
            elif prior_need and query_hash and any(query_hash != old[0] for old in prior_need):
                categories["same_need_refinement"] += 1
            elif prior_need and constraint and any(constraint != old[1] for old in prior_need):
                categories["same_need_duplicate_candidate"] += 1
            elif need not in seen_need and (query_hash or constraint):
                categories["different_need"] += 1
            else:
                categories["unknown_repeat"] += 1
            seen_exact.add(exact)
            result_count = int((results.get(iteration) or {}).get("actual_result_count") or 0)
            seen_need[need].append((query_hash, constraint, result_count))
        item = dict(categories)
        by_case[str(request.get("case_id") or request.get("trace_id"))] = item
        totals.update(item)
    return {"totals": dict(totals), "by_case": by_case}


def _budget_revision_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changed = 0
    recomputed = 0
    stale = 0
    unchanged_reasons: Counter[str] = Counter()
    for _, case_rows in _groups(rows, "case_id").items():
        ordered = sorted(case_rows, key=lambda row: row["revision_sequence"])
        for before, after in zip(ordered, ordered[1:]):
            before_signature = (
                tuple(before.get("predicted_operations") or []),
                before.get("visible_route"),
                before.get("visible_information_need_count"),
            )
            after_signature = (
                tuple(after.get("predicted_operations") or []),
                after.get("visible_route"),
                after.get("visible_information_need_count"),
            )
            plan_changed = before_signature != after_signature
            if plan_changed:
                changed += 1
                if after.get("budget_recomputed"):
                    recomputed += 1
                else:
                    stale += 1
                if after.get("planned_budget") == before.get("planned_budget"):
                    unchanged_reasons[str(after.get("budget_unchanged_reason") or "UNEXPLAINED")] += 1
    return {
        "plan_changed_revision_count": changed,
        "budget_recomputed_revision_count": recomputed,
        "budget_recomputation_rate": recomputed / changed if changed else None,
        "stale_not_recomputed_count": stale,
        "unchanged_budget_reason_distribution": dict(unchanged_reasons),
    }


def _lifecycle_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    events = [event for row in rows for event in row.get("future_operation_transitions") or []]
    states = Counter(str(event.get("new_state") or "unknown") for event in events)
    reasons = Counter(str(event.get("transition_reason") or "unknown") for event in events)
    obsolete_removed = sum(
        states[state] for state in ("completed", "cancelled", "superseded")
    )
    qp_replaced = sum(
        event.get("operation") == "query_processor.classify"
        and event.get("new_state") == "superseded"
        for event in events
    )
    return {
        "transition_count": len(events),
        "new_state_distribution": dict(states),
        "transition_reason_distribution": dict(reasons),
        "obsolete_node_removal_count": obsolete_removed,
        "query_processor_placeholder_replace_count": qp_replaced,
    }


def _prediction_reason_precision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    matched: Counter[str] = Counter()
    for request in rows:
        timeline = request.get("operation_timeline") or []
        for event in request.get("future_operation_transitions") or []:
            if event.get("previous_state") is not None or event.get("new_state") != "planned":
                continue
            reason = str(event.get("transition_reason") or "unknown")
            operation = str(event.get("operation") or "unknown")
            timestamp = str(event.get("timestamp") or "")
            totals[reason] += 1
            if any(
                str(actual.get("timestamp") or "") > timestamp
                and str(actual.get("operation") or "") == operation
                for actual in timeline
            ):
                matched[reason] += 1
    return {
        reason: {
            "predicted": count,
            "matched_later": matched[reason],
            "precision": matched[reason] / count if count else None,
        }
        for reason, count in totals.items()
    }


def analyze(report: dict[str, Any]) -> dict[str, Any]:
    requests = report.get("request_rows") or []
    eligible = [
        row for row in requests
        if row.get("plan_revision_history") and row.get("operation_timeline")
        and row.get("plan_trace_integrity") == "VALID"
        and all(
            revision.get("timestamp") and revision.get("plan_trace_integrity") == "VALID"
            for revision in row["plan_revision_history"]
        )
    ]
    profile = _cost_profile(eligible)
    old_rows: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    revision_rows: list[dict[str, Any]] = []
    for request in eligible:
        history = sorted(
            request["plan_revision_history"],
            key=lambda row: (str(row.get("timestamp") or ""), int(row.get("sequence") or 0)),
        )
        timeline = sorted(
            request["operation_timeline"], key=lambda row: str(row.get("timestamp") or ""),
        )
        old_rows.append(_prediction_row(request, history[0], timeline, label="revision_0", cost_profile=profile))
        checkpoint = _checkpoint(history)
        new_rows.append(_prediction_row(request, checkpoint, timeline, label="first_informed_revision", cost_profile=profile))
        for revision in history:
            revision_rows.append(_prediction_row(
                request, revision, timeline, label=f"revision_{revision.get('sequence')}", cost_profile=profile,
            ))

    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        metrics = error_metrics(
            rows, predicted_key="predicted_request_tokens", actual_key="actual_request_tokens",
        )
        op_errors = [abs(int(row["operation_count_error"])) for row in rows]
        metrics.update({
            "operation_count_mae": sum(op_errors) / len(op_errors) if op_errors else None,
            "operation_count_error_p95": percentile(op_errors, .95),
            "main_plan_remaining_count_mae": (
                sum(abs(int(row["main_plan_remaining_count_error"])) for row in rows) / len(rows)
                if rows else None
            ),
            "search_plan_remaining_count_mae": (
                sum(abs(int(row["search_plan_remaining_count_error"])) for row in rows) / len(rows)
                if rows else None
            ),
            "planned_budget_exceed_rate": (
                sum(row["planned_budget_exceeded"] is True for row in rows)
                / sum(row.get("planned_budget_exceeded") is not None for row in rows)
                if any(row.get("planned_budget_exceeded") is not None for row in rows) else None
            ),
        })
        for key in (
            "future_operation_precision", "future_operation_recall",
            "cost_weighted_future_recall", "cost_weighted_future_precision",
            "mandatory_future_recall", "high_cost_future_recall",
            "main_final_recall", "search_final_recall",
            "predicted_remaining_cost", "actual_remaining_cost",
            "missing_remaining_cost", "unexpected_predicted_cost",
        ):
            values = [float(row[key]) for row in rows if row.get(key) is not None]
            metrics[f"{key}_mean"] = sum(values) / len(values) if values else None
            metrics[f"{key}_p95"] = percentile(values, .95) if values else None
        return metrics

    convergence: dict[str, Any] = {}
    for case_id, rows in _groups(revision_rows, "case_id").items():
        ordered = sorted(rows, key=lambda row: row["revision_sequence"])
        convergence[case_id] = [{
            "revision": row["revision_sequence"],
            "trigger": row["trigger"],
            "visible_route": row["visible_route"],
            "visible_information_need_count": row["visible_information_need_count"],
            "remaining_operation_abs_error": abs(row["remaining_operation_count_error"]),
            "remaining_chat_token_abs_error": abs(
                row["predicted_remaining_chat_tokens"] - row["actual_remaining_chat_tokens"]
            ),
            "planned_budget_before": ordered[index - 1]["planned_budget"] if index else None,
            "planned_budget_after": row["planned_budget"],
            "predicted_remaining_cost": row["predicted_remaining_cost"],
            "actual_remaining_cost": row["actual_remaining_cost"],
            "missing_remaining_cost": row["missing_remaining_cost"],
            "unexpected_predicted_cost": row["unexpected_predicted_cost"],
            "cost_weighted_future_recall": row["cost_weighted_future_recall"],
            "cost_weighted_future_precision": row["cost_weighted_future_precision"],
            "high_cost_future_recall": row["high_cost_future_recall"],
            "missing_operations": row["missing_operations"],
            "unexpected_operations": row["unexpected_operations"],
        } for index, row in enumerate(ordered)]

    return {
        "schema_version": "resource-governance-causal-replay-v1",
        "shadow_only": True,
        "phase3_decision": "NO_GO",
        "source_trace_count": len(requests),
        "eligible_trace_count": len(eligible),
        "excluded_trace_count": len(requests) - len(eligible),
        "causal_ordering": "observation_timestamp_then_revision_sequence",
        "future_information_used": False,
        "old_predictor": summary(old_rows),
        "new_predictor_first_informed_revision": summary(new_rows),
        "route_buckets_old": bucket_metrics(old_rows, "route"),
        "route_buckets_new": bucket_metrics(new_rows, "route"),
        "benchmark_buckets_old": bucket_metrics(old_rows, "benchmark_buckets"),
        "benchmark_buckets_new": bucket_metrics(new_rows, "benchmark_buckets"),
        "operation_catalog": _operation_catalog(eligible),
        "operation_cost_profile": profile,
        "transition_statistics": _transition_statistics(eligible),
        "product_search_repeat_diagnostics": _product_repeat_diagnostics(eligible),
        "planned_budget_revision_response": _budget_revision_response(revision_rows),
        "future_operation_lifecycle": _lifecycle_statistics(eligible),
        "runtime_progress_diagnostics": summarize_runtime_progress(eligible),
        "prediction_reason_precision": _prediction_reason_precision(eligible),
        "revision_convergence": convergence,
        "old_rows": old_rows,
        "new_rows": new_rows,
    }


def _groups(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row.get(key) or "unknown")].append(row)
    return result


def _markdown(audit: dict[str, Any]) -> str:
    old = audit["old_predictor"]
    new = audit["new_predictor_first_informed_revision"]
    lines = [
        "# Resource Governance causal-smoke replay",
        "",
        f"- Eligible traces: `{audit['eligible_trace_count']}/{audit['source_trace_count']}`",
        "- Governor: `shadow-only`",
        "- Phase 3: `NO_GO`",
        "- Future information used: `false`",
        "",
        "## Old vs first informed revision",
        "",
        "| Metric | Revision 0 | First informed revision |",
        "|---|---:|---:|",
        f"| MAE | {old['mae']} | {new['mae']} |",
        f"| MAPE | {old['mape']} | {new['mape']} |",
        f"| Underprediction rate | {old['underprediction_rate']} | {new['underprediction_rate']} |",
        f"| Underprediction P95 ratio | {old['underprediction_ratio_p95']} | {new['underprediction_ratio_p95']} |",
        f"| Overprediction rate | {old['overprediction_rate']} | {new['overprediction_rate']} |",
        f"| Operation-count MAE | {old['operation_count_mae']} | {new['operation_count_mae']} |",
        f"| Planned-budget exceed rate | {old['planned_budget_exceed_rate']} | {new['planned_budget_exceed_rate']} |",
        f"| Future-operation precision | {old['future_operation_precision_mean']} | {new['future_operation_precision_mean']} |",
        f"| Future-operation recall | {old['future_operation_recall_mean']} | {new['future_operation_recall_mean']} |",
        f"| Cost-weighted future recall | {old['cost_weighted_future_recall_mean']} | {new['cost_weighted_future_recall_mean']} |",
        f"| Cost-weighted future precision | {old['cost_weighted_future_precision_mean']} | {new['cost_weighted_future_precision_mean']} |",
        f"| Mandatory future recall | {old['mandatory_future_recall_mean']} | {new['mandatory_future_recall_mean']} |",
        f"| High-cost future recall | {old['high_cost_future_recall_mean']} | {new['high_cost_future_recall_mean']} |",
        f"| Main Final recall | {old['main_final_recall_mean']} | {new['main_final_recall_mean']} |",
        f"| Search Final recall | {old['search_final_recall_mean']} | {new['search_final_recall_mean']} |",
        f"| Missing remaining cost (mean) | {old['missing_remaining_cost_mean']} | {new['missing_remaining_cost_mean']} |",
        f"| Unexpected predicted cost (mean) | {old['unexpected_predicted_cost_mean']} | {new['unexpected_predicted_cost_mean']} |",
        "",
        "## Planning transitions",
        "",
        "```json",
        json.dumps(audit["transition_statistics"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Operation catalog",
        "",
        "| Operation | Count | Token P50 | Token P95 | Mandatory | Predictable | Repeated |",
        "|---|---:|---:|---:|---|---|---:|",
        *[
            f"| `{row['operation_type']}` | {row['count']} | {row['token_p50']} | {row['token_p95']} | "
            f"{row['mandatory']} | {row['predictable']} | {row['repeated_execution_count']} |"
            for row in audit["operation_catalog"]
        ],
        "",
        "## Lifecycle and budget diagnostics",
        "",
        "```json",
        json.dumps({
            "future_operation_lifecycle": audit["future_operation_lifecycle"],
            "planned_budget_revision_response": audit["planned_budget_revision_response"],
            "prediction_reason_precision": audit["prediction_reason_precision"],
            "product_retrieval_totals": audit["product_search_repeat_diagnostics"]["totals"],
        }, ensure_ascii=False, indent=2),
        "```",
        "",
        "Revision 0 vs first informed revision compares two causal checkpoints in the same execution; it is not a controlled comparison of two software versions.",
        "Prediction-reason precision currently matches later operation names and is diagnostic only; concurrent logical-call identity requires a separate gate.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    audit = analyze(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(_markdown(audit), encoding="utf-8")
    print(json.dumps({
        "eligible": audit["eligible_trace_count"],
        "old_underprediction": audit["old_predictor"]["underprediction_rate"],
        "new_underprediction": audit["new_predictor_first_informed_revision"]["underprediction_rate"],
        "phase3": audit["phase3_decision"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
