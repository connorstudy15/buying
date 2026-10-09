"""Request-scoped shadow resource governor."""
from __future__ import annotations

import asyncio
import json
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass

from .context_governor import ContextGovernorAdapter
from .ledger import UsageEntry, UsageLedger
from .models import (
    BudgetEnvelope, BudgetUnchangedReason, ReservationDecision, ReservationDecisionCode, ResourceEstimate,
)
from .plan import FutureWorkPlan
from .policy import ResourcePolicy
from .predictor import WorkloadPredictor
from .reservations import ReservationManager
from .runtime import RuntimeObservation, RuntimeStateStore
from .continuation import ContinuationDiagnostics, TransitionProfileStore
from .runtime_trace import runtime_trace_fields


@dataclass(frozen=True)
class GovernorSnapshot:
    request_id: str
    plan_revision: int
    used: ResourceEstimate
    active_reserved: ResourceEstimate
    protected_future: ResourceEstimate
    predicted_unreserved: ResourceEstimate
    projected: ResourceEstimate
    planned_budget: BudgetEnvelope
    absolute_hard_cap: BudgetEnvelope
    shadow_only: bool


class RequestResourceGovernor:
    def __init__(
        self, request_id: str, model: str, *, shadow_only: bool = True,
        planning_safety_factor: float = 1.20, absolute_chat_hard_cap: int = 80_000,
        continuation_profiles: TransitionProfileStore | None = None,
    ) -> None:
        self.request_id = request_id
        self.shadow_only = shadow_only
        self._planning_safety_factor = planning_safety_factor
        self.ledger = UsageLedger()
        self.reservations = ReservationManager()
        self.predictor = WorkloadPredictor(model)
        self.future_plan, self.prediction = self.predictor.bootstrap(request_id)
        planned = self.predictor.planned_estimate(self.future_plan).scale(planning_safety_factor)
        self.planned_budget = BudgetEnvelope(chat_token_limit=planned.chat_total_tokens)
        self.absolute_hard_cap = BudgetEnvelope(chat_token_limit=absolute_chat_hard_cap)
        self.policy = ResourcePolicy()
        self.context = ContextGovernorAdapter()
        self._lock = asyncio.Lock()
        self.runtime = RuntimeStateStore()
        self.continuation = ContinuationDiagnostics(continuation_profiles)
        self._decisions: list[ReservationDecision] = []
        self._observed_operations: list[str] = []
        self._query_mode: str | None = None
        self._route_after_query_processor: str | None = None
        self._revision_history: list[dict[str, object]] = []
        self._last_budget_inputs = self._budget_inputs()
        self._budget_revision: dict[str, object] = {
            "budget_recomputed": True,
            "previous_planned_budget": None,
            "new_planned_budget": self.planned_budget.chat_token_limit or 0,
            "previous_projected_total": None,
            "new_projected_total": self._last_budget_inputs["projected_total"],
            "previous_predicted_unreserved": None,
            "new_predicted_unreserved": self._last_budget_inputs["predicted_unreserved"],
            "protected_future": self._last_budget_inputs["protected_future"],
            "unchanged_reason": None,
            "recompute_reason": "bootstrap",
        }
        self._record_plan_revision("bootstrap", {
            "query_mode": None,
            "known_operation_count": 0,
        })

    async def try_reserve(
        self, logical_call_id: str, expected_plan_revision: int, *, attempt: int = 1,
        estimate: ResourceEstimate | None = None, timeout_seconds: float = 300.0,
    ) -> ReservationDecision:
        async with self._lock:
            # Invariant B: both the revision and operation state are revalidated
            # while holding the same lock that creates the reservation.
            if expected_plan_revision != self.future_plan.revision:
                decision = ReservationDecision.replan_required(self.future_plan.revision)
                self._decisions.append(decision)
                return decision
            operation = self.future_plan.get(logical_call_id)
            executable, reason = self.future_plan.is_executable(logical_call_id)
            if operation is None or not executable:
                decision = ReservationDecision(
                    code=ReservationDecisionCode.NOT_EXECUTABLE,
                    execution_allowed=False,
                    would_action="replan",
                    reason=reason,
                    current_plan_revision=self.future_plan.revision,
                )
                self._decisions.append(decision)
                return decision
            candidate = estimate or operation.estimate
            projected = self._projected()
            evaluation = self.policy.evaluate(
                projected, planned_budget=self.planned_budget,
                absolute_hard_cap=self.absolute_hard_cap,
            )
            reservation = self.reservations.reserve(
                logical_call_id, attempt, operation.operation, candidate,
                timeout_seconds=timeout_seconds,
            )
            self.future_plan.activate(logical_call_id, reservation.reservation_id)
            self.future_plan.validate(self.reservations)
            self._refresh_planned_budget("operation_reserved")
            self._record_plan_revision("operation_reserved", {
                "operation": operation.operation,
                "known_operation_count": len(self._observed_operations),
            })
            decision = ReservationDecision(
                code=evaluation.code,
                # Shadow decisions never suppress the real business operation.
                execution_allowed=True if self.shadow_only else evaluation.would_action != "reject",
                would_action=evaluation.would_action,
                reason=evaluation.reason,
                current_plan_revision=self.future_plan.revision,
                reservation_id=reservation.reservation_id,
                projected=projected,
            )
            self._decisions.append(decision)
            return decision

    async def settle(
        self, reservation_id: str, actual: ResourceEstimate | None, *,
        retry: bool = False, timed_out: bool = False,
        cancelled_before_upstream: bool = False, trace_id: str = "", span_id: str = "",
    ) -> None:
        async with self._lock:
            reservation = self.reservations.settle(
                reservation_id, actual, timed_out=timed_out,
                cancelled_before_upstream=cancelled_before_upstream,
            )
            settled = reservation.settled_estimate or ResourceEstimate()
            source = (
                "actual" if actual is not None
                else "estimated_timeout" if timed_out else "estimated_missing_usage"
            )
            self.ledger.record(UsageEntry(
                logical_call_id=reservation.logical_call_id,
                attempt=reservation.attempt,
                operation=reservation.operation,
                estimate=settled,
                usage_source=source,
                trace_id=trace_id,
                span_id=span_id,
            ))
            # Invariant C: old attempt is settled before a retry can return the
            # operation to an unreserved bucket.
            self.future_plan.settle(
                reservation.logical_call_id, retry=retry,
                cancelled=cancelled_before_upstream,
            )
            self.future_plan.validate(self.reservations)
            self._refresh_planned_budget("operation_settled")
            self._record_plan_revision("operation_settled", {
                "operation": reservation.operation,
                "retry": retry,
                "known_operation_count": len(self._observed_operations),
            })

    async def settle_expired(self, *, retry: bool = True) -> int:
        """Conservatively settle timed-out work before any retry becomes active."""
        async with self._lock:
            expired = self.reservations.expired_ids()
            for reservation_id in expired:
                reservation = self.reservations.settle(reservation_id, None, timed_out=True)
                self.ledger.record(UsageEntry(
                    logical_call_id=reservation.logical_call_id,
                    attempt=reservation.attempt,
                    operation=reservation.operation,
                    estimate=reservation.settled_estimate or reservation.estimate,
                    usage_source="estimated_timeout",
                ))
                self.future_plan.settle(reservation.logical_call_id, retry=retry)
            self.future_plan.validate(self.reservations)
            if expired:
                self._refresh_planned_budget("expired_operation_settled")
                self._record_plan_revision("expired_operation_settled", {
                    "known_operation_count": len(self._observed_operations),
                })
            return len(expired)

    def record_observed_usage(
        self, *, logical_call_id: str | None, attempt: int, operation: str,
        estimate: ResourceEstimate, usage_source: str = "actual", trace_id: str = "", span_id: str = "",
    ) -> None:
        """Record non-reserved Phase-0 observations without affecting execution."""
        call_id = logical_call_id or f"{self.request_id}:observed:{uuid.uuid4().hex}"
        entry = UsageEntry(
            logical_call_id=call_id,
            attempt=attempt,
            operation=operation,
            estimate=estimate,
            usage_source=usage_source,  # type: ignore[arg-type]
            trace_id=trace_id,
            span_id=span_id,
        )
        try:
            self.ledger.record(entry)
        except ValueError:
            # Instrumentation must not break the business path. Preserve the
            # fact with a unique observation id while strict reservation/settle
            # APIs continue to reject duplicate attempts.
            self.ledger.record(UsageEntry(
                logical_call_id=f"{call_id}:duplicate:{uuid.uuid4().hex[:8]}",
                attempt=attempt,
                operation=operation,
                estimate=estimate,
                usage_source=usage_source,  # type: ignore[arg-type]
                trace_id=trace_id,
                span_id=span_id,
            ))

    def decisions(self) -> tuple[ReservationDecision, ...]:
        return tuple(self._decisions)

    @property
    def observed_operations(self) -> tuple[str, ...]:
        return tuple(self._observed_operations)

    def future_work_plan_json(self) -> str:
        """Content-free plan snapshot suitable for a bounded Trace attribute."""
        return json.dumps({
            "revision": self.future_plan.revision,
            "operations": [{
                "logical_call_id": item.logical_call_id,
                "operation": item.operation,
                "bucket": item.bucket.value,
                "priority": item.priority,
                "information_need_id": item.information_need_id,
                "chat_tokens": item.estimate.chat_total_tokens,
                "rerank_tokens": item.estimate.rerank_tokens,
                "state": item.state.value,
                "prediction_reason": item.prediction_reason,
                "flow_id": item.flow_id,
                "tool_call_id": item.tool_call_id,
            } for item in self.future_plan.operations()],
        }, ensure_ascii=False, separators=(",", ":"))

    @property
    def route_after_query_processor(self) -> str | None:
        return self._route_after_query_processor

    @property
    def route_revision_count(self) -> int:
        routes = [str(item["route"]) for item in self._revision_history]
        return sum(left != right for left, right in zip(routes, routes[1:]))

    def plan_revision_history_json(self) -> str:
        """Content-free, bounded revision history for causal offline replay."""
        return json.dumps(
            self._revision_history[-64:], ensure_ascii=False, separators=(",", ":"),
        )

    def _record_plan_revision(self, trigger: str, known_information: dict[str, object]) -> None:
        self._emit_pending_future_transitions()
        future_operations = self.future_plan.future_operations()
        protected = self.future_plan.protected_future()
        predicted = self.future_plan.predicted_unreserved()
        used = self.ledger.used()
        active = self.reservations.active_reserved()
        projected = used.plus(active).plus(protected).plus(predicted)
        inflight = sum(
            item.estimate.chat_total_tokens for item in self.future_plan.operations()
            if item.state.value == "started" and item.active_reservation_id is None
        )
        remaining_budget = (self.planned_budget.chat_token_limit or 0) + active.chat_total_tokens + inflight
        revision_row = {
            "sequence": len(self._revision_history),
            "plan_revision": self.future_plan.revision,
            "trigger": trigger,
            "known_information": known_information,
            "route": self.prediction.route,
            "route_confidence": self.prediction.confidence,
            "operation_count": len(future_operations),
            "operations": [item.operation for item in future_operations],
            "used_chat_tokens": used.chat_total_tokens,
            "active_reserved_chat_tokens": active.chat_total_tokens,
            "protected_future_chat_tokens": protected.chat_total_tokens,
            "predicted_unreserved_chat_tokens": predicted.chat_total_tokens,
            "projected_chat_tokens": projected.chat_total_tokens + inflight,
            "planned_budget_chat_tokens": self.planned_budget.chat_token_limit or 0,
            "planned_budget_scope": "unstarted_future_chat_only",
            "inflight_chat_tokens": inflight,
            "planned_remaining_chat_budget": remaining_budget,
            "planned_total_chat_budget": used.chat_total_tokens + remaining_budget,
            **self._budget_revision,
        }
        self._revision_history.append(revision_row)
        # A separate short-lived span is more reliable than one ever-growing
        # JSON attribute on commerce.turn and preserves causal ordering.
        try:
            from opentelemetry import trace
            attributes: dict[str, object] = {
                "langfuse.observation.type": "span",
                "globex.trace.stage": "resource_plan_revision",
                "globex.resource.plan_revision": int(revision_row["plan_revision"]),
                "globex.resource.revision_sequence": int(revision_row["sequence"]),
                "globex.resource.revision_trigger": trigger,
                "globex.resource.prediction_route": self.prediction.route,
                "globex.resource.prediction_confidence": self.prediction.confidence,
                "globex.resource.predicted_operation_count": int(revision_row["operation_count"]),
                "globex.resource.revision_operation_count": int(revision_row["operation_count"]),
                "globex.resource.used_chat_tokens": used.chat_total_tokens,
                "globex.resource.active_reserved_chat_tokens": active.chat_total_tokens,
                "globex.resource.protected_future_chat_tokens": protected.chat_total_tokens,
                "globex.resource.predicted_future_chat_tokens": predicted.chat_total_tokens,
                "globex.resource.projected_chat_tokens": projected.chat_total_tokens + inflight,
                "globex.resource.planned_chat_limit": self.planned_budget.chat_token_limit or 0,
                "globex.resource.planned_budget_scope": "unstarted_future_chat_only",
                "globex.resource.inflight_chat_tokens": inflight,
                "globex.resource.planned_remaining_chat_budget": remaining_budget,
                "globex.resource.planned_total_chat_budget": used.chat_total_tokens + remaining_budget,
                "globex.resource.budget_profile_source": "future_operation_profiles",
                "globex.resource.budget_floor": 0,
                "globex.resource.budget_cap": self.absolute_hard_cap.chat_token_limit or 0,
                "globex.resource.safety_factor": self._planning_safety_factor,
                "globex.resource.budget_recomputed": bool(self._budget_revision["budget_recomputed"]),
                "globex.resource.previous_planned_budget": int(self._budget_revision["previous_planned_budget"] or 0),
                "globex.resource.new_planned_budget": int(self._budget_revision["new_planned_budget"] or 0),
                "globex.resource.previous_projected_total": int(self._budget_revision["previous_projected_total"] or 0),
                "globex.resource.new_projected_total": int(self._budget_revision["new_projected_total"] or 0),
                "globex.resource.previous_predicted_unreserved": int(self._budget_revision["previous_predicted_unreserved"] or 0),
                "globex.resource.new_predicted_unreserved": int(self._budget_revision["new_predicted_unreserved"] or 0),
                "globex.resource.budget_protected_future": int(self._budget_revision["protected_future"] or 0),
                "globex.resource.budget_recompute_reason": str(self._budget_revision["recompute_reason"] or "unknown"),
            }
            if self._budget_revision.get("unchanged_reason"):
                attributes["globex.resource.budget_unchanged_reason"] = str(
                    self._budget_revision["unchanged_reason"],
                )
            # Export operations as bounded scalar attributes.  Some OTLP /
            # Langfuse paths stringify and truncate long array attributes,
            # which makes a causal replay silently parse individual
            # characters.  Indexed scalars remain lossless and auditable.
            for index, operation in enumerate(revision_row["operations"][:128]):
                attributes[f"globex.resource.revision_operation.{index}"] = operation
            for source, target in (
                ("query_mode", "globex.resource.query_mode"),
                ("information_need_count", "globex.resource.information_need_count"),
                ("known_operation_count", "globex.resource.known_operation_count"),
                ("operation", "globex.resource.completed_operation"),
                ("actual_call_id", "globex.resource.actual_call_id"),
                ("matched_future_call_id", "globex.resource.matched_future_call_id"),
                ("identity_match_quality", "globex.resource.identity_match_quality"),
                ("flow_id", "globex.resource.flow_id"),
                ("tool_names", "globex.resource.emitted_tool_names"),
                ("source_role", "globex.resource.tool_call_source_role"),
                ("main_plan_prediction_reasons", "globex.resource.main_plan_prediction_reasons"),
            ):
                value = known_information.get(source)
                if value not in (None, "", [], ()):
                    attributes[target] = tuple(value) if isinstance(value, list) else value
            with trace.get_tracer(__name__).start_as_current_span(
                "resource.plan_revision", attributes=attributes,
                record_exception=False, set_status_on_exception=False,
            ):
                pass
        except Exception:
            # Observability must never affect the business request.
            pass

    async def observe_completed_operation(
        self, operation: str, *, logical_call_id: str | None = None,
        result_typed: bool = False,
    ) -> None:
        """Reconcile observed work with the shadow plan; never affects execution."""
        async with self._lock:
            self._observed_operations.append(operation)
            from .operation import current_execution
            identity = current_execution()
            matched = self.future_plan.complete_observed(
                operation, actual_call_id=None if result_typed else logical_call_id,
                flow_id=identity.flow_id, tool_call_id=identity.tool_call_id,
            )
            if operation == "main.final":
                # A final answer closes the request; unused predicted main calls
                # are no longer future work.
                self.future_plan.discard_unstarted(
                    operation_prefix="main.", reason="request_finalized",
                    flow_id=identity.flow_id,
                )
            elif operation in {"search.final", "trade.final"}:
                # The final call is the alternative to the continuation plan
                # predicted after the last tool-result batch.  Cancel one only;
                # other concurrent Search Agents may still be active.
                self.future_plan.discard_unstarted(
                    operation_prefix=operation.replace(".final", ".plan"),
                    reason="child_flow_finalized", flow_id=identity.flow_id,
                )
            self.future_plan.validate(self.reservations)
            self.prediction = self.predictor.classify_route(
                self._observed_operations, query_mode=self._query_mode,
            )
            self._refresh_planned_budget("operation_completed")
            self._record_plan_revision("operation_completed", {
                "operation": operation,
                "actual_call_id": logical_call_id or "",
                "matched_future_call_id": matched or "",
                "identity_match_quality": ("EXACT_BOUND" if matched and logical_call_id and not result_typed
                                           else "SCOPED_OPERATION" if matched else "UNMATCHED"),
                "flow_id": identity.flow_id,
                "query_mode": self._query_mode,
                "known_operation_count": len(self._observed_operations),
            })

    async def observe_query_plan(self, mode: str, need_ids: list[str]) -> None:
        async with self._lock:
            self._query_mode = mode.upper()
            from .operation import current_execution
            identity = current_execution()
            # Replace the causally predicted generic classifier with the now
            # observed concrete result; its actual usage is already in ledger.
            self.future_plan.supersede_matching(
                operation_prefix="query_processor.classify",
                reason=f"placeholder_replaced_by_{self._query_mode.casefold()}",
                flow_id=identity.flow_id, tool_call_id=identity.tool_call_id,
            )
            if mode.upper() == "DECOMPOSE":
                self.predictor.add_decompose_followups(
                    self.future_plan, self.request_id, need_ids,
                    flow_id=identity.flow_id, tool_call_id=identity.tool_call_id,
                )
            self.prediction = self.predictor.classify_route(
                self._observed_operations, query_mode=self._query_mode,
            )
            self._route_after_query_processor = self.prediction.route
            self._refresh_planned_budget("query_processor_result")
            self._record_runtime(RuntimeObservation(
                event_id=f"query-plan:{identity.flow_id}:{identity.tool_call_id}:{self.future_plan.revision}",
                flow_id=identity.flow_id, operation=f"query_processor.{mode.casefold()}",
                agent="query_processor", tool="category_insight_tool",
                required_need_ids=tuple(f"{identity.tool_call_id}:{need}" for need in need_ids),
            ))
            self._record_plan_revision("query_processor_result", {
                "query_mode": self._query_mode,
                "information_need_count": len(need_ids),
                "information_need_ids": list(need_ids),
                "known_operation_count": len(self._observed_operations),
            })

    async def observe_tool_calls(
        self, tool_names: list[str], *, source_role: str = "main",
        continuation_signals: tuple[str, ...] = (),
        tool_calls: list[dict] | None = None,
    ) -> None:
        """Revise the shadow plan after the model has emitted concrete tools."""
        from .operation import current_execution
        async with self._lock:
            sequence = sum(item["trigger"] == "tool_calls_emitted" for item in self._revision_history) + 1
            self.predictor.add_tool_followups(
                self.future_plan, self.request_id, tool_names, sequence=sequence,
                source_role=source_role, continuation_signals=continuation_signals,
                tool_calls=tool_calls,
                flow_id=current_execution().flow_id,
            )
            self.prediction = self.predictor.classify_route(
                self._observed_operations, query_mode=self._query_mode,
            )
            self._refresh_planned_budget("tool_calls_emitted")
            self._record_plan_revision("tool_calls_emitted", {
                # Duplicate names are meaningful: parallel tool calls create
                # independent downstream resource operations.
                "tool_names": sorted(tool_names),
                "source_role": source_role,
                "query_mode": self._query_mode,
                "known_operation_count": len(self._observed_operations),
                "main_plan_prediction_reasons": list(continuation_signals),
            })

    async def observe_runtime(self, observation: RuntimeObservation) -> None:
        """Diagnostic only: never revises work, reservations or policy."""
        async with self._lock:
            self._record_runtime(observation)

    def _record_runtime(self, observation: RuntimeObservation) -> None:
        row = self.runtime.observe(observation, route=self.prediction.route)
        if row is None:
            return
        row["forecast"] = self.continuation.predict(row["after"])
        try:
            from opentelemetry import trace
            with trace.get_tracer(__name__).start_as_current_span(
                "resource.runtime_progress", attributes={
                    **runtime_trace_fields(row),
                    "langfuse.observation.type": "span",
                    "globex.trace.stage": "runtime_progress",
                    "globex.resource.flow_id": observation.flow_id,
                    "globex.resource.logical_call_id": observation.event_id,
                    "globex.resource.shadow_only": True,
                    "globex.resource.progress_class": row["progress_class"],
                    "globex.resource.refinement_class": row["refinement_class"],
                    "globex.resource.zero_progress_streak": row["after"]["zero_progress_streak"],
                    "globex.resource.loop_risk": row["after"]["loop_risk"],
                    "globex.resource.runtime_sequence": row["after"]["sequence"],
                    "globex.resource.continuation_forecast": json.dumps(row["forecast"], ensure_ascii=False, separators=(",", ":")),
                    "globex.resource.next_prediction_confidence": row["forecast"]["next_operation"]["confidence"],
                    "globex.resource.loop_prediction_confidence": row["forecast"]["remaining_rounds"]["confidence"],
                    "globex.resource.runtime_state": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                    "langfuse.observation.output": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                }, record_exception=False, set_status_on_exception=False,
            ):
                pass
        except Exception:
            pass

    async def observe_started_operation(self, operation: str, *, logical_call_id: str | None = None) -> str | None:
        """Consume a predicted future node when its upstream call starts."""
        async with self._lock:
            from .operation import current_execution, current_operation
            identity = current_execution()
            operation_context = current_operation()
            logical_id = self.future_plan.start_observed(
                operation, actual_call_id=logical_call_id,
                flow_id=identity.flow_id, tool_call_id=identity.tool_call_id,
                information_need_id=operation_context.information_need_id if operation_context else None,
            )
            if logical_id is None:
                return None
            self._refresh_planned_budget("operation_started")
            self._record_plan_revision("operation_started", {
                "operation": operation,
                "known_operation_count": len(self._observed_operations),
            })
            return logical_id

    async def mark_reserved_operation_started(self, logical_call_id: str) -> None:
        """Transition an explicitly reserved operation immediately before upstream I/O."""
        async with self._lock:
            operation = self.future_plan.get(logical_call_id)
            if operation is None:
                raise KeyError(logical_call_id)
            self.future_plan.mark_started(logical_call_id)
            self._refresh_planned_budget("operation_started")
            self._record_plan_revision("operation_started", {
                "operation": operation.operation,
                "known_operation_count": len(self._observed_operations),
            })

    def _refresh_planned_budget(self, reason: str) -> None:
        """Keep planned budget dynamic; the 80K cap remains an independent ceiling."""
        previous_budget = self.planned_budget.chat_token_limit or 0
        previous_inputs = self._last_budget_inputs
        planned = self.predictor.planned_estimate(self.future_plan).scale(
            self._planning_safety_factor,
        )
        self.planned_budget = BudgetEnvelope(chat_token_limit=planned.chat_total_tokens)
        current_inputs = self._budget_inputs()
        new_budget = self.planned_budget.chat_token_limit or 0
        unchanged_reason = None
        if new_budget == previous_budget:
            if current_inputs["raw_planned"] == previous_inputs["raw_planned"]:
                unchanged_reason = BudgetUnchangedReason.SAME_ESTIMATED_COST.value
            elif round(current_inputs["raw_planned"] * self._planning_safety_factor) == round(
                previous_inputs["raw_planned"] * self._planning_safety_factor,
            ):
                unchanged_reason = BudgetUnchangedReason.ROUNDING.value
            else:
                unchanged_reason = BudgetUnchangedReason.OTHER_EXPLAINED.value
        self._budget_revision = {
            "budget_recomputed": True,
            "previous_planned_budget": previous_budget,
            "new_planned_budget": new_budget,
            "previous_projected_total": previous_inputs["projected_total"],
            "new_projected_total": current_inputs["projected_total"],
            "previous_predicted_unreserved": previous_inputs["predicted_unreserved"],
            "new_predicted_unreserved": current_inputs["predicted_unreserved"],
            "protected_future": current_inputs["protected_future"],
            "unchanged_reason": unchanged_reason,
            "recompute_reason": reason,
        }
        self._last_budget_inputs = current_inputs

    def _budget_inputs(self) -> dict[str, int]:
        protected = self.future_plan.protected_future().chat_total_tokens
        predicted = self.future_plan.predicted_unreserved().chat_total_tokens
        used = self.ledger.used().chat_total_tokens
        active = self.reservations.active_reserved().chat_total_tokens
        inflight = sum(item.estimate.chat_total_tokens for item in self.future_plan.operations()
                       if item.state.value == "started" and item.active_reservation_id is None)
        return {
            "raw_planned": protected + predicted,
            "protected_future": protected,
            "predicted_unreserved": predicted,
            "projected_total": used + active + protected + predicted + inflight,
        }

    def _emit_pending_future_transitions(self) -> None:
        transitions = self.future_plan.pop_transitions()
        if not transitions:
            return
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer(__name__)
            for item in transitions:
                event_name = (
                    "future_operation_added"
                    if item.previous_state is None and item.new_state == "planned"
                    else f"future_operation_{item.new_state}"
                )
                attributes: dict[str, object] = {
                    "langfuse.observation.type": "span",
                    "globex.trace.stage": "future_operation_transition",
                    "globex.resource.lifecycle_event": event_name,
                    "globex.resource.logical_call_id": item.logical_call_id,
                    "globex.resource.operation": item.operation,
                    "globex.resource.flow_id": item.flow_id,
                    "globex.resource.tool_call_id": item.tool_call_id or "",
                    "globex.resource.plan_revision": item.plan_revision,
                    "globex.resource.transition_reason": item.transition_reason,
                    "globex.resource.new_state": item.new_state,
                }
                if item.previous_bucket is not None:
                    attributes["globex.resource.previous_bucket"] = item.previous_bucket
                if item.new_bucket is not None:
                    attributes["globex.resource.new_bucket"] = item.new_bucket
                if item.previous_state is not None:
                    attributes["globex.resource.previous_state"] = item.previous_state
                with tracer.start_as_current_span(
                    event_name, attributes=attributes,
                    record_exception=False, set_status_on_exception=False,
                ):
                    pass
        except Exception:
            pass

    def evaluate_current(self):
        return self.policy.evaluate(
            self.snapshot().projected,
            planned_budget=self.planned_budget,
            absolute_hard_cap=self.absolute_hard_cap,
        )

    def accounting_reconciliation(
        self, *, provider_actual_chat_tokens: int | None = None,
    ) -> dict[str, object]:
        """Validate ledger/reservation/plan invariants without changing state.

        ``provider_actual_chat_tokens`` is supplied by offline Trace replay,
        where generation usage is an independent source. Online, the ledger
        total and leak/duplicate checks are still emitted at request end.
        """
        errors: list[str] = []
        try:
            self.future_plan.validate(self.reservations)
        except AssertionError as error:
            errors.append(f"plan_reservation_invariant:{error}")
        active_count = len(self.reservations.active())
        if active_count:
            errors.append("reservation_leak")
        entries = self.ledger.entries()
        attempt_keys = [(item.logical_call_id, item.attempt) for item in entries]
        duplicate_count = len(attempt_keys) - len(set(attempt_keys))
        if duplicate_count:
            errors.append("duplicate_operation_accounting")
        ledger_total = self.ledger.used().chat_total_tokens
        difference = None
        if provider_actual_chat_tokens is not None:
            difference = ledger_total - provider_actual_chat_tokens
            if difference:
                sources = {item.usage_source for item in entries}
                if not sources & {"estimated_missing_usage", "estimated_timeout"}:
                    errors.append("unexplained_usage_difference")
        return {
            "ok": not errors,
            "errors": errors,
            "ledger_chat_total": ledger_total,
            "provider_actual_chat_total": provider_actual_chat_tokens,
            "difference": difference,
            "active_reservation_count": active_count,
            "duplicate_attempt_count": duplicate_count,
            "usage_missing_count": sum(item.usage_source == "estimated_missing_usage" for item in entries),
            "timeout_estimated_count": sum(item.usage_source == "estimated_timeout" for item in entries),
        }

    def snapshot(self) -> GovernorSnapshot:
        protected = self.future_plan.protected_future()
        predicted = self.future_plan.predicted_unreserved()
        used = self.ledger.used()
        active = self.reservations.active_reserved()
        projected = used.plus(active).plus(protected).plus(predicted)
        return GovernorSnapshot(
            request_id=self.request_id,
            plan_revision=self.future_plan.revision,
            used=used,
            active_reserved=active,
            protected_future=protected,
            predicted_unreserved=predicted,
            projected=projected,
            planned_budget=self.planned_budget,
            absolute_hard_cap=self.absolute_hard_cap,
            shadow_only=self.shadow_only,
        )

    def _projected(self) -> ResourceEstimate:
        snapshot = self.snapshot()
        return snapshot.projected


_current_governor: ContextVar[RequestResourceGovernor | None] = ContextVar(
    "globex_request_resource_governor", default=None,
)


def begin_shadow_request(
    request_id: str, model: str, *, enabled: bool = True,
    planning_safety_factor: float = 1.20, absolute_chat_hard_cap: int = 80_000,
) -> tuple[RequestResourceGovernor | None, Token]:
    governor = (
        RequestResourceGovernor(
            request_id, model, shadow_only=True,
            planning_safety_factor=planning_safety_factor,
            absolute_chat_hard_cap=absolute_chat_hard_cap,
        ) if enabled else None
    )
    return governor, _current_governor.set(governor)


def current_governor() -> RequestResourceGovernor | None:
    return _current_governor.get()


def end_shadow_request(token: Token) -> None:
    _current_governor.reset(token)

