"""Dimension-aware resource policy.

Phase 0-2 enforces no production action.  ``would_action`` records what a
future enforcing policy would do; cost and latency remain observation-only.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import BudgetEnvelope, ReservationDecisionCode, ResourceEstimate


@dataclass(frozen=True)
class DimensionChecks:
    chat_ok: bool | None
    cost_ok: bool | None
    latency_ok: bool | None
    api_calls_ok: bool | None


@dataclass(frozen=True)
class PolicyEvaluation:
    code: ReservationDecisionCode
    would_action: str
    reason: str
    checks: DimensionChecks
    profile_confidence: str = "bootstrap"
    action_eligible: bool = False
    action_scope: str = "shadow_only"


class ResourcePolicy:
    """Compare each resource dimension to its corresponding envelope field."""

    def evaluate(
        self, projected: ResourceEstimate, *, planned_budget: BudgetEnvelope,
        absolute_hard_cap: BudgetEnvelope, profile_confidence: str = "bootstrap",
        mandatory_operation: bool = False,
    ) -> PolicyEvaluation:
        confidence = profile_confidence.casefold()
        action_scope = (
            "optional_or_speculative_only" if confidence in {"high", "medium"}
            else "shadow_only"
        )
        # Even after a future Phase-3 gate, the first action-driving rollout is
        # optional/speculative only. Mandatory/Main Final stays protected.
        action_eligible = confidence in {"high", "medium"} and not mandatory_operation
        hard_chat_ok = self._le(projected.chat_total_tokens, absolute_hard_cap.chat_token_limit)
        planned_chat_ok = self._le(projected.chat_total_tokens, planned_budget.chat_token_limit)
        checks = DimensionChecks(
            chat_ok=hard_chat_ok,
            cost_ok=self._le_optional(projected.monetary_cost, absolute_hard_cap.monetary_cost_limit),
            latency_ok=self._le(projected.latency_ms, absolute_hard_cap.latency_deadline_ms),
            api_calls_ok=self._le(projected.api_calls, absolute_hard_cap.api_call_limit),
        )
        # First enforcement dimension is chat token only. Cost, latency and API
        # checks are retained for observability but cannot reject in this phase.
        if hard_chat_ok is False:
            return PolicyEvaluation(
                ReservationDecisionCode.SHADOW_WOULD_REJECT,
                "reject", "chat_absolute_hard_cap_exceeded", checks,
                profile_confidence, action_eligible, action_scope,
            )
        if planned_chat_ok is False:
            return PolicyEvaluation(
                ReservationDecisionCode.SHADOW_WOULD_DEGRADE,
                "degrade", "chat_planned_budget_exceeded", checks,
                profile_confidence, action_eligible, action_scope,
            )
        return PolicyEvaluation(
            ReservationDecisionCode.ALLOW, "allow", "within_planned_budget", checks,
            profile_confidence, action_eligible, action_scope,
        )

    @staticmethod
    def _le(value: int, limit: int | None) -> bool | None:
        return None if limit is None else value <= limit

    @staticmethod
    def _le_optional(value, limit) -> bool | None:
        return None if value is None or limit is None else value <= limit

