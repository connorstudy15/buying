from app.infrastructure import tracing
from scripts.eval.langfuse_trace import result_attributes


def test_eval_attributes_are_numeric_or_bounded_labels_and_never_include_content():
    attributes = result_attributes({
        "query": "private query",
        "retrieved": ["private evidence"],
        "latency_ms": 12.5,
        "retrieval_mode": "query_transform_decompose",
        "evidence_recall": 0.5,
        "query_processor_usage": {"input_tokens": 11, "output_tokens": 7},
        "per_need_rerank_calls": [{"latency_ms": 20, "usage": {"total_tokens": 31}}],
    })

    assert "private query" not in repr(attributes)
    assert "private evidence" not in repr(attributes)
    assert attributes["globex.eval.reranker_call_count"] == 1
    assert attributes["globex.eval.reranker_total_tokens"] == 31


def test_eval_whitelist_drops_unapproved_free_text():
    clean = tracing._sanitize_attributes({
        "globex.eval.case_id": "v4-001",
        "globex.eval.evidence_recall": 0.5,
        "globex.eval.query": "must never leave the process",
    })

    assert clean == {
        "globex.eval.case_id": "v4-001",
        "globex.eval.evidence_recall": 0.5,
    }


def test_retrieval_step_whitelist_keeps_diagnostics_but_drops_query_text():
    clean = tracing._sanitize_attributes({
        "globex.retrieval.stage": "reranker_attempt",
        "globex.retrieval.need_id": "baggage_policy",
        "globex.retrieval.attempt": 2,
        "globex.retrieval.latency_ms": 3000.0,
        "globex.retrieval.degraded": True,
        "globex.retrieval.query_text": "private user text",
    })

    assert clean == {
        "globex.retrieval.stage": "reranker_attempt",
        "globex.retrieval.need_id": "baggage_policy",
        "globex.retrieval.attempt": 2,
        "globex.retrieval.latency_ms": 3000.0,
        "globex.retrieval.degraded": True,
    }
