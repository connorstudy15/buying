"""Workload prediction; owns no runtime facts and makes no policy decisions."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import FutureBucket, InformationNeedRequirement, ResourceEstimate
from .plan import FutureOperation, FutureWorkPlan, InformationNeed
from .profiles import bootstrap_profiles


@dataclass(frozen=True)
class PredictedWorkload:
    route: str
    confidence: str
    rationale: str


class WorkloadPredictor:
    def __init__(self, model: str) -> None:
        self.model = model
        self._profiles = bootstrap_profiles(model)

    def bootstrap(self, request_id: str) -> tuple[FutureWorkPlan, PredictedWorkload]:
        plan = FutureWorkPlan()
        # Bootstrap assumption: one planning call followed by one protected final
        # call. Historical replay, rather than this class, judges its error.
        plan.add(FutureOperation(
            logical_call_id=f"{request_id}:main.plan.1",
            operation="main.plan",
            estimate=self._profiles["main.plan"],
            bucket=FutureBucket.PREDICTED_UNRESERVED,
            prediction_reason="BOOTSTRAP_SPECULATIVE",
        ))
        plan.add(FutureOperation(
            logical_call_id=f"{request_id}:main.final",
            operation="main.final",
            estimate=self._profiles["main.final"],
            bucket=FutureBucket.PROTECTED_FUTURE,
            priority="protected",
            prediction_reason="MANDATORY_FINAL_PROTECTION",
        ))
        return plan, PredictedWorkload(
            route="unknown_one_plan_plus_final",
            confidence="low",
            rationale="bootstrap_trace_p80; not a proven optimum",
        )

    def add_information_needs(
        self, plan: FutureWorkPlan, needs: list[tuple[str, InformationNeedRequirement]],
    ) -> None:
        for need_id, requirement in needs:
            plan.add_need(InformationNeed(need_id, requirement))

    def add_query_processor_route(self, plan: FutureWorkPlan, request_id: str, mode: str) -> None:
        key = "query_processor.decompose" if mode.upper() == "DECOMPOSE" else "query_processor.direct"
        logical_id = f"{request_id}:{key}"
        if plan.get(logical_id) is None:
            plan.add(FutureOperation(
                logical_call_id=logical_id,
                operation=key,
                estimate=self._profiles[key],
                bucket=FutureBucket.PREDICTED_UNRESERVED,
                prediction_reason="QUERY_PROCESSOR_ROUTE_KNOWN",
            ))

    def add_decompose_followups(
        self, plan: FutureWorkPlan, request_id: str, need_ids: list[str],
        *, flow_id: str = "main", tool_call_id: str | None = None,
    ) -> None:
        for need_id in need_ids:
            if not plan.has_need(need_id):
                plan.add_need(InformationNeed(need_id, InformationNeedRequirement.REQUIRED))
            logical_id = f"{request_id}:{flow_id}:{tool_call_id}:reranker.knowledge.need:{need_id}"
            if plan.get(logical_id) is None and plan.terminal_state(logical_id) is None:
                plan.add(FutureOperation(
                    logical_call_id=logical_id,
                    operation="reranker.knowledge.need",
                    estimate=self._profiles["reranker.knowledge.need"],
                    bucket=FutureBucket.PREDICTED_UNRESERVED,
                    information_need_id=need_id,
                    prediction_reason="UNRESOLVED_REQUIRED_NEED",
                    flow_id=flow_id, tool_call_id=tool_call_id,
                ))

    def add_tool_followups(
        self, plan: FutureWorkPlan, request_id: str, tool_names: list[str], *,
        sequence: int, source_role: str,
        continuation_signals: tuple[str, ...] = (),
        tool_calls: list[dict] | None = None, flow_id: str = "main",
        tool_call_id: str | None = None,
    ) -> None:
        """Revise future work using only tool calls already emitted by the model."""
        if tool_calls is not None:
            # Concrete emitted calls, not tool names, are the concurrency unit.
            # Arguments are used only to identify dispatch type; never persisted.
            for call in tool_calls:
                call_id = call.get("id")
                if not call_id:
                    continue  # Missing identity is NOT exact-match capable.
                if call["name"] == "task_dispatch":
                    kind = (call.get("input") or {}).get("subagent_type")
                    if kind not in {"search_agent", "trade_agent"}:
                        continue
                    role = "trade" if kind == "trade_agent" else "search"
                    for phase in ("plan", "final"):
                        operation = f"{role}.{phase}"
                        plan.add(FutureOperation(
                            logical_call_id=f"{request_id}:dispatch:{call_id}:{operation}",
                            operation=operation,
                            estimate=self._profiles.get(operation, self._profiles[f"search.{phase}"]),
                            bucket=(FutureBucket.PROTECTED_FUTURE if phase == "final"
                                    else FutureBucket.PREDICTED_UNRESERVED),
                            priority="protected" if phase == "final" else "normal",
                            prediction_reason=("TRADE_BOOTSTRAP_TRANSFER" if role == "trade"
                                               else "MANDATORY_FINAL_PROTECTION" if phase == "final"
                                               else "SEARCH_RETURN_CONTINUATION"),
                            flow_id=f"dispatch:{call_id}",
                        ))
                    continue
                self.add_tool_followups(
                    plan, request_id, [call["name"]], sequence=f"{sequence}:{call_id}",
                    source_role="main", flow_id=flow_id, tool_call_id=str(call_id),
                )
            self.add_tool_followups(
                plan, request_id, ["__batch__"], sequence=sequence,
                source_role=source_role, continuation_signals=continuation_signals,
                flow_id=flow_id,
            )
            return
        normalized = [str(name).casefold() for name in tool_names if name]
        if not normalized:
            return
        tool_counts = Counter(normalized)
        # A tool result can flow directly into the already-protected final
        # answer.  Add an extra planning round only when the runtime supplies a
        # concrete continuation signal; otherwise simple DIRECT requests are
        # systematically double-counted.
        allowed_reasons = {
            "UNRESOLVED_REQUIRED_NEED", "EVIDENCE_INSUFFICIENT",
            "RESULT_SYNTHESIS_REQUIRED", "NEW_INFORMATION_NEED",
            "EXPLICIT_LOOP_SIGNAL", "SEARCH_RETURN_CONTINUATION",
        }
        reasons = tuple(reason for reason in continuation_signals if reason in allowed_reasons)
        # A Search Agent must make exactly one more model call after a batch of
        # tool results.  Predict one continuation per batch, not per parallel
        # tool call.  If the next call is search.final, the Governor cancels
        # this unused plan placeholder.
        if source_role == "search" and "SEARCH_RETURN_CONTINUATION" not in reasons:
            reasons = (*reasons, "SEARCH_RETURN_CONTINUATION")
        if reasons:
            continuation_role = (
                "search" if source_role == "search"
                else "trade" if source_role == "trade" else "main"
            )
            continuation_operation = f"{continuation_role}.plan"
            continuation_id = f"{request_id}:{continuation_operation}.after_tool:{sequence}"
            if plan.get(continuation_id) is None:
                plan.add(FutureOperation(
                    logical_call_id=continuation_id,
                    operation=continuation_operation,
                    estimate=self._profiles.get(continuation_operation, self._profiles["main.plan"]),
                    bucket=FutureBucket.PREDICTED_UNRESERVED,
                    prediction_reason=reasons[0],
                    flow_id=flow_id,
                ))
        if tool_counts["category_insight_tool"]:
            logical_id = f"{request_id}:query_processor.classify:{sequence}"
            if plan.get(logical_id) is None:
                plan.add(FutureOperation(
                    logical_call_id=logical_id,
                    operation="query_processor.classify",
                    estimate=self._profiles["query_processor.classify"],
                    bucket=FutureBucket.PREDICTED_UNRESERVED,
                    prediction_reason="QUERY_PROCESSOR_TYPE_UNKNOWN",
                    flow_id=flow_id, tool_call_id=tool_call_id,
                ))
        # Preserve tool-call cardinality.  Several task_dispatch calls in one
        # assistant turn create several independent Search Agent lifecycles.
        for call_index in range(tool_counts["task_dispatch"]):
            for operation in ("search.plan", "search.final"):
                logical_id = (
                    f"{request_id}:{operation}.after_dispatch:{sequence}:{call_index}"
                )
                if plan.get(logical_id) is None:
                    plan.add(FutureOperation(
                        logical_call_id=logical_id,
                        operation=operation,
                        estimate=self._profiles[operation],
                        bucket=(
                            FutureBucket.PROTECTED_FUTURE
                            if operation.endswith(".final") else FutureBucket.PREDICTED_UNRESERVED
                        ),
                        priority="protected" if operation.endswith(".final") else "normal",
                        prediction_reason=(
                            "SEARCH_RETURN_CONTINUATION"
                            if operation == "search.plan" else "MANDATORY_FINAL_PROTECTION"
                        ),
                    ))
        # Parallel product calls are independent retrievals: each incurs one
        # embedding and one reranker operation and must not be collapsed by a
        # set of tool names.
        for call_index in range(tool_counts["product_search_tool"]):
            for operation in ("embedding.product_query", "reranker.product"):
                logical_id = f"{request_id}:{operation}.after_tool:{sequence}:{call_index}"
                if plan.get(logical_id) is None:
                    plan.add(FutureOperation(
                        logical_call_id=logical_id,
                        operation=operation,
                        estimate=self._profiles[operation],
                        bucket=FutureBucket.PREDICTED_UNRESERVED,
                        prediction_reason="PRODUCT_RETRIEVAL_EMITTED",
                        flow_id=flow_id, tool_call_id=tool_call_id,
                    ))

    @staticmethod
    def classify_route(
        operations: list[str], *, query_mode: str | None = None,
        context_bucket: str = "unknown",
    ) -> PredictedWorkload:
        """Classify from the execution graph, never from hand-written query rules."""
        names = set(operations)
        if any(name.startswith("trade.") for name in names):
            route = "trade"
        elif any(name.startswith("search.") or name.startswith("embedding.product") for name in names) \
                and any(name.startswith("knowledge.") or "query_processor" in name for name in names):
            route = "mixed_flow"
        elif any(name.startswith("search.") or name.startswith("embedding.product") for name in names):
            route = "product_search"
        elif str(query_mode or "").upper() == "DECOMPOSE" or any(
            name == "reranker.knowledge.need" for name in names
        ):
            route = "knowledge_decompose"
        elif any(name.startswith("knowledge.") or "query_processor" in name for name in names):
            route = "knowledge_direct"
        else:
            route = "simple_direct"
        if context_bucket == "large":
            route = "context_heavy"
        confidence = "medium" if names else "low"
        return PredictedWorkload(
            route=route,
            confidence=confidence,
            rationale="execution_graph+query_processor_mode+context_bucket",
        )

    @staticmethod
    def planned_estimate(plan: FutureWorkPlan) -> ResourceEstimate:
        return plan.protected_future().plus(plan.predicted_unreserved())

