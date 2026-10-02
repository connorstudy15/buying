# -*- coding: utf-8 -*-
"""校验阶段 B 标注，并只把 keep 条目导出给人工审批。"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from app.infrastructure.settings import PROJECT_ROOT


ROOT = PROJECT_ROOT / "eval" / "knowledge" / "v3"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def main() -> None:
    query_path = ROOT / "blind_queries.jsonl"
    label_path = ROOT / "stage_b_labels.jsonl"
    output = ROOT / "human_review.csv"
    queries = {row["id"]: row for row in load_jsonl(query_path)}
    labels = load_jsonl(label_path)
    problems: list[str] = []
    if len(labels) != len(queries) or {row["id"] for row in labels} != set(queries):
        problems.append("阶段 B 必须逐条覆盖冻结 Query")
    for row in labels:
        case_id = row["id"]
        if queries.get(case_id, {}).get("query") != row.get("query"):
            problems.append(f"{case_id}: Query 发生漂移")
        if row.get("label_decision") not in {"keep", "reject"}:
            problems.append(f"{case_id}: label_decision 非法")
        relevant = row.get("relevant") or []
        grades = row.get("graded_relevance") or {}
        evidence = row.get("evidence") or []
        if row.get("label_decision") == "keep" and row.get("answerability") != "unanswerable":
            for source in relevant:
                if grades.get(source) != 3:
                    problems.append(f"{case_id}: relevant {source} 必须 grade=3")
            if not relevant or not evidence:
                problems.append(f"{case_id}: 可回答 keep 条目缺少 relevant/evidence")
        for source, grade in grades.items():
            if type(grade) is not int or not 0 <= grade <= 3:
                problems.append(f"{case_id}: {source} grade 非 0..3 整数")
        for item in evidence:
            source_path = PROJECT_ROOT / "knowledge" / item["source"]
            if not source_path.is_file() or item["quote"] not in source_path.read_text(encoding="utf-8"):
                problems.append(f"{case_id}: evidence 无法逐字回指 {item['source']}")
    if problems:
        raise ValueError("阶段 B 校验失败：\n- " + "\n- ".join(problems))

    kept = [row for row in labels if row["label_decision"] == "keep"]
    columns = ["id", "decision", "original_kind", "answerability", "query", "relevant", "evidence",
               "graded_relevance", "hard_negatives", "label_reason", "label_confidence",
               "corrected_relevant", "corrected_grades", "corrected_evidence", "reviewer_notes"]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in kept:
            writer.writerow({
                "id": row["id"], "decision": "", "original_kind": row["original_kind"],
                "answerability": row["answerability"], "query": row["query"],
                "relevant": " | ".join(row.get("relevant") or []),
                "evidence": " || ".join(f"[{item['source']}][{item['section']}] {item['quote']}" for item in row.get("evidence") or []),
                "graded_relevance": " | ".join(f"{source}={grade}" for source, grade in row.get("graded_relevance", {}).items()),
                "hard_negatives": " || ".join(f"[{item['source']}][{item['type']}] {item['reason']}" for item in row.get("hard_negatives") or []),
                "label_reason": row["label_reason"], "label_confidence": row["label_confidence"],
                "corrected_relevant": "", "corrected_grades": "", "corrected_evidence": "", "reviewer_notes": "",
            })
    manifest = {
        "stage": "human_review_ready",
        "frozen_query_sha256": hashlib.sha256(query_path.read_bytes()).hexdigest(),
        "stage_b_labels_sha256": hashlib.sha256(label_path.read_bytes()).hexdigest(),
        "candidate_count": len(labels), "keep_count": len(kept), "reject_count": len(labels) - len(kept),
        "review_file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
