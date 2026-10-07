import pytest

from scripts.eval.evaluate_dual_tower_retriever import evaluate
from scripts.eval.validate_dual_tower_splits import validate_splits


def ranking(query_id, ordered):
    return {"query_id": query_id, "candidates": [
        {"candidate_id": candidate_id, "source": source, "score": score, "evidence_ids": evidence}
        for candidate_id, source, score, evidence in ordered
    ]}


def test_retriever_evaluator_reports_rank_movement_buckets_and_regressions():
    queries = [
        {"query_id": "q1", "case_id": "v4-006", "query": "耐用吗", "gold_evidence_ids": ["g1"],
         "hard_negative_sources": ["negative.md"], "buckets": ["DIRECT", "single_evidence"]},
        {"query_id": "q2", "case_id": "cross", "query": "规则", "gold_evidence_ids": ["g2", "g3"],
         "buckets": ["DECOMPOSE_SUBQUERY", "multi_evidence", "implicit_cross_domain", "domain_rule"]},
    ]
    baseline = [
        ranking("q1", [("n", "negative.md", .9, []), ("x", "x.md", .8, []), ("p", "p.md", .7, ["g1"])]),
        ranking("q2", [("p2", "a.md", .8, ["g2"]), ("p3", "b.md", .7, ["g3"])]),
    ]
    dual = [
        ranking("q1", [("p", "p.md", .95, ["g1"]), ("n", "negative.md", .5, [])]),
        ranking("q2", [("p2", "a.md", .9, ["g2"]), ("x", "x.md", .8, []), ("p3", "b.md", .7, ["g3"])]),
    ]
    result = evaluate(queries, baseline, dual)
    assert result["dual_tower"]["mrr"] > result["baseline"]["mrr"]
    movement = next(row for row in result["rank_movements"] if row["evidence_id"] == "g1")
    assert movement["old_rank"] == 3 and movement["dual_tower_rank"] == 1 and movement["delta"] == 2
    assert result["baseline"]["hard_negative_outrank_positive_rate"] == 1.0
    assert result["dual_tower"]["hard_negative_outrank_positive_rate"] == 0.0
    assert "DIRECT" in result["bucket_metrics"] and "domain_rule" in result["bucket_metrics"]
    assert result["strict_regression_query_ids_at_24"] == []


def test_split_validator_blocks_frozen_query_and_positive_evidence_leakage():
    train = [{
        "sample_id": "t1", "split": "train", "group_id": "g1", "query": "冻结问题",
        "positive": {"evidence_id": "gold-1", "text": "答案"},
        "hard_negatives": [{"evidence_id": "neg-1", "text": "错误答案"}],
        "provenance": {"benchmark_derived": False, "review_status": "human_approved"},
    }]
    validation = [{
        "sample_id": "v1", "split": "validation", "group_id": "g2", "query": "验证问题",
        "positive": {"evidence_id": "val-1", "text": "验证答案"},
        "hard_negatives": [{"evidence_id": "val-neg", "text": "错误"}],
        "provenance": {"benchmark_derived": False, "review_status": "human_approved"},
    }]
    frozen = [{"query_id": "f1", "case_id": "f1", "query": "冻结问题", "gold_evidence_ids": ["gold-1"]}]
    with pytest.raises(ValueError, match="train/frozen normalized query overlap"):
        validate_splits(train, validation, frozen)
