import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agentscope.message import ToolCallBlock
from agentscope.model import ChatResponse

from app.infrastructure.resource_governance.context_governor import ContextGovernorAdapter
from app.infrastructure.resource_governance.governor import RequestResourceGovernor
from app.infrastructure.resource_governance.ledger import UsageEntry, UsageLedger
from app.infrastructure.resource_governance.models import (
    BudgetEnvelope, CompactionBaseline, ContextScope, FutureBucket,
    FutureOperationState, ReservationDecisionCode, ResourceEstimate,
)
from app.infrastructure.resource_governance.policy import ResourcePolicy
from app.infrastructure.resource_governance.profiles import (
    OperationProfileBuilder, OperationProfileKey, OperationProfileStore,
)
from app.infrastructure.resource_governance.governor import begin_shadow_request, end_shadow_request
from app.infrastructure.resource_governance.middleware import ResourceOperationTracingMiddleware
from app.infrastructure.resource_governance.estimator import TokenEstimator
from app.infrastructure.resource_governance.predictor import WorkloadPredictor


def test_resource_estimate_and_envelope_are_separate_and_not_orderable():
    estimate = ResourceEstimate(chat_input_tokens=10, chat_output_tokens=5, monetary_cost=Decimal("0.1"))
    envelope = BudgetEnvelope(chat_token_limit=20, monetary_cost_limit=Decimal("0.2"))
    assert estimate.chat_total_tokens == 15
    assert envelope.chat_token_limit == 20
    with pytest.raises(TypeError):
        _ = estimate < ResourceEstimate(chat_input_tokens=20)  # type: ignore[operator]


def test_usage_ledger_is_append_only_and_prevents_double_settlement():
    ledger = UsageLedger()
    entry = UsageEntry("call", 1, "main.plan", ResourceEstimate(chat_input_tokens=10), "actual")
    ledger.record(entry)
    assert ledger.used().chat_total_tokens == 10
    with pytest.raises(ValueError, match="已结算"):
        ledger.record(entry)


@pytest.mark.asyncio
async def test_governor_records_causal_plan_revision_history():
    governor = RequestResourceGovernor("history", "model", shadow_only=True)
    initial = json.loads(governor.plan_revision_history_json())
    assert initial[0]["trigger"] == "bootstrap"
    assert initial[0]["route"] == "unknown_one_plan_plus_final"

    await governor.observe_query_plan("DECOMPOSE", ["need-a", "need-b"])
    history = json.loads(governor.plan_revision_history_json())
    assert history[-1]["trigger"] == "query_processor_result"
    assert history[-1]["known_information"]["information_need_count"] == 2
    assert governor.route_after_query_processor == "knowledge_decompose"
    assert governor.route_revision_count == 1


@pytest.mark.asyncio
async def test_tool_calls_causally_expand_shadow_future_plan():
    governor = RequestResourceGovernor("tool-history", "model", shadow_only=True)
    before = governor.snapshot().projected.chat_total_tokens
    await governor.observe_tool_calls(["category_insight_tool"], source_role="main")
    names = [item.operation for item in governor.future_plan.operations()]
    assert "main.plan" in names
    assert "query_processor.classify" in names
    assert governor.snapshot().projected.chat_total_tokens > before

    await governor.observe_query_plan("DECOMPOSE", ["need-a", "need-b"])
    names = [item.operation for item in governor.future_plan.operations()]
    assert "query_processor.classify" not in names
    assert names.count("reranker.knowledge.need") == 2


@pytest.mark.asyncio
async def test_search_tool_calls_predict_search_continuation_and_product_resources():
    governor = RequestResourceGovernor("search-tools", "model", shadow_only=True)
    await governor.observe_tool_calls(["product_search_tool"], source_role="search")
    names = [item.operation for item in governor.future_plan.operations()]
    assert "search.plan" in names
    assert "embedding.product_query" in names
    assert "reranker.product" in names

    await governor.observe_tool_calls(
        ["product_search_tool"], source_role="search",
        continuation_signals=("EVIDENCE_INSUFFICIENT",),
    )
    plans = [
        item for item in governor.future_plan.operations()
        if item.operation == "search.plan"
    ]
    assert len(plans) == 2
    assert plans[0].prediction_reason == "SEARCH_RETURN_CONTINUATION"
    assert plans[1].prediction_reason == "EVIDENCE_INSUFFICIENT"


@pytest.mark.asyncio
async def test_parallel_tool_calls_preserve_future_operation_cardinality():
    governor = RequestResourceGovernor("parallel-tools", "model", shadow_only=True)
    await governor.observe_tool_calls(
        ["task_dispatch", "task_dispatch", "task_dispatch"], source_role="main",
    )
    names = [item.operation for item in governor.future_plan.future_operations()]
    assert names.count("search.plan") == 3
    assert names.count("search.final") == 3

    await governor.observe_tool_calls(
        ["product_search_tool", "product_search_tool"], source_role="search",
    )
    names = [item.operation for item in governor.future_plan.future_operations()]
    assert names.count("embedding.product_query") == 2
    assert names.count("reranker.product") == 2


@pytest.mark.asyncio
async def test_search_final_cancels_only_one_unused_continuation():
    governor = RequestResourceGovernor("search-final", "model", shadow_only=True)
    await governor.observe_tool_calls(["product_search_tool"], source_role="search")
    plans = [
        item for item in governor.future_plan.future_operations()
        if item.operation == "search.plan"
    ]
    assert len(plans) == 1
    await governor.observe_completed_operation("search.final")
    assert governor.future_plan.terminal_state(plans[0].logical_call_id) \
        == FutureOperationState.CANCELLED


@pytest.mark.asyncio
async def test_observed_lifecycle_consumes_future_node_and_recomputes_budget():
    governor = RequestResourceGovernor("lifecycle", "model", shadow_only=True)
    await governor.observe_tool_calls(["product_search_tool"], source_role="main")
    before = governor.snapshot().predicted_unreserved.embedding_tokens

    logical_id = await governor.observe_started_operation("embedding.product_query")
    assert logical_id is not None
    assert governor.future_plan.get(logical_id).state == FutureOperationState.STARTED
    assert governor.snapshot().predicted_unreserved.embedding_tokens < before

    await governor.observe_completed_operation("embedding.product_query")
    assert governor.future_plan.get(logical_id) is None
    governor.future_plan.validate(governor.reservations)
    history = json.loads(governor.plan_revision_history_json())
    assert history[-1]["budget_recomputed"] is True


@pytest.mark.asyncio
async def test_query_processor_placeholder_is_superseded_by_concrete_result():
    governor = RequestResourceGovernor("qp-life", "model", shadow_only=True)
    await governor.observe_tool_calls(["category_insight_tool"], source_role="main")
    placeholder = next(
        item for item in governor.future_plan.operations()
        if item.operation == "query_processor.classify"
    )
    await governor.observe_started_operation("query_processor.classify")
    await governor.observe_query_plan("DIRECT", [])
    assert governor.future_plan.get(placeholder.logical_call_id) is None
    assert governor.future_plan.terminal_state(placeholder.logical_call_id) == FutureOperationState.SUPERSEDED


@pytest.mark.asyncio
async def test_plan_revision_active_reservation_and_retry_invariants():
    governor = RequestResourceGovernor("req", "model", shadow_only=True)
    operation = next(
        item for item in governor.future_plan.operations()
        if item.bucket == FutureBucket.PREDICTED_UNRESERVED
    )
    stale = await governor.try_reserve(operation.logical_call_id, governor.future_plan.revision - 1)
    assert stale.code == ReservationDecisionCode.REPLAN_REQUIRED
    assert stale.execution_allowed is False

    revision = governor.future_plan.revision
    first = await governor.try_reserve(operation.logical_call_id, revision, attempt=1)
    assert first.execution_allowed is True  # shadow never blocks the business call
    assert len(governor.reservations.active_for(operation.logical_call_id)) == 1
    governor.future_plan.validate(governor.reservations)

    await governor.settle(first.reservation_id, None, retry=True)
    assert governor.ledger.entries()[0].usage_source == "estimated_missing_usage"
    assert governor.reservations.active_for(operation.logical_call_id) == ()
    assert governor.future_plan.get(operation.logical_call_id).bucket == FutureBucket.PREDICTED_UNRESERVED

    second = await governor.try_reserve(
        operation.logical_call_id, governor.future_plan.revision, attempt=2,
    )
    assert second.reservation_id != first.reservation_id
    assert len(governor.reservations.active_for(operation.logical_call_id)) == 1
    await governor.settle(second.reservation_id, ResourceEstimate(chat_input_tokens=7), retry=False)
    assert governor.future_plan.get(operation.logical_call_id) is None
    assert governor.ledger.used().chat_total_tokens > 7  # estimated attempt 1 + actual attempt 2


@pytest.mark.asyncio
async def test_concurrent_stale_plan_and_timeout_settlement_are_explicit():
    governor = RequestResourceGovernor("concurrent", "model", shadow_only=True)
    operation = next(
        item for item in governor.future_plan.operations()
        if item.bucket == FutureBucket.PREDICTED_UNRESERVED
    )
    revision = governor.future_plan.revision
    first, second = await asyncio.gather(
        governor.try_reserve(operation.logical_call_id, revision, timeout_seconds=0),
        governor.try_reserve(operation.logical_call_id, revision, timeout_seconds=0),
    )
    assert {first.code, second.code} == {ReservationDecisionCode.ALLOW, ReservationDecisionCode.REPLAN_REQUIRED}
    assert await governor.settle_expired(retry=True) == 1
    assert governor.ledger.entries()[0].usage_source == "estimated_timeout"
    assert governor.reservations.active() == ()


def test_policy_checks_dimensions_but_only_chat_drives_phase_one_action():
    policy = ResourcePolicy()
    evaluation = policy.evaluate(
        ResourceEstimate(chat_input_tokens=20, monetary_cost=Decimal("5"), latency_ms=9999),
        planned_budget=BudgetEnvelope(chat_token_limit=30, monetary_cost_limit=Decimal("1")),
        absolute_hard_cap=BudgetEnvelope(
            chat_token_limit=40, monetary_cost_limit=Decimal("2"), latency_deadline_ms=100,
        ),
    )
    assert evaluation.code == ReservationDecisionCode.ALLOW
    assert evaluation.checks.cost_ok is False
    assert evaluation.checks.latency_ok is False


def test_operation_specific_hard_safety_and_counterfactual_roi():
    adapter = ContextGovernorAdapter(protocol_safety_margin=1000)
    main_limit = adapter.hard_safety_limit(
        model_context_window=100_000, operation="main.final", context_scope=ContextScope.MAIN,
    )
    query_limit = adapter.hard_safety_limit(
        model_context_window=100_000, operation="query_processor.decompose",
        context_scope=ContextScope.QUERY_PROCESSOR,
    )
    assert query_limit > main_limit
    baseline = CompactionBaseline(
        scope=ContextScope.MAIN,
        old_context_revision="old", new_context_revision="new",
        old_context_tokens=50_000, compacted_context_tokens=30_000,
        removed_segment_refs=("ctx_a",), estimator_version="v1", actual_summary_cost=2_000,
    )
    adapter.save_baseline(baseline)
    observed = adapter.observe_post_compaction_call(ContextScope.MAIN, actual_input_tokens=35_000)
    assert observed.counterfactual_input_tokens == 55_000
    assert observed.counterfactual_realized_saving == 20_000
    assert observed.counterfactual_realized_roi == 10


def test_profile_compatibility_does_not_use_git_commit_as_key():
    key = OperationProfileKey(
        environment="dev", component="main", operation="main.final", model="m",
        execution_path="react", context_bucket="medium", candidate_bucket="none",
        prompt_version="p1", policy_version="v1", execution_contract_hash="contract",
    )
    builder = OperationProfileBuilder()
    profile = builder.build(key, [
        {"chat_input_tokens": 10, "chat_output_tokens": 2, "api_calls": 1, "latency_ms": 10},
        {"chat_input_tokens": 20, "chat_output_tokens": 4, "api_calls": 1, "latency_ms": 20},
    ], git_commit="commit-a", relevant_code_version="code-v1")
    store = OperationProfileStore()
    store.put(profile)
    resolved, quality = store.resolve(replace(key, execution_path="react-with-readme-change"))
    assert resolved is profile
    assert quality == "operation_model_context_fallback"
    assert profile.metadata["git_commit"] == "commit-a"
    assert "git_commit" not in OperationProfileKey.__dataclass_fields__


@pytest.mark.asyncio
async def test_agent_model_operation_is_classified_as_plan_without_changing_response():
    class Model:
        model = "test-model"
        context_size = 128_000

        async def count_tokens(self, **kwargs):
            return 100

    agent = SimpleNamespace(name="commerce_concierge", model=Model())
    response = ChatResponse(
        content=[ToolCallBlock(id="c", name="product_search_tool", input="{}")],
        is_last=True,
        usage={"input_tokens": 90, "output_tokens": 10},
    )

    async def next_handler(**kwargs):
        return response

    governor, token = begin_shadow_request("middleware", "test-model")
    try:
        actual = await ResourceOperationTracingMiddleware().on_model_call(
            agent, {"messages": [], "tools": []}, next_handler,
        )
        assert actual is response
        assert governor.ledger.entries()[-1].operation == "main.plan"
        assert governor.ledger.entries()[-1].estimate.chat_total_tokens == 100
    finally:
        end_shadow_request(token)


@pytest.mark.asyncio
async def test_deepseek_estimator_counts_formatted_request_and_stays_shadow_until_promoted():
    class Tokenizer:
        def __init__(self):
            self.last = ""

        def count_payload(self, payload):
            import json
            self.last = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            return len(self.last) // 2

    class Formatter:
        async def format(self, messages):
            return [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "USER"}]

    class Model:
        model = "deepseek-v4.1-flash"
        formatter = Formatter()

        async def count_tokens(self, **kwargs):
            return 7

    tokenizer = Tokenizer()
    estimator = TokenEstimator(deepseek_tokenizer=tokenizer, deepseek_primary=False)
    comparison = await estimator.estimate_openai_payload_comparison(
        {"model": Model.model, "messages": [{"role": "system", "content": "SYSTEM"}],
         "tools": [{"type": "function", "function": {"name": "search"}}],
         "tool_choice": "auto", "enable_thinking": False, "reasoning_effort": "high"},
        operation="main.plan",
    )
    assert comparison.deepseek_v41.method == "deepseek_v41_prompt_encoder"
    assert comparison.deepseek_v41.confidence == "high"
    assert '"role":"system"' in tokenizer.last
    assert '"name":"search"' in tokenizer.last
    assert comparison.input_stage == "final_http_payload"
    assert comparison.request_traits["thinking_mode"] == "disabled"
    assert comparison.request_traits["reasoning_effort"] == "high"
    assert comparison.selected is comparison.legacy


def test_calibration_five_samples_remain_bootstrap_and_cannot_lower_floor():
    from app.infrastructure.resource_governance.estimator import EstimatorCalibration
    calibration = EstimatorCalibration()
    traits = {"provider": "aliyun_bailian", "thinking_mode": "disabled"}
    for _ in range(5):
        calibration.observe("deepseek-v4.1-flash", "main.final", 100, 80, traits=traits)
    status = calibration.status("deepseek-v4.1-flash", "main.final", traits=traits)
    assert status["samples"] == 5
    assert status["confidence"] == "bootstrap"
    assert status["safety_factor"] == 1.20


def test_calibration_confidence_thresholds_and_parent_floor():
    from app.infrastructure.resource_governance.estimator import EstimatorCalibration
    calibration = EstimatorCalibration()
    disabled = {"provider": "aliyun_bailian", "thinking_mode": "disabled"}
    enabled = {"provider": "aliyun_bailian", "thinking_mode": "enabled"}
    for _ in range(30):
        calibration.observe("deepseek-v4.1-flash", "main.plan", 100, 150, traits=disabled)
    for _ in range(30):
        calibration.observe("deepseek-v4.1-flash", "main.final", 100, 90, traits=enabled)
    status = calibration.status("deepseek-v4.1-flash", "main.final", traits=enabled)
    assert status["confidence"] == "medium"
    assert status["safety_factor"] >= 1.50


def test_one_hundred_samples_are_only_high_candidate_before_parity_gate():
    from app.infrastructure.resource_governance.estimator import EstimatorCalibration
    calibration = EstimatorCalibration(high_confidence_enabled=False)
    traits = {"provider": "aliyun_bailian", "thinking_mode": "disabled"}
    for _ in range(100):
        calibration.observe("deepseek-v4.1-flash", "main.final", 100, 110, traits=traits)
    status = calibration.status("deepseek-v4.1-flash", "main.final", traits=traits)
    assert status["samples"] == 100
    assert status["statistical_confidence"] == "high_candidate"
    assert status["confidence"] == "medium"


def test_accounting_reconciliation_and_route_are_explicit():
    governor = RequestResourceGovernor("accounting", "model")
    governor.record_observed_usage(
        logical_call_id="call", attempt=1, operation="main.final",
        estimate=ResourceEstimate(chat_input_tokens=10, chat_output_tokens=2),
    )
    report = governor.accounting_reconciliation(provider_actual_chat_tokens=12)
    assert report["ok"] is True
    assert report["difference"] == 0
    route = WorkloadPredictor.classify_route(
        ["query_processor.decompose", "reranker.knowledge.need"],
        query_mode="DECOMPOSE",
    )
    assert route.route == "knowledge_decompose"

