# -*- coding: utf-8 -*-
"""实验 A：在完全相同的 QueryProcessor 计划上，消融 REWRITE 的实际检索。

同一轮每道题只调用一次 QueryProcessor。query-transform 原样执行该计划；
query-decompose 复用同一计划，但把 REWRITE 映射为 DIRECT。两边回放相同的
QueryProcessor 耗时，使端到端延迟仍可公平比较。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.prompts.loader import load_prompts  # noqa: E402
from app.application.retrieval.query_processor import QueryPlan, QueryProcessor  # noqa: E402
from app.infrastructure.llm import create_chat_model  # noqa: E402
from app.infrastructure.rag.category_knowledge import (  # noqa: E402
    bootstrap_category_knowledge,
    build_category_knowledge_base,
)
from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.run_category_recall import load_dataset, run_dataset  # noqa: E402
from scripts.eval.run_manifest import select_cases  # noqa: E402


class SharedPlanProcessor:
    """首次调用真实模型；后续返回相同计划并回放相同等待时间。"""

    def __init__(self, inner: QueryProcessor):
        self._inner = inner
        self._cache: dict[str, QueryPlan | Exception] = {}
        self._latency: dict[str, float] = {}

    async def process(self, question: str) -> QueryPlan:
        if question in self._cache:
            await asyncio.sleep(self._latency[question])
            value = self._cache[question]
            if isinstance(value, Exception):
                raise type(value)(str(value))
            return value
        started = time.perf_counter()
        try:
            value = await self._inner.process(question)
        except Exception as err:  # noqa: BLE001 - 两个实验组必须回放同一个失败
            self._latency[question] = time.perf_counter() - started
            self._cache[question] = err
            raise
        self._latency[question] = time.perf_counter() - started
        self._cache[question] = value
        return value

    def snapshot(self) -> dict[str, dict[str, Any]]:
        rows = {}
        for question, value in self._cache.items():
            rows[question] = {
                "latency_ms": round(self._latency[question] * 1000, 3),
                "error": str(value) if isinstance(value, Exception) else None,
                "plan": None if isinstance(value, Exception) else asdict(value),
            }
        return rows


def _metrics(aggregate) -> dict[str, Any]:
    return {
        "document_recall_at_3": aggregate.recall,
        "evidence_recall_at_3": aggregate.evidence_recall,
        "all_evidence_recall_at_3": aggregate.all_evidence_recall,
        "hard_negative_hit_rate": aggregate.hard_negative_hit_rate,
        "hard_negative_above_positive_rate": aggregate.hard_negative_above_positive_rate,
        "unanswerable_accuracy": aggregate.empty_accuracy,
        "fusion_information_need_loss": aggregate.fusion_information_need_loss,
        "latency_p50_ms": aggregate.latency_p50_ms,
        "latency_p95_ms": aggregate.latency_p95_ms,
        "bucket_metrics": aggregate.bucket_metrics,
    }


def _by_case(observations: list[dict]) -> dict[str, dict]:
    return {str(row["case_id"]): row for row in observations}


def _paired_changes(legacy: list[dict], experiment: list[dict]) -> dict[str, Any]:
    old, new = _by_case(legacy), _by_case(experiment)
    correct = [case_id for case_id, row in old.items() if row.get("all_evidence_recall") == 1]
    regressions = [case_id for case_id in correct if new[case_id].get("all_evidence_recall") != 1]
    improvements = [
        case_id for case_id, row in new.items()
        if row.get("all_evidence_recall") == 1 and old[case_id].get("all_evidence_recall") != 1
    ]
    return {
        "legacy_strict_correct": len(correct),
        "regressions": regressions,
        "regression_rate": len(regressions) / len(correct) if correct else None,
        "improvements": improvements,
    }


def _median(runs: list[dict], strategy: str, metric: str) -> float | None:
    values = [run[strategy]["metrics"].get(metric) for run in runs]
    present = [float(value) for value in values if value is not None]
    return statistics.median(present) if present else None


def _bucket_median(runs: list[dict], strategy: str, bucket: str, metric: str) -> float | None:
    values = [run[strategy]["metrics"]["bucket_metrics"].get(bucket, {}).get(metric) for run in runs]
    present = [float(value) for value in values if value is not None]
    return statistics.median(present) if present else None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _render(runs: list[dict], dataset: Path, rrf_k: int) -> str:
    labels = {
        "legacy": "Legacy（旧链路）",
        "query_transform": "V2（含改写）",
        "query_decompose": "实验 A（禁用改写）",
    }
    lines = [
        "# Query Decomposition 实验 A",
        "",
        f"- 数据集：`{dataset}`，每轮 {len(runs[0]['legacy']['observations'])} 题",
        f"- 重复次数：{len(runs)}",
        f"- Top-K：3；RRF k：{rrf_k}",
        "- 每轮 V2 与实验 A 复用完全相同的 QueryProcessor 输出和回放耗时。",
        "- 实验 A 唯一策略变化：模型输出 REWRITE 时不执行改写，映射为 DIRECT。",
        "",
        "## 总体指标（多轮中位数）",
        "",
        "| 指标 | Legacy | V2 | 实验 A | 实验 A - Legacy |",
        "|---|---:|---:|---:|---:|",
    ]
    metrics = (
        ("Document Recall@3", "document_recall_at_3"),
        ("Evidence Recall@3", "evidence_recall_at_3"),
        ("All-Evidence Recall@3", "all_evidence_recall_at_3"),
        ("Hard-negative hit rate", "hard_negative_hit_rate"),
        ("Fusion information-need loss", "fusion_information_need_loss"),
        ("Unanswerable accuracy", "unanswerable_accuracy"),
        ("P50 latency (ms)", "latency_p50_ms"),
        ("P95 latency (ms)", "latency_p95_ms"),
    )
    for label, metric in metrics:
        values = {strategy: _median(runs, strategy, metric) for strategy in labels}
        delta = None if values["legacy"] is None or values["query_decompose"] is None else values["query_decompose"] - values["legacy"]
        lines.append(
            f"| {label} | {_fmt(values['legacy'])} | {_fmt(values['query_transform'])} | "
            f"{_fmt(values['query_decompose'])} | {_fmt(delta)} |"
        )

    lines += [
        "",
        "## 关键分桶（多轮中位数）",
        "",
        "| 问题类型 / 指标 | Legacy | V2 | 实验 A | 实验 A - Legacy |",
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
        values = {strategy: _bucket_median(runs, strategy, bucket, metric) for strategy in labels}
        delta = None if values["legacy"] is None or values["query_decompose"] is None else values["query_decompose"] - values["legacy"]
        lines.append(
            f"| {label} | {_fmt(values['legacy'])} | {_fmt(values['query_transform'])} | "
            f"{_fmt(values['query_decompose'])} | {_fmt(delta)} |"
        )

    lines += ["", "## 每轮退化与改善", ""]
    for index, run in enumerate(runs, 1):
        paired = run["query_decompose"]["paired_vs_legacy"]
        rate = paired["regression_rate"]
        lines.append(
            f"- 第 {index} 轮：退化 {len(paired['regressions'])}/{paired['legacy_strict_correct']} "
            f"({_fmt(rate)})，退化题 `{','.join(paired['regressions']) or '无'}`；"
            f"改善题 `{','.join(paired['improvements']) or '无'}`。"
        )

    tracked = ("blind-005", "blind-019", "blind-021", "human-mh-001", "human-mh-002")
    lines += ["", "## 重点题", "", "| case | 每轮 Legacy → V2 → 实验 A（All-Evidence） |", "|---|---|"]
    for case_id in tracked:
        values = []
        for run in runs:
            triplet = []
            for strategy in labels:
                row = _by_case(run[strategy]["observations"])[case_id]
                triplet.append(row.get("all_evidence_recall"))
            values.append(" → ".join("n/a" if value is None else f"{value:.1f}" for value in triplet))
        lines.append(f"| {case_id} | {'；'.join(values)} |")

    single_legacy = _bucket_median(runs, "legacy", "single_evidence", "evidence_recall")
    single_exp = _bucket_median(runs, "query_decompose", "single_evidence", "evidence_recall")
    cross_legacy = _bucket_median(runs, "legacy", "cross_evidence", "all_evidence_recall")
    cross_exp = _bucket_median(runs, "query_decompose", "cross_evidence", "all_evidence_recall")
    rates = [run["query_decompose"]["paired_vs_legacy"]["regression_rate"] for run in runs]
    rate_median = statistics.median(value for value in rates if value is not None)
    blind_019_ok = all(
        _by_case(run["query_decompose"]["observations"])["blind-019"].get("all_evidence_recall") == 1
        for run in runs
    )
    criteria = {
        "single_near_legacy": single_exp is not None and single_legacy is not None and single_exp >= single_legacy - 0.02,
        "cross_better_than_legacy": cross_exp is not None and cross_legacy is not None and cross_exp > cross_legacy,
        "regression_below_v2_12_5_percent": rate_median < 0.125,
        "blind_019_preserved_every_run": blind_019_ok,
    }
    passed = all(criteria.values())
    lines += ["", "## 判断", ""]
    for name, value in criteria.items():
        lines.append(f"- {'通过' if value else '未通过'}：`{name}`")
    lines += [
        "",
        f"实验 A 总结：**{'满足进入实验 B 的预设条件' if passed else '暂不进入实验 B'}**。",
        "",
        "说明：当前 cross-evidence 只有 4 题，本实验只用于架构诊断，不能作为稳定线上收益结论。",
    ]
    return "\n".join(lines) + "\n"


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Query Decomposition 实验 A")
    parser.add_argument("--dataset", type=Path, default=Path("eval/knowledge/v3/knowledge_eval_candidates.jsonl"))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/runs/query-decompose-a"))
    args = parser.parse_args(argv)
    if not 1 <= args.repetitions <= 5:
        parser.error("--repetitions 必须在 1 到 5 之间")

    cases, selection = select_cases(load_dataset(args.dataset), "all")
    settings = load_settings()
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
        # 同一轮所有策略共享每条查询的候选池，隔离远程 embedding / ANN 顺序波动。
        candidate_cache: dict = {}
        shared = SharedPlanProcessor(QueryProcessor(
            create_chat_model(processor_settings, stream=False), prompt,
            max_subqueries=settings.query_processor_max_subqueries,
            disable_thinking=settings.query_processor_disable_thinking,
        ))
        legacy_observations: list[dict] = []
        transform_observations: list[dict] = []
        decompose_observations: list[dict] = []
        legacy = await run_dataset(
            knowledge_base, cases, 3, observations=legacy_observations,
            rrf_k=args.rrf_k, candidate_cache=candidate_cache,
        )
        transform = await run_dataset(
            knowledge_base, cases, 3, observations=transform_observations,
            query_processor=shared, rrf_k=args.rrf_k, execute_rewrite=True,
            candidate_cache=candidate_cache,
        )
        decompose = await run_dataset(
            knowledge_base, cases, 3, observations=decompose_observations,
            query_processor=shared, rrf_k=args.rrf_k, execute_rewrite=False,
            candidate_cache=candidate_cache,
        )
        runs.append({
            "repetition": repetition,
            "query_plans": shared.snapshot(),
            "legacy": {"metrics": _metrics(legacy), "observations": legacy_observations},
            "query_transform": {
                "metrics": _metrics(transform), "observations": transform_observations,
                "paired_vs_legacy": _paired_changes(legacy_observations, transform_observations),
            },
            "query_decompose": {
                "metrics": _metrics(decompose), "observations": decompose_observations,
                "paired_vs_legacy": _paired_changes(legacy_observations, decompose_observations),
            },
        })
        print(
            f"第 {repetition} 轮：legacy evidence={legacy.evidence_recall:.4f}，"
            f"V2={transform.evidence_recall:.4f}，实验A={decompose.evidence_recall:.4f}"
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "query-decompose-ablation-a-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset": str(args.dataset),
        "selection": selection,
        "parameters": {
            "repetitions": args.repetitions, "top_k": 3, "rrf_k": args.rrf_k,
            "prompt_reused_without_changes": True,
            "shared_query_plan_within_repetition": True,
            "shared_candidate_pool_within_repetition": True,
            "rewrite_policy": "REWRITE maps to DIRECT only in query_decompose",
        },
        "runs": runs,
    }
    json_path = args.output_dir / f"experiment-a-{stamp}.json"
    report_path = args.output_dir / f"experiment-a-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render(runs, args.dataset, args.rrf_k), encoding="utf-8")
    print(f"完整证据：{json_path}")
    print(f"结论报告：{report_path}")


if __name__ == "__main__":
    asyncio.run(main())
