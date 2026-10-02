# -*- coding: utf-8 -*-
"""把阶段 B 文档级标注编译为可执行的 evidence-level v3 评测集。"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval.knowledge_evidence import evidence_id, inspect_evidence, quote_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT = PROJECT_ROOT / "eval" / "knowledge" / "v3"
LABEL_PATHS = [ROOT / "stage_b_labels.jsonl", ROOT / "stage_b_human_multihop_labels.jsonl"]
OUTPUT = ROOT / "knowledge_eval_candidates.jsonl"
REVIEW = ROOT / "evidence_mapping_review.csv"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def primary_kind(row: dict) -> str:
    if row.get("answerability") == "unanswerable":
        return "unanswerable"
    return str(row.get("original_kind") or "single_hop_direct")


def enrich(row: dict) -> tuple[dict, list[dict]]:
    grades = row.get("graded_relevance") or {}
    issues: list[dict] = []
    evidence_ground_truth: list[dict] = []
    for item in row.get("evidence") or []:
        source = item["source"]
        hop_ids = [hop["id"] for hop in row.get("hops") or [] if source in (hop.get("relevant") or [])]
        evidence_issues = inspect_evidence(PROJECT_ROOT, item)
        if source not in grades:
            evidence_issues.append("grade_missing")
        enriched = {
            "evidence_id": evidence_id(source, item.get("section", ""), item["quote"]),
            "source": source,
            "section": item.get("section", ""),
            "quote": item["quote"],
            "quote_sha256": quote_sha256(item["quote"]),
            "grade": grades.get(source),
            "supports": hop_ids or ["answer"],
        }
        evidence_ground_truth.append(enriched)
        if evidence_issues:
            issues.append({
                "id": row["id"], "query": row["query"], "source": source,
                "section": item.get("section", ""), "evidence_id": enriched["evidence_id"],
                "issues": " | ".join(evidence_issues), "quote": item["quote"],
            })

    hard_negatives: list[dict] = []
    for item in row.get("hard_negatives") or []:
        source = item["source"]
        grade = grades.get(source)
        enriched_negative = {**item, "grade": grade, "is_hard_negative": True}
        hard_negatives.append(enriched_negative)
        negative_issues: list[str] = []
        if grade is None:
            negative_issues.append("hard_negative_grade_missing")
        elif grade == 3:
            negative_issues.append("hard_negative_cannot_be_grade_3")
        if negative_issues:
            issues.append({
                "id": row["id"], "query": row["query"], "source": source,
                "section": "", "evidence_id": "", "issues": " | ".join(negative_issues),
                "quote": item.get("reason", ""),
            })

    relevant_sources = set(row.get("relevant") or [])
    grade3_sources = {source for source, grade in grades.items() if grade == 3}
    evidence_sources = {item["source"] for item in evidence_ground_truth if item.get("grade") == 3}
    for issue_name, sources in (
        ("relevant_without_grade_3", relevant_sources - grade3_sources),
        ("grade_3_not_in_relevant", grade3_sources - relevant_sources),
        ("relevant_without_evidence", relevant_sources - evidence_sources),
    ):
        for source in sorted(sources):
            issues.append({
                "id": row["id"], "query": row["query"], "source": source,
                "section": "", "evidence_id": "", "issues": issue_name, "quote": "",
            })

    result = {
        **row,
        "schema_version": "knowledge-eval-v3-evidence-1",
        "primary_kind": primary_kind(row),
        "tags": sorted(set([str(row.get("original_kind") or "knowledge")]
                           + (["multi_hop"] if row.get("hops") else [])
                           + (["implicit_constraint"] if row.get("original_kind") == "implicit_constraint_multi_hop" else []))),
        "evidence_ground_truth": evidence_ground_truth,
        "hard_negatives": hard_negatives,
        "label_status": "pending_human_review",
    }
    return result, issues


def main() -> None:
    rows = [row for path in LABEL_PATHS for row in load_jsonl(path) if row.get("label_decision") == "keep"]
    enriched_rows: list[dict] = []
    review_rows: list[dict] = []
    for row in rows:
        enriched, issues = enrich(row)
        enriched_rows.append(enriched)
        review_rows.extend(issues)
    OUTPUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in enriched_rows), encoding="utf-8")
    columns = ["id", "query", "source", "section", "evidence_id", "issues", "quote", "review_decision", "reviewer_notes"]
    with REVIEW.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for issue in review_rows:
            writer.writerow({**issue, "review_decision": "", "reviewer_notes": ""})
    print(json.dumps({"output": str(OUTPUT), "kept": len(enriched_rows), "review_issues": len(review_rows), "review": str(REVIEW)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
