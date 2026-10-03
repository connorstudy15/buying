"""Build the v5 Core, Partial Coverage, and Knowledge Gap datasets.

Inputs are the reviewed v4 candidates plus the independent two-phase evidence audit.
The frozen v3 files are never modified.
"""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval.knowledge_evidence import evidence_id, quote_sha256
from scripts.eval.run_category_recall import validate_coverage_contract


ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / "eval" / "knowledge" / "v4"
V5 = ROOT / "eval" / "knowledge" / "v5"

AUDITED_IDS = {
    "v4-044", "v4-045", "v4-047", "v4-060",
    "v4-r009", "v4-r011", "v4-r012", "v4-r014",
}
CORE_ADD = {"v4-060", "v4-045"}
PARTIAL_IDS = {"v4-044", "v4-047"}
GAP_IDS = {"v4-r009", "v4-r011", "v4-r012", "v4-r014"}
STATUS = {
    "v4-044": ("partial", "external_authority_required"),
    "v4-045": ("none", "missing_user_context"),
    "v4-047": ("partial", "external_authority_required"),
    "v4-060": ("complete", None),
    "v4-r009": ("partial", "knowledge_gap"),
    "v4-r011": ("partial", "knowledge_gap"),
    "v4-r012": ("partial", "knowledge_gap"),
    "v4-r014": ("none", "knowledge_gap"),
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def legacy_needs(row: dict, status: str) -> list[dict]:
    if status == "none":
        descriptions = row.get("must_cover") or ["问题所需的静态知识证据"]
        return [
            {"need_id": f"n{index}", "description": str(description), "gold_evidence_ids": []}
            for index, description in enumerate(descriptions, 1)
        ]

    evidence = row.get("evidence_ground_truth") or row.get("evidence") or []
    hops = row.get("hops") or []
    needs = []
    if hops:
        for hop in hops:
            ids = [
                item["evidence_id"] for item in evidence
                if int(item.get("grade") or 0) >= 2 and hop.get("id") in (item.get("supports") or [])
            ]
            if ids:
                needs.append({
                    "need_id": str(hop["id"]),
                    "description": str(hop.get("need") or hop["id"]),
                    "gold_evidence_ids": ids,
                })
    if not needs:
        ids = [item["evidence_id"] for item in evidence if int(item.get("grade") or 0) >= 2]
        needs = [{"need_id": "answer", "description": "完整回答所需证据", "gold_evidence_ids": ids}]
    return needs


def migrate_legacy_row(source: dict) -> dict:
    row = deepcopy(source)
    old = row.get("answerability")
    status = "none" if old == "unanswerable" else "complete"
    row["legacy_answerability"] = old
    row["answerability"] = status
    row["missing_reason"] = "realtime_required" if status == "none" else None
    row["required_information_needs"] = legacy_needs(row, status)
    row["coverage_contract_version"] = "knowledge-eval-v5-1"
    validate_coverage_contract(row)
    return row


def audited_row(source: dict, phase_a: dict, phase_b: dict) -> dict:
    row = deepcopy(source)
    case_id = str(row["id"])
    status, reason = STATUS[case_id]
    row["legacy_answerability"] = row.get("answerability")
    row["answerability"] = status
    row["missing_reason"] = reason
    row["coverage_contract_version"] = "knowledge-eval-v5-1"
    row["independent_audit_confidence"] = phase_b.get("confidence")

    phase_b_needs = {item["need_id"]: item for item in phase_b["required_information_needs"]}
    needs: list[dict] = []
    evidence_by_id: dict[str, dict] = {}
    audited_source_grades: dict[str, int] = {}
    for blind_need in phase_a["required_information_needs"]:
        need_id = str(blind_need["need_id"])
        checked = phase_b_needs[need_id]
        covered = bool(checked.get("covered"))
        # v4-r009 的阶段 A 要求具体包装方法；“核对原厂加固包装”不足以覆盖该 need。
        if case_id == "v4-r009" and need_id == "n2":
            covered = False
        gold_ids: list[str] = []
        for raw in checked.get("evidence") or []:
            source_name = str(raw["source"]).replace("\\", "/").removeprefix("knowledge/")
            grade = int(raw["grade"])
            audited_source_grades[source_name] = max(audited_source_grades.get(source_name, 0), grade)
            if not covered or grade < 2:
                continue
            stable_id = evidence_id(source_name, str(raw["section"]), str(raw["quote"]))
            gold_ids.append(stable_id)
            if stable_id not in evidence_by_id:
                evidence_by_id[stable_id] = {
                    "source": source_name,
                    "section": str(raw["section"]),
                    "quote": str(raw["quote"]),
                    "evidence_id": stable_id,
                    "quote_sha256": quote_sha256(str(raw["quote"])),
                    "grade": grade,
                    "supports": [need_id],
                }
            elif need_id not in evidence_by_id[stable_id]["supports"]:
                evidence_by_id[stable_id]["supports"].append(need_id)
                evidence_by_id[stable_id]["grade"] = max(evidence_by_id[stable_id]["grade"], grade)
        needs.append({
            "need_id": need_id,
            "description": str(blind_need["description"]),
            "gold_evidence_ids": list(dict.fromkeys(gold_ids)),
        })

    row["required_information_needs"] = needs
    evidence = list(evidence_by_id.values())
    row["evidence"] = evidence
    row["evidence_ground_truth"] = evidence

    grades = {str(key): int(value) for key, value in (row.get("graded_relevance") or {}).items()}
    positive_sources = {item["source"] for item in evidence}
    for source_name, old_grade in list(grades.items()):
        if old_grade >= 2 and source_name not in positive_sources:
            grades[source_name] = min(1, audited_source_grades.get(source_name, 1))
    for item in evidence:
        grades[item["source"]] = max(grades.get(item["source"], 0), int(item["grade"]))
    row["graded_relevance"] = grades
    row["relevant"] = [source_name for source_name, grade in grades.items() if int(grade) >= 2]
    row["hard_negatives"] = [
        item for item in (row.get("hard_negatives") or [])
        if int(grades.get(item.get("source"), item.get("grade", 0))) < 2
    ]
    row["audit_decision_reason"] = phase_b.get("decision_reason")
    validate_coverage_contract(row)
    return row


def main() -> None:
    V5.mkdir(parents=True, exist_ok=True)
    merged = read_jsonl(V4 / "knowledge_eval_candidates.reviewed.jsonl")
    by_id = {row["id"]: row for row in merged}
    phase_a = {row["id"]: row for row in read_jsonl(V4 / "independent_evidence_audit" / "phase_a_needs.jsonl")}
    phase_b = {row["id"]: row for row in read_jsonl(V4 / "independent_evidence_audit" / "phase_b_evidence_audit.jsonl")}
    if set(phase_a) != AUDITED_IDS or set(phase_b) != AUDITED_IDS:
        raise ValueError("独立盲审 ID 与预期 8 题不一致")

    unaffected = [migrate_legacy_row(row) for row in merged if row["id"] not in AUDITED_IDS]
    adjudicated = {
        case_id: audited_row(by_id[case_id], phase_a[case_id], phase_b[case_id])
        for case_id in AUDITED_IDS
    }
    core = unaffected + [adjudicated[case_id] for case_id in sorted(CORE_ADD)]
    partial = [adjudicated[case_id] for case_id in sorted(PARTIAL_IDS)]
    gaps = [adjudicated[case_id] for case_id in sorted(GAP_IDS)]
    if (len(core), len(partial), len(gaps)) != (61, 2, 4):
        raise ValueError(f"输出数量错误：{len(core)}/{len(partial)}/{len(gaps)}")

    outputs = {
        "knowledge_eval_core_61.jsonl": core,
        "knowledge_eval_partial_coverage_2.jsonl": partial,
        "knowledge_eval_knowledge_gap_4.jsonl": gaps,
    }
    for filename, rows in outputs.items():
        write_jsonl(V5 / filename, rows)

    manifest = {
        "schema_version": "knowledge-eval-v5-1",
        "source_reviewed_candidates_sha256": sha256(V4 / "knowledge_eval_candidates.reviewed.jsonl"),
        "source_phase_a_sha256": sha256(V4 / "independent_evidence_audit" / "phase_a_needs.jsonl"),
        "source_phase_b_sha256": sha256(V4 / "independent_evidence_audit" / "phase_b_evidence_audit.jsonl"),
        "outputs": {
            filename: {"count": len(rows), "sha256": sha256(V5 / filename)}
            for filename, rows in outputs.items()
        },
        "adjudication": {
            "stable_core_add": sorted(CORE_ADD),
            "partial_coverage": sorted(PARTIAL_IDS),
            "knowledge_gap": sorted(GAP_IDS),
            "v4-r009_override": "n2 packaging methods lack grade>=2 evidence; moved to partial knowledge_gap",
        },
    }
    (V5 / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
