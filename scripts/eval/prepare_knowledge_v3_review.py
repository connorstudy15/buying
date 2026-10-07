# -*- coding: utf-8 -*-
"""校验阶段 B 标注，并只把 keep 条目导出给人工审批。"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.infrastructure.settings import PROJECT_ROOT


ROOT = PROJECT_ROOT / "eval" / "knowledge" / "v3"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def main() -> None:
    query_paths = [ROOT / "blind_queries.jsonl"]
    label_paths = [ROOT / "stage_b_labels.jsonl"]
    human_multihop_queries = ROOT / "human_multihop_queries.jsonl"
    human_multihop_labels = ROOT / "stage_b_human_multihop_labels.jsonl"
    machine_multihop_queries = ROOT / "blind_multihop_queries.jsonl"
    machine_multihop_labels = ROOT / "stage_b_multihop_labels.jsonl"
    # 人工题存在时替换机器增补题；机器文件仍保留审计，但不得重复进入审批表。
    if human_multihop_queries.exists() or human_multihop_labels.exists():
        if not human_multihop_queries.exists() or not human_multihop_labels.exists():
            raise ValueError("人工多跳 Query 与阶段 B 标注必须成对存在")
        query_paths.append(human_multihop_queries)
        label_paths.append(human_multihop_labels)
    elif machine_multihop_queries.exists() or machine_multihop_labels.exists():
        if not machine_multihop_queries.exists() or not machine_multihop_labels.exists():
            raise ValueError("机器多跳 Query 与阶段 B 标注必须成对存在")
        query_paths.append(machine_multihop_queries)
        label_paths.append(machine_multihop_labels)
    output = ROOT / "human_review.csv"
    query_rows = [row for path in query_paths for row in load_jsonl(path)]
    label_rows = [row for path in label_paths for row in load_jsonl(path)]
    queries = {row["id"]: row for row in query_rows}
    labels = label_rows
    problems: list[str] = []
    if len(queries) != len(query_rows):
        problems.append("冻结 Query 存在重复 id")
    if len({row["id"] for row in labels}) != len(labels):
        problems.append("阶段 B 标注存在重复 id")
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
        derived_relevant = [source for source, grade in grades.items() if isinstance(grade, int) and grade >= 2]
        if relevant != derived_relevant:
            problems.append(
                f"{case_id}: relevant 必须严格由 graded_relevance>=2 派生；"
                f"期望 {derived_relevant}，实际 {relevant}",
            )
        if row.get("label_decision") == "keep" and row.get("answerability") != "unanswerable":
            if not relevant or not evidence:
                problems.append(f"{case_id}: 可回答 keep 条目缺少 relevant/evidence")
        for source, grade in grades.items():
            if type(grade) is not int or not 0 <= grade <= 3:
                problems.append(f"{case_id}: {source} grade 非 0..3 整数")
        for item in evidence:
            source_path = PROJECT_ROOT / "eval" / "knowledge" / "corpus" / item["source"]
            if not source_path.is_file() or item["quote"] not in source_path.read_text(encoding="utf-8"):
                problems.append(f"{case_id}: evidence 无法逐字回指 {item['source']}")
        hops = row.get("hops") or []
        if row.get("original_kind") in {"sequential_multi_hop", "implicit_constraint_multi_hop"}:
            if len(hops) < 2:
                problems.append(f"{case_id}: sequential_multi_hop 至少需要两跳")
            known_hops: set[str] = set()
            for hop in hops:
                hop_id = hop.get("id")
                if not hop_id or hop_id in known_hops:
                    problems.append(f"{case_id}: hop id 缺失或重复")
                    continue
                dependencies = hop.get("depends_on") or []
                if any(dependency not in known_hops for dependency in dependencies):
                    problems.append(f"{case_id}: {hop_id} 依赖未定义的前序 hop")
                known_hops.add(hop_id)
            if not row.get("must_cover") or not row.get("forbidden_inferences"):
                problems.append(f"{case_id}: 多跳标注缺少覆盖点或禁止推断")
    if problems:
        raise ValueError("阶段 B 校验失败：\n- " + "\n- ".join(problems))

    kept = [row for row in labels if row["label_decision"] == "keep"]
    columns = ["id", "decision", "original_kind", "answerability", "query", "dependency_hint",
               "relevant", "evidence", "graded_relevance", "hard_negatives", "hops", "must_cover",
               "forbidden_inferences", "label_reason", "label_confidence",
               "corrected_relevant", "corrected_grades", "corrected_evidence", "reviewer_notes"]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in kept:
            writer.writerow({
                "id": row["id"], "decision": "", "original_kind": row["original_kind"],
                "answerability": row["answerability"], "query": row["query"],
                "dependency_hint": queries[row["id"]].get("dependency_hint", ""),
                "relevant": " | ".join(row.get("relevant") or []),
                "evidence": " || ".join(f"[{item['source']}][{item['section']}] {item['quote']}" for item in row.get("evidence") or []),
                "graded_relevance": " | ".join(f"{source}={grade}" for source, grade in row.get("graded_relevance", {}).items()),
                "hard_negatives": " || ".join(f"[{item['source']}][{item['type']}] {item['reason']}" for item in row.get("hard_negatives") or []),
                "hops": json.dumps(row.get("hops") or [], ensure_ascii=False),
                "must_cover": " | ".join(row.get("must_cover") or []),
                "forbidden_inferences": " | ".join(row.get("forbidden_inferences") or []),
                "label_reason": row["label_reason"], "label_confidence": row["label_confidence"],
                "corrected_relevant": "", "corrected_grades": "", "corrected_evidence": "", "reviewer_notes": "",
            })
    manifest = {
        "stage": "human_review_ready",
        "frozen_query_sources": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in query_paths
        },
        "stage_b_label_sources": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in label_paths
        },
        "frozen_query_sha256": hashlib.sha256(b"".join(path.read_bytes() for path in query_paths)).hexdigest(),
        "stage_b_labels_sha256": hashlib.sha256(b"".join(path.read_bytes() for path in label_paths)).hexdigest(),
        "candidate_count": len(labels), "keep_count": len(kept), "reject_count": len(labels) - len(kept),
        "review_file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
