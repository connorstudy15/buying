# -*- coding: utf-8 -*-
"""DIRECT/DECOMPOSE 独立 holdout；不访问知识库，不把标签或问题正文发给 Langfuse。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from opentelemetry import trace  # noqa: E402
from opentelemetry.trace import Status, StatusCode  # noqa: E402

from app.application.prompts.loader import load_prompts  # noqa: E402
from app.application.retrieval.query_processor import QueryProcessor  # noqa: E402
from app.infrastructure.langfuse_config import LangfuseConfig  # noqa: E402
from app.infrastructure.llm import create_chat_model  # noqa: E402
from app.infrastructure.settings import load_settings  # noqa: E402
from app.infrastructure.tracing import setup_tracing, shutdown_tracing  # noqa: E402
from scripts.eval.langfuse_trace import EvaluationCaseTrace  # noqa: E402


def load_holdout(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [str(row.get("id") or "") for row in rows]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("holdout_case_id_invalid")
    for row in rows:
        if row.get("expected_query_strategy") not in {"DIRECT", "DECOMPOSE"}:
            raise ValueError("holdout_strategy_invalid")
        if row.get("label_status") != "frozen_holdout" or row.get("created_without_kb_content") is not True:
            raise ValueError("holdout_freeze_contract_invalid")
    return rows


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def metrics(observations: list[dict]) -> dict:
    tp = sum(row["expected"] == "DECOMPOSE" and row["predicted_decompose"] and not row["fallback"] for row in observations)
    fp = sum(row["expected"] == "DIRECT" and row["predicted_decompose"] and not row["fallback"] for row in observations)
    fn = sum(row["expected"] == "DECOMPOSE" and (not row["predicted_decompose"] or row["fallback"]) for row in observations)
    tn = sum(row["expected"] == "DIRECT" and not row["predicted_decompose"] and not row["fallback"] for row in observations)
    latencies = [float(row["latency_ms"]) for row in observations]
    input_tokens = sum(int(row["usage"].get("input_tokens") or 0) for row in observations)
    output_tokens = sum(int(row["usage"].get("output_tokens") or 0) for row in observations)
    count = len(observations)
    return {
        "count": count, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "direct_preservation_accuracy": tn / (tn + fp) if tn + fp else None,
        "accuracy": (tp + tn) / count if count else None,
        "fallback_rate": sum(row["fallback"] for row in observations) / count if count else None,
        "false_positive_ids": [row["case_id"] for row in observations if row["expected"] == "DIRECT" and row["predicted_decompose"] and not row["fallback"]],
        "false_negative_ids": [row["case_id"] for row in observations if row["expected"] == "DECOMPOSE" and (not row["predicted_decompose"] or row["fallback"])],
        "fallback_ids": [row["case_id"] for row in observations if row["fallback"]],
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "input_tokens_per_query": input_tokens / count if count else 0.0,
        "output_tokens_per_query": output_tokens / count if count else 0.0,
    }


async def run_once(processor: QueryProcessor, cases: list[dict], *, run_id: str, repetition: int,
                   dataset_hash: str, langfuse_enabled: bool) -> tuple[list[dict], dict]:
    observations = []
    for case in cases:
        root = EvaluationCaseTrace(
            enabled=langfuse_enabled, run_id=run_id, case_id=case["id"],
            strategy="decompose_trigger_holdout", dataset_hash=dataset_hash,
            answerability="complete", missing_reason=None, repetition=repetition, top_k=1, rrf_k=1,
        )
        started = time.perf_counter()
        usage: dict = {}
        plan = None
        error = None
        with trace.get_tracer(__name__).start_as_current_span(
            "knowledge.query_processor",
            attributes={"langfuse.observation.type": "span", "globex.retrieval.stage": "query_processor"},
            record_exception=False, set_status_on_exception=False,
        ) as span:
            try:
                plan, usage = await processor.process_with_metadata(case["query"])
                span.set_attributes({
                    "globex.retrieval.plan_mode": plan.mode,
                    "globex.retrieval.input_tokens": int(usage.get("input_tokens") or 0),
                    "globex.retrieval.output_tokens": int(usage.get("output_tokens") or 0),
                    "globex.retrieval.total_tokens": int(usage.get("total_tokens") or 0),
                })
            except Exception as caught:  # fallback 是被测结果，不能让整轮消失
                error = caught
                span.set_attribute("error.type", type(caught).__name__)
                span.set_status(Status(StatusCode.ERROR))
            finally:
                span.set_attribute("globex.retrieval.latency_ms", round((time.perf_counter() - started) * 1000, 3))
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        predicted = plan.mode if plan is not None else "FALLBACK"
        predicted_decompose = predicted == "DECOMPOSE"
        fallback = plan is None
        correct = not fallback and predicted_decompose == (case["expected_query_strategy"] == "DECOMPOSE")
        trace_id = root.finish({
            "globex.eval.trigger_expected": case["expected_query_strategy"],
            "globex.eval.trigger_predicted": predicted,
            "globex.eval.trigger_correct": correct,
            "globex.eval.trigger_fallback": fallback,
            "globex.eval.latency_ms": latency_ms,
        }, error=error)
        observations.append({
            "case_id": case["id"], "expected": case["expected_query_strategy"],
            "predicted": predicted, "predicted_decompose": predicted_decompose,
            "correct": correct, "fallback": fallback,
            "error_type": type(error).__name__ if error is not None else None,
            "error_code": str(error) if error is not None else None,
            "latency_ms": latency_ms, "usage": usage, "langfuse_trace_id": trace_id,
        })
    return observations, metrics(observations)


def render(payload: dict) -> str:
    lines = [
        "# DECOMPOSE Trigger Holdout", "",
        f"- 数据集：`{payload['dataset']}`；{payload['case_count']} 题；重复 {len(payload['runs'])} 轮。",
        f"- Langfuse：{'已启用' if payload['langfuse_enabled'] else '未启用'}；运行 ID：`{payload['evaluation_run_id']}`。",
        "- REWRITE 归入非 DECOMPOSE；fallback 单独计数，不冒充 DIRECT。", "",
        "| 轮次 | Precision | Recall | DIRECT 保持率 | fallback | P50/P95 | 输入/输出 token（每题） |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in payload["runs"]:
        item = run["metrics"]
        lines.append(
            f"| {run['repetition']} | {item['precision']:.2%} | {item['recall']:.2%} | "
            f"{item['direct_preservation_accuracy']:.2%} | {item['fallback_rate']:.2%} | "
            f"{item['latency_p50_ms']:.0f}/{item['latency_p95_ms']:.0f} ms | "
            f"{item['input_tokens_per_query']:.1f}/{item['output_tokens_per_query']:.1f} |"
        )
    for run in payload["runs"]:
        item = run["metrics"]
        lines += ["", f"## 第 {run['repetition']} 轮", "",
                  f"- 误拆：`{','.join(item['false_positive_ids']) or '无'}`",
                  f"- 漏拆：`{','.join(item['false_negative_ids']) or '无'}`",
                  f"- fallback：`{','.join(item['fallback_ids']) or '无'}`"]
    return "\n".join(lines) + "\n"


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="DIRECT/DECOMPOSE 独立 holdout")
    parser.add_argument("--dataset", type=Path, default=Path("eval/knowledge/v5/decompose_trigger_holdout_20.jsonl"))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/runs/decompose-trigger-holdout"))
    parser.add_argument("--langfuse", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.repetitions <= 5:
        parser.error("--repetitions 必须在 1 到 5 之间")
    cases = load_holdout(args.dataset)
    settings = load_settings()
    if args.langfuse:
        LangfuseConfig(settings.langfuse_base_url, settings.langfuse_public_key, settings.langfuse_secret_key).validate()
        setup_tracing(settings)
    processor_settings = replace(
        settings,
        llm_base_url=settings.query_processor_base_url or settings.llm_base_url,
        llm_api_key=settings.query_processor_api_key or settings.llm_api_key,
        llm_model=settings.query_processor_model or settings.llm_model,
        llm_fallback_model="",
    )
    processor = QueryProcessor(
        create_chat_model(processor_settings, stream=False),
        load_prompts()["query_processor"]["system_prompt"],
        max_subqueries=settings.query_processor_max_subqueries,
        disable_thinking=settings.query_processor_disable_thinking,
    )
    dataset_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    run_id = f"decompose-trigger-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    runs = []
    for repetition in range(1, args.repetitions + 1):
        observations, run_metrics = await run_once(
            processor, cases, run_id=run_id, repetition=repetition,
            dataset_hash=dataset_hash, langfuse_enabled=args.langfuse,
        )
        runs.append({"repetition": repetition, "metrics": run_metrics, "observations": observations})
        print(f"第 {repetition} 轮：Precision={run_metrics['precision']:.4f}，Recall={run_metrics['recall']:.4f}", flush=True)
    payload = {
        "schema_version": "decompose-trigger-holdout-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset": str(args.dataset), "dataset_sha256": dataset_hash,
        "case_count": len(cases), "evaluation_run_id": run_id,
        "langfuse_enabled": args.langfuse, "runs": runs,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = args.output_dir / f"trigger-holdout-{stamp}.json"
    report_path = args.output_dir / f"trigger-holdout-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render(payload), encoding="utf-8")
    if args.langfuse:
        shutdown_tracing()
    print(f"完整证据：{json_path}")
    print(f"报告：{report_path}")


if __name__ == "__main__":
    asyncio.run(main())
