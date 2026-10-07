# -*- coding: utf-8 -*-
"""Pure diagnostic: apply the configured reranker to selected DIRECT candidate pools."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.infrastructure.rag.category_knowledge import (
    EVALUATION_KNOWLEDGE_DIR,
    build_evaluation_knowledge_base,
    verify_evaluation_knowledge_base,
)
from app.infrastructure.rag.knowledge_retrieval import _candidate_key, retrieve_knowledge_candidates
from app.infrastructure.rerank.http_reranker import HttpReranker
from app.infrastructure.settings import load_settings
from scripts.eval.knowledge_evidence import matched_evidence_ids
from scripts.eval.run_category_recall import load_dataset


DEFAULT_CASES = ("blind-008", "blind-014", "human-mh-001", "v4-006", "v4-022")


def chunk_text(item) -> str:
    content = getattr(getattr(item, "chunk", None), "content", "")
    return str(getattr(content, "text", content) or "")


def candidate_row(candidate, rank: int, evidence: list[dict], *, rerank_score: float | None = None) -> dict:
    item = candidate.item
    metadata = getattr(getattr(item, "chunk", None), "metadata", None) or {}
    matched, _ = matched_evidence_ids([item], evidence)
    text = " ".join(chunk_text(item).split())
    return {
        "rank": rank,
        "source": str(metadata.get("source") or item.document_id),
        "document_id": str(item.document_id),
        "section": str(metadata.get("section") or metadata.get("heading") or ""),
        "retrieval_route": candidate.retrieval_route,
        "vector_score": round(float(getattr(item, "score", 0.0)), 10),
        "rerank_score": round(float(rerank_score), 10) if rerank_score is not None else None,
        "matched_gold_evidence_ids": matched,
        "excerpt": text[:260],
    }


def evidence_ranks(rows: list[dict], gold_ids: list[str]) -> dict[str, int | None]:
    return {
        evidence_id: next(
            (int(row["rank"]) for row in rows if evidence_id in row["matched_gold_evidence_ids"]),
            None,
        )
        for evidence_id in gold_ids
    }


def snapshot_candidates(snapshot: Path, case_ids: tuple[str, ...], settings) -> dict[str, list]:
    """Restore an already-recorded candidate order from local Qdrant without calling embedding."""
    from qdrant_client import QdrantClient

    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    observations = {
        str(row["case_id"]): row
        for row in payload["runs"][0]["decompose_per_need_rerank"]["observations"]
    }
    client = QdrantClient(path=str(settings.data_dir / "qdrant_kb"))
    points = []
    offset = None
    while True:
        batch, offset = client.scroll(
            settings.category_kb_eval_collection, limit=100, offset=offset,
            with_payload=True, with_vectors=False,
        )
        points.extend(batch)
        if offset is None:
            break
    client.close()
    items_by_key = {}
    for point in points:
        stored = point.payload or {}
        chunk = stored.get("chunk") or {}
        content = chunk.get("content") or {}
        metadata = {"source": chunk.get("source")}
        metadata.update(chunk.get("metadata") or {})
        item = SimpleNamespace(
            document_id=str(stored.get("document_id") or ""), score=0.0,
            chunk=SimpleNamespace(
                content=SimpleNamespace(text=str(content.get("text") or "")),
                metadata=metadata,
            ),
        )
        items_by_key[_candidate_key(item)] = item

    output = {}
    for case_id in case_ids:
        ranking = observations[case_id].get("post_fusion_ranking") or []
        restored = []
        for entry in ranking:
            item = items_by_key.get(str(entry["candidate_id"]))
            if item is None:
                raise RuntimeError(f"{case_id}: candidate not found in local Qdrant: {entry['candidate_id']}")
            item = SimpleNamespace(document_id=item.document_id, score=float(entry["ranking_score"]), chunk=item.chunk)
            restored.append(SimpleNamespace(item=item, retrieval_route="recorded_snapshot"))
        output[case_id] = restored
    return output


def render(result: dict) -> str:
    lines = [
        "# DIRECT + Reranker 诊断实验 C", "",
        "本实验不修改线上 DIRECT、DECOMPOSE、per-need reranker 或 RRF；只对指定 case 的同一候选池离线重排。",
        "", "| Case | 类型 | Vector gold ranks | Rerank gold ranks | Vector / Rerank Top-3 gold | 延迟 |",
        "|---|---|---|---|---:|---:|",
    ]
    for case in result["cases"]:
        latency = "n/a" if case["reranker_latency_ms"] is None else f"{case['reranker_latency_ms']:.1f} ms"
        lines.append(
            f"| {case['case_id']} | {case['primary_kind']} | `{case['vector_gold_ranks']}` | "
            f"`{case['rerank_gold_ranks']}` | {case['vector_top3_gold_count']} / "
            f"{case['rerank_top3_gold_count']}（gold={case['gold_count']}） | "
            f"{latency} |"
        )
    for case in result["cases"]:
        lines += ["", f"## {case['case_id']}", "", f"> {case['query']}", "",
                  "### Vector Top-5", "", "| Rank | Source | Score | Gold | Excerpt |",
                  "|---:|---|---:|---|---|"]
        for row in case["vector_top25"][:5]:
            lines.append(
                f"| {row['rank']} | {row['source']} | {row['vector_score']:.4f} | "
                f"{','.join(row['matched_gold_evidence_ids']) or '-'} | {row['excerpt'].replace('|', '/')} |"
            )
        lines += ["", "### Reranker Top-5", "", "| Rank | Source | Score | Gold | Excerpt |",
                  "|---:|---|---:|---|---|"]
        for row in case["rerank_top25"][:5]:
            lines.append(
                f"| {row['rank']} | {row['source']} | {row['rerank_score']:.4f} | "
                f"{','.join(row['matched_gold_evidence_ids']) or '-'} | {row['excerpt'].replace('|', '/')} |"
            )
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("eval/knowledge/v5/knowledge_eval_core_61.jsonl"))
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--depth", type=int, default=24)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/runs/direct-reranker-diagnostic"))
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument(
        "--candidate-snapshot", type=Path,
        help="复用已记录的完整 DIRECT 候选顺序；不调用 embedding",
    )
    parser.add_argument("--skip-reranker", action="store_true", help="只输出冻结候选诊断，不调用远程 reranker")
    args = parser.parse_args()
    wanted = tuple(args.case_ids or DEFAULT_CASES)
    cases_by_id = {str(case["id"]): case for case in load_dataset(args.dataset)}
    missing = sorted(set(wanted) - set(cases_by_id))
    if missing:
        parser.error(f"unknown case ids: {missing}")

    settings = load_settings()
    if not settings.reranker_base_url or not settings.reranker_model:
        parser.error("RERANKER_BASE_URL / RERANKER_MODEL 未配置")
    frozen_candidates = (
        snapshot_candidates(args.candidate_snapshot, wanted, settings)
        if args.candidate_snapshot else None
    )
    knowledge_base = None
    if frozen_candidates is None:
        knowledge_base = build_evaluation_knowledge_base(settings)
        await verify_evaluation_knowledge_base(knowledge_base, EVALUATION_KNOWLEDGE_DIR)
    reranker = HttpReranker(settings, timeout_seconds=args.timeout_seconds)
    rows = []
    for case_id in wanted:
        case = cases_by_id[case_id]
        candidates = (
            frozen_candidates[case_id]
            if frozen_candidates is not None
            else await retrieve_knowledge_candidates(
                knowledge_base, case["query"], args.depth, target_limit=3,
            )
        )
        evidence = case.get("evidence_ground_truth") or []
        gold_ids = [item["evidence_id"] for item in evidence if int(item.get("grade") or 0) >= 2]
        vector_rows = [candidate_row(candidate, rank, evidence) for rank, candidate in enumerate(candidates, 1)]
        scores, usage, latency_ms, rerank_error = [], {}, None, None
        rerank_rows = []
        if not args.skip_reranker:
            started = time.perf_counter()
            try:
                scores, usage = await reranker.rerank_with_metadata(
                    case["query"], [chunk_text(candidate.item) for candidate in candidates],
                )
                latency_ms = (time.perf_counter() - started) * 1000
                order = sorted(range(len(candidates)), key=lambda index: (-float(scores[index]), index))
                rerank_rows = [
                    candidate_row(candidates[index], rank, evidence, rerank_score=scores[index])
                    for rank, index in enumerate(order, 1)
                ]
            except Exception as error:  # noqa: BLE001 - 诊断报告必须保留候选证据与失败状态
                latency_ms = (time.perf_counter() - started) * 1000
                rerank_error = type(error).__name__
        rows.append({
            "case_id": case_id,
            "query": case["query"],
            "primary_kind": case.get("primary_kind"),
            "expected_query_strategy": case.get("expected_query_strategy"),
            "gold_count": len(gold_ids),
            "gold_evidence_ids": gold_ids,
            "vector_gold_ranks": evidence_ranks(vector_rows, gold_ids),
            "rerank_gold_ranks": evidence_ranks(rerank_rows, gold_ids) if rerank_rows else None,
            "vector_top3_gold_count": len({eid for row in vector_rows[:3] for eid in row["matched_gold_evidence_ids"]}),
            "rerank_top3_gold_count": (
                len({eid for row in rerank_rows[:3] for eid in row["matched_gold_evidence_ids"]})
                if rerank_rows else None
            ),
            "candidate_count": len(candidates),
            "reranker_latency_ms": round(latency_ms, 3) if latency_ms is not None else None,
            "reranker_usage": usage,
            "reranker_status": "skipped" if args.skip_reranker else "failed" if rerank_error else "complete",
            "reranker_error_type": rerank_error,
            "vector_top25": vector_rows,
            "rerank_top25": rerank_rows,
        })
        print(f"{case_id}: vector={rows[-1]['vector_gold_ranks']} rerank={rows[-1]['rerank_gold_ranks']}", flush=True)

    payload = {
        "schema_version": "direct-reranker-diagnostic-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset": str(args.dataset),
        "parameters": {
            "depth": args.depth,
            "reranker_model": settings.reranker_model,
            "production_behavior_changed": False,
            "candidate_source": str(args.candidate_snapshot) if args.candidate_snapshot else "live_embedding",
        },
        "cases": rows,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "direct-reranker-diagnostic.json"
    report_path = args.output_dir / "direct-reranker-diagnostic.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render(payload), encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
