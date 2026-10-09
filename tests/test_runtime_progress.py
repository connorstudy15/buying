import json
from dataclasses import replace

import pytest
from agentscope.message import TextBlock, ToolCallBlock, ToolResultState
from agentscope.tool import ToolChunk

from app.infrastructure.resource_governance.runtime import RuntimeObservation, RuntimeStateStore
from app.infrastructure.resource_governance.governor import RequestResourceGovernor
from app.infrastructure.resource_governance.middleware import _result_observation
from scripts.resource_governance.runtime_progress_report import summarize_runtime_progress
from app.infrastructure.tracing import _sanitize_attributes


def event(identity, **kwargs):
    return RuntimeObservation(identity, kwargs.pop("flow_id", "main"), "knowledge.retrieve",
                              tool="category_insight_tool", **kwargs)


def test_retrieved_is_not_relevant_or_sufficient():
    store = RuntimeStateStore()
    row = store.observe(event("1", evidence_ids=("chunk",), required_need_ids=("n",)), route="DIRECT")
    assert row["after"]["required_need_covered"] == 0
    assert row["after"]["required_need_remaining"] == 1
    assert row["after"]["evidence_sufficient"] is None
    assert row["after"]["need_scope_complete"] is False
    assert row["progress_class"] != "HIGH_PROGRESS"
    row = store.observe(event("2", covered_need_ids=("n",)), route="DIRECT")
    assert row["progress_class"] == "HIGH_PROGRESS"
    assert row["after"]["required_need_covered"] == 1
    assert store.history[0]["after"]["required_need_covered"] == 0


def test_dedup_event_and_unknown_need_cannot_claim_coverage():
    store = RuntimeStateStore()
    obs = event("1", covered_need_ids=("unregistered",))
    assert store.observe(obs, route="unknown")["after"]["required_need_covered"] == 0
    assert store.observe(obs, route="future-route") is None
    assert len(store.history) == 1
    assert store.history[0]["after"]["current_route"] == "unknown"


def test_parallel_children_do_not_share_evidence_or_rounds():
    store = RuntimeStateStore()
    for child in ("a", "b"):
        row = store.observe(replace(event(child, flow_id=child, evidence_ids=("same",)), operation="search.plan"), route="product_search")
        assert row["after"]["new_evidence_count"] == 1
        assert row["after"]["search_plan_round"] == 1


def test_duplicate_requires_no_freshness_and_no_new_evidence():
    store = RuntimeStateStore()
    base = event("1", query_hash="q", constraint_signature="c", need_id="n", success=True,
                 freshness_required=False, evidence_ids=("e",))
    store.observe(base, route="DIRECT")
    row = store.observe(replace(base, event_id="2"), route="DIRECT")
    assert row["refinement_class"] == "EXACT_DUPLICATE"
    assert row["progress_class"] == "ZERO_PROGRESS"
    # Model events do not incorrectly erase the retrieval streak.
    store.observe(RuntimeObservation("model", "main", "main.plan"), route="DIRECT")
    row = store.observe(replace(base, event_id="3"), route="DIRECT")
    assert row["after"]["zero_progress_streak"] == 2
    assert row["after"]["loop_risk"] == "HIGH"
    row = store.observe(replace(base, event_id="fresh", freshness_required=True), route="DIRECT")
    assert row["refinement_class"] != "EXACT_DUPLICATE"
    row = store.observe(replace(base, event_id="new", evidence_ids=("new-e",)), route="DIRECT")
    assert row["progress_class"] != "ZERO_PROGRESS"
    assert row["after"]["zero_progress_streak"] == 0


def test_changed_query_is_not_automatically_useful_or_waste():
    store = RuntimeStateStore()
    base = event("1", query_hash="q", constraint_signature="c", need_id="n", success=True)
    store.observe(base, route="DIRECT")
    row = store.observe(replace(base, event_id="2", query_hash="q2"), route="DIRECT")
    assert row["refinement_class"] == "UNKNOWN"
    row = store.observe(replace(base, event_id="3", query_hash="q3", necessary_refinement=True,
                                evidence_sufficient=False), route="DIRECT")
    assert row["refinement_class"] == "NECESSARY_BUT_NO_RESULT"
    row = store.observe(replace(base, event_id="4", query_hash="q4", outcome_fully_observed=True), route="DIRECT")
    assert row["refinement_class"] == "LOW_VALUE_REFINEMENT"


def test_failed_call_never_advances_coverage_or_proves_zero_progress():
    store = RuntimeStateStore()
    row = store.observe(event("failed", success=False, required_need_ids=("n",), covered_need_ids=("n",),
                              evidence_ids=("bad",), verified_required_evidence_ids=("bad",)), route="DIRECT")
    assert row["progress_class"] == "UNKNOWN"
    assert row["after"]["required_need_covered"] == 0
    assert row["after"]["new_evidence_count"] == 0


def test_result_adapter_excludes_score_and_does_not_persist_content():
    call = ToolCallBlock(id="a", name="category_insight_tool", input=json.dumps({"question": "private words"}))
    def output(score):
        return ToolChunk(content=[TextBlock(text=json.dumps({"insights": [{"content": "private evidence", "source": "doc", "score": score}]}))], state=ToolResultState.SUCCESS)
    first = _result_observation(call, output(0.9), flow_id="main", role="main")
    second = _result_observation(call, output(0.1), flow_id="main", role="main")
    assert first.success is True
    assert first.evidence_ids == second.evidence_ids
    assert first.evidence_sufficient is None
    assert first.freshness_required is None
    row = RuntimeStateStore().observe(first, route="DIRECT")
    assert "private" not in json.dumps(row)


def test_runtime_snapshot_survives_privacy_filter_in_off_mode():
    row = RuntimeStateStore().observe(event("1"), route="unknown")
    attrs = _sanitize_attributes({"globex.resource.runtime_state": json.dumps(row)}, content_mode="off")
    assert json.loads(attrs["globex.resource.runtime_state"])["action_driving"] is False


@pytest.mark.asyncio
async def test_runtime_diagnostics_cannot_change_future_plan_or_budgets():
    governor = RequestResourceGovernor("test", "model")
    original = governor.future_work_plan_json(), governor.planned_budget, governor.ledger.used()
    for index in range(4):
        await governor.observe_runtime(event(str(index), query_hash="q", constraint_signature="c",
                                             success=True, freshness_required=False))
    assert (governor.future_work_plan_json(), governor.planned_budget, governor.ledger.used()) == original
    assert governor.runtime.history[-1]["after"]["loop_risk"] == "HIGH"
    assert governor.shadow_only


def test_report_does_not_mix_children_or_invent_legacy_progress():
    store = RuntimeStateStore()
    base = event("1", flow_id="a", query_hash="q", constraint_signature="c", success=True, freshness_required=False)
    store.observe(base, route="DIRECT")
    store.observe(replace(base, event_id="2"), route="DIRECT")
    store.observe(RuntimeObservation("3", "b", "search.plan"), route="DIRECT")
    report = summarize_runtime_progress([{"trace_id": "t", "runtime_progress_events": store.history}])
    assert report["zero_progress_event_count"] == 1
    assert report["zero_progress_followed_by_observed_continuation_count"] == 0
    assert summarize_runtime_progress([{"trace_id": "old"}])["status"] == "NOT_AVAILABLE"


@pytest.mark.asyncio
async def test_tool_exception_is_recorded_unknown_and_reraised_unchanged():
    from app.infrastructure.resource_governance.governor import begin_shadow_request, end_shadow_request
    from app.infrastructure.resource_governance.middleware import ResourceOperationTracingMiddleware
    governor, token = begin_shadow_request("failure", "model")
    error = RuntimeError("secret provider message must not be traced")
    call = ToolCallBlock(id="bad", name="category_insight_tool", input='{"question":"test"}')
    async def handler(**kwargs):
        raise error
        yield  # async generator interface
    try:
        middleware = ResourceOperationTracingMiddleware.__new__(ResourceOperationTracingMiddleware)
        with pytest.raises(RuntimeError) as captured:
            _ = [part async for part in middleware.on_acting(None, {"tool_call": call}, handler)]
        assert captured.value is error
        assert governor.runtime.history[-1]["progress_class"] == "UNKNOWN"
        assert governor.runtime.history[-1]["after"]["last_operation"] == "tool.failed"
        assert "secret provider" not in json.dumps(governor.runtime.history)
    finally:
        end_shadow_request(token)


def test_verified_sufficiency_or_transaction_progress_is_explicit():
    store = RuntimeStateStore()
    row = store.observe(event("1", success=True, evidence_sufficient=True), route="DIRECT")
    assert row["progress_class"] == "HIGH_PROGRESS"
    row = store.observe(event("2", transaction_advanced=True, success=True), route="trade")
    assert row["progress_class"] == "HIGH_PROGRESS"
