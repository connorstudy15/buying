from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.rag.category_knowledge import (
    EVALUATION_KNOWLEDGE_DIR,
    KNOWLEDGE_DIR,
    PRODUCTION_KNOWLEDGE_DIR,
    build_category_knowledge_base,
    build_evaluation_knowledge_base,
    load_knowledge_metadata,
)
from app.infrastructure.rag.knowledge_retrieval import search_knowledge_with_trace
from scripts.eval.knowledge_quality import count_knowledge_chunks, load_knowledge_manifest


ROOT = Path(__file__).resolve().parents[1]


def _write_manifest(directory: Path, *, role: str, source_type: str) -> None:
    directory.mkdir(parents=True)
    (directory / "doc.md").write_text("# 文档\n\n## 规则\n测试内容。\n", encoding="utf-8")
    row = {
        "document_id": "doc", "filename": "doc.md", "source": "test",
        "source_type": source_type, "published_at": "2026-01-01",
        "effective_from": "2026-01-01", "effective_to": "2027-01-01",
        "region": "GLOBAL", "version": "test", "topic": "category",
        "corpus_role": role,
    }
    (directory / "manifest.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def _settings(tmp_path: Path, *, production: str = "prod", evaluation: str = "eval"):
    return SimpleNamespace(
        embedding_api_key="sk-test", embedding_base_url="https://example.invalid/v1",
        embedding_model="test", embedding_dim=3, qdrant_url="",
        data_dir=tmp_path, category_kb_collection=production,
        category_kb_eval_collection=evaluation,
    )


def test_production_admission_rejects_synthetic_fixture(tmp_path):
    directory = tmp_path / "production"
    _write_manifest(directory, role="production", source_type="synthetic_evaluation_fixture")
    with pytest.raises(ValueError, match="allowlist"):
        load_knowledge_metadata(directory, corpus_role="production")


def test_evaluation_admission_accepts_synthetic_fixture(tmp_path):
    directory = tmp_path / "evaluation"
    _write_manifest(directory, role="evaluation", source_type="synthetic_evaluation_fixture")
    assert load_knowledge_metadata(directory, corpus_role="evaluation")["doc"]["corpus_role"] == "evaluation"


def test_runtime_directory_cannot_point_to_evaluation_corpus():
    assert KNOWLEDGE_DIR == PRODUCTION_KNOWLEDGE_DIR
    assert KNOWLEDGE_DIR.resolve() != EVALUATION_KNOWLEDGE_DIR.resolve()


def test_evaluation_builder_uses_only_explicit_eval_collection(tmp_path):
    settings = _settings(tmp_path)
    knowledge_base = build_evaluation_knowledge_base(settings)
    assert knowledge_base.collection == "eval"
    assert knowledge_base._globex_corpus_role == "evaluation"


def test_production_and_eval_collection_names_must_differ(tmp_path):
    settings = _settings(tmp_path, production="same", evaluation="same")
    with pytest.raises(ValueError, match="不允许相同"):
        build_category_knowledge_base(settings)


def test_empty_production_corpus_never_falls_back_to_eval(tmp_path):
    empty = tmp_path / "production"
    empty.mkdir()
    with pytest.raises(ValueError, match="缺少 manifest"):
        load_knowledge_metadata(empty, corpus_role="production")


@pytest.mark.asyncio
async def test_migrated_evaluation_corpus_remains_151_chunks():
    assert await count_knowledge_chunks(EVALUATION_KNOWLEDGE_DIR) == 151


def test_production_documents_have_source_type_and_role():
    rows = load_knowledge_manifest(PRODUCTION_KNOWLEDGE_DIR)
    assert rows
    assert all(row.get("source_type") for row in rows)
    assert all(row.get("corpus_role") == "production" for row in rows)


def test_evaluation_documents_have_evaluation_role():
    rows = load_knowledge_manifest(EVALUATION_KNOWLEDGE_DIR)
    assert len(rows) == 45
    assert all(row.get("corpus_role") == "evaluation" for row in rows)


@pytest.mark.asyncio
async def test_trace_records_collection_and_corpus_version():
    knowledge_base = SimpleNamespace(
        collection="prod", _globex_collection_name="prod", _globex_corpus_version="abc123",
    )
    outcome = await search_knowledge_with_trace(knowledge_base, "明天汇率会涨吗")
    assert outcome.trace.collection_name == "prod"
    assert outcome.trace.corpus_version == "abc123"
