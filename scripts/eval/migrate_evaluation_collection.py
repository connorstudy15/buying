# -*- coding: utf-8 -*-
"""把冻结的 role-aware evaluation points 原样复制到隔离 collection，并验证回归。

源 collection 保留不动；目标 collection 只承载 evaluation corpus。迁移不会重切块或重算
document embeddings，因此 chunk ID、文本、向量和冻结 corpus manifest 都应保持一致。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.dual_tower_dashscope import DashScopeEmbeddingConfig, DashScopeRoleEmbeddingClient  # noqa: E402
from scripts.eval.evaluate_dual_tower_retriever import evaluate, render  # noqa: E402
from scripts.eval.run_dual_tower_d0_role import (  # noqa: E402
    canonical_json, chunk_fields, corpus_manifest, rank_queries, sha256_json, write_jsonl,
)


SOURCE_COLLECTION = "knowledge_dual_tower_exp"
FROZEN_RUN = ROOT / "eval" / "runs" / "dual-tower-d0-role"
OUTPUT = ROOT / "eval" / "runs" / "corpus-isolation-regression"


def _scroll(client: QdrantClient, collection: str, *, vectors: bool) -> list:
    points, offset = [], None
    while True:
        batch, offset = client.scroll(
            collection, limit=100, offset=offset, with_payload=True, with_vectors=vectors,
        )
        points.extend(batch)
        if offset is None:
            return points


async def run(source: str, output: Path) -> dict:
    load_dotenv(ROOT / ".env", override=False)
    settings = load_settings()
    target = settings.category_kb_eval_collection
    if target == settings.category_kb_collection:
        raise RuntimeError("evaluation collection 与 production collection 相同，拒绝迁移")

    client = QdrantClient(path=str(settings.data_dir / "qdrant_kb"))
    try:
        if not client.collection_exists(source):
            raise RuntimeError(f"冻结 role-aware 源 collection 不存在：{source}")
        source_points = _scroll(client, source, vectors=True)
        if len(source_points) != 151:
            raise RuntimeError(f"源 collection 应为 151 chunks，实际 {len(source_points)}")
        chunks = sorted((chunk_fields(point) for point in source_points), key=lambda row: row["chunk_id"])
        manifest = corpus_manifest(chunks)
        manifest_sha = sha256_json(manifest)
        frozen_sha = (FROZEN_RUN / "corpus_manifest.sha256").read_text(encoding="ascii").strip()
        if manifest_sha != frozen_sha:
            raise RuntimeError(f"源 corpus manifest 已漂移：{manifest_sha} != {frozen_sha}")

        if client.collection_exists(target):
            client.delete_collection(target)
        client.create_collection(target, vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE))
        for start in range(0, len(source_points), 20):
            client.upsert(target, points=[
                models.PointStruct(
                    id=point.id,
                    vector=point.vector,
                    payload={**(point.payload or {}), "corpus_role": "evaluation"},
                )
                for point in source_points[start:start + 20]
            ])
        target_points = _scroll(client, target, vectors=True)
    finally:
        client.close()

    migrated = sorted((chunk_fields(point) for point in target_points), key=lambda row: row["chunk_id"])
    migrated_sha = sha256_json(corpus_manifest(migrated))
    if migrated_sha != frozen_sha:
        raise RuntimeError(f"迁移后 corpus manifest 漂移：{migrated_sha} != {frozen_sha}")
    if {row["chunk_id"] for row in migrated} != {row["chunk_id"] for row in chunks}:
        raise RuntimeError("迁移后 chunk ID 集合变化")

    queries = [json.loads(line) for line in (FROZEN_RUN / "frozen_retriever_queries.jsonl").read_text(encoding="utf-8").splitlines() if line]
    dataset_rows = [json.loads(line) for line in (ROOT / "eval/knowledge/v5/knowledge_eval_core_61.jsonl").read_text(encoding="utf-8").splitlines() if line]
    dataset = {str(row["id"]): row for row in dataset_rows}
    native = DashScopeRoleEmbeddingClient(DashScopeEmbeddingConfig.from_env())
    encoded = await native.embed_queries([row["query_text"] for row in queries])
    source_rankings = rank_queries(
        queries, encoded.vectors, chunks, [row["baseline_vector"] for row in chunks], dataset,
    )
    rankings = rank_queries(
        queries, encoded.vectors, migrated, [row["baseline_vector"] for row in migrated], dataset,
    )
    frozen_rankings = [json.loads(line) for line in (FROZEN_RUN / "dual_tower_rankings.jsonl").read_text(encoding="utf-8").splitlines() if line]
    # Collection migration A/A：同一批新 query vectors 同时打旧/新 collection，隔离远端重复编码抖动。
    result = evaluate(queries, source_rankings, rankings)
    frozen_drift = evaluate(queries, frozen_rankings, rankings)
    exact_ranking_match = canonical_json(source_rankings) == canonical_json(rankings)
    exact_metric_keys = (
        "recall_at_5", "recall_at_10", "recall_at_24", "recall_at_50",
        "retrieval_loss_gold_count_at_50", "retrieval_loss_query_count_at_50",
        "hard_negative_outrank_positive_rate",
    )
    gold_rank_match = all(item["rank_delta"] == 0 for item in result["rank_movements"])
    # 百炼同一模型重复编码会出现极小浮点抖动；主召回指标和全部 gold rank 必须严格一致，
    # MRR 仅容许 1e-4 内的数值波动，避免把远端非确定性误判为 corpus 迁移。
    mrr_delta = abs(result["baseline"]["mrr"] - result["dual_tower"]["mrr"])
    metric_match = (
        all(result["baseline"][key] == result["dual_tower"][key] for key in exact_metric_keys)
        and gold_rank_match and mrr_delta <= 1e-4
    )
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "corpus_manifest.jsonl", corpus_manifest(migrated))
    write_jsonl(output / "source_rankings_same_query_vectors.jsonl", source_rankings)
    write_jsonl(output / "migrated_rankings.jsonl", rankings)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_collection": source,
        "target_collection": target,
        "production_collection": settings.category_kb_collection,
        "chunk_count": len(migrated),
        "corpus_manifest_sha256": migrated_sha,
        "frozen_corpus_manifest_sha256": frozen_sha,
        "query_plan_sha256": (FROZEN_RUN / "query_plan.sha256").read_text(encoding="ascii").strip(),
        "exact_ranking_match": exact_ranking_match,
        "metric_match": metric_match,
        "gold_rank_match": gold_rank_match,
        "mrr_absolute_delta": mrr_delta,
        "mrr_tolerance": 1e-4,
        "metrics": result["dual_tower"],
        "frozen_run_provider_drift": {
            "frozen_metrics": frozen_drift["baseline"],
            "fresh_metrics": frozen_drift["dual_tower"],
            "delta": frozen_drift["delta"],
            "note": "同一远端模型重复编码的非确定性诊断，不归因于 collection 迁移。",
        },
        "embedding_telemetry": {
            "model": native.config.model, "text_type": "query", "request_count": encoded.request_count,
            "latency_ms": encoded.latency_ms, "total_tokens": encoded.total_tokens,
        },
    }
    (output / "regression.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "regression.md").write_text(
        "# Corpus Isolation Regression\n\n"
        f"- source: `{source}`\n- target: `{target}`\n- chunks: {len(migrated)}\n"
        f"- corpus manifest: `{migrated_sha}`\n- metric match: `{metric_match}`\n"
        f"- exact ranking match: `{exact_ranking_match}`\n\n" + render(result),
        encoding="utf-8",
    )
    if not metric_match:
        raise RuntimeError(f"迁移前后 Retriever 指标变化，诊断已写入 {output}，停止后续工作")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=SOURCE_COLLECTION)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.source, args.output_dir)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
