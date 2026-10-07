# -*- coding: utf-8 -*-
"""校验人工审核前后的知识召回 v2 数据结构与证据可追溯性。"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "eval" / "knowledge" / "v2" / "knowledge_retrieval_candidates.jsonl"


def validate(path: Path) -> tuple[list[str], Counter[str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    problems: list[str] = []
    ids: set[str] = set()
    for row in rows:
        case_id = str(row.get("id", "<missing>"))
        if case_id in ids:
            problems.append(f"{case_id}: id 重复")
        ids.add(case_id)
        if row.get("split") != "candidate" and row.get("label_status") == "pending_human_review":
            problems.append(f"{case_id}: 未审批候选不能进入正式 split")
        relevant = row.get("relevant")
        evidence = row.get("evidence")
        grades = row.get("graded_relevance")
        hard_negatives = row.get("hard_negatives")
        if not isinstance(relevant, list) or not isinstance(evidence, list) or not isinstance(grades, dict):
            problems.append(f"{case_id}: relevant/evidence/graded_relevance 结构非法")
            continue
        if not isinstance(hard_negatives, list) or (not hard_negatives and not row.get("expected_unanswerable")):
            problems.append(f"{case_id}: 缺少 hard negative")
        if row.get("expected_unanswerable") and (relevant or evidence):
            problems.append(f"{case_id}: 不可回答题不能包含正例或证据")
        if not row.get("expected_unanswerable") and (not relevant or not evidence):
            problems.append(f"{case_id}: 可回答题缺少正例或证据")
        for source in relevant:
            if grades.get(source) != 3:
                problems.append(f"{case_id}: 金标 {source} 必须为 grade=3")
        for source, grade in grades.items():
            if type(grade) is not int or not 0 <= grade <= 3:
                problems.append(f"{case_id}: {source} grade 必须是 0..3 整数")
            if not (PROJECT_ROOT / "eval" / "knowledge" / "corpus" / source).is_file():
                problems.append(f"{case_id}: graded 文档不存在：{source}")
        for item in evidence:
            source = item.get("source")
            quote = item.get("quote")
            source_path = PROJECT_ROOT / "eval" / "knowledge" / "corpus" / str(source)
            if source not in relevant:
                problems.append(f"{case_id}: evidence 来源不在 relevant：{source}")
            if not source_path.is_file():
                problems.append(f"{case_id}: evidence 文档不存在：{source}")
            elif not isinstance(quote, str) or quote not in source_path.read_text(encoding="utf-8"):
                problems.append(f"{case_id}: evidence 原文无法逐字回指：{source}")
    return problems, Counter(str(row.get("kind")) for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="校验知识召回 v2 候选集")
    parser.add_argument("dataset", nargs="?", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    path = args.dataset if args.dataset.is_absolute() else PROJECT_ROOT / args.dataset
    problems, kinds = validate(path)
    print(json.dumps({"dataset": str(path), "cases": sum(kinds.values()), "kinds": kinds, "problems": problems}, ensure_ascii=False))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
