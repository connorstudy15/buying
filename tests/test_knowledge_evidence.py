# -*- coding: utf-8 -*-
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scripts.eval.knowledge_evidence import (
    evidence_id, inspect_evidence, matched_evidence_ids, normalize_text, section_for_quote,
)
from scripts.eval.enrich_knowledge_v3_labels import enrich


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


def test_relevant_is_derived_from_grades_at_positive_threshold_two():
    enriched, issues = enrich({
        "id": "q", "query": "q", "original_kind": "single_evidence",
        "relevant": ["core.md"],
        "graded_relevance": {"core.md": 3, "support.md": 2, "topic.md": 1, "noise.md": 0},
        "evidence": [], "hard_negatives": [{"source": "topic.md", "type": "near", "reason": "topic only"}],
    })
    assert enriched["relevant"] == ["core.md", "support.md"]
    assert enriched["positive_grade_threshold"] == 2
    assert any(item["issues"] == "stored_relevant_missing_positive" for item in issues)


def test_positive_grade_cannot_also_be_a_hard_negative():
    _, issues = enrich({
        "id": "q", "query": "q", "original_kind": "single_evidence",
        "relevant": ["support.md"], "graded_relevance": {"support.md": 2},
        "evidence": [],
        "hard_negatives": [{"source": "support.md", "type": "ambiguous", "reason": "conflict"}],
    })
    assert any(item["issues"] == "hard_negative_cannot_be_positive_grade" for item in issues)


def test_frozen_v1_files_and_single_ground_truth_contract_are_immutable():
    project_root = Path(__file__).resolve().parents[1]
    root = project_root / "eval" / "knowledge" / "v3"
    manifest = json.loads((root / "FROZEN_V1_MANIFEST.json").read_text(encoding="utf-8"))
    for filename, expected in manifest["sha256"].items():
        normalized = (root / filename).read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(normalized).hexdigest()
        assert actual == expected, (filename, str(root / filename), len(normalized), actual)

    rows = [
        json.loads(line)
        for line in (root / "knowledge_eval_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == manifest["counts"]["kept"] == 22
    for row in rows:
        derived = [source for source, grade in row["graded_relevance"].items() if grade >= 2]
        assert row["relevant"] == derived
        assert row["positive_grade_threshold"] == 2
        assert row["label_status"] == "frozen_v1"
        assert all(item["grade"] < 2 for item in row["hard_negatives"])
    blind_008 = next(row for row in rows if row["id"] == "blind-008")
    assert blind_008["primary_kind"] == "cross_evidence"
