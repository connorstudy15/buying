# -*- coding: utf-8 -*-
"""Dual-Tower Experiment D0-role：同模型、同 chunk，仅改变 query/document 编码角色。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.dual_tower_dashscope import (  # noqa: E402
    DashScopeEmbeddingConfig,
    DashScopeRoleEmbeddingClient,
)
from scripts.eval.evaluate_dual_tower_retriever import evaluate, render  # noqa: E402
from scripts.eval.knowledge_evidence import normalize_text  # noqa: E402

DEFAULT_SNAPSHOT = ROOT / "eval/runs/retrieval-scoped-recall-formal/experiment-b-20261004-211102.json"
DEFAULT_DATASET = ROOT / "eval/knowledge/v5/knowledge_eval_core_61.jsonl"
EXPERIMENT_COLLECTION = "knowledge_dual_tower_exp"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def chunk_fields(point: Any) -> dict:
    payload = point.payload or {}
    chunk = payload.get("chunk") or {}
    content = chunk.get("content") or {}
    metadata = dict(chunk.get("metadata") or {})
    source = str(metadata.get("source") or chunk.get("source") or payload.get("document_id") or "")
    text = str(content.get("text") or "")
    heading = ""
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            heading = line.lstrip("# ").strip()
            break
    return {
        "chunk_id": str(point.id),
        "source": source,
        "document_id": str(payload.get("document_id") or ""),
        "chunk_index": int(chunk.get("chunk_index") or 0),
        "section": heading,
        "text": text,
        "metadata": metadata,
        "payload": payload,
        "baseline_vector": list(point.vector),
    }


def corpus_manifest(chunks: list[dict]) -> list[dict]:
    return [{
        "chunk_id": row["chunk_id"],
        "source": row["source"],
        "document_id": row["document_id"],
        "chunk_index": row["chunk_index"],
        "section": row["section"],
        "text_hash": hashlib.sha256(row["text"].encode("utf-8")).hexdigest(),
        "metadata_hash": hashlib.sha256(canonical_json(row["metadata"]).encode("utf-8")).hexdigest(),
    } for row in chunks]


async def compatible_embed(texts: list[str], settings, *, max_batch: int = 10) -> tuple[list[list[float]], dict]:
    vectors: list[list[float]] = []
    latencies: list[float] = []
    usage_tokens = 0
    usage_available = True
    async with httpx.AsyncClient(timeout=30.0) as client:
        for start in range(0, len(texts), max_batch):
            chunk = texts[start:start + max_batch]
            before = time.perf_counter()
            response = await client.post(
                settings.embedding_base_url.rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
                json={"model": settings.embedding_model, "input": chunk},
            )
            response.raise_for_status()
            latencies.append((time.perf_counter() - before) * 1000)
            body = response.json()
            ordered = sorted(body["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in ordered)
            usage = body.get("usage") or {}
            token_value = usage.get("total_tokens") or usage.get("prompt_tokens")
            if isinstance(token_value, int):
                usage_tokens += token_value
            else:
                usage_available = False
    if any(len(vector) != settings.embedding_dim for vector in vectors):
        raise RuntimeError("compatible endpoint returned an unexpected embedding dimension")
    return vectors, {
        "request_count": len(latencies), "batch_sizes": [len(texts[i:i + max_batch]) for i in range(0, len(texts), max_batch)],
        "total_latency_ms": round(sum(latencies), 3), "request_latencies_ms": [round(x, 3) for x in latencies],
        "total_tokens": usage_tokens if usage_available else None,
    }


def lexical_terms(text: str) -> set[str]:
    compact = "".join(normalize_text(text).casefold().split())
    return {compact[i:i + 2] for i in range(max(0, len(compact) - 1))}


def align_subqueries_to_needs(variants: list[dict], needs: list[dict]) -> dict[str, list[str]]:
    """确定性对齐已有 subquery 与人工 need；不调用模型、不改变 query plan。"""
    if not needs:
        return {str(v["query_id"]): [] for v in variants}
    if len(needs) == 1:
        gold = list(map(str, needs[0].get("gold_evidence_ids") or []))
        return {str(v["query_id"]): gold for v in variants}
    remaining = set(range(len(needs)))
    output: dict[str, list[str]] = {}
    for variant in variants:
        q_terms = lexical_terms(str(variant.get("text") or ""))
        ranked = sorted(
            remaining,
            key=lambda idx: (-len(q_terms & lexical_terms(str(needs[idx].get("description") or ""))), idx),
        )
        chosen = ranked[0] if ranked else 0
        remaining.discard(chosen)
        output[str(variant["query_id"])] = list(map(str, needs[chosen].get("gold_evidence_ids") or []))
    return output


def special_labels(case_id: str, row: dict) -> tuple[str, str, str]:
    if case_id in {"blind-008", "human-mh-001"}:
        return "trigger_false_negative", str(row.get("label_status") or "frozen"), "diagnostic_only"
    if case_id in {"blind-014", "v4-022"}:
        return "label_dispute", "disputed", "excluded_from_primary_gate"
    return "retriever_evaluation", str(row.get("label_status") or "frozen"), "primary_gate"


def make_query_plan(snapshot: dict, dataset: dict[str, dict], repetition_index: int) -> tuple[list[dict], list[dict]]:
    run = snapshot["runs"][repetition_index]
    observations = run["decompose_per_need_rerank"]["observations"]
    plans, eval_queries = [], []
    for observation in observations:
        case_id = str(observation["case_id"])
        label = dataset[case_id]
        effective = observation.get("effective_plan_mode")
        fallback = observation.get("processor_fallback_reason")
        variants = list(observation.get("query_variants") or [])
        plan_row = {
            "case_id": case_id,
            "evaluation_run_id": snapshot["evaluation_run_id"],
            "repetition": int(run["repetition"]),
            "effective_mode": effective,
            "original_query": observation["query"],
            "subqueries": [v for v in variants if v.get("kind") == "subquery"],
            "fallback_status": fallback,
            "excluded_from_retriever_only": effective not in {"DIRECT", "DECOMPOSE"},
        }
        plans.append(plan_row)
        if effective not in {"DIRECT", "DECOMPOSE"}:
            continue
        all_gold = [str(e["evidence_id"]) for e in label.get("evidence_ground_truth") or []]
        if not all_gold:
            plan_row["excluded_from_retriever_only"] = True
            plan_row["retriever_only_exclusion_reason"] = "no_gold_evidence"
            continue
        selected = [v for v in variants if v.get("kind") == "subquery"] if effective == "DECOMPOSE" else [{
            "query_id": "original", "text": observation["query"], "information_need_id": "overall", "kind": "original",
        }]
        needs = list(label.get("required_information_needs") or [])
        aligned = align_subqueries_to_needs(selected, needs)
        root_cause, label_status, acceptance_scope = special_labels(case_id, label)
        hard_sources = [str(x.get("source")) for x in label.get("hard_negatives") or [] if x.get("source")]
        primary_kind = str(label.get("primary_kind") or "")
        tags = set(map(str, label.get("tags") or []))
        for variant in selected:
            query_id = f"{case_id}::{variant['query_id']}"
            gold = aligned.get(str(variant["query_id"])) or all_gold
            buckets = ["DECOMPOSE_SUBQUERY" if effective == "DECOMPOSE" else "DIRECT"]
            buckets.append("multi_evidence" if len(all_gold) > 1 or "cross_evidence" in primary_kind else "single_evidence")
            if "implicit_constraint" in primary_kind or "cross_evidence" in primary_kind or {"implicit_constraint", "cross_evidence"} & tags:
                buckets.append("implicit_cross_domain")
            gold_sources = {e.split("#", 1)[0] for e in all_gold}
            if any("policy" in source or source in {"cross-border-guide.md", "travel-gear.md"} for source in gold_sources):
                buckets.append("domain_rule")
            eval_queries.append({
                "query_id": query_id,
                "case_id": case_id,
                "information_need_id": str(variant.get("information_need_id") or variant["query_id"]),
                "query_text": str(variant["text"]),
                "effective_mode": effective,
                "gold_evidence_ids": gold,
                "all_case_gold_evidence_ids": all_gold,
                "hard_negative_sources": hard_sources,
                "buckets": list(dict.fromkeys(buckets)),
                "root_cause": root_cause,
                "label_status": label_status,
                "acceptance_scope": acceptance_scope,
            })
    return plans, eval_queries


def evidence_ids_for_chunk(chunk: dict, label: dict) -> list[str]:
    text = normalize_text(chunk["text"])
    source = chunk["source"]
    return [str(item["evidence_id"]) for item in label.get("evidence_ground_truth") or []
            if str(item.get("source")) == source and normalize_text(item.get("quote") or "") in text]


def rank_queries(query_rows: list[dict], query_vectors: list[list[float]], chunks: list[dict], vectors: list[list[float]], dataset: dict[str, dict]) -> list[dict]:
    output = []
    for query, query_vector in zip(query_rows, query_vectors):
        scores = [(cosine(query_vector, vector), idx) for idx, vector in enumerate(vectors)]
        scores.sort(key=lambda item: (-item[0], chunks[item[1]]["chunk_id"]))
        candidates = []
        for rank, (score, idx) in enumerate(scores[:50], 1):
            chunk = chunks[idx]
            candidates.append({
                "rank": rank, "candidate_id": chunk["chunk_id"], "source": chunk["source"],
                "document_id": chunk["document_id"], "chunk_index": chunk["chunk_index"],
                "score": round(score, 12), "evidence_ids": evidence_ids_for_chunk(chunk, dataset[query["case_id"]]),
            })
        output.append({"query_id": query["query_id"], "case_id": query["case_id"], "candidates": candidates})
    return output


def endpoint_aa(sample: list[dict], compatible: list[list[float]], native: list[list[float]]) -> dict:
    paired = [cosine(a, b) for a, b in zip(compatible, native)]
    top1_same, jaccards = 0, []
    for idx in range(len(sample)):
        aa = sorted(((cosine(compatible[idx], compatible[j]), j) for j in range(len(sample)) if j != idx), reverse=True)
        bb = sorted(((cosine(native[idx], native[j]), j) for j in range(len(sample)) if j != idx), reverse=True)
        top1_same += bool(aa and bb and aa[0][1] == bb[0][1])
        sa, sb = {j for _, j in aa[:5]}, {j for _, j in bb[:5]}
        jaccards.append(len(sa & sb) / len(sa | sb) if sa | sb else 1.0)
    return {
        "sample_size": len(sample), "seed": 20261004,
        "paired_cosine_mean": statistics.mean(paired), "paired_cosine_min": min(paired),
        "paired_cosine_median": statistics.median(paired),
        "nearest_neighbor_top1_consistency": top1_same / len(sample),
        "nearest_neighbor_top5_mean_jaccard": statistics.mean(jaccards),
        "attribution_warning": "Endpoint and text_type change together; material document-vector differences limit causal attribution to role alone.",
    }


async def run(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env", override=False)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    native_config = DashScopeEmbeddingConfig.from_env()
    native_client = DashScopeRoleEmbeddingClient(native_config)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    dataset_rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    dataset = {str(row["id"]): row for row in dataset_rows}

    qdrant = QdrantClient(path=str(settings.data_dir / "qdrant_kb"))
    points, offset = [], None
    while True:
        batch, offset = qdrant.scroll(settings.category_kb_eval_collection, limit=100, offset=offset, with_payload=True, with_vectors=True)
        points.extend(batch)
        if offset is None:
            break
    chunks = sorted((chunk_fields(point) for point in points), key=lambda row: row["chunk_id"])
    if len(chunks) != 151:
        raise RuntimeError(f"production corpus must contain exactly 151 chunks, got {len(chunks)}")

    manifests = corpus_manifest(chunks)
    manifest_sha = sha256_json(manifests)
    write_jsonl(output / "corpus_manifest.jsonl", manifests)
    (output / "corpus_manifest.sha256").write_text(manifest_sha + "\n", encoding="ascii")

    plans, query_rows = make_query_plan(snapshot, dataset, args.repetition_index)
    plan_sha = sha256_json(plans)
    write_jsonl(output / "query_plan.jsonl", plans)
    (output / "query_plan.sha256").write_text(plan_sha + "\n", encoding="ascii")
    write_jsonl(output / "frozen_retriever_queries.jsonl", query_rows)

    rng = random.Random(20261004)
    sample = rng.sample(chunks, min(20, len(chunks)))
    compatible_sample, compatible_sample_usage = await compatible_embed([x["text"] for x in sample], settings)
    native_sample_result = await native_client.embed_documents([x["text"] for x in sample])
    aa = endpoint_aa(sample, compatible_sample, native_sample_result.vectors)
    aa["compatible_usage"] = compatible_sample_usage
    aa["native_usage"] = asdict(native_sample_result) | {"vectors": f"<{len(native_sample_result.vectors)} omitted>"}
    (output / "endpoint-aa.json").write_text(json.dumps(aa, ensure_ascii=False, indent=2), encoding="utf-8")

    native_docs = await native_client.embed_documents([x["text"] for x in chunks])
    if qdrant.collection_exists(EXPERIMENT_COLLECTION):
        qdrant.delete_collection(EXPERIMENT_COLLECTION)
    qdrant.create_collection(EXPERIMENT_COLLECTION, vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE))
    for start in range(0, len(chunks), 20):
        qdrant.upsert(EXPERIMENT_COLLECTION, points=[
            models.PointStruct(id=chunks[idx]["chunk_id"], vector=native_docs.vectors[idx], payload=chunks[idx]["payload"])
            for idx in range(start, min(start + 20, len(chunks)))
        ])
    dual_points, offset = [], None
    while True:
        batch, offset = qdrant.scroll(EXPERIMENT_COLLECTION, limit=100, offset=offset, with_payload=True, with_vectors=False)
        dual_points.extend(batch)
        if offset is None:
            break
    baseline_ids, dual_ids = {x["chunk_id"] for x in chunks}, {str(p.id) for p in dual_points}
    if baseline_ids != dual_ids:
        raise RuntimeError("baseline and D0-role chunk ID sets differ")
    qdrant.close()

    query_texts = [row["query_text"] for row in query_rows]
    baseline_query_vectors, baseline_query_usage = await compatible_embed(query_texts, settings)
    native_queries = await native_client.embed_queries(query_texts)

    single_latencies, single_errors, single_retries, single_tokens = [], 0, 0, 0
    for text in query_texts:
        try:
            result = await native_client.embed_queries([text])
            single_latencies.append(result.latency_ms)
            single_retries += max(0, result.attempts - 1)
            single_tokens += result.total_tokens or 0
        except Exception:
            single_errors += 1

    baseline_rankings = rank_queries(query_rows, baseline_query_vectors, chunks, [x["baseline_vector"] for x in chunks], dataset)
    dual_rankings = rank_queries(query_rows, native_queries.vectors, chunks, native_docs.vectors, dataset)
    write_jsonl(output / "baseline_rankings.jsonl", baseline_rankings)
    write_jsonl(output / "dual_tower_rankings.jsonl", dual_rankings)
    result = evaluate(query_rows, baseline_rankings, dual_rankings)
    result["created_at"] = datetime.now(timezone.utc).isoformat()
    result["experiment"] = "D0-role"
    result["frozen_inputs"] = {
        "evaluation_run_id": snapshot["evaluation_run_id"], "repetition": snapshot["runs"][args.repetition_index]["repetition"],
        "query_plan_sha256": plan_sha, "corpus_manifest_sha256": manifest_sha,
        "evaluation_collection": settings.category_kb_eval_collection, "experiment_collection": EXPERIMENT_COLLECTION,
        "chunk_count": len(chunks), "query_instance_count": len(query_rows),
        "unsupported_excluded_count": sum(p["excluded_from_retriever_only"] for p in plans),
    }
    result["endpoint_aa"] = aa
    result["telemetry"] = {
        "document_build": {
            "batch_count": native_docs.request_count, "max_batch_size": native_config.max_batch,
            "total_latency_ms": native_docs.latency_ms, "attempts": native_docs.attempts,
            "retry_count": native_docs.attempts - native_docs.request_count,
            "total_tokens": native_docs.total_tokens, "estimated_cost_cny": None,
            "cost_note": "No verified public price for this workspace/model was injected; token usage is reported without inventing a price.",
        },
        "batch_query_encoding": {
            "baseline": baseline_query_usage,
            "dual_tower": {k: v for k, v in asdict(native_queries).items() if k != "vectors"},
        },
        "single_query_online_simulation": {
            "request_count": len(query_texts), "success_count": len(single_latencies), "error_count": single_errors,
            "error_rate": single_errors / len(query_texts) if query_texts else 0,
            "retry_count": single_retries, "retry_rate": single_retries / len(query_texts) if query_texts else 0,
            "p50_ms": percentile(single_latencies, 0.5), "p95_ms": percentile(single_latencies, 0.95),
            "total_tokens": single_tokens, "estimated_cost_per_query_cny": None,
        },
    }
    (output / "retriever-only.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "retriever-only.md").write_text(render(result), encoding="utf-8")
    print(json.dumps({
        "status": "completed", "output_dir": str(output.resolve()),
        "query_plan_sha256": plan_sha, "corpus_manifest_sha256": manifest_sha,
        "query_instances": len(query_rows), "endpoint_aa": aa,
        "baseline": result["baseline"], "dual_tower": result["dual_tower"], "delta": result["delta"],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repetition-index", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval/runs/dual-tower-d0-role")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
