from scripts.resource_governance.causal_replay import (
    _budget_revision_response, _future_overlap, _lifecycle_statistics,
)


def test_cost_weighted_future_recall_prioritizes_expensive_operation():
    result = _future_overlap(
        [
            {"operation": "search.final", "chat_tokens": 30_000},
            {"operation": "embedding.product_query", "embedding_tokens": 30},
        ],
        ["search.final"],
        {},
    )
    assert result["future_operation_recall"] == 0.5
    assert result["cost_weighted_future_recall"] > 0.99
    assert result["high_cost_future_recall"] == 1.0


def test_budget_gate_requires_recompute_not_numeric_change():
    result = _budget_revision_response([
        {
            "case_id": "c1", "revision_sequence": 0,
            "predicted_operations": ["main.final"], "visible_route": "simple",
            "visible_information_need_count": None, "planned_budget": 50_000,
            "budget_recomputed": True,
        },
        {
            "case_id": "c1", "revision_sequence": 1,
            "predicted_operations": ["main.final", "reranker.product"], "visible_route": "simple",
            "visible_information_need_count": None, "planned_budget": 50_000,
            "budget_recomputed": True, "budget_unchanged_reason": "SAME_COST_BUCKET",
        },
    ])
    assert result["budget_recomputation_rate"] == 1.0
    assert result["stale_not_recomputed_count"] == 0
    assert result["unchanged_budget_reason_distribution"] == {"SAME_COST_BUCKET": 1}


def test_lifecycle_statistics_counts_terminal_removal_and_qp_replace():
    result = _lifecycle_statistics([{
        "future_operation_transitions": [
            {"new_state": "planned", "operation": "query_processor.classify", "transition_reason": "added"},
            {
                "new_state": "superseded", "operation": "query_processor.classify",
                "transition_reason": "placeholder_replaced_by_direct",
            },
            {"new_state": "completed", "operation": "main.plan", "transition_reason": "observed_completed"},
        ],
    }])
    assert result["obsolete_node_removal_count"] == 2
    assert result["query_processor_placeholder_replace_count"] == 1

