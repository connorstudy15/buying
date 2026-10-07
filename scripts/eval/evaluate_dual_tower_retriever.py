# -*- coding: utf-8 -*-
"""Experiment D Stage 1: compare two retriever ranking artifacts, without running Candidate B."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEPTHS = (5, 10, 24, 50)
REQUIRED_BUCKETS = {
    "DIRECT", "DECOMPOSE_SUBQUERY", "single_evidence", "multi_evidence",
    "implicit_cross_domain", "domain_rule",
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _first_rank(candidates: list[dict], evidence_id: str, depth: int) -> int | None:
    return next((rank for rank, item in enumerate(candidates[:depth], 1)
                 if evidence_id in set(map(str, item.get("evidence_ids") or []))), None)


def _first_positive_rank(candidates: list[dict], gold: set[str], depth: int) -> int | None:
    return next((rank for rank, item in enumerate(candidates[:depth], 1)
                 if gold & set(map(str, item.get("evidence_ids") or []))), None)


def _first_hard_negative_rank(candidates: list[dict], query: dict, depth: int) -> int | None:
    ids = set(map(str, query.get("hard_negative_candidate_ids") or []))
    evidence = set(map(str, query.get("hard_negative_evidence_ids") or []))
    sources = set(map(str, query.get("hard_negative_sources") or []))
    return next((rank for rank, item in enumerate(candidates[:depth], 1) if (
        str(item.get("candidate_id") or "") in ids
        or bool(evidence & set(map(str, item.get("evidence_ids") or [])))
        or str(item.get("source") or "") in sources
    )), None)


def validate_artifacts(queries: list[dict], rankings: list[dict], label: str) -> dict[str, dict]:
    query_ids = [str(row.get("query_id") or "") for row in queries]
    if not all(query_ids) or len(query_ids) != len(set(query_ids)):
        raise ValueError("frozen query artifact has missing or duplicate query_id")
    rows = {str(row.get("query_id") or ""): row for row in rankings}
    if len(rows) != len(rankings) or "" in rows:
        raise ValueError(f"{label}: missing or duplicate query_id")
    missing, extra = sorted(set(query_ids) - set(rows)), sorted(set(rows) - set(query_ids))
    if missing or extra:
        raise ValueError(f"{label}: query mismatch missing={missing} extra={extra}")
    for query_id, row in rows.items():
        candidates = row.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError(f"{label}/{query_id}: candidates must be a list")
        candidate_ids = [str(item.get("candidate_id") or "") for item in candidates]
        if not all(candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError(f"{label}/{query_id}: candidate_id missing or duplicated")
        if any("score" not in item or "source" not in item for item in candidates):
            raise ValueError(f"{label}/{query_id}: every candidate needs score and source")
    return rows


def _query_observation(query: dict, candidates: list[dict], max_depth: int) -> dict:
    gold = list(map(str, query.get("gold_evidence_ids") or []))
    if not gold:
        raise ValueError(f"{query.get('query_id')}: gold_evidence_ids cannot be empty")
    gold_set = set(gold)
    ranks = {evidence_id: _first_rank(candidates, evidence_id, max_depth) for evidence_id in gold}
    recalls = {
        depth: sum(rank is not None and rank <= depth for rank in ranks.values()) / len(gold)
        for depth in DEPTHS
    }
    first_positive = _first_positive_rank(candidates, gold_set, max_depth)
    hard_negative = _first_hard_negative_rank(candidates, query, max_depth)
    hard_annotated = any(query.get(field) for field in (
        "hard_negative_candidate_ids", "hard_negative_evidence_ids", "hard_negative_sources",
    ))
    score_by_evidence = {}
    for evidence_id in gold:
        match = next((item for item in candidates[:max_depth]
                      if evidence_id in set(map(str, item.get("evidence_ids") or []))), None)
        score_by_evidence[evidence_id] = float(match["score"]) if match is not None else None
    return {
        "query_id": str(query["query_id"]),
        "case_id": str(query.get("case_id") or query["query_id"]),
        "buckets": list(dict.fromkeys(map(str, query.get("buckets") or []))),
        "gold_ranks": ranks,
        "gold_scores": score_by_evidence,
        "recalls": recalls,
        "reciprocal_rank": 1 / first_positive if first_positive else 0.0,
        "first_positive_rank": first_positive,
        "first_hard_negative_rank": hard_negative,
        "hard_negative_annotated": hard_annotated,
        "hard_negative_outranks_positive": bool(
            hard_annotated and hard_negative is not None
            and (first_positive is None or hard_negative < first_positive)
        ),
    }


def _aggregate(observations: Iterable[dict], max_depth: int) -> dict:
    observations = list(observations)
    gold_ranks = [rank for row in observations for rank in row["gold_ranks"].values()]
    censored = [rank if rank is not None else max_depth + 1 for rank in gold_ranks]
    hard_rows = [row for row in observations if row["hard_negative_annotated"]]
    return {
        "query_count": len(observations),
        **{
            f"recall_at_{depth}": (
                sum(row["recalls"][depth] for row in observations) / len(observations)
                if observations else None
            )
            for depth in DEPTHS
        },
        "mrr": (
            sum(row["reciprocal_rank"] for row in observations) / len(observations)
            if observations else None
        ),
        "gold_mean_rank_censored_at_51": statistics.mean(censored) if censored else None,
        "gold_median_rank_censored_at_51": statistics.median(censored) if censored else None,
        "retrieval_loss_gold_count_at_50": sum(rank is None for rank in gold_ranks),
        "retrieval_loss_query_count_at_50": sum(
            any(rank is None for rank in row["gold_ranks"].values()) for row in observations
        ),
        "hard_negative_outrank_positive_rate": (
            sum(row["hard_negative_outranks_positive"] for row in hard_rows) / len(hard_rows)
            if hard_rows else None
        ),
        "hard_negative_annotated_query_count": len(hard_rows),
    }


def evaluate(queries: list[dict], baseline: list[dict], dual: list[dict], max_depth: int = 50) -> dict:
    if max_depth < max(DEPTHS):
        raise ValueError("max_depth must be at least 50")
    baseline_rows = validate_artifacts(queries, baseline, "baseline")
    dual_rows = validate_artifacts(queries, dual, "dual_tower")
    present_buckets = {str(bucket) for query in queries for bucket in (query.get("buckets") or [])}
    missing_buckets = sorted(REQUIRED_BUCKETS - present_buckets)
    if missing_buckets:
        raise ValueError(f"frozen query artifact misses required buckets: {missing_buckets}")
    base_obs, dual_obs, movements = [], [], []
    bucket_names = set(REQUIRED_BUCKETS)
    for query in queries:
        query_id = str(query["query_id"])
        buckets = set(map(str, query.get("buckets") or []))
        bucket_names.update(buckets)
        b = _query_observation(query, baseline_rows[query_id]["candidates"], max_depth)
        d = _query_observation(query, dual_rows[query_id]["candidates"], max_depth)
        base_obs.append(b)
        dual_obs.append(d)
        for evidence_id in map(str, query["gold_evidence_ids"]):
            old_rank, new_rank = b["gold_ranks"][evidence_id], d["gold_ranks"][evidence_id]
            old_effective = old_rank if old_rank is not None else max_depth + 1
            new_effective = new_rank if new_rank is not None else max_depth + 1
            movements.append({
                "query_id": query_id, "case_id": b["case_id"],
                "information_need_id": str(query.get("information_need_id") or ""),
                "evidence_id": evidence_id,
                "baseline_rank": old_rank, "dual_tower_rank": new_rank,
                "rank_delta": old_effective - new_effective,
                # v1 aliases kept for existing downstream readers.
                "old_rank": old_rank,
                "delta": old_effective - new_effective,
                **{
                    f"baseline_hit_at_{depth}": old_rank is not None and old_rank <= depth
                    for depth in DEPTHS
                },
                **{
                    f"dual_hit_at_{depth}": new_rank is not None and new_rank <= depth
                    for depth in DEPTHS
                },
                "baseline_score": b["gold_scores"][evidence_id],
                "dual_tower_score": d["gold_scores"][evidence_id],
                "old_score": b["gold_scores"][evidence_id],
                "new_score": d["gold_scores"][evidence_id],
                "baseline_first_hard_negative_rank": b["first_hard_negative_rank"],
                "dual_tower_first_hard_negative_rank": d["first_hard_negative_rank"],
                "root_cause": str(query.get("root_cause") or "unspecified"),
                "label_status": str(query.get("label_status") or "unspecified"),
                "acceptance_scope": str(query.get("acceptance_scope") or "primary_gate"),
                "buckets": b["buckets"],
            })
    base_by_id = {row["query_id"]: row for row in base_obs}
    dual_by_id = {row["query_id"]: row for row in dual_obs}
    bucket_metrics = {}
    for bucket in sorted(bucket_names):
        ids = [row["query_id"] for row in base_obs if bucket in row["buckets"]]
        if ids:
            bucket_metrics[bucket] = {
                "baseline": _aggregate((base_by_id[item] for item in ids), max_depth),
                "dual_tower": _aggregate((dual_by_id[item] for item in ids), max_depth),
            }
    baseline_metrics = _aggregate(base_obs, max_depth)
    dual_metrics = _aggregate(dual_obs, max_depth)
    primary_ids = [
        str(query["query_id"]) for query in queries
        if str(query.get("acceptance_scope") or "primary_gate") == "primary_gate"
    ]
    primary_gate_metrics = {
        "baseline": _aggregate((base_by_id[item] for item in primary_ids), max_depth),
        "dual_tower": _aggregate((dual_by_id[item] for item in primary_ids), max_depth),
    }
    query_outcomes = {"win": [], "tie": [], "loss": []}
    for query_id in base_by_id:
        delta = dual_by_id[query_id]["recalls"][24] - base_by_id[query_id]["recalls"][24]
        query_outcomes["win" if delta > 0 else "loss" if delta < 0 else "tie"].append(query_id)
    movement_summary = {
        "gold_rank_improved": sum(item["rank_delta"] > 0 for item in movements),
        "gold_rank_unchanged": sum(item["rank_delta"] == 0 for item in movements),
        "gold_rank_worsened": sum(item["rank_delta"] < 0 for item in movements),
        "query_level_win": len(query_outcomes["win"]),
        "query_level_tie": len(query_outcomes["tie"]),
        "query_level_loss": len(query_outcomes["loss"]),
        "query_level_ids": query_outcomes,
    }
    strict_regressions = [
        query_id for query_id in base_by_id
        if base_by_id[query_id]["recalls"][24] > dual_by_id[query_id]["recalls"][24]
    ]
    simple_regressions = [
        query_id for query_id in base_by_id
        if "single_evidence" in base_by_id[query_id]["buckets"]
        and base_by_id[query_id]["recalls"][5] == 1.0
        and dual_by_id[query_id]["recalls"][5] < 1.0
    ]
    return {
        "schema_version": "dual-tower-retriever-eval-v1",
        "metric_contract": {
            "rank_missing_value": max_depth + 1,
            "retrieval_loss_definition": "gold evidence absent from Top-50",
            "recall_aggregation": "macro average across query instances",
        },
        "baseline": baseline_metrics,
        "dual_tower": dual_metrics,
        "delta": {
            key: (dual_metrics[key] - baseline_metrics[key])
            for key in ("recall_at_5", "recall_at_10", "recall_at_24", "recall_at_50", "mrr")
        },
        "bucket_metrics": bucket_metrics,
        "primary_gate": primary_gate_metrics,
        "rank_movement_summary": movement_summary,
        "strict_regression_query_ids_at_24": strict_regressions,
        "simple_case_regression_query_ids_at_5": simple_regressions,
        "rank_movements": movements,
        "observations": {"baseline": base_obs, "dual_tower": dual_obs},
    }


def render(result: dict) -> str:
    lines = ["# Dual-Tower Experiment D — Retriever-only", "", "## Overall", "",
             "| Metric | Baseline | Dual Tower | Delta |", "|---|---:|---:|---:|"]
    for key, label in (("recall_at_5", "Recall@5"), ("recall_at_10", "Recall@10"),
                       ("recall_at_24", "Recall@24"), ("recall_at_50", "Recall@50"),
                       ("mrr", "MRR")):
        lines.append(f"| {label} | {result['baseline'][key]:.4f} | {result['dual_tower'][key]:.4f} | {result['delta'][key]:+.4f} |")
    for key, label in (("gold_mean_rank_censored_at_51", "Gold Mean Rank (miss=51)"),
                       ("gold_median_rank_censored_at_51", "Gold Median Rank (miss=51)"),
                       ("retrieval_loss_gold_count_at_50", "Retrieval Loss gold count"),
                       ("hard_negative_outrank_positive_rate", "Hard-negative outrank positive")):
        b, d = result["baseline"][key], result["dual_tower"][key]
        lines.append(f"| {label} | {b if b is not None else 'n/a'} | {d if d is not None else 'n/a'} | n/a |")
    lines += ["", "## Buckets", ""]
    for bucket, values in result["bucket_metrics"].items():
        lines.append(
            f"- `{bucket}`：Recall@24 {values['baseline']['recall_at_24']:.4f} → "
            f"{values['dual_tower']['recall_at_24']:.4f}；MRR {values['baseline']['mrr']:.4f} → {values['dual_tower']['mrr']:.4f}。"
        )
    lines += ["", "## Rank movement", "", "| Case | Evidence | Old | Dual | Delta | Old score | New score |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for item in sorted(result["rank_movements"], key=lambda row: (-row["rank_delta"], row["case_id"], row["evidence_id"])):
        lines.append(
            f"| {item['case_id']} | {item['evidence_id']} | {item['baseline_rank'] or '>50'} | "
            f"{item['dual_tower_rank'] or '>50'} | {item['rank_delta']:+d} | "
            f"{item['baseline_score'] if item['baseline_score'] is not None else 'n/a'} | "
            f"{item['dual_tower_score'] if item['dual_tower_score'] is not None else 'n/a'} |"
        )
    lines += ["", "## Regression", "",
              f"- Strict regression @24：`{','.join(result['strict_regression_query_ids_at_24']) or 'none'}`",
              f"- Easy single-evidence regression @5：`{','.join(result['simple_case_regression_query_ids_at_5']) or 'none'}`"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment D retriever-only evaluator")
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--dual-tower", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(load_jsonl(args.queries), load_jsonl(args.baseline), load_jsonl(args.dual_tower))
    result["created_at"] = datetime.now().astimezone().isoformat()
    result["inputs"] = {"queries": str(args.queries), "baseline": str(args.baseline), "dual_tower": str(args.dual_tower)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "retriever-only.json"
    report_path = args.output_dir / "retriever-only.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render(result), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "report": str(report_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
