# -*- coding: utf-8 -*-
"""实验 B：只验证“按信息需求分别重排候选”的增量效果。"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.prompts.loader import load_prompts  # noqa: E402
from app.application.retrieval.query_processor import QueryProcessor  # noqa: E402
from app.infrastructure.llm import create_chat_model  # noqa: E402
from app.infrastructure.rag.category_knowledge import (  # noqa: E402
    bootstrap_category_knowledge,
    build_category_knowledge_base,
)
from app.infrastructure.rerank.http_reranker import HttpReranker  # noqa: E402
from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.run_category_recall import load_dataset, run_dataset  # noqa: E402
from scripts.eval.run_manifest import select_cases  # noqa: E402
from scripts.eval.run_query_decompose_ablation import (  # noqa: E402
    SharedPlanProcessor,
    _by_case,
    _metrics,
    _paired_changes,
)


class RetryingReranker:
    """实验期有限重试；全部失败就抛错，绝不把降级结果记成实验 B。"""

    def __init__(self, inner, attempts: int = 3):
        self._inner = inner
        self._attempts = attempts

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        last_error = None
        for attempt in range(1, self._attempts + 1):
            try:
                return await self._inner.rerank(query, documents)
            except Exception as err:  # noqa: BLE001 - 最终仍抛错，不静默降级
                last_error = err
                if attempt < self._attempts:
                    await asyncio.sleep(float(attempt))
        raise RuntimeError(f"per_need_reranker_failed_after_{self._attempts}_attempts") from last_error


def _median(runs, strategy: str, metric: str):
    values = [run[strategy]["metrics"].get(metric) for run in runs]
    present = [float(value) for value in values if value is not None]
    return statistics.median(present) if present else None


def _bucket_median(runs, strategy: str, bucket: str, metric: str):
    values = [run[strategy]["metrics"]["bucket_metrics"].get(bucket, {}).get(metric) for run in runs]
    present = [float(value) for value in values if value is not None]
    return statistics.median(present) if present else None


def _fmt(value):
    return "n/a" if value is None else f"{value:.4f}"


def _render(runs, dataset: Path, rrf_k: int, reranker_model: str) -> str:
    strategies = ("legacy", "decompose_rrf", "decompose_per_need_rerank")
    labels = {
        "legacy": "Legacy",
        "decompose_rrf": "实验 A：拆分+RRF",
        "decompose_per_need_rerank": "实验 B：按子问题重排+RRF",
    }
    lines = [
        "# Per-information-need Reranking 实验 B",
        "",
        f"- 数据集：`{dataset}`，每轮 {len(runs[0]['legacy']['observations'])} 题",
        f"- 重复次数：{len(runs)}；Top-K：3；RRF k：{rrf_k}",
        f"- 重排模型：`{reranker_model}`",
        "- 同一轮两组复用相同查询计划和相同候选池。",
        "- 唯一变化：实验 B 用每条子查询分别重排自己的候选；原问题候选不做全局重排。",
        "",
        "## 总体指标（多轮中位数）",
        "",
        "| 指标 | Legacy | 实验 A | 实验 B | B - A |",
        "|---|---:|---:|---:|---:|",
    ]
    metrics = (
        ("Document Recall@3", "document_recall_at_3"),
        ("Evidence Recall@3", "evidence_recall_at_3"),
        ("All-Evidence Recall@3", "all_evidence_recall_at_3"),
        ("Hard-negative hit rate", "hard_negative_hit_rate"),
        ("Hard negative above positive", "hard_negative_above_positive_rate"),
        ("Fusion information-need loss", "fusion_information_need_loss"),
        ("Unanswerable accuracy", "unanswerable_accuracy"),
        ("P50 latency (ms)", "latency_p50_ms"),
        ("P95 latency (ms)", "latency_p95_ms"),
    )
    for label, metric in metrics:
        values = {strategy: _median(runs, strategy, metric) for strategy in strategies}
        delta = (
            None if values["decompose_rrf"] is None or values["decompose_per_need_rerank"] is None
            else values["decompose_per_need_rerank"] - values["decompose_rrf"]
        )
        lines.append(
            f"| {label} | {_fmt(values['legacy'])} | {_fmt(values['decompose_rrf'])} | "
            f"{_fmt(values['decompose_per_need_rerank'])} | {_fmt(delta)} |"
        )

    lines += [
        "", "## 关键分桶（多轮中位数）", "",
        "| 问题类型 / 指标 | Legacy | 实验 A | 实验 B | B - A |",
        "|---|---:|---:|---:|---:|",
    ]
    bucket_rows = (
        ("single_evidence", "evidence_recall", "单证据 Evidence Recall"),
        ("single_evidence", "all_evidence_recall", "单证据 All-Evidence"),
        ("cross_evidence", "evidence_recall", "多证据 Evidence Recall"),
        ("cross_evidence", "all_evidence_recall", "多证据 All-Evidence"),
        ("implicit_constraint_multi_hop", "evidence_recall", "隐含约束/多跳 Evidence Recall"),
        ("implicit_constraint_multi_hop", "all_evidence_recall", "隐含约束/多跳 All-Evidence"),
    )
    for bucket, metric, label in bucket_rows:
        values = {strategy: _bucket_median(runs, strategy, bucket, metric) for strategy in strategies}
        delta = values["decompose_per_need_rerank"] - values["decompose_rrf"]
        lines.append(
            f"| {label} | {_fmt(values['legacy'])} | {_fmt(values['decompose_rrf'])} | "
            f"{_fmt(values['decompose_per_need_rerank'])} | {_fmt(delta)} |"
        )

    lines += ["", "## 每轮严格退化", ""]
    for index, run in enumerate(runs, 1):
        a = run["decompose_rrf"]["paired_vs_legacy"]
        b = run["decompose_per_need_rerank"]["paired_vs_legacy"]
        b_vs_a = run["decompose_per_need_rerank"]["paired_vs_a"]
        lines.append(
            f"- 第 {index} 轮：A 对旧链路退化 `{','.join(a['regressions']) or '无'}`；"
            f"B 对旧链路退化 `{','.join(b['regressions']) or '无'}`；"
            f"B 对 A 退化 `{','.join(b_vs_a['regressions']) or '无'}`。"
        )

    tracked = ("blind-005", "blind-019", "blind-021", "human-mh-001", "human-mh-002")
    lines += ["", "## 重点题", "", "| case | 每轮 Legacy → A → B（All-Evidence） |", "|---|---|"]
    for case_id in tracked:
        values = []
        for run in runs:
            triplet = [
                _by_case(run[strategy]["observations"])[case_id].get("all_evidence_recall")
                for strategy in strategies
            ]
            values.append(" → ".join("n/a" if value is None else f"{value:.1f}" for value in triplet))
        lines.append(f"| {case_id} | {'；'.join(values)} |")

    a_evidence = _median(runs, "decompose_rrf", "evidence_recall_at_3")
    b_evidence = _median(runs, "decompose_per_need_rerank", "evidence_recall_at_3")
    a_all = _median(runs, "decompose_rrf", "all_evidence_recall_at_3")
    b_all = _median(runs, "decompose_per_need_rerank", "all_evidence_recall_at_3")
    a_loss = _median(runs, "decompose_rrf", "fusion_information_need_loss")
    b_loss = _median(runs, "decompose_per_need_rerank", "fusion_information_need_loss")
    a_hard = _median(runs, "decompose_rrf", "hard_negative_hit_rate")
    b_hard = _median(runs, "decompose_per_need_rerank", "hard_negative_hit_rate")
    b_vs_a_regressions = [
        len(run["decompose_per_need_rerank"]["paired_vs_a"]["regressions"])
        for run in runs
    ]
    criteria = {
        "evidence_recall_not_worse": b_evidence >= a_evidence,
        "all_evidence_improves": b_all > a_all,
        "fusion_loss_decreases": b_loss < a_loss,
        "hard_negative_not_worse": b_hard <= a_hard,
        "no_strict_regression_vs_a": max(b_vs_a_regressions) == 0,
    }
    passed = all(criteria.values())
    lines += ["", "## 判断", ""]
    for name, value in criteria.items():
        lines.append(f"- {'通过' if value else '未通过'}：`{name}`")
    lines += [
        "", f"实验 B 总结：**{'值得进入更大评测集验证' if passed else '暂不采用按子问题重排'}**。", "",
        "说明：冻结集只有 22 题，本结果仍是开发诊断，不直接代表线上稳定收益。",
    ]
    return "\n".join(lines) + "\n"


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="按信息需求分别重排的实验 B")
    parser.add_argument("--dataset", type=Path, default=Path("eval/knowledge/v3/knowledge_eval_candidates.jsonl"))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/runs/per-need-rerank-b"))
    args = parser.parse_args(argv)
    if not 1 <= args.repetitions <= 5:
        parser.error("--repetitions 必须在 1 到 5 之间")

    cases, selection = select_cases(load_dataset(args.dataset), "all")
    settings = load_settings()
    if not settings.reranker_base_url or not settings.reranker_model:
        parser.error("实验 B 必须配置 RERANKER_BASE_URL 和 RERANKER_MODEL")
    knowledge_base = build_category_knowledge_base(settings)
    inserted = await bootstrap_category_knowledge(knowledge_base)
    print(f"知识库就绪（本次新增 {inserted} 篇）；共 {len(cases)} 题")
    processor_settings = replace(
        settings,
        llm_base_url=settings.query_processor_base_url or settings.llm_base_url,
        llm_api_key=settings.query_processor_api_key or settings.llm_api_key,
        llm_model=settings.query_processor_model or settings.llm_model,
        llm_fallback_model="",
    )
    prompt = load_prompts()["query_processor"]["system_prompt"]

    runs = []
    for repetition in range(1, args.repetitions + 1):
        candidate_cache: dict = {}
        shared = SharedPlanProcessor(QueryProcessor(
            create_chat_model(processor_settings, stream=False), prompt,
            max_subqueries=settings.query_processor_max_subqueries,
            disable_thinking=settings.query_processor_disable_thinking,
        ))
        reranker = RetryingReranker(HttpReranker(settings, timeout_seconds=30.0))
        observations = {"legacy": [], "a": [], "b": []}
        legacy = await run_dataset(
            knowledge_base, cases, 3, observations=observations["legacy"],
            rrf_k=args.rrf_k, candidate_cache=candidate_cache,
        )
        experiment_a = await run_dataset(
            knowledge_base, cases, 3, observations=observations["a"], query_processor=shared,
            rrf_k=args.rrf_k, execute_rewrite=False, candidate_cache=candidate_cache,
        )
        experiment_b = await run_dataset(
            knowledge_base, cases, 3, observations=observations["b"], query_processor=shared,
            rrf_k=args.rrf_k, execute_rewrite=False, candidate_cache=candidate_cache,
            per_need_reranker=reranker,
        )
        runs.append({
            "repetition": repetition,
            "query_plans": shared.snapshot(),
            "legacy": {"metrics": _metrics(legacy), "observations": observations["legacy"]},
            "decompose_rrf": {
                "metrics": _metrics(experiment_a), "observations": observations["a"],
                "paired_vs_legacy": _paired_changes(observations["legacy"], observations["a"]),
            },
            "decompose_per_need_rerank": {
                "metrics": _metrics(experiment_b), "observations": observations["b"],
                "paired_vs_legacy": _paired_changes(observations["legacy"], observations["b"]),
                "paired_vs_a": _paired_changes(observations["a"], observations["b"]),
            },
        })
        args.output_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "schema_version": "per-need-rerank-ablation-b-checkpoint-v1",
            "completed_repetitions": repetition,
            "runs": runs,
        }
        (args.output_dir / "experiment-b-in-progress.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(
            f"第 {repetition} 轮：A evidence={experiment_a.evidence_recall:.4f}，"
            f"B={experiment_b.evidence_recall:.4f}，A all={experiment_a.all_evidence_recall:.4f}，"
            f"B all={experiment_b.all_evidence_recall:.4f}", flush=True,
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "per-need-rerank-ablation-b-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset": str(args.dataset), "selection": selection,
        "parameters": {
            "repetitions": args.repetitions, "top_k": 3, "rrf_k": args.rrf_k,
            "reranker_model": settings.reranker_model,
            "shared_query_plan_within_repetition": True,
            "shared_candidate_pool_within_repetition": True,
            "global_original_query_rerank": False,
            "method": "rerank each subquery candidate list, keep all candidates, then existing RRF",
        },
        "runs": runs,
    }
    json_path = args.output_dir / f"experiment-b-{stamp}.json"
    report_path = args.output_dir / f"experiment-b-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render(runs, args.dataset, args.rrf_k, settings.reranker_model), encoding="utf-8")
    (args.output_dir / "experiment-b-in-progress.json").unlink(missing_ok=True)
    print(f"完整证据：{json_path}")
    print(f"结论报告：{report_path}")


if __name__ == "__main__":
    asyncio.run(main())
