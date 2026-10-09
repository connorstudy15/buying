"""Explicit model operation spans for Phase-0 observability."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterable
from typing import Any

from agentscope.message import ToolCallBlock
from agentscope.middleware import MiddlewareBase
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.infrastructure.context_usage import context_call_kind

from .estimator import TokenEstimator
from .governor import current_governor
from .models import ContextScope, ResourceEstimate
from .operation import OperationContext, _operation, current_execution, execution_identity
from .profiles import execution_contract_hash
from .runtime import RuntimeObservation

logger = logging.getLogger(__name__)


def _agent_role(agent: Any) -> tuple[str, ContextScope]:
    name = str(getattr(agent, "name", "")).casefold()
    if "catalog_search" in name or "search_agent" in name:
        return "search", ContextScope.SEARCH
    if "order_trade" in name or "trade_agent" in name:
        return "trade", ContextScope.TRADE
    return "main", ContextScope.MAIN


def _field(value: Any, name: str):
    if isinstance(value, dict):
        return value.get(name)
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _usage(response: Any) -> tuple[int | None, int | None]:
    usage = _field(response, "usage")
    input_tokens = _field(usage, "input_tokens")
    if input_tokens is None:
        input_tokens = _field(usage, "prompt_tokens")
    output_tokens = _field(usage, "output_tokens")
    if output_tokens is None:
        output_tokens = _field(usage, "completion_tokens")
    return (
        int(input_tokens) if isinstance(input_tokens, (int, float)) else None,
        int(output_tokens) if isinstance(output_tokens, (int, float)) else None,
    )


def _has_tool_call(response: Any) -> bool:
    return any(isinstance(block, ToolCallBlock) for block in (_field(response, "content") or []))


def _tool_call_names(response: Any) -> list[str]:
    names: list[str] = []
    for block in (_field(response, "content") or []):
        if not isinstance(block, ToolCallBlock):
            continue
        name = _field(block, "name") or _field(_field(block, "function"), "name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _tool_calls(response: Any) -> list[dict]:
    calls = []
    for block in (_field(response, "content") or []):
        if isinstance(block, ToolCallBlock):
            arguments = _field(block, "input") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (ValueError, TypeError):
                    arguments = {}
            calls.append({"id": _field(block, "id"), "name": _field(block, "name"),
                          "input": arguments if isinstance(arguments, dict) else {}})
    return calls


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _result_observation(call, result, *, flow_id: str, role: str) -> RuntimeObservation:
    calls = _tool_calls({"content": [call]})
    data = calls[0] if calls else {}
    arguments = data.get("input") or {}
    name = data.get("name") or "unknown"
    payload = None
    for block in (_field(result, "content") or []):
        text = _field(block, "text")
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    payload = parsed
                    break
            except (TypeError, ValueError):
                pass
    state = _field(result, "state")
    state = str(getattr(state, "value", state)).casefold()
    success = True if state == "success" else False if state == "error" else None
    evidence = []
    if success is True and payload is not None:
        for hit in payload.get("hits", []):
            if isinstance(hit, dict):
                evidence.append(_fingerprint({k: v for k, v in hit.items() if k not in {"score", "similarity", "rank", "rerank_score"}}))
        for hit in payload.get("insights", []):
            if isinstance(hit, dict) and hit.get("content"):
                evidence.append(_fingerprint({k: hit.get(k) for k in ("source", "content", "metadata")}))
    is_search = name in {"product_search_tool", "category_insight_tool"}
    query = arguments.get("normalized_query") or arguments.get("question")
    constraints = {k: v for k, v in arguments.items() if k not in {"normalized_query", "question", "information_need_id"}}
    return RuntimeObservation(
        event_id=f"tool-result:{flow_id}:{data.get('id')}", flow_id=flow_id,
        operation=f"tool.{name}.result", agent=role, tool=name,
        need_id=str(arguments.get("information_need_id") or "unspecified") if is_search else None,
        query_hash=_fingerprint(query) if isinstance(query, str) else None,
        constraint_signature=_fingerprint(constraints) if is_search else None,
        evidence_ids=tuple(evidence), success=success,
        evidence_sufficient=False if payload and payload.get("unanswerable") is True else None,
        # Re-querying prices/stock may be necessary even with identical input.
        freshness_required=True if name == "product_search_tool" else None,
    )


class ResourceOperationTracingMiddleware(MiddlewareBase):
    """Observe exact agent model calls without changing their arguments/results."""

    async def on_acting(self, agent, input_kwargs, next_handler):
        call = input_kwargs.get("tool_call")
        call_id = _field(call, "id")
        identity = current_execution()
        dispatch = _field(call, "name") == "task_dispatch" and bool(call_id)
        with execution_identity(
            flow_id=f"dispatch:{call_id}" if dispatch else identity.flow_id,
            tool_call_id=None if dispatch else call_id,
        ):
            governor = current_governor()
            role, _ = _agent_role(agent)
            # Handoff tool bookkeeping belongs to its caller. The worker's
            # model/tool events alone belong to dispatch:<id>; do not append
            # a parent tool result after a child's terminal final event.
            runtime_flow = identity.flow_id if dispatch else current_execution().flow_id
            observed = _tool_calls({"content": [call]})
            if governor is not None and call_id and observed:
                try:
                    await governor.observe_runtime(RuntimeObservation(
                        event_id=f"tool-start:{runtime_flow}:{call_id}",
                        flow_id=runtime_flow, operation="tool.permitted",
                        agent=role, tool=_field(call, "name"),
                        valid_action_id=_fingerprint({"name": observed[0]["name"], "input": observed[0]["input"]}),
                    ))
                except Exception as error:
                    logger.warning("runtime action observation failed error_type=%s", type(error).__name__)
            last_result = None
            try:
                async for result in next_handler(**input_kwargs):
                    last_result = result
                    yield result
            except BaseException:
                if governor is not None and call_id:
                    try:
                        await governor.observe_runtime(RuntimeObservation(
                            event_id=f"tool-failed:{runtime_flow}:{call_id}",
                            flow_id=runtime_flow, operation="tool.failed",
                            agent=role, tool=_field(call, "name"), success=False,
                        ))
                    except Exception as error:
                        logger.warning("runtime failure observation failed error_type=%s", type(error).__name__)
                raise
            if governor is not None and call_id and last_result is not None:
                try:
                    await governor.observe_runtime(_result_observation(
                        call, last_result, flow_id=runtime_flow, role=role,
                    ))
                except Exception as error:
                    logger.warning("runtime result observation failed error_type=%s", type(error).__name__)

    def __init__(self, estimator: TokenEstimator | None = None, settings=None) -> None:
        self.estimator = estimator or TokenEstimator()
        self.prompt_version = str(getattr(settings, "prompt_pin_version", "") or "runtime")
        from app.infrastructure.context_governance import POLICY_VERSION
        from app.infrastructure.runtime_version import app_source_fingerprint
        self.policy_version = POLICY_VERSION
        self.relevant_code_version = app_source_fingerprint()[:24]

    async def on_model_call(self, agent, input_kwargs, next_handler):
        role, scope = _agent_role(agent)
        summary_call = context_call_kind.get() == "summary"
        provisional = "context.summary" if summary_call else f"{role}.final"
        logical_id = uuid.uuid4().hex
        operation = OperationContext(logical_id, provisional, "agent_model", scope)
        model = input_kwargs.get("current_model", getattr(agent, "model", None))
        messages = input_kwargs.get("messages") or []
        tools = input_kwargs.get("tools") or []
        comparison = await self.estimator.estimate_model_input_comparison(
            model, messages, tools, operation=provisional,
            prompt_version=self.prompt_version,
        )
        estimate = comparison.selected
        old_estimate = comparison.legacy
        deepseek_estimate = comparison.deepseek_v41
        governor = current_governor()
        contract_hash = execution_contract_hash(
            component="agent_model", operation=provisional,
            prompt_version=self.prompt_version, policy_version=self.policy_version,
            relevant_code_version=self.relevant_code_version,
        )
        context_bucket = "small" if estimate.safe_tokens <= 24_000 else "medium" if estimate.safe_tokens <= 48_000 else "large"
        hard_limit = (governor.context if governor is not None else None)
        model_window = int(getattr(model, "context_size", 0) or 0)
        hard_safety = hard_limit.hard_safety_limit(
            model_context_window=model_window, operation=provisional, context_scope=scope,
        ) if hard_limit is not None and model_window else None
        tracer = trace.get_tracer(__name__)
        span = tracer.start_span("resource.model_operation", attributes={
            "langfuse.observation.type": "span",
            "globex.trace.stage": "resource_operation",
            "globex.resource.logical_call_id": logical_id,
            "globex.resource.flow_id": current_execution().flow_id,
            "globex.resource.operation": provisional,
            "globex.resource.component": "agent_model",
            "globex.resource.context_scope": scope.value,
            "globex.resource.shadow_only": True,
            "globex.resource.estimated_input_tokens_raw": estimate.raw_tokens,
            "globex.resource.estimated_input_tokens_safe": estimate.safe_tokens,
            "globex.resource.old_estimated_prompt_tokens": old_estimate.raw_tokens,
            "globex.resource.deepseek_estimated_prompt_tokens": deepseek_estimate.raw_tokens,
            "globex.resource.deepseek_safe_estimated_prompt_tokens": deepseek_estimate.safe_tokens,
            "globex.resource.deepseek_estimator_method": deepseek_estimate.method,
            "globex.resource.deepseek_estimator_confidence": deepseek_estimate.confidence,
            "globex.resource.estimator_version": estimate.estimator_version,
            "globex.resource.estimator_method": estimate.method,
            "globex.resource.estimator_confidence": estimate.confidence,
            "globex.resource.input_message_count": len(messages),
            "globex.resource.tool_count": len(tools),
            "globex.resource.execution_path": role,
            "globex.resource.context_bucket": context_bucket,
            "globex.resource.candidate_bucket": "none",
            "globex.resource.prompt_version": self.prompt_version,
            "globex.resource.policy_version": self.policy_version,
            "globex.resource.relevant_code_version": self.relevant_code_version,
            "globex.resource.execution_contract_hash": contract_hash,
            "globex.resource.profile_id": f"bootstrap:{contract_hash}",
            "globex.resource.profile_confidence": "bootstrap",
        }, record_exception=False, set_status_on_exception=False)
        if hard_safety is not None:
            span.set_attribute("globex.resource.operation_hard_safety_tokens", hard_safety)
        started = time.perf_counter()
        last = None
        tool_call_seen = False

        async def finalize(error: BaseException | None = None) -> None:
            nonlocal last
            if not summary_call:
                operation.operation = f"{role}.plan" if tool_call_seen else f"{role}.final"
            final_contract_hash = execution_contract_hash(
                component="agent_model", operation=operation.operation,
                prompt_version=self.prompt_version, policy_version=self.policy_version,
                relevant_code_version=self.relevant_code_version,
            )
            input_tokens, output_tokens = _usage(last)
            final_comparison = operation.pre_call_comparison or comparison
            final_estimate = final_comparison.selected
            final_old_estimate = final_comparison.legacy
            final_deepseek_estimate = final_comparison.deepseek_v41
            old_ratio = (
                input_tokens / final_old_estimate.raw_tokens
                if input_tokens is not None and final_old_estimate.raw_tokens else None
            )
            deepseek_ratio = (
                input_tokens / final_deepseek_estimate.raw_tokens
                if input_tokens is not None and final_deepseek_estimate.raw_tokens else None
            )
            output_reserve = self._output_reserve(model, input_kwargs)
            if governor is not None and model_window:
                span.set_attribute(
                    "globex.resource.operation_hard_safety_tokens",
                    governor.context.hard_safety_limit(
                        model_context_window=model_window,
                        operation=operation.operation,
                        context_scope=scope,
                    ),
                )
            span.set_attributes({
                "globex.resource.operation": operation.operation,
                "globex.resource.latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "globex.resource.usage_source": "actual" if input_tokens is not None else "estimated_missing_usage",
                "globex.resource.actual_input_tokens": input_tokens or 0,
                "globex.resource.actual_output_tokens": output_tokens or 0,
                "globex.resource.local_estimated_output_reserve": output_reserve,
                "globex.resource.attempt": 1,
                "globex.resource.execution_contract_hash": final_contract_hash,
                "globex.resource.profile_id": final_deepseek_estimate.calibration_profile_id,
                "globex.resource.profile_confidence": final_deepseek_estimate.calibration_confidence,
                "globex.resource.calibration_samples": final_deepseek_estimate.calibration_samples,
                "globex.resource.estimator_input_stage": final_comparison.input_stage,
                "globex.resource.estimated_input_tokens_raw": final_estimate.raw_tokens,
                "globex.resource.estimated_input_tokens_safe": final_estimate.safe_tokens,
                "globex.resource.old_estimated_prompt_tokens": final_old_estimate.raw_tokens,
                "globex.resource.deepseek_estimated_prompt_tokens": final_deepseek_estimate.raw_tokens,
                "globex.resource.deepseek_safe_estimated_prompt_tokens": final_deepseek_estimate.safe_tokens,
                "globex.resource.deepseek_estimator_method": final_deepseek_estimate.method,
                "globex.resource.thinking_mode": final_comparison.request_traits.get("thinking_mode", "unspecified"),
                "globex.resource.reasoning_effort": final_comparison.request_traits.get("reasoning_effort", "unspecified"),
                "globex.resource.tooling_mode": final_comparison.request_traits.get("tooling_mode", "none"),
            })
            if old_ratio is not None:
                span.set_attribute("globex.resource.old_actual_estimate_ratio", round(old_ratio, 6))
            if deepseek_ratio is not None:
                span.set_attribute("globex.resource.deepseek_actual_estimate_ratio", round(deepseek_ratio, 6))
            if input_tokens is not None:
                self.estimator.calibration.observe(
                    final_estimate.model, operation.operation, final_deepseek_estimate.raw_tokens,
                    input_tokens, prompt_version=self.prompt_version,
                    traits=final_comparison.request_traits,
                )
            if governor is not None:
                try:
                    ctx = span.get_span_context()
                    governor.record_observed_usage(
                        logical_call_id=logical_id,
                        attempt=1,
                        operation=operation.operation,
                        estimate=ResourceEstimate(
                            chat_input_tokens=input_tokens if input_tokens is not None else final_estimate.safe_tokens,
                            chat_output_tokens=output_tokens or 0,
                            api_calls=1,
                            monetary_cost=None,
                            latency_ms=round((time.perf_counter() - started) * 1000),
                        ),
                        usage_source="actual" if input_tokens is not None else "estimated_missing_usage",
                        trace_id=f"{ctx.trace_id:032x}" if ctx.is_valid else "",
                        span_id=f"{ctx.span_id:016x}" if ctx.is_valid else "",
                    )
                    if error is None:
                        await governor.observe_completed_operation(
                            operation.operation, logical_call_id=logical_id, result_typed=True,
                        )
                        await governor.observe_runtime(RuntimeObservation(
                            event_id=f"model-result:{logical_id}", flow_id=current_execution().flow_id,
                            operation=operation.operation, agent=role,
                            context_tokens=input_tokens if input_tokens is not None else None,
                        ))
                        tool_names = _tool_call_names(last)
                        if tool_names:
                            await governor.observe_tool_calls(tool_names, source_role=role, tool_calls=_tool_calls(last))
                except Exception as observation_error:
                    logger.warning("shadow resource observation failed error_type=%s", type(observation_error).__name__)
            if error is not None:
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(Status(StatusCode.ERROR))
            span.end()

        token = _operation.set(operation)
        try:
            with trace.use_span(span, end_on_exit=False):
                result = await next_handler(**input_kwargs)
        except BaseException as error:
            await finalize(error)
            raise
        finally:
            _operation.reset(token)

        if isinstance(result, AsyncIterable):
            async def stream():
                nonlocal last, tool_call_seen
                error = None
                stream_token = _operation.set(operation)
                try:
                    with trace.use_span(span, end_on_exit=False):
                        async for part in result:
                            last = part
                            tool_call_seen = tool_call_seen or _has_tool_call(part)
                            yield part
                except BaseException as caught:
                    error = caught
                    raise
                finally:
                    try:
                        close = getattr(result, "aclose", None)
                        if close is not None:
                            await close()
                    finally:
                        try:
                            await finalize(error)
                        finally:
                            _operation.reset(stream_token)
            return stream()

        last = result
        tool_call_seen = _has_tool_call(result)
        await finalize()
        return result

    @staticmethod
    def _output_reserve(model: Any, input_kwargs: dict[str, Any]) -> int:
        for source in (input_kwargs, getattr(model, "parameters", None)):
            for name in ("max_completion_tokens", "max_tokens"):
                value = _field(source, name)
                if isinstance(value, (int, float)) and value > 0:
                    return int(value)
        return 1024

