# -*- coding: utf-8 -*-
"""两阶段调优 BM25/Vector RRF 权重、rank constant、候选 N 与最终 K。

阶段一只执行一次真实 Hybrid 召回并缓存两路 Top-40，随后离线搜索参数；
阶段二只对调参集入围方案执行真实 reranker，选定方案后在保留集确认。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.domain.catalog.product_search_spec import ProductSearchSpec
from app.infrastructure.embedding.openai_embedding_client import OpenAIEmbeddingClient
from app.infrastructure.persistence.in_memory_repositories import InMemoryProductRepository
from app.infrastructure.persistence.seed_products import build_seed_products
from app.infrastructure.rerank.http_reranker import HttpReranker
from app.infrastructure.settings import load_settings
from app.infrastructure.vector.index_bootstrap import bootstrap_product_index
from app.infrastructure.vector.qdrant_product_index import QdrantProductIndex
from scripts.eval.metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k
from scripts.eval.run_product_recall import load_dataset, run_dataset


WEIGHTS = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00)
RRF_KS = (10, 30, 60)
DEPTHS = (12, 16, 20, 24, 28, 32)
FINAL_KS = (1, 3, 5)


@dataclass(frozen=True)
class Config:
    bm25_weight: float
    vector_weight: float
    rrf_k: int
    depth: int

    @property
    def name(self) -> str:
        return f"b{self.bm25_weight:g}-v{self.vector_weight:g}-r{self.rrf_k}-n{self.depth}"


def _case_spec(case: dict, *, top_k: int) -> ProductSearchSpec:
    return ProductSearchSpec(
        normalized_query=case.get("rewritten_query") or case["query"],
        top_k=top_k,
        category=case.get("category"),
        price_max_major=case.get("price_max_major"),
        ship_to=case.get("ship_to"),
        target_currency=case.get("target_currency", "CNY"),
        excluded_material_tags=case.get("excluded_material_tags", []),
        required_material_tags=case.get("required_material_tags", []),
    )


def _canonical_sequence(ids: list[str], canonical: dict[str, str]) -> list[str]:
    result: list[str] = []
    for product_id in ids:
        value = canonical.get(product_id, product_id)
        if value not in result:
            result.append(value)
    return result


def _weighted_fusion(row: dict, config: Config) -> list[str]:
    scores: dict[str, float] = {}
    for ids, weight in (
        (row["bm25_ids"], config.bm25_weight),
        (row["vector_ids"], config.vector_weight),
    ):
        # 与 CatalogSearchUseCase 完全一致：每路先截到 N，再做 RRF，融合后再截 N。
        for rank, product_id in enumerate(ids[: config.depth], start=1):
            scores[product_id] = scores.get(product_id, 0.0) + weight / (config.rrf_k + rank)
    return sorted(scores, key=lambda product_id: (-scores[product_id], product_id))[: config.depth]


def _has_constraints(case: dict) -> bool:
    return any(
        key in case
        for key in (
            "ship_to", "price_max_major", "category", "excluded_material_tags",
            "required_material_tags", "require_in_stock",
        )
    )


def _split_by_relevance_family(rows: list[dict], holdout_target: int) -> None:
    """共享 relevant 的同义/近义 query 必须整体位于同一 split。"""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owners: dict[str, int] = {}
    for index, row in enumerate(rows):
        for relevant_id in row["relevant"]:
            if relevant_id in owners:
                union(index, owners[relevant_id])
            else:
                owners[relevant_id] = index
    groups: dict[int, list[int]] = {}
    for index in range(len(rows)):
        groups.setdefault(find(index), []).append(index)
    ordered = sorted(
        groups.values(),
        key=lambda group: hashlib.sha256(
            "|".join(rows[index]["query"] for index in group).encode("utf-8")
        ).hexdigest(),
    )
    holdout: set[int] = set()
    for group in ordered:
        if len(holdout) + len(group) <= holdout_target:
            holdout.update(group)
    for index, row in enumerate(rows):
        row["split"] = "holdout" if index in holdout else "tune"


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _candidate_metrics(rows: list[dict], config: Config, split: str) -> dict:
    selected = [row for row in rows if row["split"] == split]
    recalls, lexical, semantic, constrained = [], [], [], []
    for row in selected:
        fused = _weighted_fusion(row, config)
        candidate = _canonical_sequence(fused, row["canonical"])
        score = recall_at_k(candidate, row["relevant"], config.depth)
        recalls.append(score)
        (semantic if row["kind"] == "semantic" else lexical).append(score)
        if row["constrained"]:
            constrained.append(score)
    return {
        "count": len(selected),
        "candidate_recall": round(_mean(recalls), 6),
        "lexical_recall": round(_mean(lexical), 6),
        "semantic_recall": round(_mean(semantic), 6),
        "constraint_recall": round(_mean(constrained), 6),
    }


def _select_candidate_finalists(grid: list[dict]) -> list[Config]:
    """每组权重/k 取距离 N=32 最优不超过 0.3pp 的最小 N，再取前两名。"""
    elbow_rows: list[dict] = []
    for weight in WEIGHTS:
        for rrf_k in RRF_KS:
            subset = [row for row in grid if row["config"]["bm25_weight"] == weight and row["config"]["rrf_k"] == rrf_k]
            best_recall = max(row["tune"]["candidate_recall"] for row in subset)
            eligible = [row for row in subset if row["tune"]["candidate_recall"] >= best_recall - 0.003]
            elbow_rows.append(min(eligible, key=lambda row: row["config"]["depth"]))
    elbow_rows.sort(
        key=lambda row: (
            -row["tune"]["candidate_recall"],
            -min(row["tune"]["lexical_recall"], row["tune"]["semantic_recall"]),
            -row["tune"]["constraint_recall"],
            row["config"]["depth"],
        )
    )
    baseline = Config(1.0, 1.0, 60, 24)
    finalists = [Config(**row["config"]) for row in elbow_rows[:2]]
    if baseline not in finalists:
        finalists.append(baseline)
    return finalists


async def _rerank_config(
    rows: list[dict], config: Config, reranker: HttpReranker, products: dict[str, object],
) -> dict:
    output_rows = []
    total_tokens = 0
    for row in rows:
        fused = _weighted_fusion(row, config)
        candidates = [products[product_id] for product_id in fused if product_id in products]
        documents = [product.searchable_text() for product in candidates]
        started = perf_counter()
        scores = await reranker.rerank(row["executed_query"], documents)
        latency_ms = (perf_counter() - started) * 1000
        ranked = [
            product.product_id
            for _, product in sorted(
                zip(scores, candidates),
                key=lambda pair: (-pair[0], pair[1].product_id),
            )
        ]
        canonical_ranked = _canonical_sequence(ranked, row["canonical"])
        usage = dict(reranker.last_usage)
        total_tokens += int(usage.get("prompt_tokens") or 0)
        output_rows.append({
            "query": row["query"], "split": row["split"], "kind": row["kind"],
            "constrained": row["constrained"], "relevant": row["relevant"],
            "ranked": canonical_ranked, "latency_ms": round(latency_ms, 3),
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "document_count": len(documents),
        })
    summaries = {}
    for split in ("tune", "holdout", "all"):
        selected = output_rows if split == "all" else [row for row in output_rows if row["split"] == split]
        summaries[split] = {}
        for final_k in FINAL_KS:
            summaries[split][str(final_k)] = {
                "count": len(selected),
                "recall": round(_mean([recall_at_k(row["ranked"], row["relevant"], final_k) for row in selected]), 6),
                "precision": round(_mean([precision_at_k(row["ranked"], row["relevant"], final_k) for row in selected]), 6),
                "mrr": round(_mean([mrr(row["ranked"][:final_k], row["relevant"]) for row in selected]), 6),
                "ndcg": round(_mean([ndcg_at_k(row["ranked"], row["relevant"], final_k) for row in selected]), 6),
            }
    latencies = sorted(row["latency_ms"] for row in output_rows)
    p95 = latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)] if latencies else 0.0
    return {
        "config": asdict(config), "summary": summaries,
        "reranker_prompt_tokens": total_tokens,
        "reranker_estimated_cny": round(total_tokens * 0.5 / 1_000_000, 6),
        "reranker_p95_ms": round(p95, 3), "rows": output_rows,
    }


def _render_report(payload: dict) -> str:
    lines = [
        "# RRF 权重、N 与最终 K 两阶段实验", "",
        f"运行时间：{payload['created_at']}；数据集：`{payload['dataset']}`。", "",
        "## 实验设计", "",
        "- 每条 Query 只做一次真实 BM25/Embedding Top-40 召回，缓存两路原始名次。",
        "- 按共享 relevant ID 构成 Query 家族，家族整体进入 tune 或 holdout，避免近义题泄漏。",
        "- 离线扫描 6 组 BM25 权重、3 个 RRF rank constant、6 个 N，共 108 个组合。",
        "- 每组权重/constant 选择距离该组最佳 Candidate Recall 不超过 0.3pp 的最小 N。",
        "- 只对入围方案调用真实 qwen3.7 reranker，并从同一完整排序离线计算 K=1/3/5。", "",
        "## 数据划分", "",
        f"- tune：{payload['split_counts']['tune']} 条；holdout：{payload['split_counts']['holdout']} 条。",
        f"- tune semantic：{payload['split_counts']['tune_semantic']}；holdout semantic：{payload['split_counts']['holdout_semantic']}。", "",
        "## 入围方案真实精排", "",
        "| 配置 | Split | K | Recall | Precision | MRR | nDCG | Rerank P95(ms) | Token | 估算成本(元) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in payload["rerank_results"]:
        config = Config(**result["config"])
        for split in ("tune", "holdout", "all"):
            for final_k in FINAL_KS:
                metrics = result["summary"][split][str(final_k)]
                lines.append(
                    f"| {config.name} | {split} | {final_k} | {metrics['recall']:.4f} | "
                    f"{metrics['precision']:.4f} | {metrics['mrr']:.4f} | {metrics['ndcg']:.4f} | "
                    f"{result['reranker_p95_ms']:.1f} | {result['reranker_prompt_tokens']} | "
                    f"{result['reranker_estimated_cny']:.4f} |"
                )
    winner = Config(**payload["winner"])
    lines.extend([
        "", "## 结论", "",
        f"- 推荐 RRF：BM25:Vector = **{winner.bm25_weight:g}:{winner.vector_weight:g}**，"
        f"`rrf_k={winner.rrf_k}`，`N={winner.depth}`。",
        f"- 推荐最终展示 `K={payload['recommended_final_k']}`。",
        f"- 保留集确认：{payload['holdout_verdict']}。",
        "- 完整 108 组合、逐 Query 排名和 Token 证据保存在同目录 JSON。", "",
    ])
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("eval/product_recall.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("eval/rrf-weight-tuning"))
    parser.add_argument("--holdout-size", type=int, default=22)
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
        raise RuntimeError("向量建库失败，拒绝把降级结果用于 RRF 调参")
    collector = CatalogSearchUseCase(
        repo, embedder=embedder, vector_index=vector_index,
        hybrid_enabled=True, include_retrieval_evidence=True, recall_top_n=40,
    )
    rows = []
    for case in cases:
        payload = await collector.execute(_case_spec(case, top_k=5))
        evidence = payload.get("retrieval_evidence") or {}
        if not payload.get("vector_available"):
            raise RuntimeError(f"{case['query']} 未执行真实向量召回")
        relevant = case.get("relevant_canonical_ids") or [canonical.get(pid, pid) for pid in case["relevant"]]
        rows.append({
            "query": case["query"], "executed_query": case.get("rewritten_query") or case["query"],
            "kind": case.get("kind", "lexical"), "constrained": _has_constraints(case),
            "relevant": relevant, "bm25_ids": list(evidence.get("bm25_product_ids") or []),
            "vector_ids": list(evidence.get("vector_product_ids") or []), "canonical": canonical,
        })
    _split_by_relevance_family(rows, args.holdout_size)

    grid = []
    for weight in WEIGHTS:
        for rrf_k in RRF_KS:
            for depth in DEPTHS:
                config = Config(weight, 1.0, rrf_k, depth)
                grid.append({
                    "config": asdict(config),
                    "tune": _candidate_metrics(rows, config, "tune"),
                    "holdout": _candidate_metrics(rows, config, "holdout"),
                })
    finalists = _select_candidate_finalists(grid)
    reranker = HttpReranker(settings)
    rerank_results = []
    for config in finalists:
        print(f"rerank finalist: {config.name}", flush=True)
        rerank_results.append(await _rerank_config(rows, config, reranker, products))

    def tune_key(result: dict) -> tuple:
        metrics = result["summary"]["tune"]["3"]
        config = Config(**result["config"])
        return (metrics["recall"], metrics["ndcg"], metrics["mrr"], -config.depth)

    winner_result = max(rerank_results, key=tune_key)
    winner = Config(**winner_result["config"])
    k3 = winner_result["summary"]["tune"]["3"]["recall"]
    k5 = winner_result["summary"]["tune"]["5"]["recall"]
    recommended_k = 3 if k5 - k3 < 0.01 else 5
    baseline_result = next(
        result for result in rerank_results
        if Config(**result["config"]) == Config(1.0, 1.0, 60, 24)
    )
    winner_holdout = winner_result["summary"]["holdout"][str(recommended_k)]
    baseline_holdout = baseline_result["summary"]["holdout"][str(recommended_k)]
    holdout_verdict = (
        "通过；推荐方案在 Recall/nDCG 上不低于当前基线"
        if winner_holdout["recall"] >= baseline_holdout["recall"]
        and winner_holdout["ndcg"] >= baseline_holdout["ndcg"] - 0.005
        else "未通过；推荐方案在保留集发生退化，应继续使用当前基线"
    )
    if holdout_verdict.startswith("未通过"):
        winner = Config(1.0, 1.0, 60, 24)
        winner_result = baseline_result
        recommended_k = 3

    # 对最终推荐参数再走一次真实 UseCase，留下端到端路径、硬约束与延迟证据。
    verifier = CatalogSearchUseCase(
        repo, embedder=embedder, vector_index=vector_index, reranker=reranker,
        hybrid_enabled=True, include_retrieval_evidence=True, recall_top_n=winner.depth,
        rrf_k=winner.rrf_k, rrf_weights=(winner.bm25_weight, winner.vector_weight),
    )
    verification_observations: list[dict] = []
    verification = await run_dataset(
        verifier, repo, cases, recommended_k, observations=verification_observations,
    )
    payload = {
        "created_at": datetime.now().astimezone().isoformat(), "dataset": str(args.dataset),
        "search_space": {"bm25_weights": WEIGHTS, "vector_weight": 1.0, "rrf_k": RRF_KS, "depths": DEPTHS, "final_k": FINAL_KS},
        "selection_rule": "tune 选参；每组取距最佳 Candidate Recall 0.3pp 内最小 N；保留集只确认不退化",
        "split_counts": {
            "tune": sum(row["split"] == "tune" for row in rows),
            "holdout": sum(row["split"] == "holdout" for row in rows),
            "tune_semantic": sum(row["split"] == "tune" and row["kind"] == "semantic" for row in rows),
            "holdout_semantic": sum(row["split"] == "holdout" and row["kind"] == "semantic" for row in rows),
        },
        "candidate_grid": grid, "finalists": [asdict(config) for config in finalists],
        "rerank_results": rerank_results, "winner": asdict(winner),
        "recommended_final_k": recommended_k, "holdout_verdict": holdout_verdict,
        "end_to_end_verification": {
            "candidate_recall": verification.candidate_recall, "recall": verification.recall,
            "precision": verification.precision, "mrr": verification.mrr, "ndcg": verification.ndcg,
            "filter_accuracy": verification.filter_accuracy,
            "hard_constraint_violation_rate": verification.hard_constraint_violation_rate,
            "latency_p50_ms": verification.latency_p50_ms, "latency_p95_ms": verification.latency_p95_ms,
            "actual_strategies": sorted(verification.recall_strategies),
        },
        "verification_observations": verification_observations,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = args.output_dir / f"rrf-tuning-{stamp}.json"
    report_path = args.output_dir / f"rrf-tuning-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render_report(payload), encoding="utf-8")
    print(json.dumps({
        "report": str(report_path), "evidence": str(json_path), "winner": asdict(winner),
        "recommended_final_k": recommended_k, "holdout_verdict": holdout_verdict,
        "end_to_end": payload["end_to_end_verification"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
