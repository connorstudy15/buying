"""Request-scoped resource governance primitives.

Phase 0-2 is deliberately shadow-only.  The package records observations and
computes decisions, but it is not allowed to reject or degrade a production
operation until the later enforcement phase is explicitly enabled.
"""

from .models import (
    BudgetEnvelope,
    CompactionBaseline,
    ContextSnapshot,
    ContextScope,
    FinalCallReserve,
    FutureBucket,
    InformationNeedRequirement,
    ResourceEstimate,
    TokenEstimate,
)
from .governor import RequestResourceGovernor

__all__ = [
    "BudgetEnvelope",
    "CompactionBaseline",
    "ContextSnapshot",
    "ContextScope",
    "FinalCallReserve",
    "FutureBucket",
    "InformationNeedRequirement",
    "RequestResourceGovernor",
    "ResourceEstimate",
    "TokenEstimate",
]
