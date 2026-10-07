# -*- coding: utf-8 -*-
"""Production KB V1 的小规模端到端检索 sanity evaluation。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application.prompts.loader import load_prompts  # noqa: E402
from app.application.retrieval.query_processor import QueryProcessor  # noqa: E402
from app.infrastructure.llm import create_chat_model  # noqa: E402
from app.infrastructure.rag.category_knowledge import (  # noqa: E402
    PRODUCTION_KNOWLEDGE_DIR, bootstrap_category_knowledge, build_category_knowledge_base,
    has_answerable_knowledge,
)
from app.infrastructure.rag.knowledge_retrieval import search_knowledge_with_trace  # noqa: E402
from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.knowledge_evidence import matched_evidence_ids  # noqa: E402


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo, hi = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


async def run(dataset_path: Path, output: Path, top_k: int) -> dict:
    settings = load_settings()
    kb = build_category_knowledge_base(settings)
    inserted = await bootstrap_category_knowledge(kb, PRODUCTION_KNOWLEDGE_DIR, corpus_role="production")
    documents = await kb.list_documents()
    if len(documents) != 12:
        raise RuntimeError(f"production collection 应有 12 篇文档，实际 {len(documents)}")

    query_processor = None
    if settings.knowledge_query_transform_enabled:
        processor_settings = replace(
            settings,
            llm_base_url=settings.query_processor_base_url or settings.llm_base_url,
            llm_api_key=settings.query_processor_api_key or settings.llm_api_key,
            llm_model=settings.query_processor_model or settings.llm_model,
            llm_fallback_model="",
        )
        query_processor = QueryProcessor(
            create_chat_model(processor_settings, stream=False),
            load_prompts()["query_processor"]["system_prompt"],
            max_subqueries=settings.query_processor_max_subqueries,
            disable_thinking=settings.query_processor_disable_thinking,
        )

    cases = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line]
    observations, latencies = [], []
    for case in cases:
        started = time.perf_counter()
        outcome = await search_knowledge_with_trace(
            kb, case["query"], top_k=top_k, query_processor=query_processor,
            rrf_k=settings.knowledge_rrf_k,
        )
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        matched, ranks = matched_evidence_ids(outcome.hits, case["evidence_ground_truth"])
        gold = {item["evidence_id"] for item in case["evidence_ground_truth"]}
        needs = case["required_information_needs"]
        need_hits = {
            need["need_id"]: bool(set(need["gold_evidence_ids"]) & set(matched))
            for need in needs
        }
        abstained = not has_answerable_knowledge(outcome.hits)
        observations.append({
            "id": case["id"], "query": case["query"], "kind": case["primary_kind"],
            "answerability": case["answerability"], "missing_reason": case["missing_reason"],
            "matched_evidence_ids": matched, "gold_evidence_ids": sorted(gold), "ranks": ranks,
            "evidence_recall": len(gold & set(matched)) / len(gold) if gold else None,
            "all_required_needs_recall": all(need_hits.values()) if need_hits else None,
            "information_need_coverage": sum(need_hits.values()) / len(need_hits) if need_hits else None,
            "abstained": abstained, "retrieval_mode": outcome.trace.mode,
            "collection_name": outcome.trace.collection_name,
            "corpus_version": outcome.trace.corpus_version,
            "latency_ms": round(latency, 3),
            "sources": [getattr(hit.chunk, "metadata", {}).get("source") for hit in outcome.hits],
        })

    answerable = [row for row in observations if row["answerability"] == "complete"]
    none = [row for row in observations if row["answerability"] == "none"]
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "production_manifest_sha256": hashlib.sha256((PRODUCTION_KNOWLEDGE_DIR / "manifest.jsonl").read_bytes()).hexdigest(),
        "collection": settings.category_kb_collection,
        "document_count": len(documents), "inserted_or_updated": inserted,
        "top_k": top_k, "query_transform_enabled": bool(query_processor),
        "metrics": {
            "evidence_recall_at_k": statistics.mean(row["evidence_recall"] for row in answerable),
            "all_required_needs_recall_at_k": statistics.mean(row["all_required_needs_recall"] for row in answerable),
            "information_need_coverage_at_k": statistics.mean(row["information_need_coverage"] for row in answerable),
            "unanswerable_abstention_accuracy": statistics.mean(row["abstained"] for row in none),
            "latency_p50_ms": percentile(latencies, 0.50),
            "latency_p95_ms": percentile(latencies, 0.95),
        },
        "observations": observations,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [row for row in answerable if not row["all_required_needs_recall"]]
    false_answers = [row for row in none if not row["abstained"]]
    lines = [
        "# Production Knowledge Sanity V1", "",
        f"- documents: {len(documents)}", f"- collection: `{settings.category_kb_collection}`",
        f"- Evidence Recall@{top_k}: {report['metrics']['evidence_recall_at_k']:.4f}",
        f"- All-required-needs Recall@{top_k}: {report['metrics']['all_required_needs_recall_at_k']:.4f}",
        f"- Unanswerable abstention: {report['metrics']['unanswerable_abstention_accuracy']:.4f}",
        f"- P50/P95: {report['metrics']['latency_p50_ms']:.1f}/{report['metrics']['latency_p95_ms']:.1f} ms", "",
        "## Misses", "", *(f"- {row['id']}: {row['sources']}" for row in failures), "",
        "## False answers", "", *(f"- {row['id']}: {row['sources']}" for row in false_answers), "",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval/knowledge/production_sanity_v1.jsonl")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval/runs/production-sanity-v1")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    report = asyncio.run(run(args.dataset, args.output_dir, args.top_k))
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
