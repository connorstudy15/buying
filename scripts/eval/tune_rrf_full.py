# -*- coding: utf-8 -*-
"""全对称 RRF 调参：所有配置候选均经过真实 qwen reranker 评分。"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.infrastructure.embedding.openai_embedding_client import OpenAIEmbeddingClient
from app.infrastructure.persistence.in_memory_repositories import InMemoryProductRepository
from app.infrastructure.persistence.seed_products import build_seed_products
from app.infrastructure.rerank.http_reranker import HttpReranker
from app.infrastructure.settings import load_settings
from app.infrastructure.vector.index_bootstrap import bootstrap_product_index
from app.infrastructure.vector.qdrant_product_index import QdrantProductIndex
from scripts.eval.metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k
from scripts.eval.run_product_recall import load_dataset, run_dataset
from scripts.eval.tune_rrf import (
    Config, _canonical_sequence, _case_spec, _has_constraints,
    _split_by_relevance_family, _weighted_fusion,
)


WEIGHTS = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00)
RRF_KS = (10, 30, 60, 100)
DEPTHS = (16, 20, 24, 28, 32)
FINAL_KS = (1, 3, 5)
BASELINE = Config(1.0, 1.0, 60, 24)


def _configs() -> list[Config]:
    return [Config(weight, 1.0, rrf_k, depth) for weight in WEIGHTS for rrf_k in RRF_KS for depth in DEPTHS]


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _summary(rows: list[dict], split: str, final_k: int) -> dict:
    selected = rows if split == "all" else [row for row in rows if row["split"] == split]
    def metric(kind: str, function) -> float:
        bucket = [row for row in selected if kind == "all" or row["kind"] == kind]
        return round(_mean([function(row) for row in bucket]), 6)
    return {
        "count": len(selected),
        "recall": metric("all", lambda row: recall_at_k(row["ranked"], row["relevant"], final_k)),
        "precision": metric("all", lambda row: precision_at_k(row["ranked"], row["relevant"], final_k)),
        "mrr": metric("all", lambda row: mrr(row["ranked"][:final_k], row["relevant"])),
        "ndcg": metric("all", lambda row: ndcg_at_k(row["ranked"], row["relevant"], final_k)),
        "lexical_recall": metric("lexical", lambda row: recall_at_k(row["ranked"], row["relevant"], final_k)),
        "semantic_recall": metric("semantic", lambda row: recall_at_k(row["ranked"], row["relevant"], final_k)),
        "constraint_recall": round(_mean([
            recall_at_k(row["ranked"], row["relevant"], final_k)
            for row in selected if row["constrained"]
        ]), 6),
    }


def _paired(rows_a: list[dict], rows_b: list[dict], function) -> dict:
    by_query = {row["query"]: row for row in rows_b}
    deltas = [(function(row) - function(by_query[row["query"]]), row["query"]) for row in rows_a]
    return {
        "win": sum(delta > 1e-12 for delta, _ in deltas),
        "loss": sum(delta < -1e-12 for delta, _ in deltas),
        "tie": sum(abs(delta) <= 1e-12 for delta, _ in deltas),
        "changed": [{"query": query, "delta": round(delta, 6)} for delta, query in deltas if abs(delta) > 1e-12],
    }


def _bootstrap_ci(rows_a: list[dict], rows_b: list[dict], function, rounds: int = 10000) -> dict:
    by_query = {row["query"]: row for row in rows_b}
    deltas = [function(row) - function(by_query[row["query"]]) for row in rows_a]
    rng = random.Random(20260928)
    means = sorted(_mean([deltas[rng.randrange(len(deltas))] for _ in deltas]) for _ in range(rounds))
    return {
        "mean_delta": round(_mean(deltas), 6),
        "ci95_low": round(means[math.floor(0.025 * rounds)], 6),
        "ci95_high": round(means[math.ceil(0.975 * rounds) - 1], 6),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("eval/product_recall.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("eval/rrf-full-rerank"))
    args = parser.parse_args()
    cases = load_dataset(args.dataset)
    settings = load_settings()
    repo = InMemoryProductRepository(build_seed_products())
    product_list = await repo.list_all()
    products = {product.product_id: product for product in product_list}
    canonical = {product.product_id: product.canonical_product_id or product.product_id for product in product_list}
    embedder = OpenAIEmbeddingClient(settings)
    vector_index = QdrantProductIndex(settings)
    if not await bootstrap_product_index(repo, embedder, vector_index):
        raise RuntimeError("向量建库失败，拒绝使用降级结果")
    collector = CatalogSearchUseCase(
        repo, embedder=embedder, vector_index=vector_index,
        hybrid_enabled=True, include_retrieval_evidence=True, recall_top_n=40,
    )
    rows = []
    for case in cases:
        payload = await collector.execute(_case_spec(case, top_k=5))
        evidence = payload.get("retrieval_evidence") or {}
        if not payload.get("vector_available"):
            raise RuntimeError(f"{case['query']} 没有真实向量召回证据")
        rows.append({
            "query": case["query"], "executed_query": case.get("rewritten_query") or case["query"],
            "kind": case.get("kind", "lexical"), "constrained": _has_constraints(case),
            "relevant": case.get("relevant_canonical_ids") or [canonical.get(pid, pid) for pid in case["relevant"]],
            "bm25_ids": list(evidence.get("bm25_product_ids") or []),
            "vector_ids": list(evidence.get("vector_product_ids") or []), "canonical": canonical,
        })
    _split_by_relevance_family(rows, 22)

    configs = _configs()
    reranker = HttpReranker(settings, timeout_seconds=30.0)
    scored_rows = []
    total_tokens = 0
    union_sizes = []
    consistency_checks = []
    for index, row in enumerate(rows, start=1):
        candidates_by_config = {config.name: _weighted_fusion(row, config) for config in configs}
        union_ids = list(dict.fromkeys(pid for ids in candidates_by_config.values() for pid in ids))
        union_products = [products[pid] for pid in union_ids]
        started = perf_counter()
        union_scores = await reranker.rerank(row["executed_query"], [product.searchable_text() for product in union_products])
        elapsed = (perf_counter() - started) * 1000
        total_tokens += int(reranker.last_usage.get("prompt_tokens") or 0)
        union_sizes.append(len(union_ids))
        score_map = dict(zip(union_ids, union_scores))

        # 抽样验证：同一 query-document 在大批次与基线子集中排序应一致。
        if index in {1, 12, 24, 36, 48, 60, 67}:
            subset_ids = candidates_by_config[BASELINE.name]
            subset_scores = await reranker.rerank(
                row["executed_query"], [products[pid].searchable_text() for pid in subset_ids],
            )
            union_order = sorted(subset_ids, key=lambda pid: (-score_map[pid], pid))
            subset_map = dict(zip(subset_ids, subset_scores))
            subset_order = sorted(subset_ids, key=lambda pid: (-subset_map[pid], pid))
            consistency_checks.append({
                "query": row["query"], "exact_order_match": union_order == subset_order,
                "top5_match": union_order[:5] == subset_order[:5],
                "max_abs_score_delta": round(max(abs(score_map[pid] - subset_map[pid]) for pid in subset_ids), 9),
            })
            total_tokens += int(reranker.last_usage.get("prompt_tokens") or 0)

        rankings = {}
        for config in configs:
            ids = candidates_by_config[config.name]
            ranked_ids = sorted(ids, key=lambda pid: (-score_map[pid], pid))
            rankings[config.name] = _canonical_sequence(ranked_ids, canonical)
        scored_rows.append({
            "query": row["query"], "split": row["split"], "kind": row["kind"],
            "constrained": row["constrained"], "relevant": row["relevant"],
            "rerank_latency_ms": round(elapsed, 3), "union_document_count": len(union_ids),
            "rankings": rankings,
        })
        print(f"real rerank {index}/{len(rows)} docs={len(union_ids)}", flush=True)

    results = []
    for config in configs:
        config_rows = [{**row, "ranked": row["rankings"][config.name]} for row in scored_rows]
        summaries = {
            split: {str(final_k): _summary(config_rows, split, final_k) for final_k in FINAL_KS}
            for split in ("tune", "holdout", "all")
        }
        results.append({"config": asdict(config), "summary": summaries})

    def tune_key(result: dict) -> tuple:
        metric = result["summary"]["tune"]["3"]
        config = Config(**result["config"])
        return (metric["recall"], metric["ndcg"], metric["mrr"], -config.depth, -abs(config.bm25_weight - 1.0))

    tuned = max(results, key=tune_key)
    tuned_config = Config(**tuned["config"])
    baseline = next(result for result in results if Config(**result["config"]) == BASELINE)
    tuned_rows = [{**row, "ranked": row["rankings"][tuned_config.name]} for row in scored_rows]
    baseline_rows = [{**row, "ranked": row["rankings"][BASELINE.name]} for row in scored_rows]
    holdout_tuned = tuned["summary"]["holdout"]["3"]
    holdout_base = baseline["summary"]["holdout"]["3"]
    confirmed = (
        holdout_tuned["recall"] >= holdout_base["recall"]
        and holdout_tuned["ndcg"] >= holdout_base["ndcg"] - 0.005
        and all(check["top5_match"] for check in consistency_checks)
    )
    winner = tuned_config if confirmed else BASELINE
    winner_result = tuned if confirmed else baseline
    tune_k3 = winner_result["summary"]["tune"]["3"]["recall"]
    tune_k5 = winner_result["summary"]["tune"]["5"]["recall"]
    recommended_k = 3 if tune_k5 - tune_k3 < 0.01 else 5

    winner_rows = [{**row, "ranked": row["rankings"][winner.name]} for row in scored_rows]
    pairwise = {
        "recall_at_3": _paired(winner_rows, baseline_rows, lambda row: recall_at_k(row["ranked"], row["relevant"], 3)),
        "ndcg_at_3": _paired(winner_rows, baseline_rows, lambda row: ndcg_at_k(row["ranked"], row["relevant"], 3)),
        "top1": _paired(winner_rows, baseline_rows, lambda row: float(bool(row["ranked"]) and row["ranked"][0] in set(row["relevant"]))),
    }
    bootstrap = {
        "recall_at_3": _bootstrap_ci(winner_rows, baseline_rows, lambda row: recall_at_k(row["ranked"], row["relevant"], 3)),
        "ndcg_at_3": _bootstrap_ci(winner_rows, baseline_rows, lambda row: ndcg_at_k(row["ranked"], row["relevant"], 3)),
    }

    verifier = CatalogSearchUseCase(
        repo, embedder=embedder, vector_index=vector_index, reranker=reranker,
        hybrid_enabled=True, include_retrieval_evidence=True, recall_top_n=winner.depth,
        rrf_k=winner.rrf_k, rrf_weights=(winner.bm25_weight, winner.vector_weight),
    )
    observations: list[dict] = []
    verification = await run_dataset(verifier, repo, cases, recommended_k, observations=observations)
    payload = {
        "created_at": datetime.now().astimezone().isoformat(), "dataset": str(args.dataset),
        "method": "所有120组配置可能进入的候选取并集，每个 query-document 由真实 qwen3.7 reranker 评分；随后只离线重组排名",
        "search_space": {"weights": WEIGHTS, "rrf_k": RRF_KS, "depths": DEPTHS, "final_k": FINAL_KS},
        "split_counts": {"tune": sum(row["split"] == "tune" for row in rows), "holdout": sum(row["split"] == "holdout" for row in rows)},
        "real_rerank": {
            "query_count": len(rows), "query_document_pairs": sum(union_sizes),
            "min_union_documents": min(union_sizes), "max_union_documents": max(union_sizes),
            "average_union_documents": round(_mean(union_sizes), 3), "prompt_tokens": total_tokens,
            "estimated_cny": round(total_tokens * 0.5 / 1_000_000, 6),
            "batch_invariance_checks": consistency_checks,
        },
        "results": results, "tuned_config": asdict(tuned_config), "holdout_confirmed": confirmed,
        "winner": asdict(winner), "recommended_final_k": recommended_k,
        "pairwise_vs_baseline": pairwise, "bootstrap_vs_baseline": bootstrap,
        "end_to_end": {
            "candidate_recall": verification.candidate_recall, "recall": verification.recall,
            "precision": verification.precision, "mrr": verification.mrr, "ndcg": verification.ndcg,
            "filter_accuracy": verification.filter_accuracy,
            "hard_constraint_violation_rate": verification.hard_constraint_violation_rate,
            "latency_p50_ms": verification.latency_p50_ms, "latency_p95_ms": verification.latency_p95_ms,
            "actual_strategies": sorted(verification.recall_strategies),
        },
        "observations": observations,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = args.output_dir / f"rrf-full-{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "evidence": str(path), "tuned_config": asdict(tuned_config), "holdout_confirmed": confirmed,
        "winner": asdict(winner), "recommended_final_k": recommended_k,
        "real_rerank": payload["real_rerank"], "pairwise": pairwise,
        "bootstrap": bootstrap, "end_to_end": payload["end_to_end"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
