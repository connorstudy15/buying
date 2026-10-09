import httpx

from scripts.resource_governance.run_phase25_benchmark import response_error_type
from scripts.resource_governance.phase25_report import build_report


def test_http_200_does_not_hide_explicit_agent_error():
    assert response_error_type(httpx.Response(200, json={
        "final_text": "[error] Error code: 402 - Insufficient Balance",
    })) == "provider_insufficient_balance"
    assert response_error_type(httpx.Response(200, json={
        "final_text": "[error] execution failed",
    })) == "agent_execution_error"
    assert response_error_type(httpx.Response(200, json={"final_text": "正常回复"})) is None


def test_turn_error_is_not_hidden_by_successful_http_root():
    report = build_report([
        {"traceId": "t", "name": "POST /commerce/intents", "level": "DEFAULT"},
        {"traceId": "t", "name": "commerce.turn", "level": "ERROR", "metadata": {
            "globex.resource.predicted_request_tokens": 100,
            "globex.resource.actual_request_tokens": 0,
        }},
    ])
    assert report["request_rows"][0]["execution_status"] == "ERROR"
