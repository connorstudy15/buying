from app.infrastructure.eventbus import TradeEvent
from app.infrastructure.turn_trace import TurnTraceCollector


def event(kind, payload):
    return TradeEvent("session-1", kind, payload, "now")


def test_turn_trace_distinguishes_supplied_evidence_from_observable_adoption():
    collector = TurnTraceCollector("session-1")
    collector.observe(event("agent.dispatch", {"agent": "search_agent", "demands": "private"}))
    collector.observe(event("tool.invoke", {"tool": "product_search_tool"}))
    collector.observe(event("tool.result", {
        "tool": "product_search_tool",
        "result_ref": "ctx_products",
        "hits": [{"product_id": "P1008", "skus": [{"sku_id": "P1008-S1"}]}],
    }))
    collector.observe(event("tool.result", {
        "tool": "category_insight_tool",
        "hit_count": 3,
        "retrieval_mode": "decompose",
    }))

    summary = collector.summary("建议选择 P1008；知识部分已综合说明。")

    assert summary["explicitly_referenced_product_ids"] == ["P1008"]
    assert summary["unverified_product_ids"] == []
    assert summary["evidence_refs_supplied"] == ["ctx_products"]
    assert summary["knowledge_result_count"] == 1
    assert summary["knowledge_adoption_observable"] is False
    assert summary["knowledge_adoption_status"] == "not_observable"


def test_turn_trace_reports_unverified_ids_degradation_and_context_compaction():
    collector = TurnTraceCollector("session-1")
    collector.observe(event("tool.result", {
        "tool": "category_insight_tool",
        "degraded_reason": "vector unavailable",
        "retrieval_mode": "keyword_fallback",
    }))
    collector.observe(event("context.compressed", {
        "status": "completed",
        "before_tokens": 9000,
        "after_tokens": 5000,
        "archived_results": 2,
    }))
    collector.observe(event("model.fallback", {"model": "backup"}))

    summary = collector.summary("我推荐 P9999。")

    assert summary["unverified_product_ids"] == ["P9999"]
    assert summary["degraded_count"] == 2
    assert summary["model_fallback"] is True
    assert summary["context_compactions"][0]["after_tokens"] == 5000


def test_turn_trace_ignores_other_sessions():
    collector = TurnTraceCollector("session-1")
    collector.observe(TradeEvent("session-2", "tool.result", {
        "tool": "product_search_tool",
        "hits": [{"product_id": "P1008"}],
    }, "now"))
    assert collector.summary("P1008")["verified_product_ids"] == []
