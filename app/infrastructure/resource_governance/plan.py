"""Revisioned future-work graph and its invariants."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    FutureBucket, FutureOperationState, InformationNeedRequirement, ResourceEstimate,
)
from .reservations import ReservationManager


@dataclass
class InformationNeed:
    need_id: str
    requirement: InformationNeedRequirement
    covered: bool = False


@dataclass
class FutureOperation:
    logical_call_id: str
    operation: str
    estimate: ResourceEstimate
    bucket: FutureBucket
    priority: str = "normal"
    dependencies: tuple[str, ...] = ()
    information_need_id: str | None = None
    active_reservation_id: str | None = None
    state: FutureOperationState = FutureOperationState.PLANNED
    prediction_reason: str | None = None
    flow_id: str = "main"
    tool_call_id: str | None = None


@dataclass(frozen=True)
class FutureOperationTransition:
    logical_call_id: str
    operation: str
    plan_revision: int
    transition_reason: str
    previous_bucket: str | None
    new_bucket: str | None
    previous_state: str | None
    new_state: str
    flow_id: str = "main"
    tool_call_id: str | None = None


class FutureWorkPlan:
    """Sole authority for protected and predicted future work.

    ACTIVE_RESERVED is a state/link only. Its resource value is deliberately
    excluded from all plan aggregates; ReservationManager owns that number.
    """

    def __init__(self, *, revision: int = 0) -> None:
        self.revision = revision
        self._operations: dict[str, FutureOperation] = {}
        self._needs: dict[str, InformationNeed] = {}
        self._completed: set[str] = set()
        self._terminal: dict[str, FutureOperationState] = {}
        self._pending_transitions: list[FutureOperationTransition] = []
        self._observed_bindings: dict[str, str] = {}

    def operations(self) -> tuple[FutureOperation, ...]:
        return tuple(self._operations.values())

    def future_operations(self) -> tuple[FutureOperation, ...]:
        return tuple(
            operation for operation in self._operations.values()
            if operation.state == FutureOperationState.PLANNED
        )

    def get(self, logical_call_id: str) -> FutureOperation | None:
        return self._operations.get(logical_call_id)

    def terminal_state(self, logical_call_id: str) -> FutureOperationState | None:
        return self._terminal.get(logical_call_id)

    def add_need(self, need: InformationNeed) -> int:
        self._needs[need.need_id] = need
        return self._bump()

    def has_need(self, need_id: str) -> bool:
        return need_id in self._needs

    def mark_need_covered(self, need_id: str) -> int:
        if need_id in self._needs:
            self._needs[need_id].covered = True
            return self._bump()
        return self.revision

    def add(self, operation: FutureOperation) -> int:
        if operation.logical_call_id in self._operations or operation.logical_call_id in self._terminal:
            raise ValueError(f"重复 logical_call_id: {operation.logical_call_id}")
        if operation.bucket == FutureBucket.ACTIVE_RESERVED and not operation.active_reservation_id:
            raise ValueError("ACTIVE_RESERVED operation 必须携带 reservation id")
        if operation.bucket != FutureBucket.ACTIVE_RESERVED and operation.active_reservation_id:
            raise ValueError("非 ACTIVE_RESERVED operation 不得携带 reservation id")
        self._operations[operation.logical_call_id] = operation
        revision = self._bump()
        self._transition(
            operation, previous_state=None, previous_bucket=None,
            reason=operation.prediction_reason or "future_operation_added",
        )
        return revision

    def cancel(self, logical_call_id: str) -> int:
        operation = self._require(logical_call_id)
        if operation.bucket == FutureBucket.ACTIVE_RESERVED:
            raise ValueError("active operation 应先结算 reservation 再取消")
        return self._terminalize(
            operation, FutureOperationState.CANCELLED, reason="cancelled",
        )

    def supersede(self, logical_call_id: str, *, reason: str = "superseded") -> int:
        operation = self._require(logical_call_id)
        if operation.bucket == FutureBucket.ACTIVE_RESERVED:
            raise ValueError("active operation 不能被 supersede")
        return self._terminalize(operation, FutureOperationState.SUPERSEDED, reason=reason)

    def is_executable(self, logical_call_id: str) -> tuple[bool, str]:
        operation = self._operations.get(logical_call_id)
        if operation is None:
            return False, "operation_missing"
        if operation.state != FutureOperationState.PLANNED:
            return False, f"operation_{operation.state.value}"
        if operation.bucket == FutureBucket.ACTIVE_RESERVED:
            return False, "operation_already_active"
        if any(item not in self._completed for item in operation.dependencies):
            return False, "dependency_incomplete"
        if operation.information_need_id:
            need = self._needs.get(operation.information_need_id)
            if need is not None and (
                need.covered or need.requirement == InformationNeedRequirement.REDUNDANT
            ):
                return False, "information_need_not_required"
        return True, "executable"

    def activate(self, logical_call_id: str, reservation_id: str) -> int:
        operation = self._require(logical_call_id)
        executable, reason = self.is_executable(logical_call_id)
        if not executable:
            raise ValueError(reason)
        previous_bucket = operation.bucket
        previous_state = operation.state
        operation.bucket = FutureBucket.ACTIVE_RESERVED
        operation.active_reservation_id = reservation_id
        operation.state = FutureOperationState.RESERVED
        revision = self._bump()
        self._transition(
            operation, previous_state=previous_state, previous_bucket=previous_bucket,
            reason="reservation_created",
        )
        return revision

    def mark_started(self, logical_call_id: str, *, reason: str = "upstream_started") -> int:
        operation = self._require(logical_call_id)
        if operation.state not in {FutureOperationState.PLANNED, FutureOperationState.RESERVED}:
            raise ValueError(f"operation_{operation.state.value}")
        previous_state = operation.state
        operation.state = FutureOperationState.STARTED
        revision = self._bump()
        self._transition(
            operation, previous_state=previous_state, previous_bucket=operation.bucket,
            reason=reason,
        )
        return revision

    def start_observed(
        self, operation_name: str, *, actual_call_id: str | None = None,
        flow_id: str | None = None, tool_call_id: str | None = None,
        information_need_id: str | None = None,
    ) -> str | None:
        """Start the oldest matching shadow prediction without reserving it."""
        if actual_call_id is not None and actual_call_id in self._observed_bindings:
            raise ValueError("actual call already bound")
        for logical_id, operation in self._operations.items():
            if (operation.operation == operation_name
                and operation.state == FutureOperationState.PLANNED
                and (flow_id is None or operation.flow_id == flow_id)
                and (tool_call_id is None or operation.tool_call_id == tool_call_id)
                and (information_need_id is None or operation.information_need_id == information_need_id)):
                self.mark_started(logical_id, reason="observed_upstream_started")
                if actual_call_id is not None:
                    self._observed_bindings[actual_call_id] = logical_id
                return logical_id
        return None

    def settle(
        self, logical_call_id: str, *, retry: bool = False, cancelled: bool = False,
    ) -> int:
        operation = self._require(logical_call_id)
        if operation.bucket != FutureBucket.ACTIVE_RESERVED:
            raise ValueError("operation 不是 ACTIVE_RESERVED")
        operation.active_reservation_id = None
        if retry:
            # Invariant C: old attempt is already settled before this transition;
            # a subsequent attempt may now create exactly one new reservation.
            operation.bucket = FutureBucket.PREDICTED_UNRESERVED
            previous_state = operation.state
            operation.state = FutureOperationState.PLANNED
            revision = self._bump()
            self._transition(
                operation, previous_state=previous_state,
                previous_bucket=FutureBucket.ACTIVE_RESERVED,
                reason="retry_planned",
            )
        else:
            revision = self._terminalize(
                operation,
                FutureOperationState.CANCELLED if cancelled else FutureOperationState.COMPLETED,
                reason="cancelled_before_upstream" if cancelled else "reservation_settled",
            )
        return revision

    def complete_observed(
        self, operation_name: str, *, actual_call_id: str | None = None,
        flow_id: str | None = None, tool_call_id: str | None = None,
    ) -> str | None:
        """Reconcile one shadow-predicted operation after an observed call."""
        if actual_call_id is not None:
            bound = self._observed_bindings.pop(actual_call_id, None)
            if bound is None:
                # New clients must never steal another call's prediction.
                return None
            operation = self._require(bound)
            if operation.operation != operation_name:
                raise ValueError("bound operation type mismatch")
            self._terminalize(operation, FutureOperationState.COMPLETED, reason="exact_observed_completed")
            return bound
        candidates = [
            (logical_id, operation) for logical_id, operation in self._operations.items()
            if operation.operation == operation_name
            and (flow_id is None or operation.flow_id == flow_id)
            and (tool_call_id is None or operation.tool_call_id == tool_call_id)
            and operation.bucket != FutureBucket.ACTIVE_RESERVED
            and operation.state in {FutureOperationState.PLANNED, FutureOperationState.STARTED}
        ]
        # A STARTED node is the exact observed call. Fall back to the oldest
        # PLANNED node for clients that cannot emit a start hook yet.
        candidates.sort(key=lambda item: item[1].state != FutureOperationState.STARTED)
        for logical_id, operation in candidates:
            self._terminalize(
                operation, FutureOperationState.COMPLETED, reason="observed_completed",
            )
            return logical_id
        return None

    def discard_unstarted(
        self, *, operation_prefix: str, terminal_state: FutureOperationState = FutureOperationState.CANCELLED,
        reason: str = "discarded_unstarted",
        flow_id: str | None = None,
    ) -> int:
        removed = [
            logical_id for logical_id, operation in self._operations.items()
            if operation.operation.startswith(operation_prefix)
            and (flow_id is None or operation.flow_id == flow_id)
            and operation.bucket != FutureBucket.ACTIVE_RESERVED
            and operation.state == FutureOperationState.PLANNED
        ]
        for logical_id in removed:
            self._terminalize(self._operations[logical_id], terminal_state, reason=reason)
        return len(removed)

    def discard_one_unstarted(
        self, *, operation_prefix: str,
        terminal_state: FutureOperationState = FutureOperationState.CANCELLED,
        reason: str = "discarded_unstarted",
    ) -> str | None:
        """Terminalize the oldest matching placeholder.

        Search Agents may run concurrently, so one ``search.final`` must only
        close one unused continuation prediction and leave other agents' work
        intact.
        """
        for logical_id, operation in self._operations.items():
            if (
                operation.operation.startswith(operation_prefix)
                and operation.bucket != FutureBucket.ACTIVE_RESERVED
                and operation.state == FutureOperationState.PLANNED
            ):
                self._terminalize(operation, terminal_state, reason=reason)
                return logical_id
        return None

    def supersede_matching(
        self, *, operation_prefix: str, reason: str,
        flow_id: str | None = None, tool_call_id: str | None = None,
    ) -> int:
        """Supersede non-reserved placeholders, including an observed STARTED one."""
        matched = [
            logical_id for logical_id, operation in self._operations.items()
            if operation.operation.startswith(operation_prefix)
            and (flow_id is None or operation.flow_id == flow_id)
            and (tool_call_id is None or operation.tool_call_id == tool_call_id)
            and operation.bucket != FutureBucket.ACTIVE_RESERVED
            and operation.state in {FutureOperationState.PLANNED, FutureOperationState.STARTED}
        ]
        for logical_id in matched:
            self._terminalize(
                self._operations[logical_id], FutureOperationState.SUPERSEDED, reason=reason,
            )
        return len(matched)

    def protected_future(self) -> ResourceEstimate:
        return ResourceEstimate.sum(
            item.estimate for item in self._operations.values()
            if item.bucket == FutureBucket.PROTECTED_FUTURE
            and item.state == FutureOperationState.PLANNED
        )

    def predicted_unreserved(self) -> ResourceEstimate:
        return ResourceEstimate.sum(
            item.estimate for item in self._operations.values()
            if item.bucket == FutureBucket.PREDICTED_UNRESERVED
            and item.state == FutureOperationState.PLANNED
        )

    def validate(self, reservations: ReservationManager) -> None:
        # Invariant A follows from the single map + enum bucket representation.
        active_ids: set[str] = set()
        for operation in self._operations.values():
            if operation.logical_call_id in self._completed or operation.logical_call_id in self._terminal:
                raise AssertionError("terminal logical operation 仍存在于 active/future bucket")
            if operation.bucket == FutureBucket.ACTIVE_RESERVED:
                reservation_id = operation.active_reservation_id
                if not reservation_id or not reservations.contains(reservation_id):
                    raise AssertionError("ACTIVE_RESERVED operation 缺少 active Reservation")
                reservation = reservations.get(reservation_id)
                if reservation is None or reservation.logical_call_id != operation.logical_call_id:
                    raise AssertionError("operation 与 Reservation logical_call_id 不一致")
                if reservation_id in active_ids:
                    raise AssertionError("一个 Reservation 被多个 operation 引用")
                active_ids.add(reservation_id)
                if operation.state not in {
                    FutureOperationState.RESERVED, FutureOperationState.STARTED,
                }:
                    raise AssertionError("ACTIVE_RESERVED lifecycle state 非法")
                if len(reservations.active_for(operation.logical_call_id)) != 1:
                    raise AssertionError("ACTIVE_RESERVED 必须恰好对应一个 Reservation")
            elif operation.active_reservation_id is not None:
                raise AssertionError("非 ACTIVE_RESERVED operation 持有 reservation id")
            elif operation.state not in {FutureOperationState.PLANNED, FutureOperationState.STARTED}:
                raise AssertionError("非 active future operation lifecycle state 非法")
        if active_ids != {item.reservation_id for item in reservations.active()}:
            raise AssertionError("存在未被 FutureOperation 引用的 active Reservation")

    def _require(self, logical_call_id: str) -> FutureOperation:
        operation = self._operations.get(logical_call_id)
        if operation is None:
            raise KeyError(logical_call_id)
        return operation

    def pop_transitions(self) -> tuple[FutureOperationTransition, ...]:
        values = tuple(self._pending_transitions)
        self._pending_transitions.clear()
        return values

    def _terminalize(
        self, operation: FutureOperation, state: FutureOperationState, *, reason: str,
    ) -> int:
        previous_state = operation.state
        previous_bucket = operation.bucket
        operation.state = state
        operation.active_reservation_id = None
        revision = self._bump()
        self._transition(
            operation, previous_state=previous_state, previous_bucket=previous_bucket,
            reason=reason,
        )
        logical_id = operation.logical_call_id
        if state == FutureOperationState.COMPLETED:
            self._completed.add(logical_id)
        self._terminal[logical_id] = state
        del self._operations[logical_id]
        return revision

    def _transition(
        self, operation: FutureOperation, *, previous_state: FutureOperationState | None,
        previous_bucket: FutureBucket | None, reason: str,
    ) -> None:
        self._pending_transitions.append(FutureOperationTransition(
            logical_call_id=operation.logical_call_id,
            operation=operation.operation,
            plan_revision=self.revision,
            transition_reason=reason,
            previous_bucket=previous_bucket.value if previous_bucket is not None else None,
            new_bucket=(operation.bucket.value if operation.state not in {
                FutureOperationState.COMPLETED, FutureOperationState.CANCELLED,
                FutureOperationState.SUPERSEDED,
            } else None),
            previous_state=previous_state.value if previous_state is not None else None,
            new_state=operation.state.value,
            flow_id=operation.flow_id,
            tool_call_id=operation.tool_call_id,
        ))

    def _bump(self) -> int:
        self.revision += 1
        return self.revision

