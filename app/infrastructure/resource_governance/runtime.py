"""Causal, content-free execution diagnostics. Never a policy input.

Retrieved evidence is NOT sufficient/relevant evidence. Missing annotations
remain unknown; this module does not infer relevance from scores or hit counts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class RuntimeObservation:
    event_id: str
    flow_id: str
    operation: str
    agent: str = "unknown"
    tool: str | None = None
    need_id: str | None = None
    query_hash: str | None = None
    constraint_signature: str | None = None
    evidence_ids: tuple[str, ...] = ()
    required_need_ids: tuple[str, ...] = ()
    covered_need_ids: tuple[str, ...] = ()
    verified_required_evidence_ids: tuple[str, ...] = ()
    valid_action_id: str | None = None
    evidence_sufficient: bool | None = None
    pending_mandatory_action: bool | None = None
    context_tokens: int | None = None
    success: bool | None = None
    freshness_required: bool | None = None
    transaction_advanced: bool = False
    necessary_refinement: bool | None = None
    outcome_fully_observed: bool = False
    action_for_required_need: bool = False


@dataclass(frozen=True)
class RuntimeState:
    flow_id: str
    agent_role: str = "unknown"
    sequence: int = 0
    last_operation: str = "unknown"
    current_route: str = "unknown"
    required_need_total: int = 0
    required_need_covered: int = 0
    required_need_remaining: int = 0
    # Registered needs may be only a subset of the user's intent.
    need_scope_complete: bool = False
    optional_need_remaining: int | None = None
    evidence_sufficient: bool | None = None
    new_evidence_count: int = 0
    new_required_evidence_count: int = 0
    main_plan_round: int = 0
    search_plan_round: int = 0
    last_agent: str = "unknown"
    last_tool_type: str | None = None
    last_information_need_id: str | None = None
    last_query_hash: str | None = None
    last_constraint_signature: str | None = None
    current_context_tokens: int | None = None
    last_progress_class: str = "UNKNOWN"
    zero_progress_streak: int = 0
    loop_risk: str = "UNKNOWN"
    pending_mandatory_action: bool | None = None


@dataclass(frozen=True)
class ProgressResult:
    progress_class: str
    reason: str
    refinement_class: str = "NOT_APPLICABLE"


class ProgressDetector:
    @staticmethod
    def detect(*, observation: RuntimeObservation, new_required: int,
               newly_covered: int, new_evidence: int, new_action: bool,
               new_need_count: int, sufficiency_advanced: bool,
               previous_search: tuple | None) -> ProgressResult:
        if observation.success is False:
            return ProgressResult("UNKNOWN", "operation_failed")
        if newly_covered or new_required or observation.transaction_advanced or sufficiency_advanced:
            return ProgressResult("HIGH_PROGRESS", "verified_required_or_transaction_progress",
                                  "USEFUL_REFINEMENT" if previous_search else "NOT_APPLICABLE")
        if new_need_count:
            return ProgressResult("MEDIUM_PROGRESS", "new_registered_required_need")
        if new_action:
            return ProgressResult("MEDIUM_PROGRESS" if observation.action_for_required_need else "LOW_PROGRESS",
                                  "new_permitted_action_requiredness_unverified"
                                  if not observation.action_for_required_need else "new_required_action")
        fingerprint = (observation.query_hash, observation.constraint_signature)
        if previous_search is not None and observation.success is True:
            if (fingerprint == previous_search and all(fingerprint)
                    and observation.freshness_required is False and not new_evidence):
                return ProgressResult("ZERO_PROGRESS", "duplicate_search_no_new_evidence", "EXACT_DUPLICATE")
            if fingerprint != previous_search and not new_evidence:
                if observation.necessary_refinement is True and observation.evidence_sufficient is False:
                    return ProgressResult("LOW_PROGRESS", "necessary_search_no_result", "NECESSARY_BUT_NO_RESULT")
                if observation.outcome_fully_observed:
                    return ProgressResult("ZERO_PROGRESS", "refinement_no_observed_state_delta", "LOW_VALUE_REFINEMENT")
                return ProgressResult("UNKNOWN", "refinement_value_unverified", "UNKNOWN")
        if new_evidence:
            return ProgressResult("LOW_PROGRESS", "new_retrieved_evidence_relevance_unknown",
                                  "UNKNOWN" if previous_search else "NOT_APPLICABLE")
        if observation.outcome_fully_observed and observation.success is True:
            return ProgressResult("ZERO_PROGRESS", "fully_observed_no_state_delta")
        return ProgressResult("UNKNOWN", "insufficient_progress_observability")


@dataclass
class _Flow:
    state: RuntimeState
    needs: set[str] = field(default_factory=set)
    covered: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    required_evidence: set[str] = field(default_factory=set)
    actions: set[str] = field(default_factory=set)
    searches: dict[tuple[str | None, str | None], tuple] = field(default_factory=dict)
    streaks: dict[tuple[str | None, str | None], int] = field(default_factory=dict)


class RuntimeStateStore:
    """Request-owned store; callers serialize mutation with Governor's lock."""
    def __init__(self):
        self._flows: dict[str, _Flow] = {}
        self._seen: set[str] = set()
        self.history: list[dict] = []

    def observe(self, observation: RuntimeObservation, *, route: str) -> dict | None:
        if observation.event_id in self._seen:
            return None
        self._seen.add(observation.event_id)
        flow = self._flows.setdefault(observation.flow_id, _Flow(RuntimeState(observation.flow_id)))
        before = flow.state
        # Only explicit coverage of a previously registered/current need counts.
        new_needs = set(observation.required_need_ids) - flow.needs if observation.success is not False else set()
        flow.needs.update(new_needs)
        newly_covered = ((set(observation.covered_need_ids) & flow.needs) - flow.covered
                         if observation.success is not False else set())
        new_required = (set(observation.verified_required_evidence_ids) - flow.required_evidence
                        if observation.success is not False else set())
        new_evidence = (set(observation.evidence_ids) - flow.evidence
                        if observation.success is not False else set())
        new_action = bool(observation.success is not False and observation.valid_action_id
                          and observation.valid_action_id not in flow.actions)
        search_key = (observation.tool, observation.need_id)
        previous_search = flow.searches.get(search_key) if observation.query_hash else None
        progress = ProgressDetector.detect(
            observation=observation, new_required=len(new_required), newly_covered=len(newly_covered),
            new_evidence=len(new_evidence), new_action=new_action, previous_search=previous_search,
            new_need_count=len(new_needs),
            sufficiency_advanced=observation.evidence_sufficient is True and before.evidence_sufficient is not True,
        )
        flow.covered.update(newly_covered)
        flow.evidence.update(new_evidence)
        flow.required_evidence.update(new_required)
        if new_action:
            flow.actions.add(observation.valid_action_id)
        if observation.query_hash and observation.success is True:
            flow.searches[search_key] = (observation.query_hash, observation.constraint_signature)
        streak = before.zero_progress_streak
        if observation.query_hash and observation.success is True:
            # Interleaved model/action events are not evidence that a retrieval
            # loop ended. Keep streaks independent for each tool/need stream.
            streak = flow.streaks.get(search_key, 0)
            if progress.progress_class == "ZERO_PROGRESS":
                streak += 1
            elif progress.progress_class != "UNKNOWN":
                streak = 0
            flow.streaks[search_key] = streak
        state = RuntimeState(
            flow_id=observation.flow_id, sequence=before.sequence + 1,
            agent_role=observation.agent if observation.agent in {"main", "search", "trade"} else before.agent_role,
            last_operation=observation.operation, current_route=route,
            required_need_total=len(flow.needs), required_need_covered=len(flow.covered),
            required_need_remaining=len(flow.needs - flow.covered),
            evidence_sufficient=(observation.evidence_sufficient if observation.query_hash
                                 or observation.evidence_sufficient is not None else before.evidence_sufficient),
            new_evidence_count=len(new_evidence), new_required_evidence_count=len(new_required),
            main_plan_round=before.main_plan_round + (observation.operation == "main.plan"),
            search_plan_round=before.search_plan_round + (observation.operation == "search.plan"),
            last_agent=observation.agent, last_tool_type=observation.tool,
            last_information_need_id=observation.need_id, last_query_hash=observation.query_hash,
            last_constraint_signature=observation.constraint_signature,
            current_context_tokens=observation.context_tokens if observation.context_tokens is not None else before.current_context_tokens,
            last_progress_class=progress.progress_class, zero_progress_streak=streak,
            loop_risk="HIGH" if streak >= 2 else "UNKNOWN",
            pending_mandatory_action=(observation.pending_mandatory_action
                                      if observation.pending_mandatory_action is not None
                                      else before.pending_mandatory_action),
        )
        flow.state = state
        row = {"event_id": observation.event_id, "timestamp": datetime.now(timezone.utc).isoformat(),
               "before": asdict(before), "after": asdict(state), **asdict(progress),
               "shadow_only": True, "action_driving": False}
        self.history.append(row)
        return row
