from scripts.resource_governance.replay_langfuse import replay


def observation(trace_id, obs_id, name, kind, input_tokens=None, output_tokens=None, start="2026-01-01"):
    row = {"traceId": trace_id, "id": obs_id, "name": name, "type": kind, "startTime": start}
    if input_tokens is not None:
        row["usageDetails"] = {"input": input_tokens, "output": output_tokens}
    return row


def test_historical_replay_is_content_free_and_reports_prediction_error():
    rows = [
        observation("a" * 32, "root", "POST /commerce/ag-ui/run", "SPAN"),
        observation("a" * 32, "g1", "chat model", "GENERATION", 10_000, 500, "2026-01-01T00:00:01Z"),
        observation("a" * 32, "g2", "chat model", "GENERATION", 20_000, 1_000, "2026-01-01T00:00:02Z"),
    ]
    report = replay(rows)
    assert report["content_read"] is False
    assert report["trace_count"] == 1
    item = report["observations"][0]
    assert item["actual_chat_tokens"] == 31_500
    assert item["predicted_expected_chat_tokens"] > item["actual_chat_tokens"]
    assert item["planned_chat_limit"] > item["predicted_expected_chat_tokens"]
    assert report["legacy_profile_samples"] == {"main.plan": 1, "main.final": 1}

