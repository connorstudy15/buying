import asyncio
import json

import pytest

from app.infrastructure.resource_governance.governor import RequestResourceGovernor
from app.infrastructure.resource_governance.operation import current_execution, execution_identity
from app.infrastructure.resource_governance.plan import FutureOperation, FutureWorkPlan
from app.infrastructure.resource_governance.models import FutureBucket, ResourceEstimate
from scripts.resource_governance.causal_replay import _prediction_row
from scripts.resource_governance.causal_replay import _remaining_actual


def test_reverse_completion_cannot_consume_other_parallel_prediction():
    plan = FutureWorkPlan()
    for child in ("a", "b"):
        plan.add(FutureOperation(child, "embedding.product_query", ResourceEstimate(),
                                 FutureBucket.PREDICTED_UNRESERVED,
                                 flow_id=child, tool_call_id=child))
        assert plan.start_observed("embedding.product_query", actual_call_id=f"api-{child}",
                                   flow_id=child, tool_call_id=child) == child
    assert plan.complete_observed("embedding.product_query", actual_call_id="api-b") == "b"
    assert plan.get("a") is not None
    assert plan.complete_observed("embedding.product_query", actual_call_id="unknown") is None
    assert plan.complete_observed("embedding.product_query", actual_call_id="api-a") == "a"
    with pytest.raises(ValueError):
        plan.add(FutureOperation("a", "embedding.product_query", ResourceEstimate(),
                                 FutureBucket.PREDICTED_UNRESERVED))


@pytest.mark.asyncio
async def test_concurrent_identity_is_task_local():
    async def child(name):
        with execution_identity(flow_id=name, tool_call_id=name):
            await asyncio.sleep(0)
            return current_execution().flow_id
    assert await asyncio.gather(child("a"), child("b")) == ["a", "b"]
    assert current_execution().flow_id == "main"


@pytest.mark.asyncio
async def test_qp_supersedes_only_own_tool_and_preserves_other_needs():
    governor = RequestResourceGovernor("test", "model")
    await governor.observe_tool_calls(["category_insight_tool"] * 2, tool_calls=[
        {"id": name, "name": "category_insight_tool", "input": {}} for name in ("a", "b")
    ])
    with execution_identity(flow_id="main", tool_call_id="b"):
        await governor.observe_query_plan("DECOMPOSE", ["n1", "n2"])
    placeholders = [op for op in governor.future_plan.operations() if op.operation == "query_processor.classify"]
    assert len(placeholders) == 1 and placeholders[0].tool_call_id == "a"
    with execution_identity(flow_id="main", tool_call_id="a"):
        await governor.observe_query_plan("DECOMPOSE", ["n1", "n2"])
    reranks = [op for op in governor.future_plan.operations() if op.operation == "reranker.knowledge.need"]
    assert len(reranks) == 4


@pytest.mark.asyncio
async def test_trade_dispatch_is_not_search_and_child_final_is_scoped():
    governor = RequestResourceGovernor("test", "model")
    await governor.observe_tool_calls(["task_dispatch"] * 3, tool_calls=[
        {"id": name, "name": "task_dispatch", "input": {"subagent_type": kind}}
        for name, kind in (("a", "search_agent"), ("b", "search_agent"), ("t", "trade_agent"))
    ])
    assert {op.operation for op in governor.future_plan.operations() if op.flow_id == "dispatch:t"} == {"trade.plan", "trade.final"}
    with execution_identity(flow_id="dispatch:b"):
        await governor.observe_completed_operation("search.final")
    assert not [op for op in governor.future_plan.operations() if op.flow_id == "dispatch:b"]
    assert len([op for op in governor.future_plan.operations() if op.flow_id == "dispatch:a"]) == 2


def test_budget_comparison_uses_total_not_remaining_and_legacy_is_unavailable():
    request = {"actual_request_tokens": 100, "actual_operation_count": 1}
    revision = {"used_chat_tokens": 70, "planned_budget_chat_tokens": 40,
                "planned_total_chat_budget": 110, "planned_remaining_chat_budget": 40,
                "planned_budget_scope": "unstarted_future_chat_only"}
    row = _prediction_row(request, revision, [], label="test")
    assert row["planned_budget_exceeded"] is False
    assert row["actual_remaining_chat_tokens"] == 30
    assert (100 > 110) == (30 > 40)
    assert _prediction_row(request, {}, [], label="legacy")["planned_budget_exceeded"] is None


def test_revision_exports_total_and_remaining_budget():
    governor = RequestResourceGovernor("test", "model")
    row = json.loads(governor.plan_revision_history_json())[-1]
    assert row["planned_total_chat_budget"] == row["used_chat_tokens"] + row["planned_remaining_chat_budget"]


def test_replay_includes_inflight_operation_by_end_time():
    call = {"timestamp": "2026-10-09T00:00:01Z", "end_timestamp": "2026-10-09T00:00:03Z"}
    assert _remaining_actual([call], "2026-10-09T00:00:02Z") == [call]
    assert _remaining_actual([call], "2026-10-09T00:00:04Z") == []


@pytest.mark.asyncio
async def test_acting_hook_propagates_tool_identity_without_modifying_arguments():
    from types import SimpleNamespace
    from agentscope.message import ToolCallBlock
    from app.infrastructure.resource_governance.middleware import ResourceOperationTracingMiddleware, _tool_calls

    middleware = ResourceOperationTracingMiddleware.__new__(ResourceOperationTracingMiddleware)
    call = ToolCallBlock(id="trade-1", name="task_dispatch", input=json.dumps({"subagent_type": "trade_agent", "demands": "test"}))
    arguments = {"tool_call": call}

    async def handler(**received):
        assert received == arguments
        assert current_execution().flow_id == "dispatch:trade-1"
        assert current_execution().tool_call_id is None
        yield "unchanged"

    assert [item async for item in middleware.on_acting(None, arguments, handler)] == ["unchanged"]
    assert _tool_calls(SimpleNamespace(content=[call])) == [
        {"id": "trade-1", "name": "task_dispatch", "input": {"subagent_type": "trade_agent", "demands": "test"}}
    ]
    assert current_execution().flow_id == "main"


def test_need_identity_prevents_parallel_rerank_mismatch():
    plan = FutureWorkPlan()
    for need in ("n1", "n2"):
        plan.add(FutureOperation(need, "reranker.knowledge.need", ResourceEstimate(),
                                 FutureBucket.PREDICTED_UNRESERVED,
                                 information_need_id=need, tool_call_id="tool"))
    assert plan.start_observed("reranker.knowledge.need", actual_call_id="api-n2",
                               flow_id="main", tool_call_id="tool", information_need_id="n2") == "n2"
    assert plan.complete_observed("reranker.knowledge.need", actual_call_id="api-n2") == "n2"
    assert plan.get("n1") is not None
