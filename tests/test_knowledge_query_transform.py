import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import TextBlock

from app.application.prompts.loader import load_prompts
from app.application.retrieval.query_processor import QueryPlan, QueryProcessor, QueryProcessorError, QueryVariant
from app.infrastructure.rag.knowledge_retrieval import (
    _rrf_fuse,
    search_knowledge,
    search_knowledge_with_trace,
    unsupported_fact_reason,
)
from scripts.eval.run_query_decompose_ablation import SharedPlanProcessor
from scripts.eval.run_per_need_rerank_ablation import RetryingReranker


def hit(document_id: str, text: str, *, section: str | None = None, score: float = 0.8):
    metadata = {"source": document_id}
    if section:
        metadata["section"] = section
    return SimpleNamespace(
        document_id=document_id,
        score=score,
        chunk=SimpleNamespace(content=SimpleNamespace(text=text), metadata=metadata),
    )


class PlannedProcessor:
    def __init__(self, plan=None, error=None):
        self.plan, self.error, self.calls = plan, error, []

    async def process(self, question):
        self.calls.append(question)
        if self.error:
            raise self.error
        return self.plan


def test_query_processor_prompt_decomposes_single_goal_with_independent_evidence_needs():
    prompt = load_prompts()["query_processor"]["system_prompt"]
    assert "只有一个最终判断目标" in prompt
    assert "两个可独立检索、可独立失败的信息需求" in prompt


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

    plan = QueryPlan("原问题", "", (
        QueryVariant("subquery_1", "充电宝容量限制", "battery_limit", "subquery"),
        QueryVariant("subquery_2", "航空公司携带规则", "airline_rule", "subquery"),
    ), mode="DECOMPOSE")
    outcome = await search_knowledge_with_trace(
        SimpleNamespace(search=search), "原问题", 2,
        query_processor=PlannedProcessor(plan), rrf_k=60,
    )
    assert outcome.trace.mode == "query_transform_decompose"
    assert len(outcome.trace.variants) == 3
    assert outcome.trace.pre_fusion_query_route_coverage == 1.0
    assert outcome.trace.post_fusion_query_route_coverage == 1.0
    assert all(item["provenance"] for item in outcome.trace.fused)


@pytest.mark.asyncio
async def test_direct_plan_uses_exact_legacy_ranking():
    values = [hit("a", "a1"), hit("a", "a2"), hit("b", "b")]
    kb = SimpleNamespace(search=AsyncMock(return_value=values))
    plan = QueryPlan("怎么挑", "", (), mode="DIRECT")
    outcome = await search_knowledge_with_trace(kb, "怎么挑", 2, query_processor=PlannedProcessor(plan))
    assert [item.document_id for item in outcome.hits] == ["a", "b"]
    assert outcome.trace.mode == "query_transform_direct"
    assert outcome.trace.processor_plan_mode == "DIRECT"
    assert outcome.trace.effective_plan_mode == "DIRECT"
    assert kb.search.await_count == 1


@pytest.mark.asyncio
async def test_experiment_can_disable_rewrite_without_changing_processor_plan():
    original_hits = [hit("a", "original"), hit("b", "other")]
    rewritten_hits = [hit("c", "rewritten"), hit("a", "original")]

    async def search(queries, top_k):
        return rewritten_hits if queries[0] == "清晰改写" else original_hits

    plan = QueryPlan("口语问题", "清晰改写", (), mode="REWRITE", rewrite_decision="used")
    processor = PlannedProcessor(plan)
    outcome = await search_knowledge_with_trace(
        SimpleNamespace(search=search), "口语问题", 2,
        query_processor=processor, execute_rewrite=False,
    )
    assert [item.document_id for item in outcome.hits] == ["a", "b"]
    assert outcome.trace.processor_plan_mode == "REWRITE"
    assert outcome.trace.effective_plan_mode == "DIRECT"
    assert outcome.trace.rewrite_decision == "disabled_by_experiment"
    assert outcome.trace.mode == "query_decompose_rewrite_disabled"
    assert processor.calls == ["口语问题"]


@pytest.mark.asyncio
async def test_v2_still_executes_rewrite_with_the_same_plan():
    calls = []

    async def search(queries, top_k):
        calls.append(queries[0])
        return [hit("a", queries[0])]

    plan = QueryPlan("口语问题", "清晰改写", (), mode="REWRITE", rewrite_decision="used")
    outcome = await search_knowledge_with_trace(
        SimpleNamespace(search=search), "口语问题", 1,
        query_processor=PlannedProcessor(plan), execute_rewrite=True,
    )
    assert calls == ["口语问题", "清晰改写"]
    assert outcome.trace.processor_plan_mode == "REWRITE"
    assert outcome.trace.effective_plan_mode == "REWRITE"


@pytest.mark.asyncio
async def test_ablation_reuses_one_query_plan_for_both_strategies():
    plan = QueryPlan("口语问题", "清晰改写", (), mode="REWRITE")
    inner = SimpleNamespace(process=AsyncMock(return_value=plan))
    shared = SharedPlanProcessor(inner)
    assert await shared.process("口语问题") is plan
    assert await shared.process("口语问题") is plan
    inner.process.assert_awaited_once_with("口语问题")


@pytest.mark.asyncio
async def test_paired_evaluation_can_reuse_exact_original_candidates():
    search = AsyncMock(return_value=[hit("a", "a"), hit("b", "b")])
    kb = SimpleNamespace(search=search)
    cache = {}
    legacy = await search_knowledge_with_trace(kb, "同一问题", 2, candidate_cache=cache)
    plan = QueryPlan("同一问题", "改写问题", (), mode="REWRITE")
    experiment = await search_knowledge_with_trace(
        kb, "同一问题", 2, query_processor=PlannedProcessor(plan),
        execute_rewrite=False, candidate_cache=cache,
    )
    assert experiment.hits == legacy.hits
    search.assert_awaited_once()


@pytest.mark.asyncio
async def test_per_need_reranker_scores_each_subquery_not_global_question():
    distractor = hit("distractor", "通用旅行说明")
    size = hit("size", "登机箱尺寸因航空公司而异")
    battery = hit("battery", "移动电源航空运输容量限制")

    async def search(queries, top_k):
        return [distractor, size, battery]

    class NeedReranker:
        def __init__(self):
            self.calls = []

        async def rerank(self, query, documents):
            self.calls.append(query)
            if query == "登机箱尺寸":
                return [0.0, 1.0, 0.1]
            if query == "移动电源限制":
                return [0.0, 0.1, 1.0]
            raise AssertionError("不应使用完整原问题做全局重排")

    plan = QueryPlan("箱子和充电宝能否登机", "", (
        QueryVariant("subquery_1", "登机箱尺寸", "size", "subquery", "size"),
        QueryVariant("subquery_2", "移动电源限制", "battery", "subquery", "battery"),
    ), mode="DECOMPOSE")
    reranker = NeedReranker()
    outcome = await search_knowledge_with_trace(
        SimpleNamespace(search=search), plan.original_query, 2,
        query_processor=PlannedProcessor(plan), per_need_reranker=reranker,
    )
    assert {item.document_id for item in outcome.hits} == {"size", "battery"}
    assert reranker.calls == ["登机箱尺寸", "移动电源限制"]
    assert outcome.trace.per_need_rerank_applied is True
    assert len(outcome.trace.per_need_rerank_calls) == 2


@pytest.mark.asyncio
async def test_experiment_reranker_retries_without_silent_fallback(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    inner = SimpleNamespace(rerank=AsyncMock(side_effect=[OSError("temporary"), [0.9]]))
    scores = await RetryingReranker(inner, attempts=2).rerank("问题", ["证据"])
    assert scores == [0.9]
    assert inner.rerank.await_count == 2


@pytest.mark.asyncio
async def test_decompose_can_keep_two_sections_from_same_document():
    size = hit("travel", "登机箱尺寸因航司而异", section="避坑点")
    bag = hit("travel", "折叠背包可作为第二件行李", section="当前热卖款型")

    async def search(queries, top_k):
        if "尺寸" in queries[0]:
            return [size, bag]
        if "背包" in queries[0]:
            return [bag, size]
        return [size, bag]

    plan = QueryPlan("箱子和背包", "", (
        QueryVariant("subquery_1", "登机箱尺寸", "size", "subquery", "size"),
        QueryVariant("subquery_2", "折叠背包规则", "bag", "subquery", "bag"),
    ), mode="DECOMPOSE")
    outcome = await search_knowledge_with_trace(
        SimpleNamespace(search=search), "箱子和背包", 2, query_processor=PlannedProcessor(plan),
    )
    assert {item.chunk.metadata["section"] for item in outcome.hits} == {"避坑点", "当前热卖款型"}
    assert outcome.trace.post_fusion_query_route_coverage == 1.0


def test_query_processor_rejects_duplicate_information_need_ids():
    processor = QueryProcessor(None, "prompt")
    with pytest.raises(QueryProcessorError):
        processor._validate("登机箱", {
            "mode": "DECOMPOSE", "rewritten_query": "",
            "subqueries": [
                {"information_need_id": "size", "query": "航司尺寸"},
                {"information_need_id": "size", "query": "不同航司尺寸"},
            ],
        })


def test_query_processor_rejects_dropped_numeric_or_universal_constraint():
    processor = QueryProcessor(None, "prompt")
    with pytest.raises(QueryProcessorError, match="drift"):
        processor._validate("20寸登机箱适用于任意航空公司吗", {
            "mode": "REWRITE", "rewritten_query": "登机箱航空规则", "subqueries": [],
        })


@pytest.mark.asyncio
async def test_query_processor_calls_model_once_and_accepts_fenced_json():
    model = AsyncMock(return_value=SimpleNamespace(content=[TextBlock(text='''```json
{"mode":"REWRITE","rewritten_query":"20寸登机箱 任意航空公司规则","subqueries":[]}
```''')], usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}))
    plan, metadata = await QueryProcessor(model, "prompt", disable_thinking=True).process_with_metadata(
        "20寸登机箱适用于任意航空公司吗",
    )
    assert plan.rewritten_query.startswith("20寸")
    assert metadata["input_tokens"] == 120
    assert metadata["output_tokens"] == 30
    assert metadata["total_tokens"] == 150
    assert metadata["latency_ms"] >= 0
    model.assert_awaited_once()
    assert model.await_args.kwargs["extra_body"] == {"enable_thinking": False}
    assert model.await_args.kwargs["temperature"] == 0


def test_near_identical_rewrite_is_downgraded_to_direct():
    plan = QueryProcessor(None, "prompt")._validate("旅行箱怎么挑？", {
        "mode": "REWRITE", "rewritten_query": "旅行箱怎么挑", "subqueries": [],
    })
    assert plan.mode == "DIRECT"
    assert plan.rewrite_decision == "skipped_near_duplicate"
    assert [variant.kind for variant in plan.variants()] == ["original"]


def test_same_intent_original_and_rewrite_do_not_double_vote():
    item = hit("travel", "行李箱尺寸规则")
    candidates = [
        # 两路都属于 overall，同一个候选只能取其中最大的一次贡献。
        SimpleNamespace(item=item, query_id="original", information_need_id="overall", retrieval_route="vector", rank_in_source=1, intent_group_id="overall"),
        SimpleNamespace(item=item, query_id="rewrite", information_need_id="overall", retrieval_route="vector", rank_in_source=2, intent_group_id="overall"),
    ]
    _, fused, _ = _rrf_fuse(candidates, 1, 60)
    assert fused[0]["rrf_score"] == pytest.approx(1 / 61)


@pytest.mark.parametrize("question", [
    "我昨天下的单怎么还没发货，现在到哪了？帮我查下物流。",
    "你们那个折叠双肩包黑色现在还有现货吗？我下单能不能今天就发？",
    "下个月国际运费会不会降，锂电池政策会不会松一点？帮我预测下。",
])
def test_live_or_future_questions_are_rejected_before_static_retrieval(question):
    assert unsupported_fact_reason(question) is not None
