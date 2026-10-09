"""Frozen, shadow-only next-completion and remaining-round diagnostics.

No online fitting, policy access, or FutureWorkPlan mutation. Outcomes are
same-flow observable completions, not globally ordered HTTP invocations.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math

VERSION = "continuation-v1"
TERMINALS = {"main.final", "search.final", "trade.final"}


def state_keys(state: dict) -> list[tuple]:
    unresolved = ("yes" if state.get("required_need_remaining", 0) > 0
                  else "no" if state.get("need_scope_complete") else "unknown")
    sufficient = str(state.get("evidence_sufficient")).lower()
    operation = state.get("last_operation", "unknown")
    role = state.get("agent_role", state.get("last_agent", "unknown"))
    return [
        (role, operation, unresolved, sufficient, state.get("current_route", "unknown")),
        (role, operation, unresolved, sufficient), (role, operation, unresolved), (role, operation),
    ]


def loop_keys(state: dict) -> list[tuple]:
    # Progress is an execution feature, never a normative probability penalty.
    # Round/context features remain coarsely bucketed to limit fragmentation.
    round_bucket = min(3, int(state.get("main_plan_round", 0)) + int(state.get("search_plan_round", 0)))
    return [("loop", *state_keys(state)[0], state.get("last_progress_class", "UNKNOWN"),
             min(2, int(state.get("zero_progress_streak", 0))), round_bucket,
             bool(state.get("new_evidence_count", 0))),
            *[("loop", *key) for key in state_keys(state)]]


def rule_distribution(state: dict) -> dict[str, float]:
    operation = state.get("last_operation", "unknown")
    if operation in TERMINALS:
        return {"END": 1.0}
    role = state.get("agent_role") or state.get("last_agent")
    if role not in {"main", "search", "trade"}:
        role = "main" if state.get("flow_id") == "main" else None
    if role is None:
        return {"OTHER": 1.0}
    # These are declared bootstrap priors, not measured continuation rates.
    if operation == "tool.permitted":
        tool = state.get("last_tool_type")
        return {f"tool.{tool}.result": 0.8, "tool.failed": 0.1, "OTHER": 0.1}
    if state.get("evidence_sufficient") is False or state.get("required_need_remaining", 0) > 0:
        return {f"{role}.plan": 0.7, f"{role}.final": 0.2, "OTHER": 0.1}
    return {f"{role}.plan": 0.45, f"{role}.final": 0.45, "OTHER": 0.1}


@dataclass(frozen=True)
class TrainingSample:
    trace_id: str
    group_id: str
    flow_id: str
    sequence: int
    state: dict
    next_operation: str | None
    remaining_main_plan_rounds: int | None
    remaining_search_plan_rounds: int | None


def training_samples(requests: list[dict]) -> list[TrainingSample]:
    """Labels may use the future; features are ONLY the saved causal snapshot.

    Incomplete flows can label observed adjacent transitions, but never zero
    remaining rounds or END. Unknown/censored tails are not training targets.
    """
    samples = []
    for request in requests:
        trace_id = str(request.get("trace_id") or "")
        if not trace_id:
            raise ValueError("trace_id required for split isolation")
        group = str(request.get("case_id") or request.get("group_id") or trace_id)
        flows = defaultdict(list)
        for row in request.get("runtime_progress_events") or []:
            state = row.get("after")
            if isinstance(state, dict) and state.get("flow_id") is not None:
                flows[str(state["flow_id"])].append(state)
        for flow_id, states in flows.items():
            states.sort(key=lambda state: int(state["sequence"]))
            sequences = [int(state["sequence"]) for state in states]
            if len(set(sequences)) != len(sequences):
                raise ValueError("duplicate flow sequence")
            if sequences != list(range(1, len(states) + 1)):
                # Partial export cannot establish next-event or remaining count.
                continue
            terminal_indices = [i for i, state in enumerate(states) if state.get("last_operation") in TERMINALS]
            if terminal_indices and terminal_indices != [len(states) - 1]:
                # Resumed/invalid lifecycle requires a fresh flow identity.
                continue
            complete = bool(terminal_indices)
            for index, state in enumerate(states):
                future = states[index + 1:]
                outcomes = [s for s in future if s.get("last_operation") != "tool.permitted"]
                next_operation = outcomes[0].get("last_operation") if outcomes else "END" if complete else None
                samples.append(TrainingSample(
                    trace_id, group, flow_id, int(state["sequence"]), dict(state), next_operation,
                    sum(s.get("last_operation") == "main.plan" for s in future) if complete else None,
                    sum(s.get("last_operation") == "search.plan" for s in future) if complete else None,
                ))
    return samples


class TransitionProfileStore:
    """Historical profile, deliberately capped at MEDIUM pending heldout gates."""
    def __init__(self):
        self.next_counts: dict[tuple, Counter] = defaultdict(Counter)
        self.loop_counts: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
        self.groups: set[str] = set()
        self.trace_ids: set[str] = set()
        self._seen: set[tuple] = set()
        self.support_groups: dict[tuple, set[str]] = defaultdict(set)
        self.sealed = False

    def fit(self, samples: list[TrainingSample]) -> None:
        if self.sealed:
            raise ValueError("loaded profile is immutable")
        identities = [(s.trace_id, s.flow_id, s.sequence) for s in samples]
        if len(set(identities)) != len(identities) or set(identities) & self._seen:
            raise ValueError("duplicate training sample")
        for sample in samples:
            identity = sample.trace_id, sample.flow_id, sample.sequence
            if identity in self._seen:
                raise ValueError("duplicate training sample")
            self._seen.add(identity)
            self.groups.add(sample.group_id)
            self.trace_ids.add(sample.trace_id)
            if sample.next_operation is not None:
                for key in state_keys(sample.state):
                    self.next_counts[key][sample.next_operation] += 1
                    self.support_groups[key].add(sample.group_id)
            if sample.remaining_main_plan_rounds is not None and sample.remaining_search_plan_rounds is not None:
                for key in loop_keys(sample.state):
                    self.loop_counts[key].append((sample.remaining_main_plan_rounds, sample.remaining_search_plan_rounds))
                    self.support_groups[key].add(sample.group_id)

    def _resolve(self, table, keys):
        # Prefer a supported detailed profile, then backed-off supported parent.
        # Only after all supported levels miss use sparse lowest-level profile.
        for level, key in enumerate(keys, 1):
            values = table.get(key)
            n = sum(values.values()) if isinstance(values, Counter) else len(values or [])
            groups = len(self.support_groups.get(key, ()))
            if n >= 30 and groups >= 10:
                return values, n, level, "MEDIUM", groups
        values = table.get(keys[-1])
        n = sum(values.values()) if isinstance(values, Counter) else len(values or [])
        return values, n, len(keys), "LOW" if n else "BOOTSTRAP", len(self.support_groups.get(keys[-1], ()))

    def write_json(self) -> dict:
        return {"version": VERSION, "source_groups": sorted(self.groups), "source_trace_ids": sorted(self.trace_ids),
                "support_groups": [{"key": list(key), "groups": sorted(value)} for key, value in self.support_groups.items()],
                "next": [{"key": list(key), "counts": dict(value)} for key, value in self.next_counts.items()],
                "loops": [{"key": list(key), "counts": value} for key, value in self.loop_counts.items()]}

    @classmethod
    def from_json(cls, payload: dict):
        if payload.get("version") != VERSION:
            raise ValueError("continuation profile version mismatch")
        store = cls()
        store.groups.update(payload["source_groups"])
        store.trace_ids.update(payload["source_trace_ids"])
        for row in payload["support_groups"]:
            store.support_groups[tuple(row["key"])].update(row["groups"])
        for row in payload["next"]:
            counts = row["counts"]
            if any(not isinstance(n, int) or n <= 0 for n in counts.values()):
                raise ValueError("invalid transition counts")
            store.next_counts[tuple(row["key"])] = Counter(counts)
        for row in payload["loops"]:
            if any(len(pair) != 2 or any(not isinstance(n, int) or n < 0 for n in pair) for pair in row["counts"]):
                raise ValueError("invalid loop counts")
            store.loop_counts[tuple(row["key"])] = [tuple(pair) for pair in row["counts"]]
        store.sealed = True
        return store


class NextOperationPredictor:
    def __init__(self, store: TransitionProfileStore):
        self.store = store

    def predict(self, state: dict) -> dict:
        prior = rule_distribution(state)
        if state.get("last_operation") in TERMINALS:
            return {"distribution": prior, "sample_count": 0, "confidence": "BOOTSTRAP",
                    "profile_level": "protocol_terminal", "scope": "same_flow_next_observable_completion"}
        counts, n, level, confidence, groups = self.store._resolve(self.store.next_counts, state_keys(state))
        # Five prior pseudo-observations prevent 1/1 becoming a 100% estimate.
        labels = set(prior) | set(counts or {})
        distribution = {label: ((counts or {}).get(label, 0) + 5 * prior.get(label, 0)) / (n + 5)
                        for label in sorted(labels)}
        return {"distribution": distribution, "sample_count": n, "confidence": confidence,
                "independent_group_count": groups,
                "profile_level": level, "scope": "same_flow_next_observable_completion"}


class LoopContinuationPredictor:
    def __init__(self, store: TransitionProfileStore):
        self.store = store

    def predict(self, state: dict) -> dict:
        values, n, level, confidence, groups = self.store._resolve(self.store.loop_counts, loop_keys(state))
        terminal = state.get("last_operation") in TERMINALS
        if terminal:
            values, n, level, confidence, groups = [], 0, "protocol_terminal", "BOOTSTRAP", 0
        result = {"sample_count": n, "confidence": confidence, "profile_level": level,
                  "independent_group_count": groups,
                  "scope": "same_flow_remaining_completed_plan_rounds", "progress_discount_applied": False}
        for index, role in enumerate(("main", "search")):
            counts = sorted(pair[index] for pair in values or [])
            # Sparse samples are diagnostic only, not a credible tail quantile.
            def quantile(p):
                return counts[max(0, math.ceil(len(counts) * p) - 1)]
            result[role] = {
                "expected": 0 if terminal else sum(counts) / n if n else None,
                "p50": 0 if terminal else quantile(.5) if n >= 30 and groups >= 10 else None,
                "p80": 0 if terminal else quantile(.8) if n >= 30 and groups >= 10 else None,
                "p95": 0 if terminal else quantile(.95) if n >= 100 and groups >= 30 else None,
                "probability_another": 0 if terminal else (sum(value > 0 for value in counts) + 1) / (n + 2) if n else None,
                "bucket": "NONE" if terminal else "EMPIRICAL" if n else "UNKNOWN",
            }
        return result


class ContinuationDiagnostics:
    def __init__(self, store: TransitionProfileStore | None = None):
        # Copy and seal to prevent concurrent calibration updates from changing
        # a request's predictions midway through its causal trace.
        self.store = TransitionProfileStore.from_json(store.write_json()) if store is not None else TransitionProfileStore()
        self.store.sealed = True
        self.next = NextOperationPredictor(self.store)
        self.loop = LoopContinuationPredictor(self.store)

    def predict(self, state: dict) -> dict:
        return {"version": VERSION, "shadow_only": True, "action_driving": False,
                "next_operation": self.next.predict(state), "remaining_rounds": self.loop.predict(state),
                "value_diagnostic": "PIVOT_CANDIDATE" if state.get("zero_progress_streak", 0) >= 2 else "UNKNOWN",
                "mandatory_probability_discount_applied": False}
