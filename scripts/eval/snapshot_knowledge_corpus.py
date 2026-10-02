# -*- coding: utf-8 -*-
"""冻结知识语料与评测资产，供检索实验复现和结果归因。

本脚本只读取本地文件，不调用 LLM、Embedding 或 Qdrant，也不会记录密钥、
网关地址等敏感配置。语料 fingerprint 只由会影响实验结果的稳定字段计算。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from agentscope.rag import ApproxTokenChunker, TextParser

from scripts.eval.knowledge_quality import (
    load_knowledge_manifest,
    validate_knowledge_content,
    validate_knowledge_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "knowledge" / "corpus-snapshot-20260929.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _safe_env(path: Path) -> dict[str, str]:
    """只读取允许写入快照的非敏感配置。"""
    allowed = {
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "CATEGORY_KB_COLLECTION",
        "QDRANT_URL",
    }
    values: dict[str, str] = {
        "EMBEDDING_MODEL": "text-embedding-v4",
        "EMBEDDING_DIM": "1024",
        "CATEGORY_KB_COLLECTION": "globex_category_kb",
    }
    present: set[str] = set()
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        present.add(key)
        if key in allowed:
            values[key] = value.strip().strip('"').strip("'")
    # URL 本身也不进入报告，只记录本地/远程模式。
    if "QDRANT_URL" in values:
        values["QDRANT_MODE"] = "remote" if values["QDRANT_URL"] else "local_embedded"
        del values["QDRANT_URL"]
    else:
        values["QDRANT_MODE"] = "local_embedded"
    values["EMBEDDING_ENDPOINT_SOURCE"] = (
        "dedicated_embedding_config"
        if {"EMBEDDING_BASE_URL", "EMBEDDING_API_KEY"} <= present
        else "inherits_llm_config"
    )
    return values


def _eval_asset(path: Path) -> dict[str, Any]:
    rows = _jsonl_rows(path)
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": _sha256(path.read_bytes()) if path.is_file() else None,
        "case_count": len(rows),
        "splits": dict(sorted(Counter(str(row.get("split", "legacy")) for row in rows).items())),
        "buckets": dict(sorted(Counter(str(row.get("kind", "legacy")) for row in rows).items())),
        "label_granularity": "document_filename",
        "has_evidence_span": any(bool(row.get("evidence")) for row in rows),
        "has_graded_relevance": any(bool(row.get("graded_relevance")) for row in rows),
    }


async def build_snapshot(root: Path) -> dict[str, Any]:
    knowledge_dir = root / "knowledge"
    manifest = load_knowledge_manifest(knowledge_dir)
    problems = validate_knowledge_manifest(knowledge_dir, manifest)
    problems.extend(validate_knowledge_content(knowledge_dir))
    if problems:
        raise ValueError("知识语料校验失败：\n- " + "\n- ".join(problems))

    parser = TextParser()
    chunker = ApproxTokenChunker(chunk_size=512, overlap=50)
    manifest_by_file = {entry["filename"]: entry for entry in manifest}
    documents: list[dict[str, Any]] = []
    for path in sorted(knowledge_dir.glob("*.md"), key=lambda item: item.name):
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        sections = await parser.parse(str(path), filename=path.name)
        chunks = await chunker.chunk(sections)
        title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        metadata = manifest_by_file[path.name]
        documents.append({
            "document_id": metadata["document_id"],
            "filename": path.name,
            "title": title_match.group(1).strip() if title_match else path.stem,
            "sha256": _sha256(raw),
            "bytes": len(raw),
            "characters": len(text),
            "chunk_count": len(chunks),
            "topic": metadata["topic"],
            "region": metadata["region"],
            "version": metadata["version"],
            "source_type": metadata["source_type"],
            "published_at": metadata["published_at"],
            "effective_from": metadata["effective_from"],
            "effective_to": metadata["effective_to"],
        })

    stable = {
        "documents": documents,
        "ingestion": {
            "parser": "agentscope.rag.TextParser",
            "chunker": "agentscope.rag.ApproxTokenChunker",
            "chunk_size": 512,
            "chunk_overlap": 50,
            "content_hash_salt": "chunker:512:50:v2",
            "managed_by": "globex_markdown_sync_v1",
        },
        "retrieval": {
            "method": "dense_vector_with_targeted_document_routing",
            "default_top_k": 3,
            "candidate_depth": "min(80, top_k * 8)",
            "document_deduplication": "highest_ranked_chunk_per_document",
            "answerable_score_threshold": 0.20,
            "keyword_fallback_on_vector_error": True,
        },
        "runtime": _safe_env(root / ".env"),
        "evaluation_assets": {
            "formal_regression_50": _eval_asset(root / "eval" / "v1" / "knowledge_retrieval.jsonl"),
            "legacy_regression_22": _eval_asset(root / "eval" / "category_recall.jsonl"),
        },
    }
    canonical = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "corpus_fingerprint": _sha256(canonical),
        "summary": {
            "document_count": len(documents),
            "chunk_count": sum(item["chunk_count"] for item in documents),
            "bytes": sum(item["bytes"] for item in documents),
            "characters": sum(item["characters"] for item in documents),
        },
        **stable,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="冻结 Globex 知识语料与评测资产")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = await build_snapshot(PROJECT_ROOT)
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "corpus_fingerprint": snapshot["corpus_fingerprint"],
        **snapshot["summary"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
