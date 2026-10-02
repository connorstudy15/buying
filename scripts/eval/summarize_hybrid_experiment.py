"""汇总 N=24/K=3 的 Hybrid 消融评测，不调用外部服务。"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.infrastructure.persistence.seed_products import build_seed_products
from scripts.eval.metrics import ndcg_at_k, recall_at_k


def main() -> None:
    root = Path("eval/hybrid-qwen37-n24-k3")
    specs = {
        "bm25": ("bm25", "bm25"),
        "embedding_only": ("embedding-only", "embedding_only"),
        "embedding_rerank": ("embedding-rerank", "embedding_rerank"),
        "hybrid_rrf": ("hybrid-rrf", "hybrid_rrf"),
        "hybrid_rerank": ("hybrid-rerank", "hybrid_rerank"),
    }
    observations: dict[str, list[dict]] = {}
    print("strategy,candidate,recall3,precision3,mrr3,ndcg3,filter,p50,p95,tokens,cost,avg_docs")
    for name, (folder, key) in specs.items():
        path = next((root / folder).glob("*.manifest.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        metrics = payload["execution"]["metrics"][key]
        rows = payload["execution"]["observations"][key]
        observations[name] = rows
        tokens = sum(row.get("rerank_prompt_tokens", 0) for row in rows)
        document_counts = [
            row.get("rerank_document_count", 0)
            for row in rows
            if row.get("rerank_document_count", 0)
        ]
        print(
            f"{name},{metrics['candidate_recall']:.4f},{metrics['recall']:.4f},"
            f"{metrics['precision']:.4f},{metrics['mrr']:.4f},{metrics['ndcg']:.4f},"
            f"{metrics['filter_accuracy']},{metrics['latency_p50_ms']:.1f},"
            f"{metrics['latency_p95_ms']:.1f},{tokens},{tokens * 0.5 / 1_000_000:.6f},"
            f"{statistics.mean(document_counts) if document_counts else 0:.2f}"
        )

    canonical = {
        product.product_id: product.canonical_product_id or product.product_id
        for product in build_seed_products()
    }
    hybrid = observations["hybrid_rerank"]
    baseline = {row["query"]: row for row in observations["embedding_rerank"]}
    bm25_recalls, vector_recalls, union_recalls = [], [], []
    bm25_unique_relevant = vector_unique_relevant = 0
    for row in hybrid:
        relevant = row["relevant"]
        bm25 = [canonical.get(item, item) for item in row["bm25_retrieved"]]
        vector = [canonical.get(item, item) for item in row["vector_retrieved"]]
        bm25_recalls.append(recall_at_k(bm25, relevant, 24))
        vector_recalls.append(recall_at_k(vector, relevant, 24))
        union_recalls.append(recall_at_k(list(dict.fromkeys(bm25 + vector)), relevant, 48))
        bm25_relevant = set(relevant) & set(bm25)
        vector_relevant = set(relevant) & set(vector)
        bm25_unique_relevant += len(bm25_relevant - vector_relevant)
        vector_unique_relevant += len(vector_relevant - bm25_relevant)
    print(
        "branches",
        round(statistics.mean(bm25_recalls), 4),
        round(statistics.mean(vector_recalls), 4),
        round(statistics.mean(union_recalls), 4),
        "bm25_unique_rel",
        bm25_unique_relevant,
        "vector_unique_rel",
        vector_unique_relevant,
    )

    metric_functions = {
        "recall": lambda row: recall_at_k(row["canonical_retrieved"], row["relevant"], 3),
        "ndcg": lambda row: ndcg_at_k(row["canonical_retrieved"], row["relevant"], 3),
        "top1": lambda row: float(
            bool(row["canonical_retrieved"])
            and row["canonical_retrieved"][0] in set(row["relevant"])
        ),
    }
    for metric, function in metric_functions.items():
        deltas = [function(row) - function(baseline[row["query"]]) for row in hybrid]
        print(
            metric,
            "win/loss/tie",
            sum(delta > 1e-12 for delta in deltas),
            sum(delta < -1e-12 for delta in deltas),
            sum(abs(delta) <= 1e-12 for delta in deltas),
        )
    print("filter_fail_queries", sum(row.get("filter_ok") is False for row in hybrid))
    print(
        "actual",
        sorted({row["actual_strategy"] for row in hybrid}),
        "rerank_all",
        all(row.get("rerank_applied") for row in hybrid),
        "docs_max",
        max(row.get("rerank_document_count", 0) for row in hybrid),
    )


if __name__ == "__main__":
    main()
