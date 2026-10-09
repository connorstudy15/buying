import copy
import json
from dataclasses import replace

import pytest

from app.infrastructure.resource_governance.continuation import (
    ContinuationDiagnostics, TransitionProfileStore, TrainingSample, training_samples,
)
from app.infrastructure.resource_governance.governor import RequestResourceGovernor
from app.infrastructure.resource_governance.runtime import RuntimeObservation
from app.infrastructure.tracing import _sanitize_attributes
from scripts.resource_governance.evaluate_continuation import evaluate


def state(operation="tool.product_search_tool.result", **kwargs):
    return {"flow_id": "main", "sequence": 1, "last_operation": operation,
            "agent_role": "main", "last_agent": "main", "current_route": "product_search",
            "required_need_remaining": 1, "need_scope_complete": False,
            "evidence_sufficient": None, "main_plan_round": 1, "search_plan_round": 0,
            **kwargs}


def request(trace_id="train", case="train-case", flow="main", ops=None):
    ops = ops or ["tool.product_search_tool.result", "main.plan", "main.final"]
    return {"trace_id": trace_id, "case_id": case, "runtime_progress_events": [
        {"after": state(op, sequence=i + 1, flow_id=flow)} for i, op in enumerate(ops)
    ]}


def test_labels_are_same_flow_and_features_cannot_see_future():
    data = request()
    data["runtime_progress_events"].insert(1, {"after": state("search.plan", sequence=1, flow_id="child", agent_role="search")})
    samples = training_samples([data])
    main = [sample for sample in samples if sample.flow_id == "main"]
    assert main[0].next_operation == "main.plan"
    assert main[0].remaining_main_plan_rounds == 1
    assert main[0].remaining_search_plan_rounds == 0
    before = copy.deepcopy(main[0].state)
    data["runtime_progress_events"][-1]["after"].update(current_route="future-secret", required_need_remaining=99)
    assert training_samples([data])[0].state == before


def test_incomplete_and_gapped_exports_cannot_create_zero_loop_labels():
    samples = training_samples([request(ops=["main.plan", "tool.product_search_tool.result"])])
    assert samples[-1].next_operation is None
    assert all(sample.remaining_main_plan_rounds is None for sample in samples)
    data = request()
    data["runtime_progress_events"][1]["after"]["sequence"] = 10
    assert training_samples([data]) == []


def test_next_completion_skips_permitted_start_events():
    samples = training_samples([request(ops=["main.plan", "tool.permitted", "tool.product_search_tool.result", "main.final"])])
    assert samples[0].next_operation == "tool.product_search_tool.result"
    assert samples[1].next_operation == "tool.product_search_tool.result"


def test_existing_phase25_report_format_is_supported():
    from scripts.resource_governance.evaluate_continuation import _requests
    assert _requests({"request_rows": []}) == []


def test_final_then_parent_result_is_invalid_child_lifecycle():
    assert training_samples([request(ops=["search.plan", "search.final", "tool.task_dispatch.result"])]) == []


def test_one_of_one_never_becomes_certain_or_high_confidence():
    store = TransitionProfileStore()
    sample = TrainingSample("t", "case", "main", 1, state(), "main.plan", 2, 0)
    store.fit([sample])
    result = ContinuationDiagnostics(store).predict(state())
    assert 0 < result["next_operation"]["distribution"]["main.plan"] < 1
    assert sum(result["next_operation"]["distribution"].values()) == pytest.approx(1)
    assert result["next_operation"]["confidence"] == "LOW"
    assert result["remaining_rounds"]["main"]["expected"] == 2
    assert result["remaining_rounds"]["main"]["p95"] is None


def test_many_events_from_one_case_do_not_make_profile_medium_or_tail_ready():
    store = TransitionProfileStore()
    store.fit([TrainingSample(f"t{i}", "same-case", "main", 1, state(), "main.plan", 3, 0) for i in range(120)])
    result = ContinuationDiagnostics(store).predict(state())
    assert result["next_operation"]["confidence"] == "LOW"
    assert result["remaining_rounds"]["main"]["p50"] is None
    assert result["remaining_rounds"]["main"]["p95"] is None


def test_hierarchical_backoff_and_supported_quantiles():
    store = TransitionProfileStore()
    store.fit([TrainingSample(f"t{i}", f"case{i}", "main", 1, state(), "main.plan", i % 5, 0) for i in range(120)])
    result = ContinuationDiagnostics(store).predict(state(current_route="new-route"))
    assert result["next_operation"]["profile_level"] == 2
    assert result["next_operation"]["confidence"] == "MEDIUM"
    assert result["remaining_rounds"]["main"]["p50"] <= result["remaining_rounds"]["main"]["p80"] <= result["remaining_rounds"]["main"]["p95"]


def test_zero_progress_is_value_warning_not_forced_execution_discount():
    predictor = ContinuationDiagnostics()
    good = predictor.predict(state(last_progress_class="HIGH_PROGRESS", zero_progress_streak=0))
    zero = predictor.predict(state(last_progress_class="ZERO_PROGRESS", zero_progress_streak=3))
    assert good["next_operation"]["distribution"] == zero["next_operation"]["distribution"]
    assert zero["value_diagnostic"] == "PIVOT_CANDIDATE"
    assert zero["remaining_rounds"]["progress_discount_applied"] is False


def test_bootstrap_does_not_invent_remaining_rounds_or_p95():
    result = ContinuationDiagnostics().predict(state())
    assert result["next_operation"]["confidence"] == "BOOTSTRAP"
    assert result["remaining_rounds"]["main"]["expected"] is None
    assert result["remaining_rounds"]["main"]["p95"] is None


def test_scalar_transport_survives_truncated_json_preview_and_rejects_missing_fields():
    from app.infrastructure.resource_governance.runtime_trace import runtime_trace_fields, restore_runtime_trace
    row = {"event_id": "e", "before": state(), "after": state(),
           "forecast": ContinuationDiagnostics().predict(state())}
    attrs = _sanitize_attributes(runtime_trace_fields(row), content_mode="off")
    restored = restore_runtime_trace(attrs, timestamp="now")
    assert restored["after"] == row["after"]
    assert restored["forecast"] == row["forecast"]
    attrs.pop("globex.resource.runtime_field.after/sequence")
    assert restore_runtime_trace(attrs, timestamp="now") is None


def test_terminal_is_protocol_rule_not_statistical_confidence():
    result = ContinuationDiagnostics().predict(state("main.final"))
    assert result["next_operation"]["distribution"] == {"END": 1.0}
    assert result["next_operation"]["profile_level"] == "protocol_terminal"
    assert result["remaining_rounds"]["main"]["expected"] == 0
    assert result["mandatory_probability_discount_applied"] is False


def test_train_validation_overlap_is_rejected_including_repeated_case():
    store = TransitionProfileStore()
    store.fit(training_samples([request()]))
    with pytest.raises(ValueError, match="overlap"):
        evaluate(store, [request("new-trace", "train-case")])
    with pytest.raises(ValueError, match="overlap"):
        evaluate(store, [request("train", "new-case")])


def test_profile_roundtrip_version_and_duplicate_sample_guards():
    store = TransitionProfileStore()
    samples = training_samples([request()])
    store.fit(samples)
    with pytest.raises(ValueError, match="duplicate"):
        store.fit(samples)
    loaded = TransitionProfileStore.from_json(json.loads(json.dumps(store.write_json())))
    assert ContinuationDiagnostics(loaded).predict(state()) == ContinuationDiagnostics(store).predict(state())
    with pytest.raises(ValueError, match="immutable"):
        loaded.fit([])
    with pytest.raises(ValueError, match="version"):
        TransitionProfileStore.from_json({"version": "wrong"})


def test_validation_metrics_do_not_count_trivial_terminal_accuracy():
    store = TransitionProfileStore()
    store.fit(training_samples([request()]))
    report = evaluate(store, [request("val", "val-case")])
    assert report["summary"]["N"] == 2
    assert report["phase3_decision"] == "NO_GO"
    assert report["summary"]["main"]["p95_empirical_coverage"] is None
    assert report["summary"]["main"]["p95_coverage_N"] == 0


def test_running_predictor_is_a_frozen_profile_snapshot():
    store = TransitionProfileStore()
    predictor = ContinuationDiagnostics(store)
    before = predictor.predict(state())
    store.fit(training_samples([request()]))
    assert predictor.predict(state()) == before
    with pytest.raises(ValueError, match="immutable"):
        predictor.store.fit([])


def test_evaluator_command_produces_separate_profile_and_report(tmp_path, monkeypatch, capsys):
    from scripts.resource_governance.evaluate_continuation import main
    calibration = tmp_path / "calibration.json"
    validation = tmp_path / "validation.json"
    report = tmp_path / "report.json"
    profile = tmp_path / "profile.json"
    calibration.write_text(json.dumps({"request_rows": [request()]}), encoding="utf-8")
    validation.write_text(json.dumps({"request_rows": [request("validation", "validation-case")]}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["evaluate_continuation.py", "--calibration", str(calibration),
                                    "--validation", str(validation), "--output", str(report),
                                    "--profile-output", str(profile)])
    main()
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["status"] == "OFFLINE_DIAGNOSTIC_ONLY"
    assert result["summary"]["N"] == 2
    assert result["bootstrap_baseline_summary"]["main"]["remaining_round_count_MAE"] is None
    assert TransitionProfileStore.from_json(json.loads(profile.read_text(encoding="utf-8"))).groups == {"train-case"}


@pytest.mark.asyncio
async def test_forecast_does_not_mutate_governor_plan_budget_or_usage():
    governor = RequestResourceGovernor("shadow", "model")
    before = governor.future_work_plan_json(), governor.planned_budget, governor.ledger.used()
    await governor.observe_runtime(RuntimeObservation("event", "main", "main.plan", agent="main"))
    row = governor.runtime.history[-1]
    assert row["forecast"]["action_driving"] is False
    assert row["after"]["agent_role"] == "main"
    assert (governor.future_work_plan_json(), governor.planned_budget, governor.ledger.used()) == before
    attrs = _sanitize_attributes({"globex.resource.continuation_forecast": json.dumps(row["forecast"])}, content_mode="off")
    assert json.loads(attrs["globex.resource.continuation_forecast"])["shadow_only"]


@pytest.mark.asyncio
async def test_dispatch_result_is_parent_event_not_after_child_terminal():
    from agentscope.message import ToolCallBlock, ToolResultState
    from agentscope.tool import ToolChunk
    from app.infrastructure.resource_governance.governor import begin_shadow_request, end_shadow_request
    from app.infrastructure.resource_governance.middleware import ResourceOperationTracingMiddleware
    from app.infrastructure.resource_governance.operation import current_execution
    governor, token = begin_shadow_request("dispatch", "model")
    call = ToolCallBlock(id="d", name="task_dispatch", input='{"subagent_type":"search_agent","demands":"test"}')
    async def handler(**kwargs):
        assert current_execution().flow_id == "dispatch:d"
        await governor.observe_runtime(RuntimeObservation("child-final", "dispatch:d", "search.final", agent="search"))
        yield ToolChunk(content=[], state=ToolResultState.SUCCESS)
    try:
        middleware = ResourceOperationTracingMiddleware.__new__(ResourceOperationTracingMiddleware)
        _ = [part async for part in middleware.on_acting(None, {"tool_call": call}, handler)]
        history = governor.runtime.history
        assert [row["after"]["flow_id"] for row in history] == ["main", "dispatch:d", "main"]
        samples = training_samples([{"trace_id": "d", "runtime_progress_events": history}])
        child = [sample for sample in samples if sample.flow_id == "dispatch:d"]
        assert child[-1].next_operation == "END"
    finally:
        end_shadow_request(token)
