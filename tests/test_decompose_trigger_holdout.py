from pathlib import Path

from scripts.eval.run_decompose_trigger import load_holdout, metrics


def test_trigger_holdout_is_balanced_and_frozen():
    rows = load_holdout(Path("eval/knowledge/v5/decompose_trigger_holdout_20.jsonl"))
    assert len(rows) == 20
    assert sum(row["expected_query_strategy"] == "DIRECT" for row in rows) == 10
    assert sum(row["expected_query_strategy"] == "DECOMPOSE" for row in rows) == 10


def test_trigger_metrics_keep_fallback_out_of_true_negative_count():
    rows = [
        {"case_id": "tp", "expected": "DECOMPOSE", "predicted_decompose": True, "fallback": False,
         "latency_ms": 1, "usage": {}},
        {"case_id": "tn", "expected": "DIRECT", "predicted_decompose": False, "fallback": False,
         "latency_ms": 2, "usage": {}},
        {"case_id": "fallback", "expected": "DIRECT", "predicted_decompose": False, "fallback": True,
         "latency_ms": 3, "usage": {}},
    ]
    result = metrics(rows)
    assert result["tp"] == 1 and result["tn"] == 1
    assert result["precision"] == 1 and result["recall"] == 1
    assert result["fallback_rate"] == 1 / 3
