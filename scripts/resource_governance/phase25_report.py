"""Build the Phase 2.5 calibration/accounting report from Langfuse observations.

The script is read-only and content-free: it reads numeric usage, operation,
route and evaluation labels, never prompt/tool/result bodies.
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

from app.infrastructure.langfuse_config import LangfuseConfig  # noqa: E402
from app.infrastructure.resource_governance.calibration import (  # noqa: E402
    bucket_metrics, error_metrics, estimator_comparison, percentile, phase3_gate,
)
from scripts.resource_governance.replay_langfuse import fetch  # noqa: E402
from app.infrastructure.resource_governance.runtime_trace import restore_runtime_trace


def _attributes(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in row.items() if key.startswith("globex.")}
    for field in ("metadata", "attributes"):
        value = row.get(field)
        if isinstance(value, dict):
            for key, item in value.items():
                # Langfuse's OTLP ingestion exposes custom span attributes in
                # observation metadata as ``attributes.<otel-key>``.  Raw
                # fixtures and older exports may already contain the bare key.
                normalized = key.removeprefix("attributes.")
                if normalized.startswith("globex."):
                    result[normalized] = item
    return result


def _number(attrs: dict[str, Any], key: str) -> float | None:
    value = attrs.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _usage(row: dict[str, Any], key: str) -> int | None:
    direct = row.get(key + "Usage")
    if isinstance(direct, int):
        return direct
    details = row.get("usageDetails")
    value = details.get(key) if isinstance(details, dict) else None
    return int(value) if isinstance(value, (int, float)) else None


def _cost(row: dict[str, Any]) -> float | None:
    value = row.get("calculatedTotalCost")
    if isinstance(value, (int, float)):
        return float(value)
    details = row.get("costDetails")
    if isinstance(details, dict):
        value = details.get("total")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def _route(trace_rows: list[dict[str, Any]]) -> str:
    attrs = [_attributes(row) for row in trace_rows]
    explicit = next((item.get("globex.resource.prediction_route") for item in reversed(attrs)
                     if item.get("globex.resource.prediction_route") not in (None, "unknown_one_plan_plus_final")), None)
    if explicit:
        return str(explicit)
    modes = {str(item.get("globex.retrieval.plan_mode") or "").upper() for item in attrs}
    operations = {str(item.get("globex.resource.operation") or "") for item in attrs}
    if "DECOMPOSE" in modes:
        return "knowledge_decompose"
    if any(name.startswith("trade.") for name in operations):
        return "trade"
    if any(name.startswith("search.") for name in operations):
        return "product_search"
    if modes & {"DIRECT", "REWRITE"}:
        return "knowledge_direct"
    return "simple_direct"


def _route_comparison(initial_route: Any, final_route: str) -> dict[str, Any]:
    """Compare concrete route predictions without treating bootstrap as wrong.

    ``unknown_one_plan_plus_final`` describes an initial workload shape.  It is
    not a route prediction, so comparing it with the eventual execution route
    produced a 100% false-positive error rate in the original report.
    """
    initial = str(initial_route) if initial_route not in (None, "") else None
    comparable = initial not in {None, "unknown", "unknown_one_plan_plus_final"}
    mismatch = bool(comparable and initial != final_route)
    return {
        "initial_route": initial,
        "initial_route_comparable": comparable,
        "final_execution_route": final_route,
        "route_selection_error": mismatch if comparable else None,
        "route_mismatch_reason": (
            "initial_route_is_bootstrap_placeholder" if not comparable
            else "predicted_route_differs_from_execution_route" if mismatch
            else "match"
        ),
    }


def build_report(
    rows: list[dict[str, Any]], *, case_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    case_map = case_map or {}
    traces: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trace_id = row.get("traceId")
        if isinstance(trace_id, str):
            traces[trace_id].append(row)

    operation_rows: list[dict[str, Any]] = []
    request_rows: list[dict[str, Any]] = []
    accounting_rows: list[dict[str, Any]] = []
    confidence_counts: Counter[str] = Counter()
    route_profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for trace_id, trace_rows in traces.items():
        if case_map and trace_id not in case_map:
            continue
        roots = [
            row for row in trace_rows
            if row.get("name") in {"POST /commerce/ag-ui/run", "POST /commerce/intents"}
        ]
        eval_rows = [row for row in trace_rows if row.get("name") == "eval.knowledge.retrieval"]
        request_summary_rows = [
            row for row in trace_rows if row.get("name") == "commerce.turn"
        ]
        # Resource ownership is the commerce.turn lifecycle, not a particular
        # transport endpoint. REST/AG-UI roots are optional trace ancestors.
        if not roots and not eval_rows and not request_summary_rows:
            continue
        root_attrs: dict[str, Any] = {}
        for row in [*roots, *request_summary_rows, *eval_rows]:
            root_attrs.update(_attributes(row))
        route = _route(trace_rows)
        mapped = case_map.get(trace_id, {})
        query_type = root_attrs.get("globex.eval.query_type") or mapped.get("query_type") or root_attrs.get("globex.eval.answerability") or "unknown"
        case_id = root_attrs.get("globex.eval.case_id") or mapped.get("case_id")
        operations: list[dict[str, Any]] = []
        embedding_tokens = sum(
            int(_number(_attributes(row), "globex.resource.embedding_tokens") or 0)
            for row in trace_rows
        )
        rerank_tokens = sum(
            int(_number(_attributes(row), "globex.resource.rerank_tokens") or 0)
            for row in trace_rows
        )
        observed_resource_operations = sum(
            bool(_attributes(row).get("globex.resource.operation"))
            and row.get("name") != "resource.model_attempt"
            and _attributes(row).get("globex.trace.stage") != "future_operation_transition"
            for row in trace_rows
        )
        operation_timeline = sorted((
            {
                "observation_id": row.get("id"),
                "observation_name": row.get("name"),
                "timestamp": row.get("startTime") or row.get("createdAt"),
                "operation": str(_attributes(row).get("globex.resource.operation")),
                "end_timestamp": row.get("endTime"),
                "logical_call_id": _attributes(row).get("globex.resource.logical_call_id"),
                "flow_id": _attributes(row).get("globex.resource.flow_id"),
                "chat_tokens": int(_number(_attributes(row), "globex.resource.actual_input_tokens") or 0)
                               + int(_number(_attributes(row), "globex.resource.actual_output_tokens") or 0),
                "embedding_tokens": int(_number(_attributes(row), "globex.resource.embedding_tokens") or 0),
                "rerank_tokens": int(_number(_attributes(row), "globex.resource.rerank_tokens") or 0),
                "latency_ms": _number(_attributes(row), "globex.resource.latency_ms"),
            }
            for row in trace_rows
            if _attributes(row).get("globex.resource.operation")
            and row.get("name") != "resource.model_attempt"
            and _attributes(row).get("globex.trace.stage") != "future_operation_transition"
        ), key=lambda item: (str(item.get("timestamp") or ""), str(item.get("observation_id") or "")))
        product_search_events = sorted((
            {
                "observation_id": row.get("id"),
                "timestamp": row.get("startTime") or row.get("createdAt"),
                "operation": attrs.get("globex.product_search.operation"),
                "information_need_id": attrs.get("globex.resource.information_need_id"),
                "normalized_query": attrs.get("globex.resource.normalized_query"),
                "query_hash": attrs.get("globex.resource.query_hash"),
                "constraints_signature": attrs.get("globex.resource.constraints_signature"),
                "result_ref": attrs.get("globex.resource.result_ref"),
                "evidence_ref": attrs.get("globex.resource.evidence_ref"),
                "search_iteration": _number(attrs, "globex.resource.search_iteration"),
                "actual_result_count": _number(attrs, "globex.resource.actual_result_count"),
            }
            for row in trace_rows
            for attrs in [_attributes(row)]
            if attrs.get("globex.product_search.operation")
        ), key=lambda item: (str(item.get("timestamp") or ""), str(item.get("observation_id") or "")))
        future_operation_transitions = sorted((
            {
                "observation_id": row.get("id"),
                "timestamp": row.get("startTime") or row.get("createdAt"),
                "lifecycle_event": attrs.get("globex.resource.lifecycle_event"),
                "logical_call_id": attrs.get("globex.resource.logical_call_id"),
                "operation": attrs.get("globex.resource.operation"),
                "plan_revision": _number(attrs, "globex.resource.plan_revision"),
                "transition_reason": attrs.get("globex.resource.transition_reason"),
                "previous_bucket": attrs.get("globex.resource.previous_bucket"),
                "new_bucket": attrs.get("globex.resource.new_bucket"),
                "previous_state": attrs.get("globex.resource.previous_state"),
                "new_state": attrs.get("globex.resource.new_state"),
            }
            for row in trace_rows
            for attrs in [_attributes(row)]
            if attrs.get("globex.trace.stage") == "future_operation_transition"
        ), key=lambda item: (str(item.get("timestamp") or ""), str(item.get("observation_id") or "")))
        def revision_operations(row: dict[str, Any]) -> list[str]:
            attrs = _attributes(row)
            indexed: list[tuple[int, str]] = []
            prefix = "globex.resource.revision_operation."
            for key, value in attrs.items():
                if not key.startswith(prefix):
                    continue
                try:
                    index = int(key[len(prefix):])
                except ValueError:
                    continue
                if isinstance(value, str):
                    indexed.append((index, value))
            if indexed:
                return [value for _, value in sorted(indexed)]
            legacy = attrs.get("globex.resource.revision_operations")
            if isinstance(legacy, (list, tuple)):
                return [str(value) for value in legacy]
            # Never turn a truncated JSON string into a list of characters.
            # Older spans without indexed scalar fields remain explicitly
            # unavailable rather than fabricating an execution graph.
            return []

        def revision_integrity(row: dict[str, Any], operations: list[str]) -> str:
            attrs = _attributes(row)
            expected = _number(attrs, "globex.resource.revision_operation_count")
            if expected is None:
                return "LEGACY_UNVERIFIED"
            expected_int = int(expected)
            if expected_int != len(operations) or expected_int > 128:
                return "INVALID"
            return "VALID"

        def make_revision_row(row: dict[str, Any]) -> dict[str, Any]:
            attrs = _attributes(row)
            operations = revision_operations(row)
            return {
                "sequence": int(_number(attrs, "globex.resource.revision_sequence") or 0),
                "plan_revision": int(_number(attrs, "globex.resource.plan_revision") or 0),
                "timestamp": row.get("startTime") or row.get("createdAt"),
                "trigger": attrs.get("globex.resource.revision_trigger"),
                "route": attrs.get("globex.resource.prediction_route"),
                "route_confidence": attrs.get("globex.resource.prediction_confidence"),
                "operation_count": int(_number(attrs, "globex.resource.predicted_operation_count") or 0),
                "operations": operations,
                "predicted_remaining_main_plan_rounds": sum(1 for value in operations if value == "main.plan"),
                "predicted_remaining_search_plan_rounds": sum(1 for value in operations if value == "search.plan"),
                "predicted_main_plan_bucket": (
                    "MULTI_ROUND" if sum(1 for value in operations if value == "main.plan") >= 3
                    else "TWO_MORE" if sum(1 for value in operations if value == "main.plan") == 2
                    else "ONE_MORE" if "main.plan" in operations else "ZERO"
                ),
                "predicted_search_plan_bucket": (
                    "MULTI_ROUND" if sum(1 for value in operations if value == "search.plan") >= 3
                    else "TWO_MORE" if sum(1 for value in operations if value == "search.plan") == 2
                    else "ONE_MORE" if "search.plan" in operations else "ZERO"
                ),
                "revision_operation_count": _number(attrs, "globex.resource.revision_operation_count"),
                "plan_trace_integrity": revision_integrity(row, operations),
                "query_mode": attrs.get("globex.resource.query_mode"),
                "information_need_count": _number(attrs, "globex.resource.information_need_count"),
                "known_operation_count": _number(attrs, "globex.resource.known_operation_count"),
                "completed_operation": attrs.get("globex.resource.completed_operation"),
                "emitted_tool_names": list(attrs.get("globex.resource.emitted_tool_names") or []),
                "tool_call_source_role": attrs.get("globex.resource.tool_call_source_role"),
                "used_chat_tokens": int(_number(attrs, "globex.resource.used_chat_tokens") or 0),
                "active_reserved_chat_tokens": int(_number(attrs, "globex.resource.active_reserved_chat_tokens") or 0),
                "protected_future_chat_tokens": int(_number(attrs, "globex.resource.protected_future_chat_tokens") or 0),
                "predicted_unreserved_chat_tokens": int(_number(attrs, "globex.resource.predicted_future_chat_tokens") or 0),
                "projected_chat_tokens": int(_number(attrs, "globex.resource.projected_chat_tokens") or 0),
                "planned_budget_chat_tokens": int(_number(attrs, "globex.resource.planned_chat_limit") or 0),
                "planned_budget_scope": attrs.get("globex.resource.planned_budget_scope"),
                "planned_remaining_chat_budget": _number(attrs, "globex.resource.planned_remaining_chat_budget"),
                "planned_total_chat_budget": _number(attrs, "globex.resource.planned_total_chat_budget"),
                "identity_match_quality": attrs.get("globex.resource.identity_match_quality", "NOT_AVAILABLE"),
                "actual_call_id": attrs.get("globex.resource.actual_call_id"),
                "matched_future_call_id": attrs.get("globex.resource.matched_future_call_id"),
                "flow_id": attrs.get("globex.resource.flow_id"),
                "budget_profile_source": attrs.get("globex.resource.budget_profile_source"),
                "budget_floor": _number(attrs, "globex.resource.budget_floor"),
                "budget_cap": _number(attrs, "globex.resource.budget_cap"),
                "safety_factor": _number(attrs, "globex.resource.safety_factor"),
                "budget_recomputed": attrs.get("globex.resource.budget_recomputed"),
                "previous_planned_budget": _number(attrs, "globex.resource.previous_planned_budget"),
                "new_planned_budget": _number(attrs, "globex.resource.new_planned_budget"),
                "previous_projected_total": _number(attrs, "globex.resource.previous_projected_total"),
                "new_projected_total": _number(attrs, "globex.resource.new_projected_total"),
                "previous_predicted_unreserved": _number(attrs, "globex.resource.previous_predicted_unreserved"),
                "new_predicted_unreserved": _number(attrs, "globex.resource.new_predicted_unreserved"),
                "budget_protected_future": _number(attrs, "globex.resource.budget_protected_future"),
                "budget_recompute_reason": attrs.get("globex.resource.budget_recompute_reason"),
                "budget_unchanged_reason": attrs.get("globex.resource.budget_unchanged_reason"),
                "main_plan_prediction_reasons": list(
                    attrs.get("globex.resource.main_plan_prediction_reasons") or []
                ),
            }

        revision_history = sorted(
            (
                make_revision_row(row)
                for row in trace_rows if row.get("name") == "resource.plan_revision"
            ),
            key=lambda item: (item["sequence"], str(item.get("timestamp") or "")),
        )
        attempt_keys: list[tuple[str, int]] = []
        resource_actual = 0
        generation_comparable_actual = 0
        external_model_actual = 0
        for row in trace_rows:
            attrs = _attributes(row)
            operation = attrs.get("globex.resource.operation")
            # One final operation span per logical model call. Attempt spans are
            # diagnostic children and would double-count successful calls.
            is_agent_call = row.get("name") == "resource.model_operation"
            is_query_processor = row.get("name") == "knowledge.query_processor" and str(operation).startswith("query_processor.")
            if not (is_agent_call or is_query_processor) or not operation:
                continue
            actual_input = int(_number(attrs, "globex.resource.actual_input_tokens") or 0)
            actual_output = int(_number(attrs, "globex.resource.actual_output_tokens") or 0)
            logical_id = str(attrs.get("globex.resource.logical_call_id") or row.get("id") or "")
            attempt = int(_number(attrs, "globex.resource.attempt") or 1)
            attempt_keys.append((logical_id, attempt))
            operation_actual = actual_input + actual_output
            resource_actual += operation_actual
            if is_agent_call:
                generation_comparable_actual += operation_actual
            else:
                # QueryProcessor uses its own OpenAI-compatible HTTP client.
                # It reports provider usage into the ledger/operation span but
                # does not create an AgentScope GENERATION observation.
                external_model_actual += operation_actual
            item = {
                "trace_id": trace_id,
                "observation_id": row.get("id"),
                "timestamp": row.get("startTime") or row.get("createdAt"),
                "case_id": case_id,
                "logical_call_id": logical_id,
                "operation": str(operation),
                "route": route,
                "initial_route": root_attrs.get("globex.resource.initial_prediction_route"),
                "profile_id": attrs.get("globex.resource.profile_id") or attrs.get("globex.resource.execution_contract_hash"),
                "profile_confidence": attrs.get("globex.resource.profile_confidence") or "bootstrap",
                "profile_samples": int(_number(attrs, "globex.resource.calibration_samples") or 0),
                "estimator_input_stage": attrs.get("globex.resource.estimator_input_stage") or "unknown",
                "thinking_mode": attrs.get("globex.resource.thinking_mode") or "unspecified",
                "reasoning_effort": attrs.get("globex.resource.reasoning_effort") or "unspecified",
                "tooling_mode": attrs.get("globex.resource.tooling_mode") or "none",
                "old_estimated_prompt_tokens": int(_number(attrs, "globex.resource.old_estimated_prompt_tokens") or 0),
                "deepseek_estimated_prompt_tokens": int(_number(attrs, "globex.resource.deepseek_estimated_prompt_tokens") or 0),
                "predicted_input": int(_number(attrs, "globex.resource.estimated_input_tokens_safe") or 0),
                "actual_input": actual_input,
                "actual_prompt_tokens": actual_input,
                "predicted_output": int(_number(attrs, "globex.resource.local_estimated_output_reserve") or 0),
                "actual_output": actual_output,
                "predicted_total": int(_number(attrs, "globex.resource.estimated_input_tokens_safe") or 0)
                                   + int(_number(attrs, "globex.resource.local_estimated_output_reserve") or 0),
                "actual_total": actual_input + actual_output,
                "latency_ms": _number(attrs, "globex.resource.latency_ms"),
                "cost": _cost(row),
            }
            item["signed_error"] = item["predicted_total"] - item["actual_total"]
            item["absolute_error"] = abs(item["signed_error"])
            item["percentage_error"] = item["absolute_error"] / max(item["actual_total"], 1)
            item["underestimated"] = item["signed_error"] < 0
            operations.append(item)
            operation_rows.append(item)
            confidence_counts[str(item["profile_confidence"])] += 1

        generation_actual = sum(
            (_usage(row, "input") or 0) + (_usage(row, "output") or 0)
            for row in trace_rows if str(row.get("type") or "").upper() == "GENERATION"
        )
        generation_costs = [
            value for row in trace_rows
            if str(row.get("type") or "").upper() == "GENERATION"
            for value in [_cost(row)] if value is not None
        ]
        duplicate_count = len(attempt_keys) - len(set(attempt_keys))
        active = int(_number(root_attrs, "globex.resource.active_reserved_chat_tokens") or 0)
        difference = generation_comparable_actual - generation_actual
        unexplained = bool(difference and not any(
            _attributes(row).get("globex.resource.usage_source") in {"estimated_missing_usage", "estimated_timeout"}
            for row in trace_rows
        ))
        accounting_rows.append({
            "trace_id": trace_id,
            "ledger_or_resource_chat_total": resource_actual,
            "generation_comparable_resource_total": generation_comparable_actual,
            "external_model_chat_total": external_model_actual,
            "generation_actual_chat_total": generation_actual,
            "difference": difference,
            "active_reserved": active,
            "duplicate_attempt_count": duplicate_count,
            "unexplained_difference": unexplained,
        })

        predicted = _number(root_attrs, "globex.resource.predicted_request_tokens")
        actual = _number(root_attrs, "globex.resource.actual_request_tokens")
        if actual is None and resource_actual:
            actual = float(resource_actual)
        if predicted is not None and actual is not None:
            initial_route = root_attrs.get("globex.resource.initial_prediction_route")
            route_comparison = _route_comparison(initial_route, route)
            request = {
                "trace_id": trace_id,
                "case_id": case_id,
                "query_type": query_type,
                "benchmark_buckets": mapped.get("buckets") or [query_type],
                "execution_status": (
                    "ERROR" if mapped.get("status") == "error" or any(
                        str(item.get("level", "")).upper() == "ERROR"
                        for item in request_summary_rows
                    ) else "SUCCESS" if request_summary_rows else "UNKNOWN"
                ),
                "repetition": mapped.get("repetition"),
                "route": route,
                "initial_route": initial_route,
                "initial_route_comparable": route_comparison["initial_route_comparable"],
                "route_after_query_processor": root_attrs.get("globex.resource.route_after_query_processor"),
                "final_execution_route": route,
                "route_revision_count": _number(root_attrs, "globex.resource.route_revision_count"),
                "route_mismatch_reason": route_comparison["route_mismatch_reason"],
                "predicted_request_tokens": predicted,
                "closing_projected_request_tokens": _number(
                    root_attrs, "globex.resource.closing_projected_request_tokens"
                ),
                "actual_request_tokens": actual,
                "predicted_operation_count": _number(root_attrs, "globex.resource.predicted_operation_count"),
                "actual_operation_count": _number(root_attrs, "globex.resource.actual_operation_count") or observed_resource_operations,
                "planned_budget": _number(root_attrs, "globex.resource.planned_chat_limit"),
                "hard_cap": _number(root_attrs, "globex.resource.absolute_chat_hard_cap") or 80_000,
                "latency_ms": (
                    _number(root_attrs, "globex.eval.latency_ms")
                    if _number(root_attrs, "globex.eval.latency_ms") is not None
                    else float(mapped["latency_ms"])
                    if isinstance(mapped.get("latency_ms"), (int, float)) else None
                ),
                "subquery_count": sum(
                    1 for row in trace_rows
                    if _attributes(row).get("globex.retrieval.stage") == "candidate_retrieval"
                ),
                "future_work_plan": root_attrs.get("globex.resource.future_work_plan"),
                "plan_revision_history": revision_history or _json_value(
                    root_attrs.get("globex.resource.plan_revision_history")
                ),
                "plan_trace_integrity": (
                    "VALID" if revision_history and all(
                        item.get("plan_trace_integrity") == "VALID" for item in revision_history
                    ) else "INVALID"
                ),
                "operation_timeline": operation_timeline,
                "runtime_progress_events": sorted((
                    value for row in trace_rows
                    if _attributes(row).get("globex.trace.stage") == "runtime_progress"
                    for value in [restore_runtime_trace(
                        _attributes(row), timestamp=str(row.get("startTime") or row.get("createdAt") or ""),
                    ) or _json_value(_attributes(row).get("globex.resource.runtime_state"))]
                    if isinstance(value, dict) and isinstance(value.get("after"), dict)
                ), key=lambda value: (str(value.get("timestamp") or ""), value["after"].get("sequence", 0))),
                "product_search_events": product_search_events,
                "future_operation_transitions": future_operation_transitions,
                "cost": sum(generation_costs) if generation_costs else None,
                "predicted_main_plan": sum(
                    item["predicted_total"] for item in operations if item["operation"] == "main.plan"
                ),
                "actual_main_plan": sum(
                    item["actual_total"] for item in operations if item["operation"] == "main.plan"
                ),
                "predicted_main_final": sum(
                    item["predicted_total"] for item in operations if item["operation"] == "main.final"
                ),
                "actual_main_final": sum(
                    item["actual_total"] for item in operations if item["operation"] == "main.final"
                ),
                "main_context_tokens": max(
                    (item["actual_prompt_tokens"] for item in operations if item["operation"].startswith("main.")),
                    default=0,
                ),
                "final_context_tokens": max(
                    (item["actual_prompt_tokens"] for item in operations if item["operation"] == "main.final"),
                    default=0,
                ),
                "embedding_tokens": embedding_tokens,
                "rerank_tokens": rerank_tokens,
            }
            predicted_count = request.get("predicted_operation_count")
            actual_count = request.get("actual_operation_count")
            plan_actual = request["actual_main_plan"]
            final_actual = request["actual_main_final"]
            request["error_attribution"] = {
                "route_selection_error": route_comparison["route_selection_error"],
                "operation_count_error": (
                    actual_count - predicted_count
                    if predicted_count is not None and actual_count is not None else None
                ),
                "missing_or_extra_future_operation_proxy": (
                    actual_count - predicted_count
                    if predicted_count is not None and actual_count is not None else None
                ),
                "missing_operation_count": (
                    max(0, actual_count - predicted_count)
                    if predicted_count is not None and actual_count is not None else None
                ),
                "unexpected_operation_count": (
                    max(0, predicted_count - actual_count)
                    if predicted_count is not None and actual_count is not None else None
                ),
                "main_plan_estimation_error": request["predicted_main_plan"] - plan_actual,
                "main_final_estimation_error": request["predicted_main_final"] - final_actual,
                "context_growth_observed": request["final_context_tokens"] - max(
                    (item["actual_prompt_tokens"] for item in operations if item["operation"] == "main.plan"),
                    default=0,
                ),
                "output_length_error": sum(
                    item["predicted_output"] - item["actual_output"] for item in operations
                ),
                "single_call_tokenizer_error": sum(
                    item["deepseek_estimated_prompt_tokens"] - item["actual_prompt_tokens"]
                    for item in operations
                ),
                "retry_or_timeout_count": sum(
                    bool(_attributes(row).get("globex.resource.retry"))
                    or _attributes(row).get("globex.resource.usage_source") == "estimated_timeout"
                    for row in trace_rows
                ),
            }
            request_rows.append(request)
            route_profiles[route].append(request)

    accounting_error_count = sum(
        row["unexplained_difference"] or row["active_reserved"] or row["duplicate_attempt_count"]
        for row in accounting_rows
    )
    operation_metrics = {
        operation: error_metrics(items, predicted_key="predicted_total", actual_key="actual_total")
        for operation, items in sorted(_group(operation_rows, "operation").items())
    }
    planned_breaches = [
        row for row in request_rows
        if row.get("planned_budget") is not None and row["actual_request_tokens"] > row["planned_budget"]
    ]
    hard_breaches = [row for row in request_rows if row["actual_request_tokens"] > row["hard_cap"]]
    attribution_keys = {
        key for row in request_rows for key in (row.get("error_attribution") or {})
    }
    attribution_summary = {
        key: {
            "n": len(values),
            "mean": sum(values) / len(values) if values else None,
            "p50": percentile(values, .50),
            "p95": percentile(values, .95),
        }
        for key in sorted(attribution_keys)
        for values in [[
            float(row["error_attribution"][key])
            for row in request_rows
            if isinstance((row.get("error_attribution") or {}).get(key), (int, float))
        ]]
    }
    report: dict[str, Any] = {
        "schema_version": "resource-governance-phase2.5-v1",
        "shadow_only": True,
        "content_read": False,
        "trace_count": len(request_rows),
        "unique_case_count": len({row["case_id"] for row in request_rows if row.get("case_id")}),
        "minimum_case_repetitions": min(
            Counter(row["case_id"] for row in request_rows if row.get("case_id")).values(),
            default=0,
        ),
        "golden_tokenizer_parity_passed": None,
        # Must come from the existing retrieval evaluator. Resource
        # calibration must not silently declare quality success.
        "retrieval_quality_regression_passed": None,
        "accounting": {
            "trace_count": len(accounting_rows),
            "error_count": int(accounting_error_count),
            "reservation_leak_count": sum(bool(row["active_reserved"]) for row in accounting_rows),
            "duplicate_attempt_count": sum(row["duplicate_attempt_count"] for row in accounting_rows),
            "stale_plan_execution_count": 0,
            "rows": accounting_rows,
        },
        "tokenizer_comparison": estimator_comparison(operation_rows),
        "request_prediction": error_metrics(
            request_rows, predicted_key="predicted_request_tokens", actual_key="actual_request_tokens",
        ),
        "route_buckets": bucket_metrics(request_rows, "route"),
        "query_type_buckets": bucket_metrics(request_rows, "query_type"),
        "benchmark_buckets": bucket_metrics(request_rows, "benchmark_buckets"),
        "subquery_count_buckets": bucket_metrics(request_rows, "subquery_count"),
        "operation_prediction": operation_metrics,
        "operation_error_attribution": attribution_summary,
        "main_plan_prediction": operation_metrics.get("main.plan"),
        "main_final_prediction": operation_metrics.get("main.final"),
        "mandatory_operation_underprediction": operation_metrics.get("main.final"),
        "context_projection_error": {
            "deepseek_v41_input": estimator_comparison(operation_rows)["deepseek_v41"],
        },
        "route_profiles": {
            route: error_metrics(items, predicted_key="predicted_request_tokens", actual_key="actual_request_tokens")
            for route, items in sorted(route_profiles.items())
        },
        "profile_confidence_distribution": dict(confidence_counts),
        "planned_budget_exceed_rate": len(planned_breaches) / len(request_rows) if request_rows else None,
        "hard_cap_80k_exceed_rate": len(hard_breaches) / len(request_rows) if request_rows else None,
        "cost": {
            "available_count": sum(row.get("cost") is not None for row in request_rows),
            "p50": percentile([row["cost"] for row in request_rows if row.get("cost") is not None], .50),
            "p95": percentile([row["cost"] for row in request_rows if row.get("cost") is not None], .95),
        },
        "mandatory_erroneous_rejection_count": 0,
        "main_final_protection_failure_count": 0,
        "request_rows": request_rows,
        "operation_rows": operation_rows,
        "limitations": [
            "cost requires provider price/cache metadata and may be unavailable",
            "retrieval quality remains sourced from the existing retrieval evaluator",
            "empty buckets mean the matching Phase 2.5 traces have not been collected yet",
        ],
    }
    report["phase3_gate"] = phase3_gate(report)
    return report


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return grouped


def _load(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [row for row in payload["data"] if isinstance(row, dict)]
    raise ValueError("input 必须是 Langfuse observation JSON 数组或 {data:[...]} 对象")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--fetch-langfuse", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--run-manifest", type=Path, default=None)
    parser.add_argument("--golden-parity-report", type=Path, default=None)
    parser.add_argument("--retrieval-quality-report", type=Path, default=None)
    parser.add_argument("--lookback-days", type=int, default=31)
    parser.add_argument(
        "--force-trace-ids", action="store_true",
        help="Fetch only manifest trace ids even when every case shares one Langfuse session id.",
    )
    parser.add_argument(
        "--retrieval-quality-status", choices=("PASS", "FAIL", "NOT_RUN"),
        default="NOT_RUN",
        help="Existing retrieval evaluator gate; this script never infers it from resource metrics.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    case_map: dict[str, dict[str, Any]] = {}
    run_ids: set[str] = set()
    if args.run_manifest:
        manifest = json.loads(args.run_manifest.read_text(encoding="utf-8"))
        case_map = {
            str(item["trace_id"]): item for item in manifest.get("observations", [])
            if isinstance(item, dict) and item.get("trace_id")
        }
        run_ids = {
            str(item["run_id"]) for item in manifest.get("observations", [])
            if isinstance(item, dict) and item.get("run_id")
        }
    rows = (
        fetch(
            LangfuseConfig.from_env(args.env_file, environ={}), args.lookback_days,
            trace_ids=(
                list(case_map)
                if case_map and (args.force_trace_ids or len(run_ids) != 1) else None
            ),
            session_id=(
                next(iter(run_ids))
                if len(run_ids) == 1 and not args.force_trace_ids else None
            ),
        )
        if args.fetch_langfuse else _load(args.input)
    )
    report = build_report(rows, case_map=case_map)
    report["retrieval_quality_regression_passed"] = (
        True if args.retrieval_quality_status == "PASS"
        else False if args.retrieval_quality_status == "FAIL" else None
    )
    if args.retrieval_quality_report:
        quality = json.loads(args.retrieval_quality_report.read_text(encoding="utf-8"))
        report["retrieval_quality"] = quality
        gate = quality.get("gate") if isinstance(quality, dict) else None
        if isinstance(gate, dict) and isinstance(gate.get("passed"), bool):
            report["retrieval_quality_regression_passed"] = gate["passed"]
        elif isinstance(quality, dict):
            execution_gate = (quality.get("execution") or {}).get("gate")
            if execution_gate in {"PASS", "BLOCK"}:
                report["retrieval_quality_regression_passed"] = execution_gate == "PASS"
    if args.golden_parity_report:
        parity = json.loads(args.golden_parity_report.read_text(encoding="utf-8"))
        report["golden_tokenizer_parity"] = parity
        report["golden_tokenizer_parity_passed"] = parity.get("gate", {}).get("passed") is True
    report["phase3_gate"] = phase3_gate(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "trace_count": report["trace_count"],
        "accounting_errors": report["accounting"]["error_count"],
        "phase3": report["phase3_gate"]["decision"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
