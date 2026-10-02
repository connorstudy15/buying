from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import TextBlock

from app.application.retrieval.query_processor import QueryPlan, QueryProcessor, QueryProcessorError, QueryVariant
from app.infrastructure.rag.knowledge_retrieval import search_knowledge, search_knowledge_with_trace


def hit(document_id: str, text: str):
    return SimpleNamespace(
        document_id=document_id,
        score=0.8,
        chunk=SimpleNamespace(content=SimpleNamespace(text=text), metadata={"source": document_id}),
    )


class PlannedProcessor:
    def __init__(self, plan=None, error=None):
        self.plan, self.error, self.calls = plan, error, []

    async def process(self, question):
        self.calls.append(question)
        if self.error:
            raise self.error
        return self.plan


@pytest.mark.asyncio
async def test_disabled_pipeline_is_exact_legacy_document_dedupe():
    kb = SimpleNamespace(search=AsyncMock(return_value=[hit("a", "a1"), hit("a", "a2"), hit("b", "b")]))
    outcome = await search_knowledge_with_trace(kb, "如何挑旅行箱", 2)
    assert [item.document_id for item in outcome.hits] == ["a", "b"]
    assert outcome.trace.mode == "legacy"
    assert [item.document_id for item in await search_knowledge(kb, "如何挑旅行箱", 2)] == ["a", "b"]


@pytest.mark.asyncio
async def test_unsupported_gate_runs_before_query_processor():
    processor = PlannedProcessor()
    kb = SimpleNamespace(search=AsyncMock())
    outcome = await search_knowledge_with_trace(
        kb, "没有目的国，请直接给出精确关税金额", 3, query_processor=processor,
    )
    assert outcome.hits == [] and outcome.trace.mode == "unsupported"
    assert processor.calls == []
    kb.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_processor_failure_uses_exact_legacy_not_original_rrf():
    values = [hit("a", "a1"), hit("a", "a2"), hit("b", "b")]
    kb = SimpleNamespace(search=AsyncMock(return_value=values))
    processor = PlannedProcessor(error=RuntimeError("bad model"))
    outcome = await search_knowledge_with_trace(kb, "怎么挑", 2, query_processor=processor)
    assert [item.document_id for item in outcome.hits] == ["a", "b"]
    assert outcome.trace.mode == "legacy_fallback"
    assert kb.search.await_count == 1


@pytest.mark.asyncio
async def test_rrf_keeps_provenance_and_exposes_fusion_coverage():
    a, b = hit("a", "battery"), hit("b", "airline")

    async def search(queries, top_k):
        return [a, b] if queries[0] == "原问题" else [b, a]

    plan = QueryPlan("原问题", "移动电源 航空限制", (
        QueryVariant("subquery_1", "充电宝容量限制", "battery_limit", "subquery"),
        QueryVariant("subquery_2", "航空公司携带规则", "airline_rule", "subquery"),
    ))
    outcome = await search_knowledge_with_trace(
        SimpleNamespace(search=search), "原问题", 2,
        query_processor=PlannedProcessor(plan), rrf_k=60,
    )
    assert outcome.trace.mode == "query_transform_rrf"
    assert len(outcome.trace.variants) == 4
    assert outcome.trace.pre_fusion_query_route_coverage == 1.0
    assert outcome.trace.post_fusion_query_route_coverage == 1.0
    assert all(item["provenance"] for item in outcome.trace.fused)


def test_query_processor_rejects_duplicate_information_need_ids():
    processor = QueryProcessor(None, "prompt")
    with pytest.raises(QueryProcessorError):
        processor._validate("登机箱", {
            "rewritten_query": "航空 登机箱",
            "subqueries": [
                {"information_need_id": "size", "query": "航司尺寸"},
                {"information_need_id": "size", "query": "不同航司尺寸"},
            ],
        })


def test_query_processor_rejects_dropped_numeric_or_universal_constraint():
    processor = QueryProcessor(None, "prompt")
    with pytest.raises(QueryProcessorError, match="drift"):
        processor._validate("20寸登机箱适用于任意航空公司吗", {
            "rewritten_query": "登机箱航空规则",
            "subqueries": [],
        })


@pytest.mark.asyncio
async def test_query_processor_calls_model_once_and_accepts_fenced_json():
    model = AsyncMock(return_value=SimpleNamespace(content=[TextBlock(text='''```json
{"rewritten_query":"20寸登机箱 任意航空公司规则","subqueries":[]}
```''')]))
    plan = await QueryProcessor(model, "prompt", disable_thinking=True).process("20寸登机箱适用于任意航空公司吗")
    assert plan.rewritten_query.startswith("20寸")
    model.assert_awaited_once()
    assert model.await_args.kwargs["extra_body"] == {"enable_thinking": False}
