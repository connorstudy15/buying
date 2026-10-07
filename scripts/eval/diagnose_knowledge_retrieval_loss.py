"""Diagnose gold evidence that is absent from the raw knowledge candidate pool."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.infrastructure.rag.category_knowledge import (  # noqa: E402
    EVALUATION_KNOWLEDGE_DIR,
    build_evaluation_knowledge_base,
    verify_evaluation_knowledge_base,
)
from app.infrastructure.rag.knowledge_retrieval import retrieve_knowledge_candidates  # noqa: E402
from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.knowledge_evidence import matched_evidence_ids  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Diagnose knowledge retrieval loss at a deeper candidate depth")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--repetition", type=int, default=2)
    parser.add_argument("--depth", type=int, default=80)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    cases = {row["id"]: row for row in read_jsonl(args.dataset)}
    experiment = json.loads(args.experiment.read_text(encoding="utf-8"))
    run = experiment["runs"][args.repetition - 1]
    observations = run["decompose_per_need_rerank"]["observations"]
    failing = [row for row in observations if row.get("retrieval_loss_evidence_ids")]

    knowledge_base = build_evaluation_knowledge_base(load_settings())
    await verify_evaluation_knowledge_base(knowledge_base, EVALUATION_KNOWLEDGE_DIR)
    results: list[dict] = []
    for observation in failing:
        case = cases[observation["case_id"]]
        evidence = case.get("evidence_ground_truth") or []
        lost = set(observation["retrieval_loss_evidence_ids"])
        variants = observation.get("query_variants") or [{
            "query_id": "original", "information_need_id": "overall", "text": case["query"],
        }]
        variant_results = []
        best_rank: dict[str, int] = {}
        for variant in variants:
            candidates = await retrieve_knowledge_candidates(
                knowledge_base,
                variant["text"],
                args.depth,
                target_limit=3,
                query_id=variant.get("query_id", "diagnostic"),
                information_need_id=variant.get("information_need_id", "overall"),
            )
            matched, ranks = matched_evidence_ids([candidate.item for candidate in candidates], evidence)
            for evidence_id, rank in ranks.items():
                if evidence_id in lost:
                    best_rank[evidence_id] = min(rank, best_rank.get(evidence_id, rank))
            variant_results.append({
                "query_id": variant.get("query_id"),
                "information_need_id": variant.get("information_need_id"),
                "text": variant["text"],
                "candidate_count": len(candidates),
                "matched_lost_evidence_ids": [eid for eid in matched if eid in lost],
                "lost_evidence_ranks": {eid: rank for eid, rank in ranks.items() if eid in lost},
            })
        unresolved = sorted(lost - set(best_rank))
        if best_rank and not unresolved:
            diagnosis = "depth_ceiling"
        elif len(variants) == 1 and case.get("primary_kind") in {
            "cross_evidence", "implicit_constraint", "implicit_constraint_multi_hop",
        }:
            diagnosis = "decomposition_gap"
        else:
            diagnosis = "semantic_or_query_mismatch"
        results.append({
            "case_id": observation["case_id"],
            "query": case["query"],
            "primary_kind": case.get("primary_kind"),
            "processor_plan_mode": observation.get("processor_plan_mode"),
            "lost_evidence_ids": sorted(lost),
            "best_rank_at_depth": best_rank,
            "unresolved_at_depth": unresolved,
            "diagnosis": diagnosis,
            "variants": variant_results,
        })

    payload = {
        "schema_version": "knowledge-retrieval-loss-diagnosis-v1",
        "dataset": str(args.dataset),
        "experiment": str(args.experiment),
        "repetition": args.repetition,
        "diagnostic_depth": args.depth,
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "case_count": len(results),
        "diagnoses": {
            name: sum(row["diagnosis"] == name for row in results)
            for name in sorted({row["diagnosis"] for row in results})
        },
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
