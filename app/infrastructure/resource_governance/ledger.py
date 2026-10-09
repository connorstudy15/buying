"""Append-only usage ledger: the sole source of already-consumed resources."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from .models import ResourceEstimate

UsageSource = Literal["actual", "estimated_missing_usage", "estimated_timeout"]


@dataclass(frozen=True)
class UsageEntry:
    logical_call_id: str
    attempt: int
    operation: str
    estimate: ResourceEstimate
    usage_source: UsageSource
    trace_id: str = ""
    span_id: str = ""
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class UsageLedger:
    """Stores facts only; it does not predict, reserve, or make policy decisions."""

    def __init__(self) -> None:
        self._entries: list[UsageEntry] = []
        self._attempt_keys: set[tuple[str, int]] = set()

    def record(self, entry: UsageEntry) -> None:
        key = (entry.logical_call_id, entry.attempt)
        if key in self._attempt_keys:
            raise ValueError(f"usage attempt 已结算: {entry.logical_call_id}/{entry.attempt}")
        self._attempt_keys.add(key)
        self._entries.append(entry)

    def entries(self) -> tuple[UsageEntry, ...]:
        return tuple(self._entries)

    def used(self) -> ResourceEstimate:
        return ResourceEstimate.sum(item.estimate for item in self._entries)


@dataclass(frozen=True)
class AttemptLifecycle:
    logical_call_id: str
    attempt: int
    reservation_id: str
    usage_source: UsageSource

