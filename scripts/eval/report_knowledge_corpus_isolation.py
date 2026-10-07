# -*- coding: utf-8 -*-
"""汇总 Production/Evaluation corpus 隔离、collection 与 sanity 结果。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.rag.category_knowledge import (  # noqa: E402
    EVALUATION_KNOWLEDGE_DIR, PRODUCTION_KNOWLEDGE_DIR,
)
from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.knowledge_quality import count_knowledge_chunks, load_knowledge_manifest  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main() -> None:
    settings = load_settings()
    production = load_knowledge_manifest(PRODUCTION_KNOWLEDGE_DIR)
    evaluation = load_knowledge_manifest(EVALUATION_KNOWLEDGE_DIR)
    client = QdrantClient(path=str(settings.data_dir / "qdrant_kb"))
    try:
        collections = {item.name for item in client.get_collections().collections}
        production_points = client.get_collection(settings.category_kb_collection).points_count
        evaluation_points = client.get_collection(settings.category_kb_eval_collection).points_count
    finally:
        client.close()
    regression = json.loads((ROOT / "eval/runs/corpus-isolation-regression/regression.json").read_text(encoding="utf-8"))
    sanity = json.loads((ROOT / "eval/runs/production-sanity-v1/result.json").read_text(encoding="utf-8"))
    payload = {
        "production": {
            "directory": str(PRODUCTION_KNOWLEDGE_DIR), "document_count": len(production),
            "chunk_count_from_source": await count_knowledge_chunks(PRODUCTION_KNOWLEDGE_DIR),
            "collection": settings.category_kb_collection, "collection_point_count": production_points,
            "manifest_sha256": sha(PRODUCTION_KNOWLEDGE_DIR / "manifest.jsonl"),
            "source_types": dict(Counter(row["source_type"] for row in production)),
            "authority_levels": dict(Counter(row["authority_level"] for row in production)),
        },
        "evaluation": {
            "directory": str(EVALUATION_KNOWLEDGE_DIR), "document_count": len(evaluation),
            "chunk_count_from_source": await count_knowledge_chunks(EVALUATION_KNOWLEDGE_DIR),
            "collection": settings.category_kb_eval_collection, "collection_point_count": evaluation_points,
            "manifest_sha256": sha(EVALUATION_KNOWLEDGE_DIR / "manifest.jsonl"),
            "frozen_corpus_manifest_sha256": regression["corpus_manifest_sha256"],
            "source_types": dict(Counter(row["source_type"] for row in evaluation)),
        },
        "isolation": {
            "collection_names_distinct": settings.category_kb_collection != settings.category_kb_eval_collection,
            "dual_tower_collections_preserved": all(name in collections for name in (
                "knowledge_dual_tower_exp", "knowledge_dual_tower_full_exp",
            )),
            "migration_exact_ranking_match": regression["exact_ranking_match"],
            "migration_metric_match": regression["metric_match"],
            "migration_query_plan_sha256": regression["query_plan_sha256"],
        },
        "production_sanity": sanity["metrics"],
        "recommendation": (
            "暂不把 role-aware Flash 接入正式 Candidate B。当前 24 题在现有 production retriever 上的"
            " answerable Recall@3 已无提升空间，但不可回答拒答率明显不足；先人工抽查 sanity gold，"
            "扩大 production 查询与困难负例，再做 symmetric vs role-aware 的独立对照。"
        ),
    }
    output = ROOT / "docs/evaluation/knowledge-corpus-isolation-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Knowledge Corpus Isolation Report", "",
        "## Corpus", "",
        f"- Production：{len(production)} docs / {payload['production']['chunk_count_from_source']} chunks；collection `{settings.category_kb_collection}` / {production_points} points。",
        f"- Evaluation：{len(evaluation)} docs / {payload['evaluation']['chunk_count_from_source']} chunks；collection `{settings.category_kb_eval_collection}` / {evaluation_points} points。",
        f"- Production manifest SHA-256：`{payload['production']['manifest_sha256']}`",
        f"- Evaluation source manifest SHA-256：`{payload['evaluation']['manifest_sha256']}`",
        f"- Frozen evaluation corpus manifest SHA-256：`{regression['corpus_manifest_sha256']}`", "",
        "## Isolation regression", "",
        f"- Exact ranking match：`{regression['exact_ranking_match']}`",
        f"- Metric match：`{regression['metric_match']}`",
        f"- Query Plan SHA-256：`{regression['query_plan_sha256']}`", "",
        "## Production sanity", "",
        *(f"- {key}: `{value}`" for key, value in sanity["metrics"].items()), "",
        "## Recommendation", "", payload["recommendation"], "",
    ]
    output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
