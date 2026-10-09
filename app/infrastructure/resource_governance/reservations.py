"""Active reservation lifecycle.

This manager is the *only* authority for active reserved resource.  Future
operations may carry a reservation id as a foreign key but never contribute
their estimates to the active-reserved aggregate.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import ReservationStatus, ResourceEstimate


@dataclass
class Reservation:
    reservation_id: str
    logical_call_id: str
    attempt: int
    operation: str
    estimate: ResourceEstimate
    status: ReservationStatus = ReservationStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    settled_estimate: ResourceEstimate | None = None


class ReservationManager:
    """Owns active reservations and their terminal history."""

    def __init__(self) -> None:
        self._active: dict[str, Reservation] = {}
        self._active_by_logical: dict[str, str] = {}
        self._history: list[Reservation] = []

    def reserve(
        self, logical_call_id: str, attempt: int, operation: str,
        estimate: ResourceEstimate, *, timeout_seconds: float = 300.0,
    ) -> Reservation:
        if logical_call_id in self._active_by_logical:
            raise ValueError(f"logical_call_id 已有 active reservation: {logical_call_id}")
        now = datetime.now(timezone.utc)
        reservation = Reservation(
            reservation_id=uuid.uuid4().hex,
            logical_call_id=logical_call_id,
            attempt=attempt,
            operation=operation,
            estimate=estimate,
            expires_at=now + timedelta(seconds=max(0.0, timeout_seconds)),
        )
        self._active[reservation.reservation_id] = reservation
        self._active_by_logical[logical_call_id] = reservation.reservation_id
        return reservation

    def contains(self, reservation_id: str) -> bool:
        return reservation_id in self._active

    def get(self, reservation_id: str) -> Reservation | None:
        return self._active.get(reservation_id)

    def active(self) -> tuple[Reservation, ...]:
        return tuple(self._active.values())

    def active_for(self, logical_call_id: str) -> tuple[Reservation, ...]:
        reservation_id = self._active_by_logical.get(logical_call_id)
        reservation = self._active.get(reservation_id or "")
        return (reservation,) if reservation is not None else ()

    def active_reserved(self) -> ResourceEstimate:
        return ResourceEstimate.sum(item.estimate for item in self._active.values())

    def settle(
        self, reservation_id: str, actual: ResourceEstimate | None, *,
        timed_out: bool = False, cancelled_before_upstream: bool = False,
    ) -> Reservation:
        reservation = self._active.pop(reservation_id)
        self._active_by_logical.pop(reservation.logical_call_id, None)
        if cancelled_before_upstream:
            reservation.status = ReservationStatus.CANCELLED_ZERO
            reservation.settled_estimate = ResourceEstimate()
        elif actual is not None:
            reservation.status = ReservationStatus.SETTLED_ACTUAL
            reservation.settled_estimate = actual
        else:
            reservation.status = (
                ReservationStatus.TIMED_OUT_ESTIMATED
                if timed_out else ReservationStatus.SETTLED_ESTIMATED
            )
            reservation.settled_estimate = reservation.estimate
        self._history.append(reservation)
        return reservation

    def history(self) -> tuple[Reservation, ...]:
        return tuple(self._history)

    def expired_ids(self, now: datetime | None = None) -> tuple[str, ...]:
        now = now or datetime.now(timezone.utc)
        return tuple(
            item.reservation_id for item in self._active.values()
            if item.expires_at is not None and item.expires_at <= now
        )

