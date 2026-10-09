"""Context safety and counterfactual compaction ROI accounting."""
from __future__ import annotations

from dataclasses import dataclass

from .estimator import TokenEstimator
from .models import CompactionBaseline, ContextScope, ContextSnapshot


@dataclass(frozen=True)
class CounterfactualRoiObservation:
    actual_input_tokens: int
    counterfactual_input_tokens: int
    counterfactual_realized_saving: int
    counterfactual_realized_roi: float


class ContextGovernorAdapter:
    DEFAULT_OUTPUT_RESERVES = {
        "main.final": 8192,
        "main.plan": 2048,
        "search.plan": 2048,
        "search.final": 4096,
        "trade.plan": 2048,
        "trade.final": 4096,
        "query_processor.direct": 1000,
        "query_processor.decompose": 1000,
        "context.summary": 4096,
    }

    def __init__(
        self, estimator: TokenEstimator | None = None, *,
        soft_target_tokens: int = 48_000, high_pressure_tokens: int = 60_000,
        protocol_safety_margin: int = 6_400,
    ) -> None:
        self.estimator = estimator or TokenEstimator()
        self.soft_target_tokens = soft_target_tokens
        self.high_pressure_tokens = high_pressure_tokens
        self.protocol_safety_margin = protocol_safety_margin
        self._baselines: dict[ContextScope, CompactionBaseline] = {}
        self._savings: dict[ContextScope, int] = {}

    def hard_safety_limit(
        self, *, model_context_window: int, operation: str, context_scope: ContextScope,
        operation_output_reserve: int | None = None, protocol_safety_margin: int | None = None,
    ) -> int:
        del context_scope  # retained in the contract because profiles are scope-specific
        reserve = operation_output_reserve
        if reserve is None:
            reserve = self.DEFAULT_OUTPUT_RESERVES.get(operation, 4096)
        margin = self.protocol_safety_margin if protocol_safety_margin is None else protocol_safety_margin
        return max(0, model_context_window - reserve - margin)

    def save_baseline(self, baseline: CompactionBaseline) -> None:
        self._baselines[baseline.scope] = baseline
        self._savings[baseline.scope] = 0

    def snapshot(
        self, *, scope: ContextScope, context_revision: str,
        estimated_input_tokens: int, reclaimable_tokens: int,
        model_context_window: int, operation: str,
    ) -> ContextSnapshot:
        return ContextSnapshot(
            scope=scope,
            context_revision=context_revision,
            estimated_input_tokens=max(0, estimated_input_tokens),
            reclaimable_tokens=max(0, reclaimable_tokens),
            soft_target_tokens=self.soft_target_tokens,
            high_pressure_tokens=self.high_pressure_tokens,
            operation_hard_safety_tokens=self.hard_safety_limit(
                model_context_window=model_context_window,
                operation=operation,
                context_scope=scope,
            ),
        )

    def baseline(self, scope: ContextScope) -> CompactionBaseline | None:
        return self._baselines.get(scope)

    def observe_post_compaction_call(
        self, scope: ContextScope, *, actual_input_tokens: int,
    ) -> CounterfactualRoiObservation | None:
        baseline = self._baselines.get(scope)
        if baseline is None:
            return None
        counterfactual = self.estimator.estimate_counterfactual_input(
            actual_input_tokens=actual_input_tokens,
            old_context_tokens=baseline.old_context_tokens,
            compacted_context_tokens=baseline.compacted_context_tokens,
        )
        avoided = max(counterfactual - actual_input_tokens, 0)
        self._savings[scope] = self._savings.get(scope, 0) + avoided
        return CounterfactualRoiObservation(
            actual_input_tokens=actual_input_tokens,
            counterfactual_input_tokens=counterfactual,
            counterfactual_realized_saving=self._savings[scope],
            counterfactual_realized_roi=(
                self._savings[scope] / max(baseline.actual_summary_cost, 1)
            ),
        )

