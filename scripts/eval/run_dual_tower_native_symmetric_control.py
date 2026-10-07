# -*- coding: utf-8 -*-
"""B0-native-symmetric vs D0-role 控制实验。

两组共用已经冻结的 D0 document vectors，唯一变量是 Query 使用
``text_type=document`` 还是 ``text_type=query``。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.dual_tower_dashscope import (  # noqa: E402
    DashScopeEmbeddingConfig,
    DashScopeRoleEmbeddingClient,
)
from scripts.eval.evaluate_dual_tower_retriever import evaluate, load_jsonl, render  # noqa: E402
from scripts.eval.run_dual_tower_d0_role import (  # noqa: E402
    EXPERIMENT_COLLECTION,
    chunk_fields,
    corpus_manifest,
    rank_queries,
    sha256_json,
)


def load_chunks(settings) -> list[dict]:
    client = QdrantClient(path=str(settings.data_dir / "qdrant_kb"))
    points, offset = [], None
    while True:
        batch, offset = client.scroll(
            EXPERIMENT_COLLECTION,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        points.extend(batch)
        if offset is None:
            break
    client.close()
    return sorted((chunk_fields(point) for point in points), key=lambda row: row["chunk_id"])


def top20_comparison(
    case_id: str,
    queries: list[dict],
    legacy: list[dict],
    symmetric: list[dict],
    role: list[dict],
) -> dict:
    query_ids = [row["query_id"] for row in queries if row["case_id"] == case_id]
    maps = {
        "B0-compatible": {row["query_id"]: row for row in legacy},
        "B0-native-symmetric": {row["query_id"]: row for row in symmetric},
        "D0-role": {row["query_id"]: row for row in role},
    }
    output = {"case_id": case_id, "query_ids": query_ids, "arms": {}}
    for arm, rows in maps.items():
        output["arms"][arm] = {
            query_id: rows[query_id]["candidates"][:20]
            for query_id in query_ids
        }
    return output


def render_control(result: dict) -> str:
    b, d = result["baseline"], result["dual_tower"]
    lines = [
        "# B0-native-symmetric vs D0-role", "",
        "两组共用同一批 DashScope native `text_type=document` 文档向量；唯一变量是 Query 的 `text_type`。", "",
        "| Metric | Native symmetric (query=document) | D0-role (query=query) | Delta |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (("recall_at_5", "Recall@5"), ("recall_at_10", "Recall@10"),
                       ("recall_at_24", "Recall@24"), ("recall_at_50", "Recall@50"),
                       ("mrr", "MRR")):
        lines.append(f"| {label} | {b[key]:.4f} | {d[key]:.4f} | {result['delta'][key]:+.4f} |")
    lines += [
        f"| Retrieval Loss gold | {b['retrieval_loss_gold_count_at_50']} | {d['retrieval_loss_gold_count_at_50']} | "
        f"{d['retrieval_loss_gold_count_at_50'] - b['retrieval_loss_gold_count_at_50']:+d} |",
        f"| Hard-negative outrank positive | {b['hard_negative_outrank_positive_rate']:.4f} | "
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
    lines += ["", "## Paired movement", "", json.dumps(result["rank_movement_summary"], ensure_ascii=False, indent=2)]
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env", override=False)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    config = DashScopeEmbeddingConfig.from_env()
    client = DashScopeRoleEmbeddingClient(config)

    queries = load_jsonl(args.d0_dir / "frozen_retriever_queries.jsonl")
    d0_rankings = load_jsonl(args.d0_dir / "dual_tower_rankings.jsonl")
    legacy_rankings = load_jsonl(args.d0_dir / "baseline_rankings.jsonl")
    original_manifest_sha = (args.d0_dir / "corpus_manifest.sha256").read_text(encoding="ascii").strip()
    chunks = load_chunks(settings)
    current_manifest_sha = sha256_json(corpus_manifest(chunks))
    if len(chunks) != 151 or current_manifest_sha != original_manifest_sha:
        raise RuntimeError(
            f"D0 document corpus changed: count={len(chunks)}, "
            f"expected_sha={original_manifest_sha}, actual_sha={current_manifest_sha}"
        )

    query_texts = [str(row["query_text"]) for row in queries]
    # 这是控制组的唯一新 API 变量：把 Query 当 document 编码。
    symmetric = await client.embed_documents(query_texts)
    dataset_rows = [
        json.loads(line)
        for line in (ROOT / "eval/knowledge/v5/knowledge_eval_core_61.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dataset = {str(row["id"]): row for row in dataset_rows}
    symmetric_rankings = rank_queries(
        queries,
        symmetric.vectors,
        chunks,
        [row["baseline_vector"] for row in chunks],
        dataset,
    )
    rankings_path = args.output_dir / "b0-native-symmetric-rankings.jsonl"
    rankings_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in symmetric_rankings),
        encoding="utf-8",
    )

    result = evaluate(queries, symmetric_rankings, d0_rankings)
    result.update({
        "schema_version": "dual-tower-native-symmetric-control-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "B0-native-symmetric_vs_D0-role",
        "causal_variable": "query text_type: document vs query",
        "frozen_document_collection": EXPERIMENT_COLLECTION,
        "corpus_manifest_sha256": current_manifest_sha,
        "query_plan_sha256": (args.d0_dir / "query_plan.sha256").read_text(encoding="ascii").strip(),
        "query_encoding_telemetry": {k: v for k, v in asdict(symmetric).items() if k != "vectors"},
        "arm_names": {"baseline": "B0-native-symmetric", "dual_tower": "D0-role"},
    })
    (args.output_dir / "native-symmetric-control.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "native-symmetric-control.md").write_text(render_control(result), encoding="utf-8")
    v4 = top20_comparison("v4-006", queries, legacy_rankings, symmetric_rankings, d0_rankings)
    (args.output_dir / "v4-006-top20-three-arms.json").write_text(
        json.dumps(v4, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "status": "completed", "output_dir": str(args.output_dir.resolve()),
        "query_count": len(queries), "corpus_manifest_sha256": current_manifest_sha,
        "baseline_native_symmetric": result["baseline"], "d0_role": result["dual_tower"],
        "delta": result["delta"], "movement": result["rank_movement_summary"],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--d0-dir", type=Path, default=ROOT / "eval/runs/dual-tower-d0-role")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval/runs/dual-tower-native-symmetric-control")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
