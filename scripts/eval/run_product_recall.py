# -*- coding: utf-8 -*-
"""商品检索（product_search）召回评测 —— 见教程 13-2 章。

直连 `CatalogSearchUseCase`，不过 HTTP、不过 Agent：召回评测的定位是模块级
「日常体检」，改一行权重、换一版 reranker 都该能几秒钟跑一遍，才可能常驻 CI。

用法（项目根目录执行）：

    # 默认档（有 embedding 凭据就走向量+精排，否则自动降级）
    uv run python scripts/eval/run_product_recall.py

    # 三档降级链对比：量化"降级到底损失多少召回质量"
    uv run python scripts/eval/run_product_recall.py --compare-strategies

    # 无凭据也能跑：纯关键词档，适合 CI
    uv run python scripts/eval/run_product_recall.py --strategy keyword_2gram

关于 N/K 的选择（重要）：`--recall-depth` 控制一阶段候选深度 N，`--top-k`
控制最终截断 K。默认都为 8 以保持既有线上口径；做 reranker 实验时应显式满足
N >= K，并在报告中同时保留候选召回和最终排序指标。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.usecases.catalog_search import CatalogSearchUseCase  # noqa: E402
from app.domain.catalog.product_search_spec import ProductSearchSpec  # noqa: E402
from app.infrastructure.embedding.openai_embedding_client import (  # noqa: E402
    OpenAIEmbeddingClient,
)
from app.infrastructure.persistence.in_memory_repositories import (  # noqa: E402
    InMemoryProductRepository,
)
from app.infrastructure.persistence.seed_products import build_seed_products  # noqa: E402
from app.infrastructure.rerank.http_reranker import HttpReranker  # noqa: E402
from app.infrastructure.settings import load_settings  # noqa: E402
from app.infrastructure.vector.index_bootstrap import bootstrap_product_index  # noqa: E402
from app.infrastructure.vector.qdrant_product_index import QdrantProductIndex  # noqa: E402
from scripts.eval.metrics import (  # noqa: E402
    Aggregate,
    QueryResult,
    Thresholds,
    evaluate,
    gate,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from scripts.eval.hard_constraints import find_hit_constraint_violations  # noqa: E402
from scripts.eval.run_manifest import (  # noqa: E402
    SPLITS, build_manifest, finish_manifest, manifest_report, select_cases,
    validate_baseline_selection, write_manifest,
)

_DATASET = Path("eval/product_recall.jsonl")
_COMPARISON_STRATEGIES = ("embedding_rerank", "embedding_only", "keyword_2gram")
_STRATEGIES = (*_COMPARISON_STRATEGIES, "bm25", "hybrid_rrf", "hybrid_rerank")


def profile_thresholds(profile: str) -> Thresholds:
    """返回正式线上链路或离线降级链路的门禁口径。"""
    if profile == "online-main":
        return Thresholds(
            recall=0.90, precision=None, mrr=0.85, ndcg=0.85,
            empty_accuracy=1.0, filter_accuracy=1.0,
            max_hard_constraint_violation_rate=0.0,
            required_recall_strategies=frozenset({"embedding_rerank"}),
        )
    if profile == "offline-fallback":
        # 关键词档用于离线退化监控；质量由批准基线约束，安全底线仍必须绝对通过。
        return Thresholds(
            recall=0.0, precision=None, mrr=0.0, ndcg=0.0,
            empty_accuracy=1.0, filter_accuracy=1.0,
            max_hard_constraint_violation_rate=0.0,
            required_recall_strategies=frozenset({"keyword_2gram"}),
        )
    if profile == "hybrid-experimental":
        return Thresholds(
            recall=0.90, precision=None, mrr=0.85, ndcg=0.85,
            empty_accuracy=1.0, filter_accuracy=1.0,
            max_hard_constraint_violation_rate=0.0,
            # 空候选无需执行精排；完整执行要求由逐条 hybrid_execution_errors 校验。
            required_recall_strategies=None,
        )
    raise ValueError(f"未知评测 profile：{profile}")


def load_dataset(path: Path) -> list[dict]:
    cases = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            cases.append(json.loads(raw))
    return cases


def load_baselines(path: Path | None) -> dict[str, dict[str, float]]:
    """读取经人工批准的各检索档位基线；未传文件时只执行绝对门槛。"""
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    strategies = raw.get("strategies", raw)
    if not isinstance(strategies, dict):
        raise ValueError("基线文件必须是 {strategy: {recall, precision, mrr, ndcg}} 对象")
    return {
        str(name): {metric: float(value) for metric, value in metrics.items()}
        for name, metrics in strategies.items()
        if isinstance(metrics, dict)
    }


async def build_usecase(
    strategy: str, catalog_path: Path | None = None, recall_depth: int = 8,
    *, rrf_k: int = 60, rrf_weights: tuple[float, float] = (1.0, 1.0),
) -> tuple[CatalogSearchUseCase, InMemoryProductRepository, str]:
    """按目标档位装配 UseCase。

    降级档位不是靠开关切换的，而是**靠少注入依赖自然形成**——这正好复用了线上
    真实的降级逻辑（`execute()` 里 embedder/vector_index 为 None 就走关键词），
    评测因此测的是真链路，不是为评测另写的一套。
    """
    repo = InMemoryProductRepository(build_seed_products(catalog_path))
    if strategy in {"keyword_2gram", "bm25"}:
        return CatalogSearchUseCase(
            repo, hybrid_enabled=strategy == "bm25", include_retrieval_evidence=True,
            recall_top_n=recall_depth,
        ), repo, strategy

    settings = load_settings()
    embedder = OpenAIEmbeddingClient(settings)
    vector_index = QdrantProductIndex(settings)
    ok = await bootstrap_product_index(repo, embedder, vector_index)
    if not ok:
        print("  [warn] 向量建库失败，本档实际会降级到关键词召回")

    reranker = None
    if strategy in {"embedding_rerank", "hybrid_rerank"}:
        if settings.reranker_base_url:
            reranker = HttpReranker(settings)
        else:
            print("  [warn] 未配置 RERANKER_BASE_URL，embedding_rerank 档实际等价于 embedding_only")
    return (
        CatalogSearchUseCase(
            repo, embedder=embedder, vector_index=vector_index, reranker=reranker,
            hybrid_enabled=strategy in {"hybrid_rrf", "hybrid_rerank"},
            include_retrieval_evidence=True,
            recall_top_n=recall_depth,
            rrf_k=rrf_k,
            rrf_weights=rrf_weights,
        ),
        repo,
        strategy,
    )


def check_filter_details(
    case: dict, hits: list[dict], filtered_out: list[dict], repo_products: dict[str, Any],
) -> tuple[Optional[bool], str, int, int]:
    """硬约束过滤是否正确。

    只对声明了约束的 query 判定；未声明的返回 None（不参与统计）。

    这里刻意**不重算汇率与关税**——那是 TariffSchedule 的职责，评测重算一遍等于
    把业务逻辑抄两份，抄错了还会误判。改为查两个不依赖换算的事实：
      1. 泄漏：返回结果里有不满足 ship_to 的商品（ships_to 是明确的枚举，无歧义）
      2. 误杀：标注为相关的商品出现在 filtered_out 里
    """
    ship_to = case.get("ship_to")
    price_cap = case.get("price_max_major")
    excluded_material_tags = case.get("excluded_material_tags", [])
    required_material_tags = case.get("required_material_tags", [])
    category = case.get("category")
    if (
        not ship_to and price_cap is None and not excluded_material_tags
        and not required_material_tags and not category and "require_in_stock" not in case
    ):
        return None, "", 0, 0

    problems = []
    violations = find_hit_constraint_violations(
        hits,
        repo_products,
        price_max_major=price_cap,
        ship_to=ship_to,
        category=category,
        target_currency=case.get("target_currency", "CNY"),
        excluded_material_tags=excluded_material_tags,
        required_material_tags=required_material_tags,
    )
    for product_id, reasons in sorted(violations.items()):
        problems.append(f"泄漏 {product_id}（{','.join(sorted(reasons))}）")

    rejected_ids = {item["product_id"] for item in filtered_out}
    for pid in case["relevant"]:
        if pid in rejected_ids:
            problems.append(f"误杀 {pid}（标注为相关却被硬约束挡掉）")

    return (not problems), "；".join(problems), len(violations), len(hits)


def check_filter(
    case: dict, hits: list[dict], filtered_out: list[dict], repo_products: dict[str, Any],
) -> tuple[Optional[bool], str]:
    """兼容既有测试与调用方；详细违规计数由 ``check_filter_details`` 提供。"""
    ok, note, _, _ = check_filter_details(case, hits, filtered_out, repo_products)
    return ok, note


_STABLE_ID = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]+[-_:]?[A-Za-z0-9-]*\d[A-Za-z0-9-]*(?![A-Za-z0-9])")


def check_rewrite_drift(case: dict) -> tuple[bool | None, str]:
    """确定性检查原始诉求到实际检索 query 是否丢失关键项。

    runner 不另造一套 LLM rewriter；它评估数据中记录的 ``original_query`` 与真正传给
    CatalogSearchUseCase 的 ``rewritten_query``。稳定型号/ID 自动保护，其余业务关键字由
    ``rewrite_must_preserve`` / ``rewrite_must_not_add`` 显式标注。
    """
    original = str(case.get("original_query") or "").strip()
    if not original:
        return None, ""
    rewritten = str(case.get("rewritten_query") or case["query"]).strip()
    required = list(dict.fromkeys([
        *[str(value) for value in case.get("rewrite_must_preserve", [])],
        *_STABLE_ID.findall(original),
    ]))
    forbidden = [str(value) for value in case.get("rewrite_must_not_add", [])]
    missing = [value for value in required if value.casefold() not in rewritten.casefold()]
    added = [value for value in forbidden if value.casefold() in rewritten.casefold()]
    notes = []
    if missing:
        notes.append("丢失:" + ",".join(missing))
    if added:
        notes.append("误加:" + ",".join(added))
    return bool(notes), "；".join(notes)


async def run_dataset(
    usecase: CatalogSearchUseCase, repo: InMemoryProductRepository, cases: list[dict], top_k: int,
    *, observations: list[dict] | None = None,
) -> Aggregate:
    products = {p.product_id: p for p in await repo.list_all()}
    results: list[QueryResult] = []
    empty_results: list[bool] = []
    recall_strategies: set[str] = set()
    latencies_ms: list[float] = []

    for case in cases:
        executed_query = case.get("rewritten_query") or case["query"]
        rewrite_drift, rewrite_note = check_rewrite_drift(case)
        spec = ProductSearchSpec(
            normalized_query=executed_query,
            top_k=top_k,
            category=case.get("category"),
            price_max_major=case.get("price_max_major"),
            ship_to=case.get("ship_to"),
            target_currency=case.get("target_currency", "CNY"),
            excluded_material_tags=case.get("excluded_material_tags", []),
            required_material_tags=case.get("required_material_tags", []),
        )
        started = perf_counter()
        payload = await usecase.execute(spec)
        latency_ms = (perf_counter() - started) * 1000
        latencies_ms.append(latency_ms)
        recall_strategies.add(str(payload.get("recall_strategy", "unknown")))
        hits = payload.get("hits", [])
        raw_retrieved = [hit["product_id"] for hit in hits]

        def canonical(product_id: str) -> str:
            product = products.get(product_id)
            return product.canonical_product_id if product and product.canonical_product_id else product_id

        retrieved = []
        for product_id in raw_retrieved:
            canonical_id = canonical(product_id)
            if canonical_id not in retrieved:
                retrieved.append(canonical_id)
        relevant = case.get("relevant_canonical_ids") or [canonical(product_id) for product_id in case["relevant"]]
        evidence = payload.get("retrieval_evidence") or {}
        candidate_raw = list(evidence.get("candidate_product_ids") or [])
        candidate_retrieved: list[str] = []
        for product_id in candidate_raw:
            canonical_id = canonical(product_id)
            if canonical_id not in candidate_retrieved:
                candidate_retrieved.append(canonical_id)
        candidate_depth = int(evidence.get("candidate_metric_depth") or top_k)
        candidate_metric_k = candidate_depth
        candidate_recall = (
            recall_at_k(candidate_retrieved, relevant, candidate_metric_k)
            if candidate_raw else None
        )
        final_recall = recall_at_k(retrieved, relevant, top_k)
        duplicate_rate = (
            (len(raw_retrieved) - len(retrieved)) / len(raw_retrieved)
            if raw_retrieved else 0.0
        )
        dimensions = {
            "category": str(case.get("category") or "ALL"),
            "target_currency": str(case.get("target_currency") or "CNY"),
            "ship_to": str(case.get("ship_to") or "ALL"),
            "split": str(case.get("split") or "ALL"),
            "subset": str(case.get("subset") or "ALL"),
            "scenario": str(case.get("scenario") or (
                "hard_constraint" if any(
                    key in case for key in (
                        "ship_to", "price_max_major", "category",
                        "excluded_material_tags", "required_material_tags", "require_in_stock",
                    )
                ) else "legacy"
            )),
        }
        observation = {
            "case_id": case.get("id"), "query": case["query"], "split": case.get("split"),
            "original_query": case.get("original_query"), "executed_query": executed_query,
            "rewrite_drift": rewrite_drift, "rewrite_note": rewrite_note,
            "latency_ms": round(latency_ms, 3), "metric_k": top_k,
            "actual_strategy": str(payload.get("recall_strategy", "unknown")),
            "retrieval_variant": payload.get("retrieval_variant", "legacy_two_stage"),
            "rerank_applied": payload.get("rerank_applied"), "vector_available": payload.get("vector_available"),
            "raw_retrieved": raw_retrieved, "canonical_retrieved": retrieved, "relevant": relevant,
            "candidate_retrieved": candidate_retrieved,
            "candidate_metric_k": candidate_metric_k,
            "candidate_recall": candidate_recall,
            "bm25_retrieved": list(evidence.get("bm25_product_ids") or []),
            "vector_retrieved": list(evidence.get("vector_product_ids") or []),
            "rerank_prompt_tokens": int((evidence.get("rerank_usage") or {}).get("prompt_tokens") or 0),
            "rerank_document_count": int((evidence.get("rerank_usage") or {}).get("document_count") or 0),
            "expected_empty": bool(case.get("expected_empty")), "empty_pass": not retrieved if case.get("expected_empty") else None,
        }
        if observations is not None:
            observations.append(observation)

        # 无结果题是负例，不能把空 relevant 的 Recall=0 混进正例均值；
        # 它的正确性是“没有返回任何候选”，单独以泄漏率门禁。
        if case.get("expected_empty"):
            empty_results.append(not retrieved)
            continue

        filter_ok, filter_note, violation_count, checked_hits = check_filter_details(
            case, hits, payload.get("filtered_out", []), products,
        )
        filtered_ids = {
            canonical(str(item.get("product_id", "")))
            for item in payload.get("filtered_out", [])
        }
        if final_recall >= 1.0:
            miss_stage = "none"
        elif candidate_recall is None or candidate_recall < 1.0:
            miss_stage = "candidate_generation_miss"
        elif set(relevant) & filtered_ids:
            miss_stage = "hard_constraint_filter"
        else:
            miss_stage = "rerank_miss"
        observation.update(
            filter_ok=filter_ok, filter_note=filter_note,
            hard_constraint_violations=violation_count,
            hard_constraint_checked_hits=checked_hits,
            miss_stage=miss_stage,
        )
        results.append(
            QueryResult(
                query=case["query"],
                retrieved=retrieved,
                relevant=relevant,
                recall=final_recall,
                mrr=mrr(retrieved, relevant),
                ndcg=ndcg_at_k(retrieved, relevant, top_k),
                precision=precision_at_k(retrieved, relevant, top_k),
                filter_ok=filter_ok,
                note=filter_note,
                kind=case.get("kind", "lexical"),
                canonical_duplicate_rate=duplicate_rate,
                latency_ms=latency_ms,
                hard_constraint_violations=violation_count,
                hard_constraint_checked_hits=checked_hits,
                rewrite_drift=rewrite_drift,
                rewrite_note=rewrite_note,
                candidate_recall=candidate_recall,
                candidate_depth=candidate_metric_k if candidate_recall is not None else None,
                miss_stage=miss_stage,
                dimensions=dimensions,
            ),
        )
    return evaluate(
        results, k=top_k, empty_results=empty_results,
        recall_strategies=sorted(recall_strategies),
        latencies_ms=latencies_ms,
    )


def by_kind(agg: Aggregate) -> dict[str, Aggregate]:
    """按 query 类型拆开。

    拆开是必需的：字面类 query 上关键词召回本来就很强（语料描述关键词密集），
    混在一起算总均会把语义类的差距抹平，看不出向量召回到底买到了什么。
    """
    groups: dict[str, list[QueryResult]] = {}
    for r in agg.per_query:
        groups.setdefault(r.kind, []).append(r)
    return {kind: evaluate(rs, k=agg.k) for kind, rs in sorted(groups.items())}


def hybrid_execution_errors(observations: list[dict]) -> list[str]:
    errors = []
    for row in observations:
        if row.get("actual_strategy") not in {"hybrid_rerank", "hybrid_only"}:
            errors.append(f"{row.get('case_id') or row['query']}: 实际策略不是 Hybrid 向量链")
        if row.get("vector_available") is not True:
            errors.append(f"{row.get('case_id') or row['query']}: Hybrid 向量侧未证明健康")
        if row.get("raw_retrieved") and (row.get("rerank_applied") is not True or row.get("actual_strategy") != "hybrid_rerank"):
            errors.append(f"{row.get('case_id') or row['query']}: 非空候选未执行真实精排")
    return errors


def by_dimension(agg: Aggregate, dimension: str) -> dict[str, Aggregate]:
    """按正式集的业务维度分桶，避免总平均掩盖局部退化。"""
    groups: dict[str, list[QueryResult]] = {}
    for result in agg.per_query:
        value = result.dimensions.get(dimension, "ALL")
        groups.setdefault(value, []).append(result)
    return {value: evaluate(results, k=agg.k) for value, results in sorted(groups.items())}


def print_summary(label: str, agg: Aggregate) -> None:
    filt = "n/a" if agg.filter_accuracy is None else f"{agg.filter_accuracy:.3f}"
    empty = "n/a" if agg.empty_accuracy is None else f"{agg.empty_accuracy:.3f} ({agg.empty_count} 条)"
    duplicate = "n/a" if agg.canonical_duplicate_rate is None else f"{agg.canonical_duplicate_rate:.3f}"
    actual_strategy = ",".join(sorted(agg.recall_strategies)) or "unknown"
    violation = "n/a" if agg.hard_constraint_violation_rate is None else f"{agg.hard_constraint_violation_rate:.3f}"
    latency = "n/a" if agg.latency_p95_ms is None else f"{agg.latency_p95_ms:.1f}ms"
    drift = "n/a" if agg.rewrite_drift_rate is None else f"{agg.rewrite_drift_rate:.3f} ({agg.rewrite_count} 条)"
    candidate = "n/a" if agg.candidate_recall is None else f"{agg.candidate_recall:.3f}"
    candidate_depth = agg.candidate_depth or agg.k
    print(
        f"  {label:<18} CandidateRecall@{candidate_depth}={candidate}  FinalRecall@{agg.k}={agg.recall:.3f}  Precision@{agg.k}={agg.precision:.3f}  MRR={agg.mrr:.3f}  "
        f"NDCG@{agg.k}={agg.ndcg:.3f}  过滤准确率={filt}  硬约束违规率={violation}  "
        f"P95={latency}  改写漂移率={drift}  无结果准确率={empty}  同款重复率={duplicate}  实际链路={actual_strategy}",
    )
    for kind, sub in by_kind(agg).items():
        print(
            f"    └─ {kind:<10}({sub.count:>2} 条) CandidateRecall="
            f"{'n/a' if sub.candidate_recall is None else f'{sub.candidate_recall:.3f}'}  "
            f"FinalRecall={sub.recall:.3f}  Precision={sub.precision:.3f}  "
            f"MRR={sub.mrr:.3f}  NDCG={sub.ndcg:.3f}",
        )


def render_report(
    per_strategy: dict[str, Aggregate], thresholds: Thresholds, top_k: int,
    baselines: dict[str, dict[str, float]] | None = None,
    dataset: Path | str = _DATASET,
    profile: str = "custom",
) -> str:
    candidate_depth = max(
        (agg.candidate_depth or top_k for agg in per_strategy.values()),
        default=top_k,
    )
    lines = [
        f"# 商品检索召回评测报告（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）",
        "",
        f"标注集 `{dataset}`，profile={profile}，K={top_k}。",
        "",
        "## 指标总览",
        "",
        f"| 档位 | 实际召回链 | Candidate Recall@{candidate_depth} | Final Recall@{top_k} | Precision@{top_k} | MRR | NDCG@{top_k} | 过滤准确率 | 硬约束违规率 | P50/P95 延迟(ms) | 改写漂移率 | 无结果准确率 | 同款重复率 | 门禁 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, agg in per_strategy.items():
        verdict, _ = gate(agg, thresholds, (baselines or {}).get(name))
        filt = "n/a" if agg.filter_accuracy is None else f"{agg.filter_accuracy:.3f}"
        empty = "n/a" if agg.empty_accuracy is None else f"{agg.empty_accuracy:.3f}"
        duplicate = "n/a" if agg.canonical_duplicate_rate is None else f"{agg.canonical_duplicate_rate:.3f}"
        violation = "n/a" if agg.hard_constraint_violation_rate is None else f"{agg.hard_constraint_violation_rate:.3f}"
        latency = "n/a" if agg.latency_p95_ms is None else f"{agg.latency_p50_ms:.1f}/{agg.latency_p95_ms:.1f}"
        drift = "n/a" if agg.rewrite_drift_rate is None else f"{agg.rewrite_drift_rate:.3f}"
        candidate = "n/a" if agg.candidate_recall is None else f"{agg.candidate_recall:.3f}"
        lines.append(
            f"| {name} | {','.join(sorted(agg.recall_strategies)) or 'unknown'} | {candidate} | {agg.recall:.3f} | {agg.precision:.3f} | {agg.mrr:.3f} | {agg.ndcg:.3f} | {filt} | {violation} | {latency} | {drift} | {empty} | {duplicate} | {verdict} |",
        )

    precision_gate = "观察项（未穷举金标，不阻断）" if thresholds.precision is None else f"≥ {thresholds.precision}"
    lines += ["", f"门禁阈值：Recall ≥ {thresholds.recall}、Precision {precision_gate}、MRR ≥ {thresholds.mrr}"
              f"、NDCG ≥ {thresholds.ndcg}、过滤准确率 ≥ {thresholds.filter_accuracy}、无结果准确率 ≥ {thresholds.empty_accuracy}"
              f"、硬约束违规率 ≤ {thresholds.max_hard_constraint_violation_rate}、P95 延迟 ≤ {thresholds.max_latency_p95_ms}ms"
              f"、改写漂移率 ≤ {thresholds.max_rewrite_drift_rate}。", ""]

    lines += ["## 按 query 类型拆分", "",
              "字面类（lexical）query 与语料共享词汇，关键词召回天然占优；"
              "语义类（semantic）query 刻意不含商品字面，是向量召回真正创造价值的地方。", "",
              f"| 档位 | 类型 | 条数 | Recall@{top_k} | Precision@{top_k} | MRR | NDCG@{top_k} |",
              "|---|---|---|---|---|---|---|"]
    for name, agg in per_strategy.items():
        for kind, sub in by_kind(agg).items():
            lines.append(
                f"| {name} | {kind} | {sub.count} | {sub.recall:.3f} | {sub.precision:.3f} | "
                f"{sub.mrr:.3f} | {sub.ndcg:.3f} |",
            )
    lines.append("")

    lines += ["## 正式分桶监控", "",
              "以下各桶分别展示，供定位品类、币种、目的国和 dev/release 的局部退化；正式数据缺桶会在数据校验阶段直接报错。", "",
              f"| 档位 | 维度 | 取值 | 条数 | Recall@{top_k} | Precision@{top_k} | MRR | NDCG@{top_k} |", 
              "|---|---|---|---|---|---|---|---|"]
    for name, agg in per_strategy.items():
        for dimension in ("category", "target_currency", "ship_to", "scenario", "subset", "split"):
            for value, sub in by_dimension(agg, dimension).items():
                lines.append(
                    f"| {name} | {dimension} | {value} | {sub.count} | {sub.recall:.3f} | "
                    f"{sub.precision:.3f} | {sub.mrr:.3f} | {sub.ndcg:.3f} |",
                )
    lines.append("")

    lines += ["## Miss 阶段归因", "",
              "`candidate_generation_miss` 表示一阶段候选未覆盖全部金标；"
              "`rerank_miss` 表示候选已覆盖但最终 Top-K 丢失；"
              "`hard_constraint_filter` 表示金标在结构化过滤阶段被挡掉。", "",
              "| 档位 | none | candidate generation | rerank | hard constraint/filter |",
              "|---|---|---|---|---|"]
    for name, agg in per_strategy.items():
        counts = agg.miss_stage_counts
        lines.append(
            f"| {name} | {counts.get('none', 0)} | {counts.get('candidate_generation_miss', 0)} | "
            f"{counts.get('rerank_miss', 0)} | {counts.get('hard_constraint_filter', 0)} |",
        )
    lines.append("")

    for name, agg in per_strategy.items():
        verdict, reasons = gate(agg, thresholds, (baselines or {}).get(name))
        lines += [f"## {name}（{verdict}，{agg.count} 条）", ""]
        if reasons:
            lines += ["未达标项：", *[f"- {r}" for r in reasons], ""]
        lines += ["| query | 类型 | Candidate Recall | Final Recall | Precision | MRR | NDCG | Miss stage | 延迟(ms) | 违规命中 | 改写漂移 | 召回序 | 标注 | 过滤 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in agg.per_query:
            filt = "-" if r.filter_ok is None else ("OK" if r.filter_ok else f"FAIL {r.note}")
            lines.append(
                f"| {r.query} | {r.kind} | {'-' if r.candidate_recall is None else f'{r.candidate_recall:.2f}'} | {r.recall:.2f} | {r.precision:.2f} | {r.mrr:.2f} | {r.ndcg:.2f} | {r.miss_stage} | "
                f"{r.latency_ms or 0:.1f} | {r.hard_constraint_violations}/{r.hard_constraint_checked_hits} | "
                f"{'-' if r.rewrite_drift is None else ('FAIL ' + r.rewrite_note if r.rewrite_drift else 'OK')} | "
                f"{','.join(r.retrieved) or '（空）'} | {','.join(r.relevant)} | {filt} |",
            )
        lines.append("")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="商品检索召回评测")
    parser.add_argument("--dataset", default=str(_DATASET))
    parser.add_argument("--catalog", type=Path, default=None, help="可选商品 JSONL；默认保持现有 data/catalog-v1.jsonl")
    parser.add_argument("--split", choices=SPLITS, default="all", help="先选择输入集，再执行与门禁；默认 all 兼容旧命令")
    parser.add_argument("--dry-run", action="store_true", help="只校验选集并写 NOT_RUN 证据，不调用模型或向量服务")
    parser.add_argument("--top-k", type=int, default=8, help="最终结果截断 K，默认 8")
    parser.add_argument("--recall-depth", type=int, default=8, help="一阶段候选深度 N；线上默认仍为 8")
    parser.add_argument("--rrf-k", type=int, default=60, help="RRF rank constant")
    parser.add_argument("--rrf-bm25-weight", type=float, default=1.0)
    parser.add_argument("--rrf-vector-weight", type=float, default=1.0)
    parser.add_argument("--strategy", choices=_STRATEGIES, default="embedding_rerank")
    parser.add_argument("--compare-strategies", action="store_true", help="三档降级链对比")
    parser.add_argument("--min-recall", type=float, default=0.75)
    parser.add_argument("--min-precision", type=float, default=0.45)
    parser.add_argument("--min-mrr", type=float, default=0.65)
    parser.add_argument("--min-ndcg", type=float, default=0.70)
    parser.add_argument("--min-empty-accuracy", type=float, default=None)
    parser.add_argument("--max-hard-constraint-violation-rate", type=float, default=0.0)
    parser.add_argument("--max-p95-ms", type=float, default=None)
    parser.add_argument("--max-rewrite-drift-rate", type=float, default=None)
    parser.add_argument("--formal-gates", action="store_true", help="兼容旧命令，等同 --profile online-main")
    parser.add_argument("--profile", choices=("online-main", "offline-fallback", "hybrid-experimental"), default=None)
    parser.add_argument("--baseline-file", type=Path, default=None, help="批准基线 JSON；任一指标下降超过 2 个百分点即阻断")
    parser.add_argument("--report-dir", default="eval")
    args = parser.parse_args(argv)
    if args.top_k <= 0:
        parser.error("--top-k 必须为正整数")
    if args.recall_depth <= 0:
        parser.error("--recall-depth 必须为正整数")
    if args.top_k > args.recall_depth and args.strategy in {"embedding_only", "embedding_rerank", "hybrid_rrf", "hybrid_rerank"}:
        parser.error("embedding 策略要求 --top-k 不大于 --recall-depth")
    try:
        cases, selection = select_cases(load_dataset(Path(args.dataset)), args.split)
        validate_baseline_selection(args.baseline_file, selection, Path(args.dataset))
    except (ValueError, OSError) as err:
        parser.error(str(err))
    print(f"标注集 {args.dataset}：split={args.split}，{len(cases)} 条，K={args.top_k}")

    profile = args.profile
    if args.formal_gates:
        if profile and profile != "online-main":
            parser.error("--formal-gates 只能与 --profile online-main 一起使用")
        profile = "online-main"
    if profile == "online-main":
        if args.compare_strategies or args.strategy != "embedding_rerank":
            parser.error("online-main 只评 embedding_rerank；关键词降级请使用 --profile offline-fallback")
        thresholds = profile_thresholds(profile)
    elif profile == "offline-fallback":
        if args.compare_strategies or args.strategy != "keyword_2gram":
            parser.error("offline-fallback 只评 keyword_2gram")
        if args.baseline_file is None:
            parser.error("offline-fallback 必须提供 --baseline-file，防止无基线时假绿")
        thresholds = profile_thresholds(profile)
    elif profile == "hybrid-experimental":
        if args.compare_strategies or args.strategy != "hybrid_rerank":
            parser.error("hybrid-experimental 只评显式 --strategy hybrid_rerank，不替代 online-main")
        thresholds = profile_thresholds(profile)
    else:
        thresholds = Thresholds(
            recall=args.min_recall, precision=args.min_precision, mrr=args.min_mrr,
            ndcg=args.min_ndcg, empty_accuracy=args.min_empty_accuracy,
            max_hard_constraint_violation_rate=args.max_hard_constraint_violation_rate,
            max_latency_p95_ms=args.max_p95_ms,
            max_rewrite_drift_rate=args.max_rewrite_drift_rate,
        )
    targets = list(_COMPARISON_STRATEGIES) if args.compare_strategies else [args.strategy]
    baselines = load_baselines(args.baseline_file)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"recall-{args.split}-report-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.md"
    manifest = build_manifest(
        runner="product_recall", dataset=Path(args.dataset), selection=selection, baseline=args.baseline_file,
        catalog=args.catalog,
        parameters={"profile": profile or "custom", "top_k": args.top_k, "requested_strategies": targets,
                    "thresholds": thresholds, "dry_run": args.dry_run,
                    "recall_depth": args.recall_depth,
                    "rrf_k": args.rrf_k,
                    "rrf_weights": [args.rrf_bm25_weight, args.rrf_vector_weight],
                    "variant": "bm25_vector_rrf_v1" if args.strategy in {"bm25", "hybrid_rrf", "hybrid_rerank"} else "legacy_two_stage",
                    "gate_scope": "experiment" if args.strategy in {"bm25", "hybrid_rrf", "hybrid_rerank"} else "release" if args.split == "release" and profile == "online-main" else "diagnostic"},
    )
    if args.dry_run:
        path = write_manifest(manifest, report_path)
        print(f"仅校验选集：NOT_RUN；未计算指标、未判定通过。证据：{path}")
        return

    per_strategy: dict[str, Aggregate] = {}
    observations: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    for strategy in targets:
        print(f"\n[{strategy}] 装配中…")
        observations[strategy] = []
        try:
            usecase, repo, _ = await build_usecase(
                strategy, args.catalog, args.recall_depth,
                rrf_k=args.rrf_k,
                rrf_weights=(args.rrf_bm25_weight, args.rrf_vector_weight),
            )
            agg = await run_dataset(usecase, repo, cases, args.top_k, observations=observations[strategy])
        except Exception as err:  # 保留失败证据，不把初始化异常或部分执行算作通过
            errors[strategy] = f"{type(err).__name__}: {err}"
            print(f"  [error] {errors[strategy]}")
            continue
        per_strategy[strategy] = agg
        print_summary(strategy, agg)

    verdicts = {name: gate(agg, thresholds, baselines.get(name))[0] for name, agg in per_strategy.items()}
    if profile == "hybrid-experimental":
        failures = hybrid_execution_errors(observations.get("hybrid_rerank", []))
        if failures:
            errors["hybrid_execution"] = "；".join(failures)
    blocked = bool(errors) or not verdicts or "BLOCK" in verdicts.values()
    stable = finish_manifest(
        manifest, actual_strategies={name: sorted(agg.recall_strategies) for name, agg in per_strategy.items()},
        gate="BLOCK" if blocked else "PASS", status="ERROR" if errors else "COMPLETED",
        metrics=per_strategy, observations=observations, errors=errors, strategy_verdicts=verdicts,
    )
    write_manifest(manifest, report_path)
    report_path.write_text(
        render_report(per_strategy, thresholds, args.top_k, baselines, dataset=Path(args.dataset), profile=profile or "custom")
        + manifest_report(manifest)
        + ("\n执行错误：\n" + "\n".join(f"- {name}: {message}" for name, message in errors.items()) if errors else ""),
        encoding="utf-8",
    )
    print(f"\n报告已写入 {report_path}")

    # 任一档位被阻断即以非零码退出，便于直接接 CI
    print(f"最终门禁：{manifest['execution']['gate']}；" + "，".join(f"{n}={v}" for n, v in verdicts.items()))
    if not stable:
        print("阻断原因：运行期间代码或数据输入发生变化，需在固定版本上重跑。")
    if blocked or not stable:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
