"""Read-only historical Langfuse replay for Phase-2 shadow prediction.

No prompt, tool input, tool output or business content is requested or emitted.
Legacy traces do not contain explicit resource operation attributes, so main
plan/final profile labels are reconstructed from the main-agent generation
order and are marked LOW-confidence in the report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.infrastructure.langfuse_config import LangfuseConfig  # noqa: E402
from app.infrastructure.resource_governance.governor import RequestResourceGovernor  # noqa: E402


# Resource-governance and retrieval calibration attributes are exported as
# Langfuse observation metadata.  Omitting ``metadata`` leaves the observation
# tree intact but silently removes every predictor/accounting field needed by
# the Phase 2.5 report.
FIELDS = "core,basic,model,usage,metrics,metadata"


def _get_pages(client: httpx.Client, params: dict) -> list[dict]:
    rows, cursors = [], set()
    for _ in range(50):
        response = None
        for attempt in range(8):
            response = client.get("api/public/v2/observations", params=params)
            if response.status_code != 429:
                break
            if attempt < 7:
                retry_after = response.headers.get("retry-after", "")
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2 ** (attempt + 1)
                time.sleep(min(max(delay, 1.0), 60.0))
        assert response is not None
        response.raise_for_status()
        payload = response.json()
        rows.extend(row for row in payload.get("data", []) if isinstance(row, dict))
        cursor = (payload.get("meta") or {}).get("cursor")
        if not cursor:
            return rows
        if cursor in cursors:
            raise RuntimeError("langfuse_cursor_cycle")
        cursors.add(cursor)
        params = {**params, "cursor": cursor}
    raise RuntimeError("langfuse_pagination_limit")


def _tokens(row: dict, key: str) -> int | None:
    value = row.get(key + "Usage")
    if type(value) is int and value >= 0:
        return value
    details = row.get("usageDetails")
    value = details.get(key) if isinstance(details, dict) else None
    return value if type(value) is int and value >= 0 else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * q) - 1))]


def _profile_percentiles(rows: list[dict]) -> dict:
    def summarize(key: str) -> dict:
        values = [int(row.get(key) or 0) for row in rows]
        return {
            "p50": _percentile(values, .50),
            "p80": _percentile(values, .80),
            "p95": _percentile(values, .95),
        }
    return {
        "sample_count": len(rows),
        "chat_input_tokens": summarize("chat_input_tokens"),
        "chat_output_tokens": summarize("chat_output_tokens"),
        "latency_ms": summarize("latency_ms"),
    }


def replay(rows: list[dict], *, model: str = "historical") -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        trace_id = row.get("traceId")
        if isinstance(trace_id, str):
            grouped.setdefault(trace_id, []).append(row)
    business = [
        (trace_id, trace_rows) for trace_id, trace_rows in grouped.items()
        if any(str(item.get("name") or "").startswith("POST /commerce/ag-ui/run") for item in trace_rows)
    ]
    observations = []
    plan_rows, final_rows = [], []
    for trace_id, trace_rows in business:
        generations = [
            item for item in trace_rows
            if str(item.get("type") or "").upper() == "GENERATION"
            and _tokens(item, "input") is not None and _tokens(item, "output") is not None
        ]
        if not generations:
            continue
        generations.sort(key=lambda item: str(item.get("startTime") or ""))
        actual = sum((_tokens(item, "input") or 0) + (_tokens(item, "output") or 0) for item in generations)
        governor = RequestResourceGovernor(trace_id, model, shadow_only=True)
        snapshot = governor.snapshot()
        predicted = snapshot.protected_future.plus(snapshot.predicted_unreserved).chat_total_tokens
        planned_limit = snapshot.planned_budget.chat_token_limit or 0
        error = predicted - actual
        observations.append({
            "trace_sha256": hashlib.sha256(trace_id.encode()).hexdigest()[:16],
            "generation_calls": len(generations),
            "predicted_expected_chat_tokens": predicted,
            "planned_chat_limit": planned_limit,
            "actual_chat_tokens": actual,
            "signed_error_tokens": error,
            "absolute_error_tokens": abs(error),
            "relative_error": abs(error) / max(actual, 1),
            "underpredicted": predicted < actual,
            "planned_budget_breached": planned_limit < actual,
            "actual_exceeded_absolute_cap": actual > (snapshot.absolute_hard_cap.chat_token_limit or 0),
        })
        # Legacy reconstruction only: last main-like generation is final; prior
        # generations are planning. Explicit operation spans supersede this.
        for index, item in enumerate(generations):
            target = final_rows if index == len(generations) - 1 else plan_rows
            target.append({
                "chat_input_tokens": _tokens(item, "input") or 0,
                "chat_output_tokens": _tokens(item, "output") or 0,
                "api_calls": 1,
                "latency_ms": max(0, round(float(item.get("latency") or 0) * 1000)),
            })
    abs_errors = [item["absolute_error_tokens"] for item in observations]
    relative = [item["relative_error"] for item in observations]
    bucketed = {}
    for label, selected in (
        ("one_generation", [item for item in observations if item["generation_calls"] == 1]),
        ("two_generations", [item for item in observations if item["generation_calls"] == 2]),
        ("three_or_more_generations", [item for item in observations if item["generation_calls"] >= 3]),
    ):
        bucketed[label] = {
            "trace_count": len(selected),
            "actual_chat_tokens_p50": _percentile([item["actual_chat_tokens"] for item in selected], .50),
            "mean_absolute_percentage_error": (
                statistics.fmean(item["relative_error"] for item in selected) if selected else None
            ),
            "underprediction_rate": (
                statistics.fmean(item["underpredicted"] for item in selected) if selected else None
            ),
            "planned_budget_breach_rate": (
                statistics.fmean(item["planned_budget_breached"] for item in selected) if selected else None
            ),
        }
    return {
        "schema_version": 1,
        "shadow_only": True,
        "content_read": False,
        "legacy_operation_reconstruction_confidence": "low",
        "bootstrap_parameters_are_provisional": True,
        "trace_count": len(observations),
        "summary": {
            "predicted_expected_chat_tokens_per_request": observations[0]["predicted_expected_chat_tokens"] if observations else None,
            "planned_chat_limit_per_request": observations[0]["planned_chat_limit"] if observations else None,
            "actual_chat_tokens_p50": _percentile([item["actual_chat_tokens"] for item in observations], .50),
            "actual_chat_tokens_p80": _percentile([item["actual_chat_tokens"] for item in observations], .80),
            "actual_chat_tokens_p95": _percentile([item["actual_chat_tokens"] for item in observations], .95),
            "absolute_error_p50": _percentile(abs_errors, .50),
            "absolute_error_p95": _percentile(abs_errors, .95),
            "mean_absolute_percentage_error": statistics.fmean(relative) if relative else None,
            "underprediction_rate": statistics.fmean(item["underpredicted"] for item in observations) if observations else None,
            "planned_budget_breach_rate": statistics.fmean(item["planned_budget_breached"] for item in observations) if observations else None,
            "absolute_cap_exceed_rate": statistics.fmean(item["actual_exceeded_absolute_cap"] for item in observations) if observations else None,
        },
        "legacy_profile_samples": {"main.plan": len(plan_rows), "main.final": len(final_rows)},
        "legacy_profile_percentiles": {
            "main.plan": _profile_percentiles(plan_rows),
            "main.final": _profile_percentiles(final_rows),
        },
        "generation_count_buckets": bucketed,
        "observations": observations,
    }


def fetch(
    config: LangfuseConfig, lookback_days: int, *, trace_ids: list[str] | None = None,
    session_id: str | None = None,
) -> list[dict]:
    config.validate()
    now = datetime.now(timezone.utc)
    with httpx.Client(
        base_url=config.base_url.rstrip("/") + "/", timeout=20,
        headers={"Authorization": config.authorization_header}, follow_redirects=False,
    ) as client:
        window = {
            "fields": FIELDS,
            "limit": 100,
            "fromStartTime": (now - timedelta(days=lookback_days)).isoformat(),
            "toStartTime": (now + timedelta(seconds=1)).isoformat(),
        }
        if trace_ids is None:
            # Fetch only business roots first; evaluation runs can contain
            # thousands of unrelated observations.
            root_names = ("POST /commerce/ag-ui/run", "POST /commerce/intents")
            roots = []
            for root_name in root_names:
                roots.extend(_get_pages(client, {**window, "name": root_name}))
            trace_ids = sorted({
                row.get("traceId") for row in roots
                if row.get("name") in root_names and isinstance(row.get("traceId"), str)
            })
        # A benchmark run has one Langfuse session id. Fetch it in one
        # paginated query instead of making one request per trace, which can
        # trigger 429 rate limiting for a 67x2 run.
        if session_id:
            try:
                session_rows = _get_pages(client, {**window, "sessionId": session_id})
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in {400, 404}:
                    raise
            else:
                if session_rows:
                    return session_rows

        rows: list[dict] = []
        for index, trace_id in enumerate(trace_ids):
            # Keep the public API below its burst limit when the session
            # filter is unavailable and we must fall back to trace IDs.
            if index:
                time.sleep(0.5)
            rows.extend(_get_pages(client, {**window, "traceId": trace_id}))
        return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--lookback-days", type=int, default=31)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.lookback_days <= 31:
        raise SystemExit("lookback-days 必须在 1..31")
    report = replay(fetch(LangfuseConfig.from_env(args.env_file, environ={}), args.lookback_days))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"trace_count": report["trace_count"], **report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

