import hashlib
import json
from pathlib import Path

from scripts.eval.run_category_recall import load_dataset


ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / "eval" / "knowledge" / "v5"


def test_v5_coverage_sets_match_manifest_and_do_not_overlap():
    manifest = json.loads((V5 / "MANIFEST.json").read_text(encoding="utf-8"))
    expected = {
        "knowledge_eval_core_61.jsonl": 61,
        "knowledge_eval_partial_coverage_2.jsonl": 2,
        "knowledge_eval_knowledge_gap_4.jsonl": 4,
    }
    id_sets = []
    for filename, count in expected.items():
        path = V5 / filename
        rows = load_dataset(path)
        assert len(rows) == count == manifest["outputs"][filename]["count"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["outputs"][filename]["sha256"]
        ids = {row["id"] for row in rows}
        assert len(ids) == count
        for row in rows:
            derived = [source for source, grade in row.get("graded_relevance", {}).items() if int(grade) >= 2]
            assert row.get("relevant", []) == derived
            if row["answerability"] == "none":
                assert row.get("evidence_ground_truth", []) == []
                assert row.get("relevant", []) == []
        id_sets.append(ids)
    assert not (id_sets[0] & id_sets[1] or id_sets[0] & id_sets[2] or id_sets[1] & id_sets[2])


def test_v5_adjudicated_cases_have_expected_orthogonal_labels():
    core = {row["id"]: row for row in load_dataset(V5 / "knowledge_eval_core_61.jsonl")}
    partial = {row["id"]: row for row in load_dataset(V5 / "knowledge_eval_partial_coverage_2.jsonl")}
    gaps = {row["id"]: row for row in load_dataset(V5 / "knowledge_eval_knowledge_gap_4.jsonl")}

    assert core["v4-060"]["answerability"] == "complete"
    assert core["v4-060"]["missing_reason"] is None
    assert core["v4-045"]["answerability"] == "none"
    assert core["v4-045"]["missing_reason"] == "missing_user_context"
    assert set(partial) == {"v4-044", "v4-047"}
    assert all(row["answerability"] == "partial" for row in partial.values())
    assert all(row["missing_reason"] == "external_authority_required" for row in partial.values())
    assert set(gaps) == {"v4-r009", "v4-r011", "v4-r012", "v4-r014"}
    assert all(row["missing_reason"] == "knowledge_gap" for row in gaps.values())
    r009_needs = {item["need_id"]: item for item in gaps["v4-r009"]["required_information_needs"]}
    assert r009_needs["n1"]["gold_evidence_ids"]
    assert r009_needs["n2"]["gold_evidence_ids"] == []
