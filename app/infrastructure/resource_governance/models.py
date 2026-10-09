"""Value objects shared by resource-governance components.

``ResourceEstimate`` describes consumption. ``BudgetEnvelope`` describes
limits.  They intentionally have no total ordering: tokens, money and latency
are independent dimensions and must be evaluated separately by policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any


class ContextScope(str, Enum):
    MAIN = "main"
    SEARCH = "search"
    TRADE = "trade"
    QUERY_PROCESSOR = "query_processor"
    KNOWLEDGE = "knowledge"
    PRODUCT = "product"
    SYSTEM = "system"


class FutureBucket(str, Enum):
    PROTECTED_FUTURE = "protected_future"
    PREDICTED_UNRESERVED = "predicted_unreserved"
    ACTIVE_RESERVED = "active_reserved"


class FutureOperationState(str, Enum):
    """Lifecycle of one logical future operation.

    Buckets answer who currently owns the estimate; lifecycle state answers
    whether the work is still future work.  Keeping the two concepts separate
    prevents a completed shadow prediction from remaining in either future
    aggregate.
    """

    PLANNED = "planned"
    RESERVED = "reserved"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class BudgetUnchangedReason(str, Enum):
    """Explanations for a recomputed budget retaining its numeric value.

    Floor/cap values are part of the trace contract, not switches that enable
    those policies.  The current shadow planner applies neither floors nor a
    hard-cap clamp and therefore must not emit those explanations.
    """

    SAME_ESTIMATED_COST = "SAME_ESTIMATED_COST"
    SAME_COST_BUCKET = "SAME_COST_BUCKET"
    ROUNDING = "ROUNDING"
    SAFETY_FLOOR_DOMINATED = "SAFETY_FLOOR_DOMINATED"
    PROFILE_FLOOR_DOMINATED = "PROFILE_FLOOR_DOMINATED"
    HARD_CAP_CLAMPED = "HARD_CAP_CLAMPED"
    BOOTSTRAP_FLOOR = "BOOTSTRAP_FLOOR"
    OTHER_EXPLAINED = "OTHER_EXPLAINED"
    STALE_NOT_RECOMPUTED = "STALE_NOT_RECOMPUTED"


class InformationNeedRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    REDUNDANT = "redundant"


class ReservationStatus(str, Enum):
    ACTIVE = "active"
    SETTLED_ACTUAL = "settled_actual"
    SETTLED_ESTIMATED = "settled_estimated"
    TIMED_OUT_ESTIMATED = "timed_out_estimated"
    CANCELLED_ZERO = "cancelled_zero"


class ReservationDecisionCode(str, Enum):
    ALLOW = "allow"
    SHADOW_WOULD_DEGRADE = "shadow_would_degrade"
    SHADOW_WOULD_REJECT = "shadow_would_reject"
    REPLAN_REQUIRED = "replan_required"
    NOT_EXECUTABLE = "not_executable"


@dataclass(frozen=True)
class ResourceEstimate:
    chat_input_tokens: int = 0
    chat_output_tokens: int = 0
    embedding_tokens: int = 0
    rerank_tokens: int = 0
    api_calls: int = 0
    monetary_cost: Decimal | None = Decimal("0")
    latency_ms: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "chat_input_tokens", "chat_output_tokens", "embedding_tokens",
            "rerank_tokens", "api_calls", "latency_ms",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} 不能为负数")
        if self.monetary_cost is not None and self.monetary_cost < 0:
            raise ValueError("monetary_cost 不能为负数")

    @property
    def chat_total_tokens(self) -> int:
        return self.chat_input_tokens + self.chat_output_tokens

    def plus(self, other: "ResourceEstimate") -> "ResourceEstimate":
        cost = (
            self.monetary_cost + other.monetary_cost
            if self.monetary_cost is not None and other.monetary_cost is not None
            else None
        )
        return ResourceEstimate(
            chat_input_tokens=self.chat_input_tokens + other.chat_input_tokens,
            chat_output_tokens=self.chat_output_tokens + other.chat_output_tokens,
            embedding_tokens=self.embedding_tokens + other.embedding_tokens,
            rerank_tokens=self.rerank_tokens + other.rerank_tokens,
            api_calls=self.api_calls + other.api_calls,
            monetary_cost=cost,
            latency_ms=self.latency_ms + other.latency_ms,
        )

    def scale(self, factor: float) -> "ResourceEstimate":
        if factor < 0:
            raise ValueError("factor 不能为负数")
        cost = None if self.monetary_cost is None else self.monetary_cost * Decimal(str(factor))
        return ResourceEstimate(
            chat_input_tokens=round(self.chat_input_tokens * factor),
            chat_output_tokens=round(self.chat_output_tokens * factor),
            embedding_tokens=round(self.embedding_tokens * factor),
            rerank_tokens=round(self.rerank_tokens * factor),
            api_calls=round(self.api_calls * factor),
            monetary_cost=cost,
            latency_ms=round(self.latency_ms * factor),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "chat_input_tokens": self.chat_input_tokens,
            "chat_output_tokens": self.chat_output_tokens,
            "chat_total_tokens": self.chat_total_tokens,
            "embedding_tokens": self.embedding_tokens,
            "rerank_tokens": self.rerank_tokens,
            "api_calls": self.api_calls,
            "monetary_cost": str(self.monetary_cost) if self.monetary_cost is not None else None,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def sum(cls, values) -> "ResourceEstimate":
        total = cls()
        for value in values:
            total = total.plus(value)
        return total


@dataclass(frozen=True)
class BudgetEnvelope:
    chat_token_limit: int | None = None
    monetary_cost_limit: Decimal | None = None
    latency_deadline_ms: int | None = None
    api_call_limit: int | None = None

    def __post_init__(self) -> None:
        for value in (self.chat_token_limit, self.latency_deadline_ms, self.api_call_limit):
            if value is not None and value < 0:
                raise ValueError("预算上限不能为负数")
        if self.monetary_cost_limit is not None and self.monetary_cost_limit < 0:
            raise ValueError("monetary_cost_limit 不能为负数")


@dataclass(frozen=True)
class TokenEstimate:
    raw_tokens: int
    safe_tokens: int
    model: str
    method: str
    safety_factor: float
    confidence: str
    estimator_version: str
    calibration_samples: int = 0
    calibration_confidence: str = "bootstrap"
    calibration_profile_id: str = ""


@dataclass(frozen=True)
class FinalCallReserve:
    operation: str
    context_scope: ContextScope
    estimate: ResourceEstimate
    protected: bool = True


@dataclass(frozen=True)
class CompactionBaseline:
    scope: ContextScope
    old_context_revision: str
    new_context_revision: str
    old_context_tokens: int
    compacted_context_tokens: int
    removed_segment_refs: tuple[str, ...]
    estimator_version: str
    actual_summary_cost: int = 0

    def __post_init__(self) -> None:
        if self.old_context_tokens < 0 or self.compacted_context_tokens < 0:
            raise ValueError("context tokens 不能为负数")
        if self.actual_summary_cost < 0:
            raise ValueError("actual_summary_cost 不能为负数")


@dataclass(frozen=True)
class ContextSnapshot:
    scope: ContextScope
    context_revision: str
    estimated_input_tokens: int
    reclaimable_tokens: int
    soft_target_tokens: int
    high_pressure_tokens: int
    operation_hard_safety_tokens: int

    @property
    def pressure(self) -> str:
        if self.estimated_input_tokens > self.operation_hard_safety_tokens:
            return "hard_safety_exceeded"
        if self.estimated_input_tokens >= self.high_pressure_tokens:
            return "high"
        if self.estimated_input_tokens >= self.soft_target_tokens:
            return "soft"
        return "normal"


@dataclass(frozen=True)
class ReservationDecision:
    code: ReservationDecisionCode
    execution_allowed: bool
    would_action: str
    reason: str
    current_plan_revision: int
    reservation_id: str | None = None
    projected: ResourceEstimate | None = None

    @classmethod
    def replan_required(cls, current_revision: int) -> "ReservationDecision":
        return cls(
            code=ReservationDecisionCode.REPLAN_REQUIRED,
            execution_allowed=False,
            would_action="replan",
            reason="stale_plan_revision",
            current_plan_revision=current_revision,
        )
