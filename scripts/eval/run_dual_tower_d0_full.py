# -*- coding: utf-8 -*-
"""D0-full: qwen3.7-text-embedding role-aware retriever-only paired evaluation."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.dual_tower_dashscope import DashScopeEmbeddingConfig, DashScopeRoleEmbeddingClient  # noqa: E402
from scripts.eval.evaluate_dual_tower_retriever import evaluate, load_jsonl  # noqa: E402
from scripts.eval.run_dual_tower_d0_role import corpus_manifest, percentile, rank_queries, sha256_json  # noqa: E402
from scripts.eval.run_dual_tower_native_symmetric_control import load_chunks  # noqa: E402

FULL_MODEL = "qwen3.7-text-embedding"
FULL_COLLECTION = "knowledge_dual_tower_full_exp"
FULL_PRICE_PER_1K_CNY = 0.0005
FLASH_PRICE_PER_1K_CNY = 0.000125


def hard_negative_group(raw_type: str, source: str) -> set[str]:
    value = raw_type.casefold()
    groups: set[str] = set()
    if "wrong_product" in value or "wrong_category" in value or "wrong_constraint" in value:
        groups.add("same_product_wrong_need")
    if any(term in value for term in ("policy", "rule", "scope", "current_", "forecast", "authority")):
        groups.add("same_domain_wrong_rule")
    if "title_match" in value or "same_term" in value or "topic_match" in value:
        groups.add("keyword_overlap_wrong_answer")
    if any(term in value for term in ("generic", "missing", "partial", "no_threshold", "without_")):
        groups.add("generic_vs_specific")
    if source.startswith("eval-"):
        groups.add("repeated_template_competition")
    return groups or {"other_annotated_hard_negative"}


def first_positive_rank(candidates: list[dict], gold: set[str]) -> int | None:
    return next((i for i, row in enumerate(candidates, 1) if gold & set(map(str, row.get("evidence_ids") or []))), None)


def hard_negative_analysis(queries: list[dict], flash: list[dict], full: list[dict], dataset: dict[str, dict]) -> dict:
    flash_map = {row["query_id"]: row["candidates"] for row in flash}
    full_map = {row["query_id"]: row["candidates"] for row in full}
    stats: dict[str, dict[str, int]] = {}
    for query in queries:
        annotations = dataset[query["case_id"]].get("hard_negatives") or []
        gold = set(map(str, query.get("gold_evidence_ids") or []))
        for annotation in annotations:
            source = str(annotation.get("source") or "")
            for group in hard_negative_group(str(annotation.get("type") or ""), source):
                row = stats.setdefault(group, {"observations": 0, "flash_outrank": 0, "full_outrank": 0})
                row["observations"] += 1
                for label, ranking in (("flash", flash_map[query["query_id"]]), ("full", full_map[query["query_id"]])):
                    positive = first_positive_rank(ranking, gold)
                    negative = next((i for i, item in enumerate(ranking, 1) if item.get("source") == source), None)
                    if negative is not None and (positive is None or negative < positive):
                        row[f"{label}_outrank"] += 1
    return {
        group: {
            **values,
            "flash_rate": values["flash_outrank"] / values["observations"] if values["observations"] else None,
            "full_rate": values["full_outrank"] / values["observations"] if values["observations"] else None,
        }
        for group, values in sorted(stats.items())
    }


def selected_case_diagnostics(result: dict, flash: list[dict], full: list[dict]) -> dict:
    watched = {"v4-006", "v4-051", "v4-048", "blind-019", "blind-008", "human-mh-001"}
    movements = [row for row in result["rank_movements"] if row["case_id"] in watched]
    flash_map = {row["query_id"]: row["candidates"] for row in flash}
    full_map = {row["query_id"]: row["candidates"] for row in full}
    v4_ids = sorted({row["query_id"] for row in movements if row["case_id"] == "v4-006"})
    return {
        "rank_movements": movements,
        "v4_006_top20": {
            query_id: {"flash_role": flash_map[query_id][:20], "full_role": full_map[query_id][:20]}
            for query_id in v4_ids
        },
    }


def render_report(result: dict) -> str:
    b, d = result["baseline"], result["dual_tower"]
    lines = [
        "# Dual-Tower Experiment D0-full", "",
        "本实验只把 role-aware encoder 从 Flash 换成 Full；Query Plan、151 个 chunk、角色、Top-50 和 evaluator 均冻结。", "",
        "| Metric | Flash role | Full role | Delta |", "|---|---:|---:|---:|",
    ]
    for key, label in (("recall_at_5", "Recall@5"), ("recall_at_10", "Recall@10"),
                       ("recall_at_24", "Recall@24"), ("recall_at_50", "Recall@50"), ("mrr", "MRR")):
        lines.append(f"| {label} | {b[key]:.4f} | {d[key]:.4f} | {result['delta'][key]:+.4f} |")
    lines += [
        f"| Retrieval Loss gold | {b['retrieval_loss_gold_count_at_50']} | {d['retrieval_loss_gold_count_at_50']} | "
        f"{d['retrieval_loss_gold_count_at_50'] - b['retrieval_loss_gold_count_at_50']:+d} |",
        f"| Hard-negative outrank-positive | {b['hard_negative_outrank_positive_rate']:.4f} | "
        f"{d['hard_negative_outrank_positive_rate']:.4f} | "
        f"{d['hard_negative_outrank_positive_rate'] - b['hard_negative_outrank_positive_rate']:+.4f} |",
        "", "## Buckets", "",
    ]
    for bucket, values in result["bucket_metrics"].items():
        lines.append(
            f"- `{bucket}`：Recall@24 {values['baseline']['recall_at_24']:.4f} → "
            f"{values['dual_tower']['recall_at_24']:.4f}；MRR "
            f"{values['baseline']['mrr']:.4f} → {values['dual_tower']['mrr']:.4f}。"
        )
    lines += ["", "## Rank movement", "", f"```json\n{json.dumps(result['rank_movement_summary'], ensure_ascii=False, indent=2)}\n```"]
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env", override=False)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    config = replace(DashScopeEmbeddingConfig.from_env(), model=FULL_MODEL, dimension=1024, max_batch=20)
    embedder = DashScopeRoleEmbeddingClient(config)

    queries = load_jsonl(args.d0_role_dir / "frozen_retriever_queries.jsonl")
    flash_rankings = load_jsonl(args.d0_role_dir / "dual_tower_rankings.jsonl")
    chunks = load_chunks(settings)
    expected_manifest_sha = (args.d0_role_dir / "corpus_manifest.sha256").read_text(encoding="ascii").strip()
    actual_manifest_sha = sha256_json(corpus_manifest(chunks))
    if len(chunks) != 151 or actual_manifest_sha != expected_manifest_sha:
        raise RuntimeError(
            f"corpus mismatch count={len(chunks)}, expected={expected_manifest_sha}, actual={actual_manifest_sha}"
        )

    full_docs = await embedder.embed_documents([row["text"] for row in chunks])
    if any(len(vector) != 1024 for vector in full_docs.vectors):
        raise RuntimeError("D0-full document dimension is not 1024")
    qdrant = QdrantClient(path=str(settings.data_dir / "qdrant_kb"))
    if qdrant.collection_exists(FULL_COLLECTION):
        qdrant.delete_collection(FULL_COLLECTION)
    qdrant.create_collection(FULL_COLLECTION, vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE))
    for start in range(0, len(chunks), 20):
        qdrant.upsert(FULL_COLLECTION, points=[
            models.PointStruct(id=chunks[index]["chunk_id"], vector=full_docs.vectors[index], payload=chunks[index]["payload"])
            for index in range(start, min(start + 20, len(chunks)))
        ])
    count = qdrant.count(FULL_COLLECTION, exact=True).count
    full_ids, offset = set(), None
    while True:
        points, offset = qdrant.scroll(FULL_COLLECTION, limit=100, offset=offset, with_payload=False, with_vectors=False)
        full_ids.update(str(point.id) for point in points)
        if offset is None:
            break
    qdrant.close()
    if count != 151 or full_ids != {row["chunk_id"] for row in chunks}:
        raise RuntimeError("D0-full collection failed corpus identity check")

    texts = [str(row["query_text"]) for row in queries]
    full_queries = await embedder.embed_queries(texts)
    single_latencies, errors, retries, single_tokens = [], 0, 0, 0
    for text in texts:
        try:
            probe = await embedder.embed_queries([text])
            single_latencies.append(probe.latency_ms)
            retries += max(0, probe.attempts - probe.request_count)
            single_tokens += probe.total_tokens or 0
        except Exception:
            errors += 1

    dataset_rows = [
        json.loads(line)
        for line in (ROOT / "eval/knowledge/v5/knowledge_eval_core_61.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dataset = {str(row["id"]): row for row in dataset_rows}
    full_rankings = rank_queries(queries, full_queries.vectors, chunks, full_docs.vectors, dataset)
    rankings_path = args.output_dir / "d0-full-rankings.jsonl"
    rankings_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in full_rankings), encoding="utf-8")

    result = evaluate(queries, flash_rankings, full_rankings)
    flash_previous = json.loads((args.d0_role_dir / "retriever-only.json").read_text(encoding="utf-8"))
    result.update({
        "schema_version": "dual-tower-d0-full-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "D0-role-flash_vs_D0-full",
        "arm_names": {"baseline": "D0-role Flash", "dual_tower": "D0-full"},
        "full_model": {"model": FULL_MODEL, "dimension": 1024, "dimension_policy": "official_default", "instruct": None},
        "frozen_inputs": {
            "query_plan_sha256": (args.d0_role_dir / "query_plan.sha256").read_text(encoding="ascii").strip(),
            "corpus_manifest_sha256": actual_manifest_sha,
            "chunk_count": len(chunks), "query_instance_count": len(queries),
            "flash_collection": "knowledge_dual_tower_exp", "full_collection": FULL_COLLECTION,
        },
        "hard_negative_groups": hard_negative_analysis(queries, flash_rankings, full_rankings, dataset),
        "selected_case_diagnostics": selected_case_diagnostics(result, flash_rankings, full_rankings),
        "telemetry": {
            "document_build": {
                "batch_count": full_docs.request_count, "total_tokens": full_docs.total_tokens,
                "total_wall_time_ms": full_docs.latency_ms, "retry_count": full_docs.attempts - full_docs.request_count,
                "error_count": 0,
                "cost_cny": (full_docs.total_tokens or 0) / 1000 * FULL_PRICE_PER_1K_CNY,
                "price_cny_per_1k_tokens": FULL_PRICE_PER_1K_CNY,
            },
            "batch_query": {
                **{k: v for k, v in asdict(full_queries).items() if k != "vectors"},
                "cost_cny": (full_queries.total_tokens or 0) / 1000 * FULL_PRICE_PER_1K_CNY,
            },
            "single_query": {
                "request_count": len(texts), "success_count": len(single_latencies), "error_count": errors,
                "error_rate": errors / len(texts), "retry_count": retries, "retry_rate": retries / len(texts),
                "p50_ms": percentile(single_latencies, 0.5), "p95_ms": percentile(single_latencies, 0.95),
                "total_tokens": single_tokens, "mean_tokens_per_query": single_tokens / len(texts),
                "mean_cost_per_query_cny": single_tokens / len(texts) / 1000 * FULL_PRICE_PER_1K_CNY,
            },
            "flash_reference": {
                "document_build": flash_previous["telemetry"]["document_build"],
                "single_query": flash_previous["telemetry"]["single_query_online_simulation"],
                "price_cny_per_1k_tokens": FLASH_PRICE_PER_1K_CNY,
            },
        },
    })
    (args.output_dir / "d0-full-retriever-only.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "d0-full-retriever-only.md").write_text(render_report(result), encoding="utf-8")
    print(json.dumps({
        "status": "completed", "output_dir": str(args.output_dir.resolve()),
        "flash_role": result["baseline"], "full_role": result["dual_tower"], "delta": result["delta"],
        "movement": result["rank_movement_summary"], "telemetry": result["telemetry"],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--d0-role-dir", type=Path, default=ROOT / "eval/runs/dual-tower-d0-role")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval/runs/dual-tower-d0-full")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
