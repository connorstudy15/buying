# -*- coding: utf-8 -*-
"""Validate train/validation/frozen-test separation for Experiment D."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalized_query(value: str) -> str:
    return "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]+", str(value).casefold()))


def validate_splits(train: list[dict], validation: list[dict], frozen: list[dict], *, strict_evidence: bool = True) -> dict:
    issues: list[str] = []
    for split_name, rows in (("train", train), ("validation", validation)):
        ids = [str(row.get("sample_id") or "") for row in rows]
        if not all(ids) or len(ids) != len(set(ids)):
            issues.append(f"{split_name}: sample_id missing or duplicated")
        for row in rows:
            if row.get("split") != split_name:
                issues.append(f"{split_name}/{row.get('sample_id')}: split field mismatch")
            positive = row.get("positive") or {}
            negatives = row.get("hard_negatives") or []
            if not row.get("query") or not positive.get("evidence_id") or not positive.get("text"):
                issues.append(f"{split_name}/{row.get('sample_id')}: query/positive incomplete")
            if not negatives:
                issues.append(f"{split_name}/{row.get('sample_id')}: at least one hard negative required")
            if positive.get("evidence_id") in {item.get("evidence_id") for item in negatives}:
                issues.append(f"{split_name}/{row.get('sample_id')}: positive also appears as hard negative")
            provenance = row.get("provenance") or {}
            if provenance.get("benchmark_derived") is not False:
                issues.append(f"{split_name}/{row.get('sample_id')}: benchmark_derived must be false")
            if provenance.get("review_status") not in {"human_approved", "llm_then_human_approved"}:
                issues.append(f"{split_name}/{row.get('sample_id')}: sample not approved")

    def query_set(rows):
        return {normalized_query(row.get("query") or "") for row in rows if row.get("query")}

    train_queries, validation_queries, frozen_queries = query_set(train), query_set(validation), query_set(frozen)
    if train_queries & validation_queries:
        issues.append("train/validation normalized query overlap")
    if train_queries & frozen_queries:
        issues.append("train/frozen normalized query overlap")
    if validation_queries & frozen_queries:
        issues.append("validation/frozen normalized query overlap")
    train_groups = {str(row.get("group_id") or "") for row in train if row.get("group_id")}
    validation_groups = {str(row.get("group_id") or "") for row in validation if row.get("group_id")}
    if train_groups & validation_groups:
        issues.append("train/validation group_id overlap")
    frozen_case_ids = {str(row.get("case_id") or "") for row in frozen if row.get("case_id")}
    for split_name, rows in (("train", train), ("validation", validation)):
        leaked = {str(row.get("case_id") or "") for row in rows if row.get("case_id")} & frozen_case_ids
        if leaked:
            issues.append(f"{split_name}/frozen case_id overlap: {sorted(leaked)}")
    if strict_evidence:
        frozen_evidence = {str(eid) for row in frozen for eid in (row.get("gold_evidence_ids") or [])}
        for split_name, rows in (("train", train), ("validation", validation)):
            leaked = {
                str((row.get("positive") or {}).get("evidence_id") or "") for row in rows
            } & frozen_evidence
            leaked.discard("")
            if leaked:
                issues.append(f"{split_name}/frozen positive evidence overlap: {sorted(leaked)}")
    if issues:
        raise ValueError("; ".join(issues))
    return {
        "status": "PASS", "train_count": len(train), "validation_count": len(validation),
        "frozen_count": len(frozen), "strict_evidence_holdout": strict_evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--allow-frozen-evidence-in-train", action="store_true")
    args = parser.parse_args()
    result = validate_splits(
        load_jsonl(args.train), load_jsonl(args.validation), load_jsonl(args.frozen),
        strict_evidence=not args.allow_frozen_evidence_in_train,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
