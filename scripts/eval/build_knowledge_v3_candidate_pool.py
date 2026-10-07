# -*- coding: utf-8 -*-
"""为冻结的 v3 Query 建立与线上排序解耦的多路候选池。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.infrastructure.rag.category_knowledge import build_evaluation_knowledge_base
from app.infrastructure.rag.knowledge_retrieval import targeted_documents
from app.infrastructure.settings import PROJECT_ROOT, load_settings


DEFAULT_QUERIES = PROJECT_ROOT / "eval" / "knowledge" / "v3" / "blind_queries.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "knowledge" / "v3" / "candidate_pool.jsonl"


def terms(text: str) -> list[str]:
    normalized = text.casefold()
    output = re.findall(r"[a-z0-9_]+", normalized)
    for seq in re.findall(r"[\u4e00-\u9fff]+", normalized):
        output.extend(seq[index:index + 2] for index in range(max(1, len(seq) - 1)))
    return output


def bm25_rank(query: str, documents: dict[str, str], limit: int = 10) -> list[tuple[str, float]]:
    tokenized = {name: terms(text) for name, text in documents.items()}
    frequencies = {name: Counter(tokens) for name, tokens in tokenized.items()}
    lengths = {name: len(tokens) for name, tokens in tokenized.items()}
    average = sum(lengths.values()) / max(len(lengths), 1)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized.values():
        document_frequency.update(set(tokens))
    scores: defaultdict[str, float] = defaultdict(float)
    count = len(documents)
    for token in terms(query):
        df = document_frequency[token]
        if not df:
            continue
        inverse = math.log(1 + (count - df + 0.5) / (df + 0.5))
        for name, freq in frequencies.items():
            tf = freq[token]
            if not tf:
                continue
            denominator = tf + 1.5 * (1 - 0.75 + 0.75 * lengths[name] / max(average, 1))
            scores[name] += inverse * tf * 2.5 / denominator
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]


def chunk_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if getattr(content, "text", None) is not None:
        return str(content.text)
    if isinstance(content, dict):
        return str(content.get("text") or content)
    return str(content)


async def main() -> None:
    parser = argparse.ArgumentParser(description="构建知识召回 v3 多路候选池")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    query_path = args.queries if args.queries.is_absolute() else PROJECT_ROOT / args.queries
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    queries = [json.loads(line) for line in query_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    corpus = PROJECT_ROOT / "eval" / "knowledge" / "corpus"
    documents = {path.name: path.read_text(encoding="utf-8") for path in sorted(corpus.glob("*.md"))}
    settings = load_settings()
    kb = build_evaluation_knowledge_base(settings)
    # 阶段 B 只允许读取既有本地索引：不得在候选池构建时把正文重新提交给外部 Embedding。
    await kb.ensure_collection()
    registered = await kb.list_documents()
    if not registered:
        raise RuntimeError("本地知识索引为空；请在单独、明确授权的入库流程完成后再构建候选池")
    rows = []
    for case in queries:
        query = case["query"]
        merged: dict[str, dict[str, Any]] = {}
        for rank, (source, score) in enumerate(bm25_rank(query, documents), 1):
            merged.setdefault(source, {"source": source})
            merged[source].update(bm25_rank=rank, bm25_score=round(score, 6))
        vector_hits = await kb.search(queries=[query], top_k=40)
        seen: set[str] = set()
        vector_rank = 0
        for hit in vector_hits:
            source = (hit.chunk.metadata or {}).get("source", f"{hit.document_id}.md")
            if source in seen:
                continue
            seen.add(source)
            vector_rank += 1
            merged.setdefault(source, {"source": source})
            merged[source].update(vector_rank=vector_rank, vector_score=round(float(hit.score), 6),
                                  vector_excerpt=chunk_text(hit.chunk.content)[:700])
            if vector_rank >= 10:
                break
        for rank, document in enumerate(targeted_documents(registered, query, 10), 1):
            source = document.metadata.get("source", f"{document.document_id}.md")
            merged.setdefault(source, {"source": source})
            merged[source]["title_route_rank"] = rank
        candidates = sorted(merged.values(), key=lambda item: (
            min(item.get("bm25_rank", 999), item.get("vector_rank", 999), item.get("title_route_rank", 999)),
            item.get("vector_rank", 999), item.get("bm25_rank", 999), item["source"],
        ))
        rows.append({**case, "candidates": candidates})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    manifest = {
        "stage": "candidate_pool",
        "query_sha256": hashlib.sha256(query_path.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "strategies": ["document_bm25_top10", "raw_vector_document_top10", "title_route"],
        "query_count": len(rows),
        "average_candidates": round(sum(len(row["candidates"]) for row in rows) / max(len(rows), 1), 2),
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dim,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
