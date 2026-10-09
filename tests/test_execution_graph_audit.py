from scripts.resource_governance.analyze_execution_graph import analyze


def test_execution_graph_audit_does_not_treat_bootstrap_route_as_error():
    report = {
        "request_rows": [{
            "trace_id": "t1",
            "case_id": "case-1",
            "query_type": "multi_hop",
            "route": "knowledge_decompose",
            "initial_route": "unknown_one_plan_plus_final",
            "predicted_operation_count": 2,
            "actual_operation_count": 5,
            "predicted_request_tokens": 100,
            "actual_request_tokens": 200,
            "subquery_count": 2,
            "final_context_tokens": 50,
        }],
        "operation_rows": [
            {"trace_id": "t1", "operation": "main.plan"},
            {"trace_id": "t1", "operation": "main.plan"},
            {"trace_id": "t1", "operation": "query_processor.decompose"},
            {"trace_id": "t1", "operation": "main.final"},
        ],
    }
    audit = analyze(report)
    assert audit["route_selection_diagnostic"]["finding"] == "report_bug"
    assert audit["most_frequently_missing_operations"][0] == {
        "operation": "main.plan", "count": 1,
    }
    row = audit["execution_graph_rows"][0]
    assert row["missing_operations"]["query_processor.decompose"] == 1
    assert row["missing_operations"]["unclassified_observed_resource_operation"] == 1
    assert audit["replay"]["status"] == "BLOCKED_MISSING_CAUSAL_EVENTS"
