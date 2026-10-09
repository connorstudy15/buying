from app.infrastructure.resource_governance.calibration import error_metrics, phase3_gate
from app.infrastructure.resource_governance.estimator import (
    DEEPSEEK_V41_TOKENIZER_SHA256,
    TokenEstimator,
)
from scripts.resource_governance.phase25_report import build_report
from scripts.resource_governance.replay_langfuse import FIELDS


def test_langfuse_replay_requests_observation_metadata():
    assert "metadata" in FIELDS.split(",")


def test_bundled_deepseek_v41_tokenizer_has_official_digest():
    status = TokenEstimator().tokenizer_status()
    assert status["asset_status"] == "verified"
    assert status["asset_sha256"] == DEEPSEEK_V41_TOKENIZER_SHA256


def test_deepseek_v41_tokenizer_hash_mismatch_is_not_ready(tmp_path):
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text("{}", encoding="utf-8")
    status = TokenEstimator(tokenizer_path=tokenizer).tokenizer_status()
    assert status["asset_status"] == "hash_mismatch"
    assert status["high_confidence_ready"] is False


def test_underprediction_metrics_are_reported_separately():
    metrics = error_metrics([
        {"predicted": 80, "actual": 100},
        {"predicted": 120, "actual": 100},
    ], predicted_key="predicted", actual_key="actual")
    assert metrics["underprediction_rate"] == .5
    assert metrics["underprediction_p95"] == 20
    assert metrics["overprediction_rate"] == .5


def test_no_underprediction_is_reported_as_zero_not_missing():
    metrics = error_metrics([
        {"predicted": 120, "actual": 100},
        {"predicted": 100, "actual": 100},
    ], predicted_key="predicted", actual_key="actual")
    assert metrics["underprediction_count"] == 0
    assert metrics["underprediction_rate"] == 0
    assert metrics["underprediction_p95"] == 0
    assert metrics["underprediction_ratio_p95"] == 0


def test_phase25_report_reconciles_and_compares_estimators():
    trace_id = "a" * 32
    rows = [
        {
            "traceId": trace_id, "name": "POST /commerce/ag-ui/run", "type": "SPAN",
            "metadata": {
                "globex.resource.predicted_request_tokens": 120,
                "globex.resource.actual_request_tokens": 100,
                "globex.resource.planned_chat_limit": 140,
                "globex.resource.absolute_chat_hard_cap": 80000,
                "globex.resource.active_reserved_chat_tokens": 0,
                "globex.resource.prediction_route": "simple_direct",
            },
        },
        {
            "traceId": trace_id, "id": "op", "name": "resource.model_operation", "type": "SPAN",
            "metadata": {
                "globex.resource.logical_call_id": "call-1",
                "globex.resource.operation": "main.final",
                "globex.resource.attempt": 1,
                "globex.resource.actual_input_tokens": 90,
                "globex.resource.actual_output_tokens": 10,
                "globex.resource.old_estimated_prompt_tokens": 80,
                "globex.resource.deepseek_estimated_prompt_tokens": 88,
                "globex.resource.estimated_input_tokens_safe": 96,
                "globex.resource.local_estimated_output_reserve": 20,
                "globex.resource.profile_confidence": "bootstrap",
            },
        },
        {
            "traceId": trace_id, "id": "generation", "name": "chat deepseek-v4.1-flash",
            "type": "GENERATION", "usageDetails": {"input": 90, "output": 10},
        },
    ]
    report = build_report(rows)
    assert report["accounting"]["error_count"] == 0
    assert report["tokenizer_comparison"]["legacy"]["mae"] == 10
    assert report["tokenizer_comparison"]["deepseek_v41"]["mae"] == 2
    assert report["profile_confidence_distribution"] == {"bootstrap": 1}
    request = report["request_rows"][0]
    assert request["initial_route_comparable"] is False
    assert request["error_attribution"]["route_selection_error"] is None
    assert request["route_mismatch_reason"] == "initial_route_is_bootstrap_placeholder"
    assert report["phase3_gate"]["decision"] == "NO_GO"


def test_phase25_report_accepts_rest_root_and_filters_by_manifest_trace():
    included = "b" * 32
    excluded = "c" * 32
    rows = []
    for trace_id in (included, excluded):
        rows.extend([
            {
                "traceId": trace_id, "name": "POST /commerce/intents", "type": "SPAN",
                "metadata": {
                    "attributes.http.route": "/commerce/intents",
                },
            },
            {
                "traceId": trace_id, "name": "commerce.turn", "type": "CHAIN",
                "metadata": {
                    "attributes.globex.resource.predicted_request_tokens": 100,
                    "attributes.globex.resource.actual_request_tokens": 100,
                    "attributes.globex.resource.planned_chat_limit": 120,
                    "attributes.globex.resource.absolute_chat_hard_cap": 80000,
                    "attributes.globex.resource.active_reserved_chat_tokens": 0,
                    "attributes.globex.resource.prediction_route": "knowledge_direct",
                },
            },
            {
                "traceId": trace_id, "id": f"op-{trace_id}",
                "name": "resource.model_operation", "type": "SPAN",
                "metadata": {
                    "attributes.globex.resource.logical_call_id": f"call-{trace_id}",
                    "attributes.globex.resource.operation": "main.final",
                    "attributes.globex.resource.attempt": 1,
                    "attributes.globex.resource.actual_input_tokens": 90,
                    "attributes.globex.resource.actual_output_tokens": 10,
                    "attributes.globex.resource.old_estimated_prompt_tokens": 80,
                    "attributes.globex.resource.deepseek_estimated_prompt_tokens": 88,
                    "attributes.globex.resource.estimated_input_tokens_safe": 90,
                    "attributes.globex.resource.local_estimated_output_reserve": 10,
                    "attributes.globex.resource.profile_confidence": "bootstrap",
                },
            },
            {
                "traceId": trace_id, "id": f"generation-{trace_id}",
                "name": "chat deepseek-v4.1-flash", "type": "GENERATION",
                "usageDetails": {"input": 90, "output": 10},
            },
        ])

    report = build_report(rows, case_map={
        included: {"case_id": "blind-001", "query_type": "multi_hop", "latency_ms": 1234.5},
    })

    assert report["trace_count"] == 1
    assert report["accounting"]["trace_count"] == 1
    assert report["request_rows"][0]["case_id"] == "blind-001"
    assert report["request_rows"][0]["latency_ms"] == 1234.5
    assert report["query_type_buckets"]["multi_hop"]["n"] == 1
    assert report["query_type_buckets"]["multi_hop"]["latency_p50"] == 1234.5


def test_phase25_report_uses_commerce_turn_as_lifecycle_owner_without_http_root():
    trace_id = "e" * 32
    report = build_report([
        {
            "traceId": trace_id, "name": "commerce.turn", "type": "CHAIN",
            "metadata": {
                "attributes.globex.resource.lifecycle_owner": "commerce.turn",
                "attributes.globex.resource.predicted_request_tokens": 100,
                "attributes.globex.resource.actual_request_tokens": 90,
                "attributes.globex.resource.planned_chat_limit": 120,
                "attributes.globex.resource.absolute_chat_hard_cap": 80000,
            },
        },
    ], case_map={trace_id: {"case_id": "case", "query_type": "single_evidence"}})
    assert report["trace_count"] == 1
    assert report["request_rows"][0]["case_id"] == "case"


def test_query_processor_usage_is_not_mistaken_for_generation_mismatch():
    trace_id = "d" * 32
    rows = [
        {
            "traceId": trace_id, "name": "POST /commerce/intents", "type": "SPAN",
        },
        {
            "traceId": trace_id, "name": "commerce.turn", "type": "CHAIN",
            "metadata": {
                "attributes.globex.resource.predicted_request_tokens": 150,
                "attributes.globex.resource.actual_request_tokens": 150,
                "attributes.globex.resource.planned_chat_limit": 180,
                "attributes.globex.resource.active_reserved_chat_tokens": 0,
            },
        },
        {
            "traceId": trace_id, "id": "main", "name": "resource.model_operation",
            "type": "SPAN", "metadata": {
                "attributes.globex.resource.logical_call_id": "main-call",
                "attributes.globex.resource.operation": "main.final",
                "attributes.globex.resource.attempt": 1,
                "attributes.globex.resource.actual_input_tokens": 90,
                "attributes.globex.resource.actual_output_tokens": 10,
            },
        },
        {
            "traceId": trace_id, "id": "qp", "name": "knowledge.query_processor",
            "type": "CHAIN", "metadata": {
                "attributes.globex.resource.logical_call_id": "qp-call",
                "attributes.globex.resource.operation": "query_processor.direct",
                "attributes.globex.resource.attempt": 1,
                "attributes.globex.resource.actual_input_tokens": 40,
                "attributes.globex.resource.actual_output_tokens": 10,
            },
        },
        {
            "traceId": trace_id, "id": "generation", "name": "chat deepseek-v4.1-flash",
            "type": "GENERATION", "usageDetails": {"input": 90, "output": 10},
        },
    ]

    report = build_report(rows)
    accounting = report["accounting"]
    assert accounting["error_count"] == 0
    assert accounting["rows"][0]["ledger_or_resource_chat_total"] == 150
    assert accounting["rows"][0]["generation_comparable_resource_total"] == 100
    assert accounting["rows"][0]["external_model_chat_total"] == 50


def test_phase3_gate_requires_every_condition():
    report = {
        "trace_count": 134,
        "unique_case_count": 67,
        "minimum_case_repetitions": 2,
        "golden_tokenizer_parity_passed": True,
        "retrieval_quality_regression_passed": True,
        "accounting": {"error_count": 0, "reservation_leak_count": 0,
                       "duplicate_attempt_count": 0, "stale_plan_execution_count": 0},
        "request_prediction": {"underprediction_rate": 0.05, "underprediction_ratio_p95": 0.08},
        "main_final_prediction": {"n": 1, "underprediction_ratio_p95": 0.08},
        "planned_budget_exceed_rate": 0.05,
        "mandatory_erroneous_rejection_count": 0,
        "main_final_protection_failure_count": 0,
    }
    assert phase3_gate(report)["decision"] == "GO"


def test_phase3_gate_accepts_measured_zero_main_final_underprediction():
    report = {
        "trace_count": 134,
        "unique_case_count": 67,
        "minimum_case_repetitions": 2,
        "golden_tokenizer_parity_passed": True,
        "retrieval_quality_regression_passed": True,
        "accounting": {"error_count": 0, "reservation_leak_count": 0,
                       "duplicate_attempt_count": 0, "stale_plan_execution_count": 0},
        "request_prediction": {"underprediction_rate": 0.05, "underprediction_ratio_p95": 0.08},
        "main_final_prediction": {"n": 134, "underprediction_count": 0,
                                  "underprediction_rate": 0,
                                  "underprediction_ratio_p95": 0},
        "planned_budget_exceed_rate": 0.05,
        "mandatory_erroneous_rejection_count": 0,
        "main_final_protection_failure_count": 0,
    }
    assert phase3_gate(report)["conditions"][
        "main_final_underprediction_p95_ratio_lte_10pct"
    ] is True
