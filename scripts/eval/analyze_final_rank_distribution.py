"""Analyze where gold evidence lands after RRF but before final Top-K selection."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def rank_bucket(rank: int | None) -> str:
    if rank is None:
        return "missing"
    if rank <= 3:
        return "rank_1_3"
    if rank <= 5:
        return "rank_4_5"
    if rank <= 10:
        return "rank_6_10"
    return "rank_gt_10"


def ranking_score(entry: dict) -> float | None:
    value = entry.get("ranking_score", entry.get("rrf_score"))
    return float(value) if value is not None else None


def analyze(payload: dict, strategy: str, ranking_companion: dict | None = None) -> dict:
    details: list[dict] = []
    coverage_loss_cases: set[str] = set()
    same_document_cases: set[str] = set()
    same_section_cases: set[str] = set()
    selection_override_cases: set[str] = set()
    capacity_exceeded_cases: set[str] = set()
    mode_counts: Counter = Counter()
    companion_rows: dict[tuple[int, str], dict] = {}
    if ranking_companion is not None:
        for companion_run in ranking_companion["runs"]:
            for row in companion_run[strategy]["observations"]:
                companion_rows[(int(companion_run["repetition"]), str(row["case_id"]))] = row
    hydrated_cases: set[str] = set()
    for run in payload["runs"]:
        for observation in run[strategy]["observations"]:
            lost = observation.get("top_k_truncation_loss_evidence_ids") or []
            if not lost:
                continue
            ranking = observation.get("post_fusion_ranking") or []
            ranks = observation.get("post_fusion_evidence_ranks") or {}
            if not ranking and observation.get("effective_plan_mode") != "DECOMPOSE":
                companion = companion_rows.get((int(run["repetition"]), str(observation["case_id"])))
                if companion is not None:
                    companion_ranks = companion.get("post_fusion_evidence_ranks") or {}
                    # 伴随运行只用于补旧 DIRECT 的分数快照；gold 名次必须一致，避免混入模型波动。
                    if all(companion_ranks.get(evidence_id) == ranks.get(evidence_id) for evidence_id in lost):
                        ranking = companion.get("post_fusion_ranking") or []
                        hydrated_cases.add(str(observation["case_id"]))
            selected = [entry for entry in ranking if entry.get("selected")]
            if any(int(entry.get("rank") or 0) > 3 for entry in selected):
                selection_override_cases.add(str(observation["case_id"]))
            if len(set(observation.get("gold_evidence_ids") or [])) > 3:
                capacity_exceeded_cases.add(str(observation["case_id"]))
            documents = Counter(entry.get("document_id") for entry in selected)
            sections = Counter(
                (entry.get("document_id"), entry.get("section"))
                for entry in selected if entry.get("section")
            )
            if any(count > 1 for count in documents.values()):
                same_document_cases.add(observation["case_id"])
            if any(count > 1 for count in sections.values()):
                same_section_cases.add(observation["case_id"])
            pre = observation.get("pre_fusion_information_need_coverage")
            post = observation.get("post_fusion_information_need_coverage")
            if pre is not None and post is not None and pre > post:
                coverage_loss_cases.add(observation["case_id"])
            cutoff_score = ranking_score(ranking[2]) if len(ranking) >= 3 else None
            for evidence_id in lost:
                mode_counts[str(observation.get("effective_plan_mode") or observation.get("retrieval_mode"))] += 1
                rank = int(ranks[evidence_id]) if evidence_id in ranks else None
                entry = next(
                    (candidate for candidate in ranking if evidence_id in candidate.get("matched_gold_evidence_ids", [])),
                    None,
                )
                score = ranking_score(entry) if entry is not None else None
                details.append({
                    "repetition": run["repetition"],
                    "case_id": observation["case_id"],
                    "evidence_id": evidence_id,
                    "rank": rank,
                    "rank_bucket": rank_bucket(rank),
                    "ranking_score": score,
                    "ranking_score_type": (
                        entry.get("ranking_score_type") or ("rrf" if entry.get("rrf_score") is not None else None)
                        if entry is not None else None
                    ),
                    "rank3_cutoff_score": cutoff_score,
                    "score_gap_to_rank3": (
                        round(cutoff_score - score, 10)
                        if cutoff_score is not None and score is not None else None
                    ),
                    "pre_need_coverage": pre,
                    "post_need_coverage": post,
                    "selected_documents": [candidate.get("document_id") for candidate in selected],
                    "selected_sections": [candidate.get("section") for candidate in selected],
                })
    buckets = Counter(item["rank_bucket"] for item in details)
    gaps_by_type: dict[str, list[float]] = {}
    for item in details:
        if item["score_gap_to_rank3"] is not None and item["ranking_score_type"]:
            gaps_by_type.setdefault(item["ranking_score_type"], []).append(item["score_gap_to_rank3"])
    return {
        "schema_version": "final-rank-distribution-v1",
        "experiment": payload.get("evaluation_run_id"),
        "strategy": strategy,
        "top_k_loss_evidence_observations": len(details),
        "rank_buckets": dict(buckets),
        "rank_bucket_rates": {
            key: round(value / len(details), 4) if details else 0.0
            for key, value in buckets.items()
        },
        "score_gap_to_rank3_by_type": {
            score_type: {
                "count": len(values),
                "median": statistics.median(values),
                "p95": sorted(values)[round((len(values) - 1) * 0.95)],
            }
            for score_type, values in gaps_by_type.items()
        },
        "loss_evidence_by_effective_mode": dict(mode_counts),
        "information_need_coverage_loss_cases": sorted(coverage_loss_cases),
        "selected_same_document_cases": sorted(same_document_cases),
        "selected_same_section_cases": sorted(same_section_cases),
        "selection_override_cases": sorted(selection_override_cases),
        "top3_capacity_exceeded_cases": sorted(capacity_exceeded_cases),
        "ranking_hydrated_from_companion_cases": sorted(hydrated_cases),
        "details": details,
    }


def render(result: dict) -> str:
    total = result["top_k_loss_evidence_observations"]
    buckets = result["rank_buckets"]
    lines = [
        "# Final Rank Distribution Diagnostic", "",
        f"- Strategy: `{result['strategy']}`",
        f"- Top-K loss evidence observations: {total}", "",
        "| Fusion rank | Count | Rate |", "|---|---:|---:|",
    ]
    labels = (("rank_1_3", "Rank 1-3"), ("rank_4_5", "Rank 4-5"),
              ("rank_6_10", "Rank 6-10"), ("rank_gt_10", "Rank >10"), ("missing", "Missing"))
    for key, label in labels:
        count = buckets.get(key, 0)
        lines.append(f"| {label} | {count} | {(count / total if total else 0):.2%} |")
    lines += [
        "", "## Selection diagnostics", "",
        f"- Information-need coverage lost: `{','.join(result['information_need_coverage_loss_cases']) or 'none'}`",
        f"- Final selection contains repeated documents: `{','.join(result['selected_same_document_cases']) or 'none'}`",
        f"- Final selection contains repeated document sections: `{','.join(result['selected_same_section_cases']) or 'none'}`",
        f"- DIRECT ranking hydrated from matched companion pass: `{','.join(result['ranking_hydrated_from_companion_cases']) or 'none'}`",
        f"- Final selector chose candidates below raw rank 3: `{','.join(result['selection_override_cases']) or 'none'}`",
        f"- Gold evidence count exceeds Top-3 capacity: `{','.join(result['top3_capacity_exceeded_cases']) or 'none'}`",
        f"- Lost evidence by effective mode: `{result['loss_evidence_by_effective_mode']}`",
        f"- Score gap to rank 3 (kept separate by score type): `{result['score_gap_to_rank3_by_type']}`",
        "", "## Lost evidence", "",
        "| Run | Case | Rank | Bucket | Score type | Gap to rank 3 |", "|---:|---|---:|---|---|---:|",
    ]
    for item in result["details"]:
        lines.append(
            f"| {item['repetition']} | {item['case_id']} | {item['rank'] or 'n/a'} | "
            f"{item['rank_bucket']} | {item['ranking_score_type']} | {item['score_gap_to_rank3']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--strategy", default="decompose_per_need_rerank")
    parser.add_argument(
        "--ranking-companion", type=Path,
        help="可选：为旧 DIRECT 结果补完整排序快照；仅在丢失 gold 的名次完全一致时采用",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.experiment.read_text(encoding="utf-8"))
    companion = (
        json.loads(args.ranking_companion.read_text(encoding="utf-8"))
        if args.ranking_companion else None
    )
    result = analyze(payload, args.strategy, companion)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "final-rank-distribution.json"
    report_path = args.output_dir / "final-rank-distribution.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render(result), encoding="utf-8")
    print(json.dumps({
        "rank_buckets": result["rank_buckets"],
        "coverage_loss_cases": result["information_need_coverage_loss_cases"],
        "same_document_cases": result["selected_same_document_cases"],
        "same_section_cases": result["selected_same_section_cases"],
        "report": str(report_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
