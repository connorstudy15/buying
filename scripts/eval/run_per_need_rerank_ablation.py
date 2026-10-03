# -*- coding: utf-8 -*-
"""实验 B：只验证“按信息需求分别重排候选”的增量效果。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.prompts.loader import load_prompts  # noqa: E402
from app.application.retrieval.query_processor import QueryProcessor  # noqa: E402
from app.infrastructure.llm import create_chat_model  # noqa: E402
from app.infrastructure.langfuse_config import LangfuseConfig  # noqa: E402
from app.infrastructure.rag.category_knowledge import (  # noqa: E402
    bootstrap_category_knowledge,
    build_category_knowledge_base,
)
from app.infrastructure.rerank.http_reranker import HttpReranker  # noqa: E402
from app.infrastructure.settings import load_settings  # noqa: E402
from app.infrastructure.tracing import setup_tracing, shutdown_tracing  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.trace import Status, StatusCode  # noqa: E402
from scripts.eval.run_category_recall import load_dataset, run_dataset  # noqa: E402
from scripts.eval.run_manifest import select_cases  # noqa: E402
from scripts.eval.run_query_decompose_ablation import (  # noqa: E402
    SharedPlanProcessor,
    _by_case,
    _metrics,
    _paired_changes,
)


class RetryingReranker:
    """给远程重排设置硬延迟预算；用尽后可显式回到原候选顺序。"""

    def __init__(
        self, inner, attempts: int = 2, *, attempt_timeout_seconds: float = 3.0,
        backoff_seconds: float = 0.25, fallback_on_failure: bool = False,
    ):
        self._inner = inner
        self._attempts = attempts
        self._attempt_timeout_seconds = attempt_timeout_seconds
        self._backoff_seconds = backoff_seconds
        self._fallback_on_failure = fallback_on_failure

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        scores, _ = await self.rerank_with_metadata(query, documents)
        return scores

    async def rerank_with_metadata(self, query: str, documents: list[str]):
        last_error = None
        for attempt in range(1, self._attempts + 1):
            started = time.perf_counter()
            with trace.get_tracer(__name__).start_as_current_span(
                "knowledge.reranker.attempt",
                attributes={
                    "langfuse.observation.type": "span",
                    "globex.retrieval.stage": "reranker_attempt",
                    "globex.retrieval.attempt": attempt,
                    "globex.retrieval.max_attempts": self._attempts,
                    "globex.retrieval.document_count": len(documents),
                },
                record_exception=False, set_status_on_exception=False,
            ) as span:
                try:
                    async with asyncio.timeout(self._attempt_timeout_seconds):
                        if hasattr(self._inner, "rerank_with_metadata"):
                            result = await self._inner.rerank_with_metadata(query, documents)
                        else:
                            result = await self._inner.rerank(query, documents), {}
                    span.set_attribute(
                        "globex.retrieval.total_tokens", int((result[1] or {}).get("total_tokens") or 0),
                    )
                    return result
                except Exception as err:  # noqa: BLE001 - 最终仍抛错，不静默降级
                    last_error = err
                    span.set_attribute("error.type", type(err).__name__)
                    span.set_status(Status(StatusCode.ERROR))
                finally:
                    span.set_attribute(
                        "globex.retrieval.latency_ms", round((time.perf_counter() - started) * 1000, 3),
                    )
            if attempt < self._attempts:
                await asyncio.sleep(self._backoff_seconds * attempt)
        if self._fallback_on_failure:
            # 分数严格递减，保持输入候选原顺序；degraded 必须进入 trace/报告，不能静默冒充成功重排。
            return [float(len(documents) - index) for index in range(len(documents))], {
                "total_tokens": 0,
                "document_count": len(documents),
                "degraded": 1,
                "failure_type": type(last_error).__name__ if last_error is not None else "UnknownError",
            }
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


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _telemetry(runs, strategy: str) -> dict[str, float | int | None]:
    observations = [row for run in runs for row in run[strategy]["observations"]]
    total_latencies = [float(row["latency_ms"]) for row in observations]
    processor_latencies = [
        float(row["query_processor_latency_ms"])
        for row in observations if row.get("query_processor_latency_ms") is not None
    ]
    rerank_calls = [call for row in observations for call in row.get("per_need_rerank_calls") or []]
    degraded_calls = [call for call in rerank_calls if call.get("degraded")]
    rerank_call_latencies = [float(call["latency_ms"]) for call in rerank_calls]
    # 子查询重排并发执行，因此一次 Query 的重排墙钟代价取最慢调用，而不是把各调用相加。
    rerank_query_wall = [
        max((float(call["latency_ms"]) for call in row.get("per_need_rerank_calls") or []), default=0.0)
        for row in observations
    ]
    triggered = [row for row in observations if row.get("per_need_rerank_calls")]
    triggered_query_wall = [
        max(float(call["latency_ms"]) for call in row["per_need_rerank_calls"])
        for row in triggered
    ]
    processor_input = sum(int((row.get("query_processor_usage") or {}).get("input_tokens") or 0) for row in observations)
    processor_output = sum(int((row.get("query_processor_usage") or {}).get("output_tokens") or 0) for row in observations)
    reranker_tokens = sum(int((call.get("usage") or {}).get("total_tokens") or 0) for call in rerank_calls)
    triggered_processor_input = sum(int((row.get("query_processor_usage") or {}).get("input_tokens") or 0) for row in triggered)
    triggered_processor_output = sum(int((row.get("query_processor_usage") or {}).get("output_tokens") or 0) for row in triggered)
    count = len(observations)
    # 华北2公开原价：DeepSeek V4.1 Flash 闲/忙输入 1/2 元、输出 4/8 元；Qwen rerank 输入 0.5 元/百万 token。
    idle_cost = (processor_input * 1 + processor_output * 4 + reranker_tokens * 0.5) / 1_000_000
    busy_cost = (processor_input * 2 + processor_output * 8 + reranker_tokens * 0.5) / 1_000_000
    triggered_count = len(triggered)
    triggered_idle_cost = (
        triggered_processor_input * 1 + triggered_processor_output * 4 + reranker_tokens * 0.5
    ) / 1_000_000
    triggered_busy_cost = (
        triggered_processor_input * 2 + triggered_processor_output * 8 + reranker_tokens * 0.5
    ) / 1_000_000
    return {
        "observation_count": count,
        "total_p50_ms": _percentile(total_latencies, 0.5),
        "total_p95_ms": _percentile(total_latencies, 0.95),
        "query_processor_p50_ms": _percentile(processor_latencies, 0.5),
        "query_processor_p95_ms": _percentile(processor_latencies, 0.95),
        "reranker_call_p50_ms": _percentile(rerank_call_latencies, 0.5),
        "reranker_call_p95_ms": _percentile(rerank_call_latencies, 0.95),
        "reranker_query_wall_p50_ms": _percentile(rerank_query_wall, 0.5),
        "reranker_query_wall_p95_ms": _percentile(rerank_query_wall, 0.95),
        "triggered_query_count": triggered_count,
        "triggered_reranker_wall_p50_ms": _percentile(triggered_query_wall, 0.5),
        "triggered_reranker_wall_p95_ms": _percentile(triggered_query_wall, 0.95),
        "reranker_call_count": len(rerank_calls),
        "reranker_degraded_call_count": len(degraded_calls),
        "reranker_degraded_call_rate": len(degraded_calls) / len(rerank_calls) if rerank_calls else 0.0,
        "reranker_calls_per_query": len(rerank_calls) / count if count else 0.0,
        "reranker_calls_per_triggered_query": len(rerank_calls) / triggered_count if triggered_count else 0.0,
        "processor_input_tokens_per_query": processor_input / count if count else 0.0,
        "processor_output_tokens_per_query": processor_output / count if count else 0.0,
        "reranker_tokens_per_query": reranker_tokens / count if count else 0.0,
        "reranker_tokens_per_triggered_query": reranker_tokens / triggered_count if triggered_count else 0.0,
        "estimated_idle_cny_per_query": idle_cost / count if count else 0.0,
        "estimated_busy_cny_per_query": busy_cost / count if count else 0.0,
        "estimated_idle_cny_per_triggered_query": triggered_idle_cost / triggered_count if triggered_count else 0.0,
        "estimated_busy_cny_per_triggered_query": triggered_busy_cost / triggered_count if triggered_count else 0.0,
    }


def _stage_loss_metrics(runs, strategy: str) -> dict[str, object]:
    """按 gold evidence 的首次丢失阶段归因；四类 loss 互斥。"""
    observations = [row for run in runs for row in run[strategy]["observations"]]
    stages = (
        "retrieval_loss_evidence_ids", "reranker_loss_evidence_ids",
        "fusion_loss_evidence_ids", "top_k_truncation_loss_evidence_ids",
    )
    total_gold = sum(len(set(row.get("gold_evidence_ids") or [])) for row in observations)
    result: dict[str, object] = {"gold_evidence_observations": total_gold}
    for field in stages:
        count = sum(len(set(row.get(field) or [])) for row in observations)
        result[field.replace("_evidence_ids", "_count")] = count
        result[field.replace("_evidence_ids", "_rate")] = count / total_gold if total_gold else None
        result[field.replace("_evidence_ids", "_case_ids")] = sorted({
            str(row["case_id"]) for row in observations if row.get(field)
        })
    return result


def _stage_latency_metrics(runs, strategy: str, mode: str | None = None) -> dict[str, float | int | None]:
    observations = [row for run in runs for row in run[strategy]["observations"]]
    if mode is not None:
        observations = [row for row in observations if row.get("effective_plan_mode") == mode]
    fields = {
        "query_processor": "query_processor_stage_latency_ms",
        "retrieval": "retrieval_stage_latency_ms",
        "per_need_reranker": "reranker_stage_latency_ms",
        "fusion": "fusion_stage_latency_ms",
        "end_to_end": "latency_ms",
    }
    output: dict[str, float | int | None] = {"count": len(observations)}
    for label, field in fields.items():
        values = [float(row[field]) for row in observations if row.get(field) is not None]
        output[f"{label}_p50_ms"] = _percentile(values, 0.5)
        output[f"{label}_p95_ms"] = _percentile(values, 0.95)
    return output


def _cost_efficiency(runs, baseline: str, experiment: str) -> dict[str, float | int | None]:
    old = [row for run in runs for row in run[baseline]["observations"]]
    new = [row for run in runs for row in run[experiment]["observations"]]
    old_complete = sum(row.get("all_evidence_recall") == 1 for row in old)
    new_complete = sum(row.get("all_evidence_recall") == 1 for row in new)
    additional = new_complete - old_complete
    old_cost = float(_telemetry(runs, baseline)["estimated_idle_cny_per_query"] or 0.0)
    new_cost = float(_telemetry(runs, experiment)["estimated_idle_cny_per_query"] or 0.0)
    delta_cost = new_cost - old_cost
    delta_all = (_median(runs, experiment, "all_evidence_recall_at_3") or 0.0) - (
        _median(runs, baseline, "all_evidence_recall_at_3") or 0.0
    )
    additional_rate = additional / len(new) if new else 0.0
    return {
        "baseline_fully_correct": old_complete,
        "experiment_fully_correct": new_complete,
        "additional_fully_correct": additional,
        "delta_cost_cny_per_query": delta_cost,
        "cost_per_additional_fully_correct_case_cny": (
            delta_cost / additional_rate if additional_rate > 0 and delta_cost >= 0 else None
        ),
        "delta_all_evidence_recall": delta_all,
        "delta_all_evidence_recall_per_cny": delta_all / delta_cost if delta_cost > 0 else None,
    }


def _decompose_trigger_metrics(runs, dataset: Path) -> dict[str, Any]:
    """评价“是否应该拆”的分类质量；优先使用人工策略标签，旧集才按问题桶兼容推导。"""
    cases = {str(row["id"]): row for row in load_dataset(dataset)}
    rows = []
    explicit_rows = []
    inferred_count = 0
    for run in runs:
        for observation in run["decompose_per_need_rerank"]["observations"]:
            if observation.get("expected_unanswerable"):
                continue  # unsupported gate 在 QueryProcessor 之前，不能算分类器的 DIRECT。
            case = cases[str(observation["case_id"])]
            expected_strategy = str(case.get("expected_query_strategy") or "").upper()
            is_explicit = expected_strategy in {"DIRECT", "DECOMPOSE"}
            if not is_explicit:
                inferred_count += 1
                expected_strategy = (
                    "DECOMPOSE"
                    if str(case.get("primary_kind")) in {"cross_evidence", "implicit_constraint_multi_hop"}
                    else "DIRECT"
                )
            row = {
                "case_id": str(observation["case_id"]),
                "expected": expected_strategy == "DECOMPOSE",
                "predicted": observation.get("processor_plan_mode") == "DECOMPOSE",
            }
            rows.append(row)
            if is_explicit:
                explicit_rows.append(row)

    def counts(selected):
        tp = sum(row["expected"] and row["predicted"] for row in selected)
        fp = sum(not row["expected"] and row["predicted"] for row in selected)
        fn = sum(row["expected"] and not row["predicted"] for row in selected)
        tn = sum(not row["expected"] and not row["predicted"] for row in selected)
        return tp, fp, fn, tn

    tp, fp, fn, tn = counts(rows)
    explicit_tp, explicit_fp, explicit_fn, explicit_tn = counts(explicit_rows)
    ids = lambda predicate: sorted({row["case_id"] for row in rows if predicate(row)})
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_trigger_rate": fp / (fp + tn) if fp + tn else None,
        "direct_preservation_accuracy": tn / (tn + fp) if tn + fp else None,
        "false_positive_ids": ids(lambda row: not row["expected"] and row["predicted"]),
        "false_negative_ids": ids(lambda row: row["expected"] and not row["predicted"]),
        "judgement_source": (
            "explicit_expected_query_strategy"
            if inferred_count == 0
            else "mixed_explicit_and_legacy_primary_kind_inference"
            if inferred_count < len(rows)
            else "legacy_primary_kind_inference"
        ),
        "inferred_observation_count": inferred_count,
        "explicit": {
            "count": len(explicit_rows),
            "tp": explicit_tp, "fp": explicit_fp, "fn": explicit_fn, "tn": explicit_tn,
            "precision": explicit_tp / (explicit_tp + explicit_fp) if explicit_tp + explicit_fp else None,
            "recall": explicit_tp / (explicit_tp + explicit_fn) if explicit_tp + explicit_fn else None,
            "false_trigger_rate": (
                explicit_fp / (explicit_fp + explicit_tn) if explicit_fp + explicit_tn else None
            ),
            "false_positive_ids": ids(lambda row: row in explicit_rows and not row["expected"] and row["predicted"]),
            "false_negative_ids": ids(lambda row: row in explicit_rows and row["expected"] and not row["predicted"]),
        },
    }


def _render(
    runs, dataset: Path, rrf_k: int, reranker_model: str, *,
    evaluation_run_id: str = "", langfuse_enabled: bool = False,
) -> str:
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
        f"- Langfuse：{'已启用' if langfuse_enabled else '未启用'}"
        + (f"；评测运行 ID：`{evaluation_run_id}`" if evaluation_run_id else ""),
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

    a_telemetry = _telemetry(runs, "decompose_rrf")
    b_telemetry = _telemetry(runs, "decompose_per_need_rerank")
    lines += [
        "", "## 调用量与估算费用（质量配对 pass）", "",
        "本 pass 共享候选缓存，只用于质量和调用量对比；端到端延迟请看后面的独立无缓存探针。",
        "",
        "| 指标 | 实验 A | 实验 B |",
        "|---|---:|---:|",
        f"| 每个 Query 的并发 reranker 墙钟 P50 / P95 | 0 / 0 ms | {_fmt(b_telemetry['reranker_query_wall_p50_ms'])} / {_fmt(b_telemetry['reranker_query_wall_p95_ms'])} ms |",
        f"| 仅触发拆分的 Query：reranker 墙钟 P50 / P95 | n/a | {_fmt(b_telemetry['triggered_reranker_wall_p50_ms'])} / {_fmt(b_telemetry['triggered_reranker_wall_p95_ms'])} ms |",
        f"| 单次 reranker 调用 P50 / P95 | n/a | {_fmt(b_telemetry['reranker_call_p50_ms'])} / {_fmt(b_telemetry['reranker_call_p95_ms'])} ms |",
        f"| reranker 调用总数 / 平均每 Query | 0 / 0 | {b_telemetry['reranker_call_count']} / {_fmt(b_telemetry['reranker_calls_per_query'])} |",
        f"| reranker 降级调用数 / 比例 | 0 / 0 | {b_telemetry['reranker_degraded_call_count']} / {_fmt(b_telemetry['reranker_degraded_call_rate'])} |",
        f"| 触发拆分的 Query 数 / 平均调用数 | 0 / 0 | {b_telemetry['triggered_query_count']} / {_fmt(b_telemetry['reranker_calls_per_triggered_query'])} |",
        f"| QueryProcessor 输入 / 输出 token（每 Query） | {_fmt(a_telemetry['processor_input_tokens_per_query'])} / {_fmt(a_telemetry['processor_output_tokens_per_query'])} | {_fmt(b_telemetry['processor_input_tokens_per_query'])} / {_fmt(b_telemetry['processor_output_tokens_per_query'])} |",
        f"| reranker token（每 Query） | 0 | {_fmt(b_telemetry['reranker_tokens_per_query'])} |",
        f"| reranker token（每个触发拆分的 Query） | 0 | {_fmt(b_telemetry['reranker_tokens_per_triggered_query'])} |",
        f"| API 估算成本（闲时 / 忙时，每 Query） | ¥{a_telemetry['estimated_idle_cny_per_query']:.6f} / ¥{a_telemetry['estimated_busy_cny_per_query']:.6f} | ¥{b_telemetry['estimated_idle_cny_per_query']:.6f} / ¥{b_telemetry['estimated_busy_cny_per_query']:.6f} |",
        f"| API 估算成本（每个触发拆分的 Query） | n/a | ¥{b_telemetry['estimated_idle_cny_per_triggered_query']:.6f} / ¥{b_telemetry['estimated_busy_cny_per_triggered_query']:.6f} |",
        "",
        "费用按华北2公开原价估算，不含免费额度、缓存折扣和活动优惠：DeepSeek V4.1 Flash 输入闲/忙 1/2 元、输出 4/8 元/百万 token；Qwen3.7 Text Rerank 输入 0.5 元/百万 token。",
    ]

    a_loss_stages = _stage_loss_metrics(runs, "decompose_rrf")
    b_loss_stages = _stage_loss_metrics(runs, "decompose_per_need_rerank")
    lines += [
        "", "## Gold evidence 分阶段去向", "",
        "每条 gold evidence 只归入它首次丢失的阶段，因此四类 loss 不会重复计数。",
        "", "| 首次丢失阶段 | 实验 A 数量 / 比例 | 实验 B 数量 / 比例 |",
        "|---|---:|---:|",
    ]
    for field, label in (
        ("retrieval_loss", "Retrieval Loss（原始召回未出现）"),
        ("reranker_loss", "Reranker Loss（重排后消失）"),
        ("fusion_loss", "Fusion Loss（融合池中消失）"),
        ("top_k_truncation_loss", "Top-K Truncation Loss（最终截断丢失）"),
    ):
        lines.append(
            f"| {label} | {a_loss_stages[field + '_count']} / {_fmt(a_loss_stages[field + '_rate'])} | "
            f"{b_loss_stages[field + '_count']} / {_fmt(b_loss_stages[field + '_rate'])} |"
        )
    lines += ["", "实验 B 丢失 case："]
    for field, label in (
        ("retrieval_loss", "召回失败"), ("reranker_loss", "reranker 丢失"),
        ("fusion_loss", "fusion 丢失"), ("top_k_truncation_loss", "Top-K 截断"),
    ):
        ids = b_loss_stages[field + "_case_ids"]
        lines.append(f"- {label}：`{','.join(ids) or '无'}`")

    latency_all = _stage_latency_metrics(runs, "decompose_per_need_rerank_latency_uncached")
    latency_direct = _stage_latency_metrics(runs, "decompose_per_need_rerank_latency_uncached", "DIRECT")
    latency_decompose = _stage_latency_metrics(runs, "decompose_per_need_rerank_latency_uncached", "DECOMPOSE")
    lines += [
        "", "## 实验 B 分阶段延迟（独立无缓存探针）", "",
        f"样本数：全部 {latency_all['count']}；DIRECT {latency_direct['count']}；DECOMPOSE {latency_decompose['count']}。",
        "", "| 阶段 | 全部 P50 / P95 | DIRECT P50 / P95 | DECOMPOSE P50 / P95 |",
        "|---|---:|---:|---:|",
    ]
    for field, label in (
        ("query_processor", "QueryProcessor"), ("retrieval", "Raw Retrieval"),
        ("per_need_reranker", "Per-Need Reranker"), ("fusion", "RRF / Fusion"),
        ("end_to_end", "End-to-End"),
    ):
        lines.append(
            f"| {label} | {_fmt(latency_all[field + '_p50_ms'])} / {_fmt(latency_all[field + '_p95_ms'])} ms | "
            f"{_fmt(latency_direct[field + '_p50_ms'])} / {_fmt(latency_direct[field + '_p95_ms'])} ms | "
            f"{_fmt(latency_decompose[field + '_p50_ms'])} / {_fmt(latency_decompose[field + '_p95_ms'])} ms |"
        )
    latency_rows = [
        row for run in runs
        for row in run["decompose_per_need_rerank_latency_uncached"]["observations"]
    ]
    lines += [
        "", "### 最慢 case（无缓存）", "",
        "| case | 模式 | End-to-End | QP | Retrieval | Reranker | Fusion | 主要瓶颈 | Langfuse trace |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    stage_fields = {
        "QueryProcessor": "query_processor_stage_latency_ms",
        "Retrieval": "retrieval_stage_latency_ms",
        "Reranker": "reranker_stage_latency_ms",
        "Fusion": "fusion_stage_latency_ms",
    }
    for row in sorted(latency_rows, key=lambda item: float(item["latency_ms"]), reverse=True)[:10]:
        stage_values = {label: float(row.get(field) or 0.0) for label, field in stage_fields.items()}
        bottleneck = max(stage_values, key=stage_values.get)
        lines.append(
            f"| {row['case_id']} | {row.get('effective_plan_mode') or row.get('retrieval_mode')} | "
            f"{float(row['latency_ms']):.1f} | {stage_values['QueryProcessor']:.1f} | "
            f"{stage_values['Retrieval']:.1f} | {stage_values['Reranker']:.1f} | "
            f"{stage_values['Fusion']:.1f} | {bottleneck} | `{row.get('langfuse_trace_id') or 'n/a'}` |"
        )

    legacy_efficiency = _cost_efficiency(runs, "legacy", "decompose_per_need_rerank")
    rerank_efficiency = _cost_efficiency(runs, "decompose_rrf", "decompose_per_need_rerank")
    lines += [
        "", "## 成本换效果", "",
        "这里只计算 QueryProcessor 与 reranker 的边际 API 费用，不把各策略共同承担的 embedding 成本重复算入。",
        "", "| 对比 | 新增完整正确 case | 每 Query 增量成本 | 每新增一个完整正确 case 的成本 | ΔAll-Evidence Recall / ΔCost |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, efficiency in (
        ("Legacy → 实验 B", legacy_efficiency),
        ("实验 A → 实验 B（reranker 增量）", rerank_efficiency),
    ):
        cost_per_case = efficiency["cost_per_additional_fully_correct_case_cny"]
        recall_per_cost = efficiency["delta_all_evidence_recall_per_cny"]
        lines.append(
            f"| {label} | {efficiency['additional_fully_correct']} | "
            f"¥{float(efficiency['delta_cost_cny_per_query']):.6f} | "
            f"{'n/a' if cost_per_case is None else f'¥{float(cost_per_case):.6f}'} | "
            f"{'n/a' if recall_per_cost is None else f'{float(recall_per_cost):.4f} / ¥1'} |"
        )

    trigger = _decompose_trigger_metrics(runs, dataset)
    explicit = trigger["explicit"]
    lines += [
        "", "## DECOMPOSE 触发准确性", "",
        "`DECOMPOSE Trigger Precision` 表示：所有被模型判为需要拆分的问题中，真正应该拆分的比例。",
        "", "| 指标 | 值 |", "|---|---:|",
        f"| Trigger Precision | {_fmt(trigger['precision'])} |",
        f"| Trigger Recall | {_fmt(trigger['recall'])} |",
        f"| False Trigger Rate | {_fmt(trigger['false_trigger_rate'])} |",
        f"| DIRECT 保持准确率 | {_fmt(trigger['direct_preservation_accuracy'])} |",
        f"| TP / FP / FN / TN | {trigger['tp']} / {trigger['fp']} / {trigger['fn']} / {trigger['tn']} |",
        f"| 显式人工标签题数 | {explicit['count']} |",
        f"| 显式标签 Trigger Precision | {_fmt(explicit['precision'])} |",
        f"| 显式标签 Trigger Recall | {_fmt(explicit['recall'])} |",
        f"| 显式标签 False Trigger Rate | {_fmt(explicit['false_trigger_rate'])} |",
        "",
        f"- 误拆 case：`{','.join(trigger['false_positive_ids']) or '无'}`",
        f"- 漏拆 case：`{','.join(trigger['false_negative_ids']) or '无'}`",
        f"- 判定真值来源：`{trigger['judgement_source']}`。",
        f"- 显式标签误拆：`{','.join(explicit['false_positive_ids']) or '无'}`；"
        f"漏拆：`{','.join(explicit['false_negative_ids']) or '无'}`。",
    ]
    if trigger["inferred_observation_count"]:
        lines.append(
            f"- 注意：有 {trigger['inferred_observation_count']} 条旧 Core 观测没有显式 "
            "`expected_query_strategy`，暂按问题桶推导；Trigger Precision 目前只能作为诊断，不能作为正式门禁。"
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
        f"说明：本轮共有 {len(runs[0]['legacy']['observations'])} 题、{len(runs)} 次重复；"
        "正式冻结前仍需补齐旧 Core 的显式策略标签，并用多次重复确认模型波动。",
    ]
    return "\n".join(lines) + "\n"


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="按信息需求分别重排的实验 B")
    parser.add_argument("--dataset", type=Path, default=Path("eval/knowledge/v3/knowledge_eval_candidates.jsonl"))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/runs/per-need-rerank-b"))
    parser.add_argument("--reranker-timeout-seconds", type=float, default=3.0)
    parser.add_argument("--reranker-attempts", type=int, default=2)
    parser.add_argument("--reranker-backoff-seconds", type=float, default=0.25)
    parser.add_argument(
        "--langfuse", action="store_true",
        help="把脱敏后的逐题评测 trace 发到 Langfuse；不上传 query 或知识正文",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.repetitions <= 5:
        parser.error("--repetitions 必须在 1 到 5 之间")
    if not 1 <= args.reranker_attempts <= 3 or args.reranker_timeout_seconds <= 0 or args.reranker_backoff_seconds < 0:
        parser.error("reranker 延迟预算无效")

    cases, selection = select_cases(load_dataset(args.dataset), "all")
    settings = load_settings()
    if args.langfuse:
        try:
            LangfuseConfig(
                settings.langfuse_base_url, settings.langfuse_public_key, settings.langfuse_secret_key,
            ).validate()
        except ValueError as error:
            parser.error(f"--langfuse 配置不可用：{error}")
        setup_tracing(settings)
    dataset_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    evaluation_run_id = f"knowledge-v5-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
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

    def write_checkpoint(completed_repetitions: int) -> None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "schema_version": "per-need-rerank-ablation-b-checkpoint-v2",
            "completed_repetitions": completed_repetitions,
            "runs": runs,
        }
        (args.output_dir / "experiment-b-in-progress.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    for repetition in range(1, args.repetitions + 1):
        candidate_cache: dict = {}
        shared = SharedPlanProcessor(QueryProcessor(
            create_chat_model(processor_settings, stream=False), prompt,
            max_subqueries=settings.query_processor_max_subqueries,
            disable_thinking=settings.query_processor_disable_thinking,
        ))
        reranker = RetryingReranker(
            HttpReranker(settings, timeout_seconds=args.reranker_timeout_seconds),
            attempts=args.reranker_attempts,
            attempt_timeout_seconds=args.reranker_timeout_seconds,
            backoff_seconds=args.reranker_backoff_seconds,
            fallback_on_failure=True,
        )
        observations = {"legacy": [], "a": [], "b": []}
        legacy = await run_dataset(
            knowledge_base, cases, 3, observations=observations["legacy"],
            rrf_k=args.rrf_k, candidate_cache=candidate_cache,
            langfuse_enabled=args.langfuse, evaluation_run_id=evaluation_run_id,
            evaluation_strategy="legacy", dataset_hash=dataset_hash, repetition=repetition,
        )
        experiment_a = await run_dataset(
            knowledge_base, cases, 3, observations=observations["a"], query_processor=shared,
            rrf_k=args.rrf_k, execute_rewrite=False, candidate_cache=candidate_cache,
            langfuse_enabled=args.langfuse, evaluation_run_id=evaluation_run_id,
            evaluation_strategy="decompose_rrf", dataset_hash=dataset_hash, repetition=repetition,
        )
        experiment_b = await run_dataset(
            knowledge_base, cases, 3, observations=observations["b"], query_processor=shared,
            rrf_k=args.rrf_k, execute_rewrite=False, candidate_cache=candidate_cache,
            per_need_reranker=reranker,
            langfuse_enabled=args.langfuse, evaluation_run_id=evaluation_run_id,
            evaluation_strategy="decompose_per_need_rerank", dataset_hash=dataset_hash,
            repetition=repetition,
        )
        run_record = {
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
            "decompose_per_need_rerank_latency_uncached": {
                "status": "pending",
                "observations": [],
            },
        }
        runs.append(run_record)
        # 质量结果先落盘；无缓存探针依赖远程 embedding，失败时不能丢掉已完成的质量 pass。
        write_checkpoint(repetition - 1)
        latency_observations: list[dict] = []
        try:
            await run_dataset(
                knowledge_base, cases, 3, observations=latency_observations, query_processor=shared,
                rrf_k=args.rrf_k, execute_rewrite=False, candidate_cache=None,
                per_need_reranker=reranker,
                langfuse_enabled=args.langfuse, evaluation_run_id=evaluation_run_id,
                evaluation_strategy="decompose_per_need_rerank_latency_uncached", dataset_hash=dataset_hash,
                repetition=repetition,
            )
        except BaseException as error:
            run_record["decompose_per_need_rerank_latency_uncached"] = {
                "status": "failed",
                "error_type": type(error).__name__,
                "status_code": getattr(error, "status_code", None),
                "completed_observation_count": len(latency_observations),
                "observations": latency_observations,
            }
            write_checkpoint(repetition - 1)
            raise
        run_record["decompose_per_need_rerank_latency_uncached"] = {
            "status": "complete",
            "observations": latency_observations,
        }
        write_checkpoint(repetition)
        print(
            f"第 {repetition} 轮：A evidence={experiment_a.evidence_recall:.4f}，"
            f"B={experiment_b.evidence_recall:.4f}，A all={experiment_a.all_evidence_recall:.4f}，"
            f"B all={experiment_b.all_evidence_recall:.4f}", flush=True,
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "per-need-rerank-ablation-b-v2-stage-attribution",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset": str(args.dataset), "selection": selection,
        "evaluation_run_id": evaluation_run_id,
        "langfuse_enabled": args.langfuse,
        "langfuse_content_policy": "technical metadata and metrics only; query and knowledge text excluded",
        "parameters": {
            "repetitions": args.repetitions, "top_k": 3, "rrf_k": args.rrf_k,
            "reranker_model": settings.reranker_model,
            "shared_query_plan_within_repetition": True,
            "shared_candidate_pool_within_repetition": True,
            "quality_and_latency_measurement_separated": True,
            "latency_probe_candidate_cache": False,
            "global_original_query_rerank": False,
            "reranker_attempt_timeout_seconds": args.reranker_timeout_seconds,
            "reranker_attempts": args.reranker_attempts,
            "reranker_backoff_seconds": args.reranker_backoff_seconds,
            "reranker_fallback": "preserve original candidate order and mark degraded",
            "method": "rerank each subquery candidate list, keep all candidates, then existing RRF",
            "pricing_cny_per_million_tokens": {
                "query_processor_input_idle": 1.0,
                "query_processor_input_busy": 2.0,
                "query_processor_output_idle": 4.0,
                "query_processor_output_busy": 8.0,
                "reranker_input": 0.5,
                "as_of": "2026-10-04",
                "source": "https://help.aliyun.com/zh/model-studio/model-pricing",
            },
        },
        "runs": runs,
    }
    json_path = args.output_dir / f"experiment-b-{stamp}.json"
    report_path = args.output_dir / f"experiment-b-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render(
        runs, args.dataset, args.rrf_k, settings.reranker_model,
        evaluation_run_id=evaluation_run_id, langfuse_enabled=args.langfuse,
    ), encoding="utf-8")
    (args.output_dir / "experiment-b-in-progress.json").unlink(missing_ok=True)
    if args.langfuse:
        shutdown_tracing()
    print(f"完整证据：{json_path}")
    print(f"结论报告：{report_path}")


if __name__ == "__main__":
    asyncio.run(main())
