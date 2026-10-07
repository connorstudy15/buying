"""品类知识候选召回、Query Transformation 与融合。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

from agentscope.rag import KnowledgeBase
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.application.retrieval.query_processor import QueryPlan, QueryProcessor, QueryVariant
from app.infrastructure.rag.category_knowledge import MIN_ANSWERABLE_KNOWLEDGE_SCORE


_TRACE_CANDIDATE_LIMIT = 50
_TRACE_CONTENT_PREVIEW_CHARS = 320


def _trace_json(value: Any) -> str:
    """Langfuse OTEL 属性只接收标量；结构化诊断统一编码为 JSON。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def unsupported_fact_reason(question: str) -> str | None:
    """只拦截明显越过证据边界的确定事实请求。"""
    if re.search(r"(如何|怎么).*(核对|查证|计算|判断)|需要哪些.*(资料|参数|证据)", question) and not re.search(r"直接(告诉|给出)", question):
        return None
    if re.search(r"明年.*(新品|售价)|明[日天].*(汇率|收盘价|价格)|预测.*(汇率|收盘价)", question):
        return "future_fact_not_available"
    if re.search(r"(下个月|未来|之后).*(运费|价格|政策|限制).*(会不会|是否会|预测|涨|降|松|严)", question):
        return "future_fact_not_available"
    if re.search(r"(昨天下的单|订单|物流).*(发货|到哪|进度|状态|查)", question):
        return "requires_live_order_logistics"
    if re.search(r"(现货|库存|有货).*(今天|现在|立即|马上)?.*(发货|能不能发|可发)?", question):
        return "requires_live_inventory_or_fulfillment"
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

    region_aliases = {
        "CN": ("中国", "国内"), "EU": ("欧洲", "欧盟"), "JP": ("日本",),
        "SG": ("新加坡",), "US": ("美国", "美洲"),
    }
    regions = {word.upper() for word in re.findall(r"(?<![A-Za-z])[A-Za-z]{2,6}(?![A-Za-z])", question)}
    regions.update(
        region for region, aliases in region_aliases.items()
        if any(alias in question for alias in aliases)
    )
    if not selected and re.search(r"政策|规则|法规|来源|有效期", question):
        scoped = [
            document for document in documents
            if document.metadata.get("topic") == "policy" and document.metadata.get("region") in regions
        ]
        if scoped and not re.search(r"电池|材质|运费|体积重", question):
            selected = sorted(
                scoped,
                key=lambda document: (len(str(document.metadata.get("document_title", ""))), document.document_id),
            )[:1]
    return selected[:limit]


def supplemental_documents(documents, question: str, limit: int) -> list:
    """按稳定业务领域补文档内候选；只扩候选池，不获得置顶权重。"""
    # 向量 Top-24 容易漏掉“商品词很强、通用规则词较弱”的正确 section。
    # 这里只按业务领域补文档内 Top-1，不扩大全库候选深度，也不读取评测标注。
    source_routes: list[str] = []
    if re.search(r"移动电源|充电宝|锂电|电池|带电|充电器|航空|飞机|安检", question):
        source_routes.extend((
            "power-bank-air-travel-global.md", "battery-wh-calculation.md", "smart-luggage-battery.md",
            "eval-policy-battery.md", "cross-border-guide.md",
        ))
    if re.search(r"国外|海外|出国|电压|频率|插头|兼容", question):
        source_routes.append("cross-border-guide.md")
    if re.search(r"体积重|运费|邮费|计费重|国际运|跨境|清关|海关|寄(?:往|到|去|给)?|邮寄|搬到", question):
        source_routes.extend((
            "dhl-volumetric-weight.md", "ups-dimensional-weight.md", "cross-border-landed-cost.md",
            "eval-policy-global-shipping.md", "cross-border-guide.md",
        ))
    if re.search(r"收纳|家居|棉麻|织物", question):
        source_routes.append("home-living.md")
    if re.search(r"材质|竹木|木制|棉麻|织物|陶瓷|餐具|过敏|检疫", question):
        source_routes.extend((
            "eu-food-contact-materials.md", "eval-policy-material.md", "cross-border-guide.md",
        ))

    by_source = {
        str(document.metadata.get("source") or ""): document
        for document in documents
    }
    selected: list = []
    selected_ids: set[str] = set()
    for source in source_routes:
        document = by_source.get(source)
        if document is not None and document.document_id not in selected_ids:
            selected.append(document)
            selected_ids.add(document.document_id)
        if len(selected) >= limit:
            break
    return selected[:limit]


@dataclass(frozen=True)
class KnowledgeCandidate:
    item: Any
    query_id: str
    information_need_id: str
    retrieval_route: str
    rank_in_source: int
    intent_group_id: str = "overall"
    retrieval_rank_in_source: int | None = None
    per_need_relevance_score: float | None = None


@dataclass
class KnowledgeRetrievalTrace:
    mode: str
    variants: list[dict[str, str]] = field(default_factory=list)
    candidates: list[KnowledgeCandidate] = field(default_factory=list, repr=False)
    raw_candidates: list[KnowledgeCandidate] = field(default_factory=list, repr=False)
    reranked_candidates: list[KnowledgeCandidate] = field(default_factory=list, repr=False)
    fusion_candidates: list[Any] = field(default_factory=list, repr=False)
    fusion_ranked: list[dict[str, Any]] = field(default_factory=list, repr=False)
    fused: list[dict[str, Any]] = field(default_factory=list)
    processor_fallback_reason: str | None = None
    pre_fusion_query_route_coverage: float | None = None
    post_fusion_query_route_coverage: float | None = None
    # processor_plan_mode 是模型原始选择；effective_plan_mode 是执行策略实际采用的模式。
    # query_plan_mode 暂作 effective_plan_mode 的兼容别名。
    processor_plan_mode: str | None = None
    effective_plan_mode: str | None = None
    query_plan_mode: str | None = None
    rewrite_similarity: float | None = None
    rewrite_decision: str | None = None
    near_duplicate_decisions: list[dict[str, Any]] = field(default_factory=list)
    per_need_rerank_applied: bool = False
    per_need_rerank_calls: list[dict[str, Any]] = field(default_factory=list)
    query_processor_latency_ms: float | None = None
    query_processor_usage: dict[str, int] = field(default_factory=dict)
    retrieval_latency_ms: float | None = None
    reranker_latency_ms: float | None = None
    fusion_latency_ms: float | None = None
    collection_name: str | None = None
    corpus_version: str | None = None


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
    intent_group_id: str = "overall",
) -> list[KnowledgeCandidate]:
    """现有候选层：向量召回 + title/region scoped 补召回，不最终去重/截断。"""
    results = await knowledge_base.search(queries=[question], top_k=min(80, depth))
    routes = ["vector"] * len(results)
    targets = []
    supplementals = []
    if isinstance(knowledge_base, KnowledgeBase):
        documents = await knowledge_base.list_documents()
        targets = targeted_documents(documents, question, target_limit)
        supplementals = supplemental_documents(documents, question, target_limit)
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

        exact_additions = await asyncio.gather(*(scoped_search(doc) for doc in targets if doc.document_id not in present))
        supplemental_additions = await asyncio.gather(*(scoped_search(doc) for doc in supplementals))
        seen_candidate_keys = {_candidate_key(item) for item in results}
        for route, additions in (("document_scoped", exact_additions), ("domain_scoped", supplemental_additions)):
            for group in additions:
                for item in group:
                    key = _candidate_key(item)
                    if key in seen_candidate_keys:
                        continue
                    results.append(item)
                    routes.append(route)
                    seen_candidate_keys.add(key)

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
        KnowledgeCandidate(
            item, query_id, information_need_id, route, rank, intent_group_id,
            retrieval_rank_in_source=rank,
        )
        for rank, (_, (item, route)) in enumerate(ordered, 1)
    ]


def _legacy_finalize(
    candidates: list[KnowledgeCandidate], top_k: int, *, max_chunks_per_document: int = 1,
    min_distinct_documents: int = 1,
) -> list[Any]:
    """保序选择候选；冻结 Legacy 每文档 1 块，DIRECT 可显式放宽到多 section。"""
    selected: list[Any] = []
    document_counts: dict[str, int] = {}
    seen_chunks: set[str] = set()

    def add(candidate: KnowledgeCandidate) -> bool:
        item = candidate.item
        chunk_key = _candidate_key(item)
        document_id = str(item.document_id)
        if chunk_key in seen_chunks or document_counts.get(document_id, 0) >= max_chunks_per_document:
            return False
        selected.append(item)
        seen_chunks.add(chunk_key)
        document_counts[document_id] = document_counts.get(document_id, 0) + 1
        return True

    # DIRECT 的 Top-3 先保证基本文档多样性，再用剩余名额补同文档第二个必要 section。
    diversity_target = min(top_k, max(1, min_distinct_documents))
    for candidate in candidates:
        if str(candidate.item.document_id) in document_counts:
            continue
        add(candidate)
        if len(document_counts) >= diversity_target:
            break
    for candidate in candidates:
        if len(selected) >= top_k:
            break
        add(candidate)
    return selected


async def _legacy_outcome(
    knowledge_base, question: str, depth: int, top_k: int, *, trace_mode: str,
    processor_fallback_reason: str | None = None,
    processor_plan_mode: str | None = None,
    effective_plan_mode: str | None = None,
    rewrite_similarity: float | None = None,
    rewrite_decision: str | None = None,
    candidate_cache: dict[tuple[str, int, int], list[KnowledgeCandidate]] | None = None,
    query_processor_latency_ms: float | None = None,
    query_processor_usage: dict[str, Any] | None = None,
) -> KnowledgeRetrievalOutcome:
    """关闭、回退和 DIRECT 共用同一条旧检索实现，避免三份代码逐渐产生差异。"""
    retrieval_started = time.perf_counter()
    candidates = await _retrieve_candidates(
        knowledge_base, question, depth, target_limit=top_k,
        candidate_cache=candidate_cache,
    )
    retrieval_latency_ms = round((time.perf_counter() - retrieval_started) * 1000, 3)
    variants = []
    if processor_plan_mode is not None:
        variants = [{
            "query_id": "original", "text": question, "information_need_id": "overall",
            "intent_group_id": "global", "kind": "original",
        }]
    max_chunks_per_document = 2 if effective_plan_mode == "DIRECT" else 1
    selection_started = time.perf_counter()
    with trace.get_tracer(__name__).start_as_current_span(
        "knowledge.direct_selection",
        attributes={
            "langfuse.observation.type": "chain",
            "langfuse.observation.input": _trace_json({
                "strategy": "direct_document_diversity",
                "top_k": top_k,
                "max_chunks_per_document": max_chunks_per_document,
                **_trace_candidates(candidates),
            }),
            "globex.retrieval.stage": "direct_selection",
            "globex.retrieval.candidate_count": len(candidates),
            "globex.retrieval.top_k": top_k,
            "globex.retrieval.max_chunks_per_document": max_chunks_per_document,
        },
        record_exception=False, set_status_on_exception=False,
    ) as selection_span:
        hits = _legacy_finalize(
            candidates, top_k, max_chunks_per_document=max_chunks_per_document,
            min_distinct_documents=2 if effective_plan_mode == "DIRECT" else 1,
        )
        selection_span.set_attribute("globex.retrieval.selected_chunk_count", len(hits))
        selection_span.set_attribute(
            "globex.retrieval.selected_document_count", len({str(item.document_id) for item in hits}),
        )
        selected_keys = {_candidate_key(item) for item in hits}
        selection_span.set_attribute("langfuse.observation.output", _trace_json({
            "selected_chunk_count": len(hits),
            "selected_document_count": len({str(item.document_id) for item in hits}),
            **_trace_candidates(candidates, selected_keys=selected_keys),
        }))
    selection_latency_ms = round((time.perf_counter() - selection_started) * 1000, 3)
    selected_keys = {_candidate_key(item) for item in hits}
    fusion_ranked = [{
        "item": candidate.item,
        "candidate_id": _candidate_key(candidate.item),
        "document_id": str(candidate.item.document_id),
        "rrf_score": None,
        "ranking_score": float(getattr(candidate.item, "score", 0.0)),
        "ranking_score_type": "retrieval_similarity",
        "best_rank": rank,
        "eligible": _candidate_is_eligible(candidate),
        "provenance": [{
            "query_id": candidate.query_id,
            "information_need_id": candidate.information_need_id,
            "intent_group_id": candidate.intent_group_id,
            "retrieval_route": candidate.retrieval_route,
            "rank_in_source": candidate.rank_in_source,
        }],
        "selected": _candidate_key(candidate.item) in selected_keys,
    } for rank, candidate in enumerate(candidates, 1)]
    return KnowledgeRetrievalOutcome(
        hits,
        KnowledgeRetrievalTrace(
            trace_mode, variants=variants, candidates=candidates,
            raw_candidates=list(candidates), reranked_candidates=list(candidates),
            fusion_candidates=[candidate.item for candidate in candidates],
            fusion_ranked=fusion_ranked,
            processor_fallback_reason=processor_fallback_reason,
            processor_plan_mode=processor_plan_mode,
            effective_plan_mode=effective_plan_mode,
            query_plan_mode=effective_plan_mode,
            rewrite_similarity=rewrite_similarity,
            rewrite_decision=rewrite_decision,
            query_processor_latency_ms=query_processor_latency_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            reranker_latency_ms=0.0,
            fusion_latency_ms=selection_latency_ms,
            query_processor_usage={
                key: int((query_processor_usage or {}).get(key) or 0)
                for key in ("input_tokens", "output_tokens", "total_tokens")
            },
        ),
    )


async def _retrieve_candidates(
    knowledge_base, question: str, depth: int, *, target_limit: int,
    query_id: str = "original", information_need_id: str = "overall",
    intent_group_id: str = "overall",
    candidate_cache: dict[tuple[str, int, int], list[KnowledgeCandidate]] | None = None,
) -> list[KnowledgeCandidate]:
    """可选地复用原始候选，只用于严格配对评测；线上默认不传缓存。"""
    key = (question, depth, target_limit)
    templates = candidate_cache.get(key) if candidate_cache is not None else None
    cache_hit = templates is not None
    started = time.perf_counter()
    with trace.get_tracer(__name__).start_as_current_span(
        "knowledge.candidate_retrieval",
        attributes={
            "langfuse.observation.type": "retriever",
            "langfuse.observation.input": _trace_json({
                "query": question,
                "query_id": query_id,
                "information_need_id": information_need_id,
                "intent_group_id": intent_group_id,
                "recall_depth": depth,
                "target_limit": target_limit,
            }),
            "globex.retrieval.stage": "candidate_retrieval",
            "globex.retrieval.query_id": query_id,
            "globex.retrieval.need_id": information_need_id,
            "globex.retrieval.intent_group_id": intent_group_id,
            "globex.retrieval.cache_hit": cache_hit,
            "globex.retrieval.top_k": target_limit,
        },
        record_exception=False, set_status_on_exception=False,
    ) as span:
        try:
            if templates is None:
                templates = await retrieve_knowledge_candidates(
                    knowledge_base, question, depth, target_limit=target_limit,
                    query_id="candidate_cache", information_need_id="candidate_cache",
                    intent_group_id="candidate_cache",
                )
                if candidate_cache is not None:
                    candidate_cache[key] = templates
            output = [
                KnowledgeCandidate(
                    template.item, query_id, information_need_id, template.retrieval_route,
                    template.rank_in_source, intent_group_id,
                    retrieval_rank_in_source=(template.retrieval_rank_in_source or template.rank_in_source),
                )
                for template in templates
            ]
            span.set_attribute("globex.retrieval.candidate_count", len(output))
            span.set_attribute("langfuse.observation.output", _trace_json(_trace_candidates(output)))
            return output
        except BaseException as error:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            span.set_attribute("globex.retrieval.latency_ms", round((time.perf_counter() - started) * 1000, 3))


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


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
        return round(parsed, 6) if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _trace_candidate(candidate: KnowledgeCandidate, *, selected: bool | None = None) -> dict[str, Any]:
    """用于开发 Trace 的有界候选摘要，不改变候选对象或排序。"""
    item = candidate.item
    metadata = getattr(getattr(item, "chunk", None), "metadata", None) or {}
    retrieval_rank = candidate.retrieval_rank_in_source or candidate.rank_in_source
    row: dict[str, Any] = {
        "candidate_id": _candidate_key(item),
        "document_id": str(item.document_id),
        "source": str(metadata.get("source") or ""),
        "section": str(metadata.get("section") or metadata.get("heading") or ""),
        "content_preview": _chunk_text(item)[:_TRACE_CONTENT_PREVIEW_CHARS],
        "query_id": candidate.query_id,
        "information_need_id": candidate.information_need_id,
        "intent_group_id": candidate.intent_group_id,
        "retrieval_route": candidate.retrieval_route,
        "retrieval_rank": retrieval_rank,
        "current_rank": candidate.rank_in_source,
        "rank_delta": retrieval_rank - candidate.rank_in_source,
        "retrieval_score": _finite_float(getattr(item, "score", None)),
        "reranker_score": _finite_float(candidate.per_need_relevance_score),
        "eligible": _candidate_is_eligible(item),
    }
    if selected is not None:
        row["selected"] = selected
    return row


def _trace_candidates(
    candidates: list[KnowledgeCandidate], *, selected_keys: set[str] | None = None,
) -> dict[str, Any]:
    limited = candidates[:_TRACE_CANDIDATE_LIMIT]
    return {
        "candidate_count": len(candidates),
        "candidates_truncated": len(candidates) > len(limited),
        "candidates": [
            _trace_candidate(
                candidate,
                selected=(_candidate_key(candidate.item) in selected_keys) if selected_keys is not None else None,
            )
            for candidate in limited
        ],
    }


def _trace_fusion_entry(entry: dict[str, Any]) -> dict[str, Any]:
    item = entry["item"]
    metadata = getattr(getattr(item, "chunk", None), "metadata", None) or {}
    return {
        "candidate_id": entry["candidate_id"],
        "document_id": str(entry["document_id"]),
        "source": str(metadata.get("source") or ""),
        "section": str(metadata.get("section") or metadata.get("heading") or ""),
        "content_preview": _chunk_text(item)[:_TRACE_CONTENT_PREVIEW_CHARS],
        "rrf_score": _finite_float(entry.get("rrf_score")),
        "ranking_score": _finite_float(entry.get("ranking_score")),
        "ranking_score_type": entry.get("ranking_score_type"),
        "best_rank": entry.get("best_rank"),
        "eligible": bool(entry.get("eligible")),
        "selected": bool(entry.get("selected")),
        "provenance": entry.get("provenance") or [],
    }


def _text_similarity(left: str, right: str) -> float:
    def grams(value: str) -> set[str]:
        normalized = "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]+", value.casefold()))
        if len(normalized) < 2:
            return {normalized} if normalized else set()
        return {normalized[index:index + 2] for index in range(len(normalized) - 1)}

    a, b = grams(left), grams(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def _section_key(item: Any) -> tuple[str, str] | None:
    metadata = getattr(getattr(item, "chunk", None), "metadata", None) or {}
    section = str(metadata.get("section") or metadata.get("heading") or "").strip().casefold()
    return (str(item.document_id), section) if section else None


def _candidate_is_eligible(item: Any) -> bool:
    """覆盖保留位只接受达到最低向量相关性阈值的候选，缺少分数则不强保。"""
    try:
        return float(getattr(item, "score")) >= MIN_ANSWERABLE_KNOWLEDGE_SCORE
    except (TypeError, ValueError, AttributeError):
        return False


async def _rerank_information_need(
    reranker, variant: QueryVariant, candidates: list[KnowledgeCandidate],
) -> tuple[list[KnowledgeCandidate], dict[str, Any]]:
    """只用当前子问题给它自己的候选重排；不拿完整原问题做全局重排。"""
    started = time.perf_counter()
    documents = [_chunk_text(candidate.item) for candidate in candidates]
    with trace.get_tracer(__name__).start_as_current_span(
        "knowledge.reranker.need",
        attributes={
            "langfuse.observation.type": "span",
            "langfuse.observation.input": _trace_json({
                "query": variant.text,
                "query_id": variant.query_id,
                "information_need_id": variant.information_need_id,
                **_trace_candidates(candidates),
            }),
            "globex.retrieval.stage": "reranker_need",
            "globex.retrieval.query_id": variant.query_id,
            "globex.retrieval.need_id": variant.information_need_id,
            "globex.retrieval.intent_group_id": variant.intent_group_id,
            "globex.retrieval.document_count": len(documents),
        },
        record_exception=False, set_status_on_exception=False,
    ) as span:
        try:
            if hasattr(reranker, "rerank_with_metadata"):
                scores, usage = await reranker.rerank_with_metadata(variant.text, documents)
            else:
                scores = await reranker.rerank(variant.text, documents)
                usage = {}
            if len(scores) != len(candidates) or not all(math.isfinite(float(score)) for score in scores):
                raise RuntimeError("per_need_reranker_invalid_scores")
            ranked = sorted(
                zip(candidates, (float(score) for score in scores)),
                key=lambda pair: (-pair[1], pair[0].rank_in_source, _candidate_key(pair[0].item)),
            )
            output = [
                replace(
                    candidate,
                    rank_in_source=rank,
                    retrieval_rank_in_source=(candidate.retrieval_rank_in_source or candidate.rank_in_source),
                    per_need_relevance_score=score,
                )
                for rank, (candidate, score) in enumerate(ranked, 1)
            ]
            span.set_attribute("globex.retrieval.total_tokens", int(usage.get("total_tokens") or 0))
            span.set_attribute("globex.retrieval.degraded", bool(usage.get("degraded")))
            span.set_attribute("langfuse.observation.output", _trace_json({
                "information_need_id": variant.information_need_id,
                "degraded": bool(usage.get("degraded")),
                "total_tokens": int(usage.get("total_tokens") or 0),
                **_trace_candidates(output),
            }))
            return output, {
                "query_id": variant.query_id,
                "information_need_id": variant.information_need_id,
                "document_count": len(documents),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "usage": usage,
                "degraded": bool(usage.get("degraded")),
            }
        except BaseException as error:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            span.set_attribute("globex.retrieval.latency_ms", round((time.perf_counter() - started) * 1000, 3))


def _rrf_fuse(
    candidates: list[KnowledgeCandidate], top_k: int, rrf_k: int, *,
    expected_needs: tuple[str, ...] = (), max_chunks_per_document: int = 2,
) -> tuple[list[Any], list[dict[str, Any]], list[dict[str, Any]], list[Any], list[dict[str, Any]]]:
    group_scores: dict[str, dict[str, float]] = {}
    best: dict[str, KnowledgeCandidate] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        key = _candidate_key(candidate.item)
        contribution = 1.0 / (rrf_k + candidate.rank_in_source)
        # 同一意图组内只保留最大贡献；不同信息需求之间仍可相加。
        per_group = group_scores.setdefault(key, {})
        per_group[candidate.intent_group_id] = max(per_group.get(candidate.intent_group_id, 0.0), contribution)
        current = best.get(key)
        if current is None or candidate.rank_in_source < current.rank_in_source:
            best[key] = candidate
        provenance.setdefault(key, []).append({
            "query_id": candidate.query_id,
            "information_need_id": candidate.information_need_id,
            "intent_group_id": candidate.intent_group_id,
            "retrieval_route": candidate.retrieval_route,
            "rank_in_source": candidate.rank_in_source,
            "retrieval_rank_in_source": getattr(candidate, "retrieval_rank_in_source", None),
            "per_need_relevance_score": getattr(candidate, "per_need_relevance_score", None),
            "rrf_contribution": contribution,
        })

    entries = [{
        "candidate_id": key,
        "document_id": best[key].item.document_id,
        "item": best[key].item,
        "group_scores": group_scores[key],
        "rrf_score": sum(group_scores[key].values()),
        "provenance": provenance[key],
        "eligible": _candidate_is_eligible(best[key].item),
        "best_rank": best[key].rank_in_source,
    } for key in best]
    entries.sort(key=lambda item: (-item["rrf_score"], item["best_rank"], item["candidate_id"]))

    # 只合并同文档、同小节且文本高度重叠的片段。不同小节可以同时进入 Top-K。
    deduped: list[dict[str, Any]] = []
    duplicate_decisions: list[dict[str, Any]] = []
    for entry in entries:
        section = _section_key(entry["item"])
        duplicate = None
        similarity = 0.0
        if section is not None:
            for kept in deduped:
                if _section_key(kept["item"]) != section:
                    continue
                similarity = _text_similarity(_chunk_text(entry["item"]), _chunk_text(kept["item"]))
                if similarity >= 0.92:
                    duplicate = kept
                    break
        if duplicate is None:
            deduped.append(entry)
            continue
        for group, score in entry["group_scores"].items():
            duplicate["group_scores"][group] = max(duplicate["group_scores"].get(group, 0.0), score)
        duplicate["rrf_score"] = sum(duplicate["group_scores"].values())
        duplicate["provenance"].extend(entry["provenance"])
        duplicate_decisions.append({
            "dropped_candidate_id": entry["candidate_id"],
            "kept_candidate_id": duplicate["candidate_id"],
            "similarity": round(similarity, 4),
            "reason": "same_document_section_near_duplicate",
        })
    deduped.sort(key=lambda item: (-item["rrf_score"], item["best_rank"], item["candidate_id"]))

    selected_ids: set[str] = set()
    document_counts: dict[str, int] = {}

    def select(entry: dict[str, Any], *, enforce_document_cap: bool = True) -> bool:
        key, document_id = entry["candidate_id"], entry["document_id"]
        if key in selected_ids:
            return True
        if enforce_document_cap and document_counts.get(document_id, 0) >= max_chunks_per_document:
            return False
        selected_ids.add(key)
        document_counts[document_id] = document_counts.get(document_id, 0) + 1
        return True

    # 仅拆分模式使用覆盖保留位：每个子需求尽量先保住一条合格候选。
    for need in expected_needs:
        if len(selected_ids) >= top_k:
            break
        supporting = [
            entry for entry in deduped
            if entry["eligible"] and any(p["information_need_id"] == need for p in entry["provenance"])
            and entry["candidate_id"] not in selected_ids
        ]
        if supporting:
            supporting.sort(key=lambda entry: (
                -max(
                    p["rrf_contribution"] for p in entry["provenance"]
                    if p["information_need_id"] == need
                ),
                entry["best_rank"], entry["candidate_id"],
            ))
            for entry in supporting:
                if select(entry):
                    break
    for entry in deduped:
        if len(selected_ids) >= top_k:
            break
        select(entry)
    # 文档上限是软限制：若候选不足，放开上限补满，不返回少于 K 条。
    for entry in deduped:
        if len(selected_ids) >= top_k:
            break
        select(entry, enforce_document_cap=False)

    selected = [entry for entry in deduped if entry["candidate_id"] in selected_ids][:top_k]
    fused = [{key: value for key, value in entry.items() if key not in {"item", "group_scores", "best_rank"}} for entry in selected]
    ranked = [{
        "item": entry["item"],
        "candidate_id": entry["candidate_id"],
        "document_id": entry["document_id"],
        "rrf_score": entry["rrf_score"],
        "ranking_score": entry["rrf_score"],
        "ranking_score_type": "rrf",
        "best_rank": entry["best_rank"],
        "eligible": entry["eligible"],
        "provenance": entry["provenance"],
        "selected": entry["candidate_id"] in selected_ids,
    } for entry in deduped]
    return (
        [entry["item"] for entry in selected], fused, duplicate_decisions,
        [entry["item"] for entry in deduped], ranked,
    )


async def search_knowledge_with_trace(
    knowledge_base,
    question: str,
    top_k: int = 3,
    *,
    query_processor: QueryProcessor | None = None,
    rrf_k: int = 60,
    execute_rewrite: bool = True,
    candidate_cache: dict[tuple[str, int, int], list[KnowledgeCandidate]] | None = None,
    per_need_reranker=None,
) -> KnowledgeRetrievalOutcome:
    collection_name = str(
        getattr(knowledge_base, "_globex_collection_name", None)
        or getattr(knowledge_base, "collection", "unknown")
    )
    corpus_version = str(getattr(knowledge_base, "_globex_corpus_version", "unknown"))
    current_span = trace.get_current_span()
    current_span.set_attribute("globex.knowledge.collection_name", collection_name)
    current_span.set_attribute("globex.knowledge.corpus_version", corpus_version)
    current_span.set_attribute("langfuse.observation.metadata.collection_name", collection_name)
    current_span.set_attribute("langfuse.observation.metadata.corpus_version", corpus_version)

    def observed(outcome: KnowledgeRetrievalOutcome) -> KnowledgeRetrievalOutcome:
        outcome.trace.collection_name = collection_name
        outcome.trace.corpus_version = corpus_version
        return outcome

    if type(top_k) is not int or not 1 <= top_k <= 10:
        raise ValueError("知识结果数须在1到10之间")
    reason = unsupported_fact_reason(question)
    if reason:
        return observed(KnowledgeRetrievalOutcome([], KnowledgeRetrievalTrace("unsupported", processor_fallback_reason=reason)))

    depth = min(80, top_k * 8)
    if query_processor is None:
        return observed(await _legacy_outcome(
            knowledge_base, question, depth, top_k, trace_mode="legacy",
            candidate_cache=candidate_cache,
        ))

    processor_started = time.perf_counter()
    processor_metadata: dict[str, Any] = {}
    with trace.get_tracer(__name__).start_as_current_span(
        "knowledge.query_processor",
        attributes={
            "langfuse.observation.type": "chain",
            "langfuse.observation.input": _trace_json({"question": question}),
            "globex.retrieval.stage": "query_processor",
        },
        record_exception=False, set_status_on_exception=False,
    ) as processor_span:
        try:
            if hasattr(query_processor, "process_with_metadata"):
                plan, processor_metadata = await query_processor.process_with_metadata(question)
            else:
                plan = await query_processor.process(question)
            processor_metadata.setdefault(
                "latency_ms", round((time.perf_counter() - processor_started) * 1000, 3),
            )
            processor_span.set_attributes({
                "globex.retrieval.plan_mode": plan.mode,
                "globex.retrieval.input_tokens": int(processor_metadata.get("input_tokens") or 0),
                "globex.retrieval.output_tokens": int(processor_metadata.get("output_tokens") or 0),
                "globex.retrieval.total_tokens": int(processor_metadata.get("total_tokens") or 0),
                "langfuse.observation.output": _trace_json({
                    "mode": plan.mode,
                    "rewritten_query": plan.rewritten_query,
                    "rewrite_similarity": plan.rewrite_similarity,
                    "rewrite_decision": plan.rewrite_decision,
                    "variants": [{
                        "query_id": variant.query_id,
                        "query": variant.text,
                        "information_need_id": variant.information_need_id,
                        "intent_group_id": variant.intent_group_id,
                        "kind": variant.kind,
                    } for variant in plan.variants()],
                }),
            })
        except Exception as err:  # noqa: BLE001 - 精确回到 legacy，不走新管线 original-only
            processor_span.set_attribute("error.type", type(err).__name__)
            processor_span.set_status(Status(StatusCode.ERROR))
            fallback_metadata = getattr(err, "metadata", {}) or {}
            processor_span.set_attribute("langfuse.observation.output", _trace_json({
                "fallback": "legacy",
                "reason": str(err),
                "model_decision": getattr(err, "model_decision", None),
            }))
            return observed(await _legacy_outcome(
                knowledge_base, question, depth, top_k, trace_mode="legacy_fallback",
                processor_fallback_reason=str(err), candidate_cache=candidate_cache,
                processor_plan_mode=getattr(err, "model_decision", None),
                effective_plan_mode="FALLBACK",
                query_processor_latency_ms=(
                    fallback_metadata.get("latency_ms")
                    or round((time.perf_counter() - processor_started) * 1000, 3)
                ),
                query_processor_usage=fallback_metadata,
            ))
        finally:
            processor_span.set_attribute(
                "globex.retrieval.latency_ms", round((time.perf_counter() - processor_started) * 1000, 3),
            )

    processor_mode = plan.mode
    effective_mode = "DIRECT" if processor_mode == "REWRITE" and not execute_rewrite else processor_mode
    rewrite_decision = (
        "disabled_by_experiment"
        if processor_mode == "REWRITE" and not execute_rewrite
        else plan.rewrite_decision
    )

    # DIRECT 与“实验中禁用 REWRITE”都逐字复用旧链路；仅多出前置模型分类时间。
    if effective_mode == "DIRECT":
        return observed(await _legacy_outcome(
            knowledge_base, question, depth, top_k,
            trace_mode=("query_decompose_rewrite_disabled" if processor_mode == "REWRITE" else "query_transform_direct"),
            processor_plan_mode=processor_mode,
            effective_plan_mode=effective_mode,
            rewrite_similarity=plan.rewrite_similarity,
            rewrite_decision=rewrite_decision,
            candidate_cache=candidate_cache,
            query_processor_latency_ms=processor_metadata.get("latency_ms"),
            query_processor_usage=processor_metadata,
        ))

    variants: tuple[QueryVariant, ...] = plan.variants()
    retrieval_started = time.perf_counter()
    groups = await asyncio.gather(*(
        _retrieve_candidates(
            knowledge_base, variant.text, depth, target_limit=top_k,
            query_id=variant.query_id, information_need_id=variant.information_need_id,
            intent_group_id=variant.intent_group_id,
            candidate_cache=candidate_cache,
        ) for variant in variants
    ))
    retrieval_latency_ms = round((time.perf_counter() - retrieval_started) * 1000, 3)
    raw_candidates = [candidate for group in groups for candidate in group]
    rerank_calls: list[dict[str, Any]] = []
    reranker_started = time.perf_counter()
    if effective_mode == "DECOMPOSE" and per_need_reranker is not None:
        reranked = await asyncio.gather(*(
            _rerank_information_need(per_need_reranker, variant, list(group))
            if variant.kind == "subquery"
            else asyncio.sleep(0, result=(list(group), None))
            for variant, group in zip(variants, groups)
        ))
        groups = tuple(group for group, _ in reranked)
        rerank_calls = [call for _, call in reranked if call is not None]
    reranker_latency_ms = round((time.perf_counter() - reranker_started) * 1000, 3)
    candidates = [candidate for group in groups for candidate in group]
    expected_needs = tuple(dict.fromkeys(
        variant.information_need_id for variant in variants
        if variant.kind == "subquery"
    ))
    fusion_started = time.perf_counter()
    with trace.get_tracer(__name__).start_as_current_span(
        "knowledge.rrf_fusion",
        attributes={
            "langfuse.observation.type": "chain",
            "langfuse.observation.input": _trace_json({
                "rrf_k": max(1, int(rrf_k)),
                "top_k": top_k,
                "expected_information_needs": list(expected_needs),
                **_trace_candidates(candidates),
            }),
            "globex.retrieval.stage": "rrf_fusion",
            "globex.retrieval.candidate_count": len(candidates),
            "globex.retrieval.top_k": top_k,
            "globex.retrieval.rrf_k": max(1, int(rrf_k)),
        },
        record_exception=False, set_status_on_exception=False,
    ) as fusion_span:
        try:
            hits, fused, duplicate_decisions, fusion_candidates, fusion_ranked = _rrf_fuse(
                candidates, top_k, max(1, int(rrf_k)), expected_needs=expected_needs,
            )
            fusion_span.set_attribute("globex.retrieval.fused_count", len(hits))
            represented_needs = {
                source["information_need_id"]
                for item in fused for source in item["provenance"]
            }
            covered_needs = sorted(set(expected_needs) & represented_needs)
            ranked_limit = fusion_ranked[:_TRACE_CANDIDATE_LIMIT]
            fusion_span.set_attribute("langfuse.observation.output", _trace_json({
                "selected_candidate_ids": [item["candidate_id"] for item in fused],
                "expected_information_needs": list(expected_needs),
                "covered_information_needs": covered_needs,
                "represented_information_needs": sorted(represented_needs),
                "duplicate_decisions": duplicate_decisions,
                "ranking_count": len(fusion_ranked),
                "ranking_truncated": len(fusion_ranked) > len(ranked_limit),
                "ranking": [_trace_fusion_entry(item) for item in ranked_limit],
            }))
        except BaseException as error:
            fusion_span.set_attribute("error.type", type(error).__name__)
            fusion_span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            fusion_span.set_attribute(
                "globex.retrieval.latency_ms", round((time.perf_counter() - fusion_started) * 1000, 3),
            )
    pre_needs = {candidate.information_need_id for candidate in candidates}
    post_needs = {
        source["information_need_id"]
        for item in fused for source in item["provenance"]
    }
    expected_need_set = set(expected_needs)
    pre_coverage = len(expected_need_set & pre_needs) / len(expected_need_set) if expected_need_set else None
    post_coverage = len(expected_need_set & post_needs) / len(expected_need_set) if expected_need_set else None
    return observed(KnowledgeRetrievalOutcome(hits, KnowledgeRetrievalTrace(
        "query_transform_rewrite" if effective_mode == "REWRITE" else "query_transform_decompose",
        variants=[{
            "query_id": variant.query_id, "text": variant.text,
            "information_need_id": variant.information_need_id,
            "intent_group_id": variant.intent_group_id, "kind": variant.kind,
        } for variant in variants],
        candidates=candidates,
        raw_candidates=raw_candidates,
        reranked_candidates=list(candidates),
        fusion_candidates=fusion_candidates,
        fusion_ranked=fusion_ranked,
        fused=fused,
        pre_fusion_query_route_coverage=pre_coverage,
        post_fusion_query_route_coverage=post_coverage,
        processor_plan_mode=processor_mode,
        effective_plan_mode=effective_mode,
        query_plan_mode=effective_mode,
        rewrite_similarity=plan.rewrite_similarity,
        rewrite_decision=rewrite_decision,
        near_duplicate_decisions=duplicate_decisions,
        per_need_rerank_applied=any(not call.get("degraded") for call in rerank_calls),
        per_need_rerank_calls=rerank_calls,
        query_processor_latency_ms=processor_metadata.get("latency_ms"),
        retrieval_latency_ms=retrieval_latency_ms,
        reranker_latency_ms=reranker_latency_ms,
        fusion_latency_ms=round((time.perf_counter() - fusion_started) * 1000, 3),
        query_processor_usage={
            key: int(processor_metadata.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        },
    )))


async def search_knowledge(
    knowledge_base, question: str, top_k: int = 3, *, query_processor=None,
    rrf_k: int = 60, execute_rewrite: bool = True,
    candidate_cache: dict[tuple[str, int, int], list[KnowledgeCandidate]] | None = None,
    per_need_reranker=None,
):
    """兼容旧调用；需要诊断信息时使用 ``search_knowledge_with_trace``。"""
    outcome = await search_knowledge_with_trace(
        knowledge_base, question, top_k, query_processor=query_processor, rrf_k=rrf_k,
        execute_rewrite=execute_rewrite,
        candidate_cache=candidate_cache,
        per_need_reranker=per_need_reranker,
    )
    return outcome.hits
