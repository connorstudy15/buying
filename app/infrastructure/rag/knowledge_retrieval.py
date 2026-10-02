"""品类知识候选召回、Query Transformation 与融合。"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from agentscope.rag import KnowledgeBase

from app.application.retrieval.query_processor import QueryPlan, QueryProcessor, QueryVariant


def unsupported_fact_reason(question: str) -> str | None:
    """只拦截明显越过证据边界的确定事实请求。"""
    if re.search(r"(如何|怎么).*(核对|查证|计算|判断)|需要哪些.*(资料|参数|证据)", question) and not re.search(r"直接(告诉|给出)", question):
        return None
    if re.search(r"明年.*(新品|售价)|明[日天].*(汇率|收盘价|价格)|预测.*(汇率|收盘价)", question):
        return "future_fact_not_available"
    if re.search(r"(没有|缺少|未提供|未给出?|没给|未确定|不知道).*(目的国|国家|地址|尺寸|容量|重量|价格|币种)", question) and re.search(r"(精确|准确|确定|能否|直接告诉|直接给出)", question):
        return "missing_required_parameters"
    if re.search(r"(没有|缺少|未经核实|未经证实).*来源|网传|传闻", question) and re.search(r"直接告诉|直接给出|确定|准确", question):
        return "unverified_source_claim"
    if re.search(r"(未登记|未知|不明).*(平台|品牌|商家).*(承诺|时效|价格|库存|保修|售后)", question):
        return "entity_outside_knowledge_scope"
    if re.search(r"(精确|准确|确定).*(税率|税额|关税|清关时效|配送时效|体积重|官方零售价)", question):
        return "requires_structured_or_live_evidence"
    if re.search(r"直接告诉.*(配送服务等级|履约承诺|实时库存)", question) or re.search(r"(某品牌|某商家|未知品牌).*(官方|价格|售价|发售)", question):
        return "entity_outside_knowledge_scope"
    return None


def _title_core(title: str) -> str:
    return re.sub(r"\s", "", re.sub(r"(评测知识快照|品类洞察|选购指南|知识快照)$", "", title).strip())


def targeted_documents(documents, question: str, limit: int) -> list:
    """使用已登记标题和地域定位明确主题；不读取评测 ID 或答案。"""
    query = re.sub(r"[\s，,。？?、]", "", question).casefold()
    matches = []
    for document in documents:
        core = _title_core(str(document.metadata.get("document_title", ""))).casefold()
        if core and core in query:
            matches.append((query.index(core), -len(core), document))
    matches.sort(key=lambda item: item[:2])
    covered_until, selected = -1, []
    for start, negative_length, document in matches:
        if start >= covered_until:
            selected.append(document)
            covered_until = start - negative_length
    if not selected and re.search(r"政策|规则|法规|来源|有效期", question):
        regions = {word.upper() for word in re.findall(r"(?<![A-Za-z])[A-Za-z]{2,6}(?![A-Za-z])", question)}
        scoped = [d for d in documents if d.metadata.get("topic") == "policy" and d.metadata.get("region") in regions]
        if scoped and not re.search(r"电池|材质|运费|体积重", question):
            selected = sorted(scoped, key=lambda d: (len(str(d.metadata.get("document_title", ""))), d.document_id))[:1]
    return selected[:limit]


@dataclass(frozen=True)
class KnowledgeCandidate:
    item: Any
    query_id: str
    information_need_id: str
    retrieval_route: str
    rank_in_source: int


@dataclass
class KnowledgeRetrievalTrace:
    mode: str
    variants: list[dict[str, str]] = field(default_factory=list)
    candidates: list[KnowledgeCandidate] = field(default_factory=list, repr=False)
    fused: list[dict[str, Any]] = field(default_factory=list)
    processor_fallback_reason: str | None = None
    pre_fusion_query_route_coverage: float | None = None
    post_fusion_query_route_coverage: float | None = None


@dataclass
class KnowledgeRetrievalOutcome:
    hits: list[Any]
    trace: KnowledgeRetrievalTrace


async def retrieve_knowledge_candidates(
    knowledge_base,
    question: str,
    depth: int,
    *,
    target_limit: int = 3,
    query_id: str = "original",
    information_need_id: str = "overall",
) -> list[KnowledgeCandidate]:
    """现有候选层：向量召回 + title/region scoped 补召回，不最终去重/截断。"""
    results = await knowledge_base.search(queries=[question], top_k=min(80, depth))
    routes = ["vector"] * len(results)
    targets = []
    if isinstance(knowledge_base, KnowledgeBase):
        targets = targeted_documents(await knowledge_base.list_documents(), question, target_limit)
        present = {item.document_id for item in results}

        async def scoped_search(document):
            filters = dict(knowledge_base.metadata_filter or {})
            source = document.metadata.get("source")
            if not source or ("source" in filters and filters["source"] != source):
                return []
            filters["source"] = source
            view = KnowledgeBase(
                name="scoped_insight", description="主题内证据检索",
                embedding_model=knowledge_base.embedding_model,
                vector_store=knowledge_base.vector_store,
                collection=knowledge_base.collection,
                metadata_filter=filters,
            )
            return await view.search(queries=[question], top_k=1)

        additions = await asyncio.gather(*(scoped_search(doc) for doc in targets if doc.document_id not in present))
        for group in additions:
            results.extend(group)
            routes.extend(["document_scoped"] * len(group))

    target_order = {doc.document_id: index for index, doc in enumerate(targets)}
    ordered = sorted(
        enumerate(zip(results, routes)),
        key=lambda pair: (
            0 if pair[1][0].document_id in target_order else 1,
            target_order.get(pair[1][0].document_id, pair[0]),
            pair[0],
        ),
    )
    return [
        KnowledgeCandidate(item, query_id, information_need_id, route, rank)
        for rank, (_, (item, route)) in enumerate(ordered, 1)
    ]


def _legacy_finalize(candidates: list[KnowledgeCandidate], top_k: int) -> list[Any]:
    documents: dict[str, Any] = {}
    for candidate in candidates:
        documents.setdefault(candidate.item.document_id, candidate.item)
    return list(documents.values())[:top_k]


def _chunk_text(item: Any) -> str:
    content = getattr(getattr(item, "chunk", None), "content", "")
    return str(getattr(content, "text", content))


def _candidate_key(item: Any) -> str:
    metadata = getattr(getattr(item, "chunk", None), "metadata", None) or {}
    stable = "\0".join((
        str(item.document_id), str(metadata.get("source") or ""),
        str(metadata.get("section") or metadata.get("heading") or ""), _chunk_text(item),
    ))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _rrf_fuse(candidates: list[KnowledgeCandidate], top_k: int, rrf_k: int) -> tuple[list[Any], list[dict[str, Any]]]:
    scores: dict[str, float] = {}
    best: dict[str, KnowledgeCandidate] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        key = _candidate_key(candidate.item)
        contribution = 1.0 / (rrf_k + candidate.rank_in_source)
        scores[key] = scores.get(key, 0.0) + contribution
        best.setdefault(key, candidate)
        provenance.setdefault(key, []).append({
            "query_id": candidate.query_id,
            "information_need_id": candidate.information_need_id,
            "retrieval_route": candidate.retrieval_route,
            "rank_in_source": candidate.rank_in_source,
            "rrf_contribution": contribution,
        })
    ranked = sorted(scores, key=lambda key: (-scores[key], best[key].rank_in_source, key))
    hits: list[Any] = []
    fused: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    for key in ranked:
        candidate = best[key]
        if candidate.item.document_id in seen_documents:
            continue
        seen_documents.add(candidate.item.document_id)
        hits.append(candidate.item)
        fused.append({
            "candidate_id": key, "document_id": candidate.item.document_id,
            "rrf_score": scores[key], "provenance": provenance[key],
        })
        if len(hits) >= top_k:
            break
    return hits, fused


async def search_knowledge_with_trace(
    knowledge_base,
    question: str,
    top_k: int = 3,
    *,
    query_processor: QueryProcessor | None = None,
    rrf_k: int = 60,
) -> KnowledgeRetrievalOutcome:
    if type(top_k) is not int or not 1 <= top_k <= 10:
        raise ValueError("知识结果数须在1到10之间")
    reason = unsupported_fact_reason(question)
    if reason:
        return KnowledgeRetrievalOutcome([], KnowledgeRetrievalTrace("unsupported", processor_fallback_reason=reason))

    depth = min(80, top_k * 8)
    if query_processor is None:
        candidates = await retrieve_knowledge_candidates(knowledge_base, question, depth, target_limit=top_k)
        return KnowledgeRetrievalOutcome(
            _legacy_finalize(candidates, top_k), KnowledgeRetrievalTrace("legacy", candidates=candidates),
        )

    try:
        plan: QueryPlan = await query_processor.process(question)
    except Exception as err:  # noqa: BLE001 - 精确回到 legacy，不走新管线 original-only
        candidates = await retrieve_knowledge_candidates(knowledge_base, question, depth, target_limit=top_k)
        return KnowledgeRetrievalOutcome(
            _legacy_finalize(candidates, top_k),
            KnowledgeRetrievalTrace("legacy_fallback", candidates=candidates, processor_fallback_reason=str(err)),
        )

    variants: tuple[QueryVariant, ...] = plan.variants()
    groups = await asyncio.gather(*(
        retrieve_knowledge_candidates(
            knowledge_base, variant.text, depth, target_limit=top_k,
            query_id=variant.query_id, information_need_id=variant.information_need_id,
        ) for variant in variants
    ))
    candidates = [candidate for group in groups for candidate in group]
    hits, fused = _rrf_fuse(candidates, top_k, max(1, int(rrf_k)))
    expected_needs = {
        variant.information_need_id for variant in variants
        if variant.kind == "subquery"
    }
    pre_needs = {candidate.information_need_id for candidate in candidates}
    post_needs = {
        source["information_need_id"]
        for item in fused for source in item["provenance"]
    }
    pre_coverage = len(expected_needs & pre_needs) / len(expected_needs) if expected_needs else None
    post_coverage = len(expected_needs & post_needs) / len(expected_needs) if expected_needs else None
    return KnowledgeRetrievalOutcome(hits, KnowledgeRetrievalTrace(
        "query_transform_rrf",
        variants=[{
            "query_id": variant.query_id, "text": variant.text,
            "information_need_id": variant.information_need_id, "kind": variant.kind,
        } for variant in variants],
        candidates=candidates,
        fused=fused,
        pre_fusion_query_route_coverage=pre_coverage,
        post_fusion_query_route_coverage=post_coverage,
    ))


async def search_knowledge(knowledge_base, question: str, top_k: int = 3, *, query_processor=None, rrf_k: int = 60):
    """兼容旧调用；需要诊断信息时使用 ``search_knowledge_with_trace``。"""
    outcome = await search_knowledge_with_trace(
        knowledge_base, question, top_k, query_processor=query_processor, rrf_k=rrf_k,
    )
    return outcome.hits
