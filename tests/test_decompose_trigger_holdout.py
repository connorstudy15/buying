from pathlib import Path

from scripts.eval.run_decompose_trigger import load_holdout, metrics


def test_trigger_holdout_is_balanced_and_frozen():
    rows = load_holdout(Path("eval/knowledge/v5/decompose_trigger_holdout_20.jsonl"))
    assert len(rows) == 20
    assert sum(row["expected_query_strategy"] == "DIRECT" for row in rows) == 10
    assert sum(row["expected_query_strategy"] == "DECOMPOSE" for row in rows) == 10


def test_trigger_metrics_keep_fallback_out_of_true_negative_count():
    rows = [
        {"case_id": "tp", "expected": "DECOMPOSE", "model_predicted_decompose": True,
         "predicted_decompose": True, "fallback": False,
         "latency_ms": 1, "usage": {}},
        {"case_id": "tn", "expected": "DIRECT", "model_predicted_decompose": False,
         "predicted_decompose": False, "fallback": False,
         "latency_ms": 2, "usage": {}},
        {"case_id": "fallback", "expected": "DIRECT", "model_predicted_decompose": False,
         "predicted_decompose": False, "fallback": True,
         "latency_ms": 3, "usage": {}},
    ]
    result = metrics(rows)
    assert result["tp"] == 1 and result["tn"] == 1
    assert result["precision"] == 1 and result["recall"] == 1
    assert result["fallback_rate"] == 1 / 3
    assert result["accuracy"] == 2 / 3


def test_trigger_fallback_on_decompose_counts_as_false_negative():
    rows = [
        {"case_id": "fallback", "expected": "DECOMPOSE", "model_predicted_decompose": True,
         "predicted_decompose": False,
         "fallback": True, "latency_ms": 1, "usage": {}},
    ]
    result = metrics(rows)
    assert result["fn"] == 1
    assert result["recall"] == 0
    assert result["model_decision_recall"] == 1
    assert result["effective_decompose_recall"] == 0
    assert result["false_negative_ids"] == ["fallback"]
