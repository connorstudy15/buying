# -*- coding: utf-8 -*-
from pathlib import Path
from types import SimpleNamespace

from scripts.eval.knowledge_evidence import (
    evidence_id, inspect_evidence, matched_evidence_ids, normalize_text, section_for_quote,
)


def test_stable_evidence_id_ignores_whitespace_but_keeps_scope():
    first = evidence_id("travel.md", "避坑点", "航空  限制\n需要核对")
    second = evidence_id("travel.md", "避坑点", "航空 限制 需要核对")
    assert first == second
    assert first != evidence_id("other.md", "避坑点", "航空 限制 需要核对")


def test_section_for_quote_uses_nearest_markdown_heading():
    section, occurrences = section_for_quote("# 标题\n## 规则\n这是证据。\n", "这是证据。")
    assert section == "规则"
    assert occurrences == 1


def test_matched_evidence_requires_source_and_exact_normalized_quote():
    hits = [
        SimpleNamespace(document_id="a.md", chunk=SimpleNamespace(metadata={"source": "a.md"}, text="前文 关键 证据 后文")),
        SimpleNamespace(document_id="b.md", chunk=SimpleNamespace(metadata={"source": "b.md"}, text="关键 证据")),
    ]
    gold = [{"evidence_id": "a#1", "source": "a.md", "quote": "关键\n证据"}]
    matched, ranks = matched_evidence_ids(hits, gold)
    assert matched == ["a#1"]
    assert ranks == {"a#1": 1}


def test_inspect_evidence_flags_wrong_declared_section(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "a.md").write_text("# 文档\n## 正确章节\n证据原文\n", encoding="utf-8")
    issues = inspect_evidence(tmp_path, {"source": "a.md", "section": "错误章节", "quote": "证据原文"})
    assert issues == ["section_mismatch:正确章节"]


def test_normalize_text_only_normalizes_whitespace():
    assert normalize_text("  一行\n 二行  ") == "一行 二行"
