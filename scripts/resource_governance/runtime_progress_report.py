"""Summarize causal runtime progress without inferring unobserved relevance."""
from collections import Counter, defaultdict


def summarize_runtime_progress(requests: list[dict]) -> dict:
    events = []
    streams = defaultdict(list)
    missing = 0
    for request in requests:
        rows = request.get("runtime_progress_events") or []
        missing += not bool(rows)
        for row in rows:
            if not isinstance(row.get("after"), dict):
                continue
            events.append(row)
            streams[(request.get("trace_id"), row["after"].get("flow_id"))].append(row)
    zeros = continued = 0
    for rows in streams.values():
        rows.sort(key=lambda row: row["after"].get("sequence", 0))
        for index, row in enumerate(rows):
            if row.get("progress_class") != "ZERO_PROGRESS":
                continue
            zeros += 1
            # Same child stream only. No cross-agent next-event leakage.
            continued += any(later["after"].get("last_operation") in {
                "main.plan", "search.plan", "trade.plan", "tool.permitted",
            } for later in rows[index + 1:])
    return {
        "status": "AVAILABLE" if events else "NOT_AVAILABLE",
        "shadow_only": True, "action_driving": False,
        "observed_event_count": len(events), "trace_missing_runtime_events": missing,
        "progress_distribution": dict(Counter(row.get("progress_class", "UNKNOWN") for row in events)),
        "refinement_distribution": dict(Counter(
            row.get("refinement_class", "UNKNOWN") for row in events
            if row.get("refinement_class") != "NOT_APPLICABLE"
        )),
        "zero_progress_event_count": zeros,
        "zero_progress_followed_by_observed_continuation_count": continued,
        "zero_progress_followed_by_observed_continuation_rate": continued / zeros if zeros else None,
        "max_zero_progress_streak": max((row["after"].get("zero_progress_streak", 0) for row in events), default=None),
        "evidence_sufficiency_unknown_count": sum(row["after"].get("evidence_sufficient") is None for row in events),
        "next_prediction_confidence_distribution": dict(Counter(
            row["forecast"]["next_operation"]["confidence"] for row in events if row.get("forecast")
        )),
        "loop_prediction_confidence_distribution": dict(Counter(
            row["forecast"]["remaining_rounds"]["confidence"] for row in events if row.get("forecast")
        )),
        "interpretation": "Unverified retrieval relevance remains UNKNOWN; this is not a quality gate or a continuation predictor.",
    }
