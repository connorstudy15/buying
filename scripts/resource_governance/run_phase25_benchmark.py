"""Run the frozen 67-query knowledge suite through the complete Agent path.

Resource Governor remains shadow-only. The script writes only case ids/status
locally; detailed resource observations are emitted to the configured Trace
backend. Retrieval quality is still scored by ``run_category_recall.py`` and
is not reimplemented here.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.application.agents.orchestrator import SubmitIntentInput  # noqa: E402
from app.composition import build_container  # noqa: E402

DEFAULT_DATASETS = (
    ROOT / "eval/knowledge/v5/knowledge_eval_core_61.jsonl",
    ROOT / "eval/knowledge/v5/knowledge_eval_partial_coverage_2.jsonl",
    ROOT / "eval/knowledge/v5/knowledge_eval_knowledge_gap_4.jsonl",
)


def case_buckets(case: dict) -> list[str]:
    kind = str(case.get("primary_kind") or case.get("original_kind") or "unknown")
    strategy = str(case.get("expected_query_strategy") or "DIRECT").upper()
    needs = case.get("required_information_needs") or []
    sources = {
        str(evidence.get("source")) for evidence in (case.get("evidence_ground_truth") or [])
        if isinstance(evidence, dict) and evidence.get("source")
    }
    buckets = {kind, strategy}
    buckets.add("Multi-hop" if len(needs) > 1 or strategy == "DECOMPOSE" else "Single-hop")
    buckets.add("Cross Evidence" if len(sources) > 1 or len(needs) > 1 else "Single Evidence")
    buckets.add("Context-heavy request" if len(needs) > 1 else "Simple request")
    return sorted(buckets)


def load_cases(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        rows.extend(
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Phase 2.5 dataset contains duplicate case ids")
    return rows


def response_error_type(response: httpx.Response) -> str | None:
    """Detect application-level failures hidden behind a HTTP 200 response.

    The commerce endpoint may translate an upstream provider failure into a
    normal HTTP response.  The resource benchmark must not call that a
    successful observation, otherwise provider/model access failures distort
    latency and token regression statistics.
    """
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    # The synchronous DTO currently drops SubmitIntentOutput.error and only
    # preserves its explicit error-prefixed final_text. HTTP 200 is not proof
    # of a successful agent lifecycle. Never persist the provider error body.
    final_text = payload.get("final_text")
    if isinstance(final_text, str) and final_text.lstrip().startswith("[error]"):
        if "Insufficient Balance" in final_text or "402" in final_text:
            return "provider_insufficient_balance"
        return "agent_execution_error"
    error = payload.get("error")
    if error:
        if isinstance(error, dict):
            return str(error.get("code") or error.get("type") or "api_error")
        return "api_error"
    if payload.get("ok") is False or str(payload.get("status", "")).lower() in {"error", "failed"}:
        return str(payload.get("error_code") or payload.get("status") or "api_error")
    return None


async def run(args) -> list[dict]:
    cases = load_cases(args.dataset or list(DEFAULT_DATASETS))
    if args.case_id:
        requested = list(dict.fromkeys(args.case_id))
        by_id = {str(case["id"]): case for case in cases}
        missing = [case_id for case_id in requested if case_id not in by_id]
        if missing:
            raise ValueError(f"Unknown case ids: {', '.join(missing)}")
        cases = [by_id[case_id] for case_id in requested]
    if args.limit:
        cases = cases[:args.limit]
    dataset_hash = hashlib.sha256("\n".join(str(row["id"]) for row in cases).encode()).hexdigest()
    run_id = args.run_id or f"phase25-{uuid.uuid4().hex[:12]}"
    container = None
    client = None
    if args.base_url:
        client = httpx.AsyncClient(base_url=args.base_url.rstrip("/") + "/", timeout=args.timeout)
    else:
        container = await build_container()
        await container.startup()
    observations: list[dict] = []
    try:
        for repetition in range(1, args.repetitions + 1):
            for case in cases:
                case_id = str(case["id"])
                session_id = f"{run_id}-{case_id}-r{repetition}"
                started = time.perf_counter()
                error_type = None
                remote_trace_id = None
                with trace.get_tracer("globex.eval.resource").start_as_current_span(
                    "eval.resource_governance.agent",
                    attributes={
                        "langfuse.session.id": run_id,
                        "langfuse.observation.type": "chain",
                        "globex.eval.run_id": run_id,
                        "globex.eval.case_id": case_id,
                        "globex.eval.dataset_hash": dataset_hash,
                        "globex.eval.repetition": repetition,
                        "globex.eval.query_type": str(case.get("primary_kind") or case.get("original_kind") or "unknown"),
                        "globex.eval.answerability": str(case.get("answerability") or "unknown"),
                    },
                    record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    try:
                        if client is not None:
                            headers: dict[str, str] = {}
                            TraceContextTextMapPropagator().inject(headers)
                            response = await client.post("commerce/intents", headers=headers, json={
                                "shopping_session_id": session_id,
                                "buyer_id": "resource-governance-eval",
                                "request_id": f"{run_id}-{case_id}-r{repetition}",
                                "locale": "zh-CN",
                                "currency": "CNY",
                                "raw_query": str(case["query"]),
                            })
                            response.raise_for_status()
                            remote_trace_id = response.headers.get("x-trace-id")
                            error_type = response_error_type(response)
                            if error_type:
                                span.set_attribute("error.type", error_type)
                                span.set_status(Status(StatusCode.ERROR))
                        else:
                            assert container is not None
                            result = await container.orchestrator.handle_intent(
                                SubmitIntentInput(
                                    shopping_session_id=session_id,
                                    buyer_id="resource-governance-eval",
                                    locale="zh-CN",
                                    currency="CNY",
                                    raw_query=str(case["query"]),
                                ),
                                use_semantic_cache=False,
                                fresh_session=True,
                            )
                            if result.error:
                                error_type = result.error_code or "agent_error"
                                span.set_status(Status(StatusCode.ERROR))
                    except BaseException as error:
                        error_type = type(error).__name__
                        span.set_attribute("error.type", error_type)
                        span.set_status(Status(StatusCode.ERROR))
                        if args.fail_fast:
                            raise
                    finally:
                        latency_ms = round((time.perf_counter() - started) * 1000, 3)
                        span.set_attribute("globex.eval.latency_ms", latency_ms)
                observations.append({
                    "run_id": run_id,
                    "case_id": case_id,
                    "query_type": str(case.get("primary_kind") or case.get("original_kind") or "unknown"),
                    "buckets": case_buckets(case),
                    "repetition": repetition,
                    "latency_ms": latency_ms,
                    "status": "error" if error_type else "success",
                    "error_type": error_type,
                    "trace_id": remote_trace_id,
                })
                # Preserve completed requests across provider failures or an
                # interrupted smoke; no prompt/response body is persisted.
                if getattr(args, "output", None):
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps({
                        "shadow_only": True, "complete": False,
                        "repetitions": args.repetitions,
                        "observation_count": len(observations), "observations": observations,
                    }, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"completed": len(observations), "case_id": case_id,
                                  "status": observations[-1]["status"], "latency_ms": latency_ms}), flush=True)
                if error_type == "provider_insufficient_balance":
                    args.aborted_reason = "provider_insufficient_balance"
                    return observations  # Do not turn an account-wide failure into more invalid cases.
    finally:
        if client is not None:
            await client.aclose()
        if container is not None:
            await container.shutdown()
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, action="append")
    parser.add_argument(
        "--case-id", action="append", default=[],
        help="Run only this case id; repeat the option to preserve an explicit causal-smoke set.",
    )
    parser.add_argument("--repetitions", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--base-url", default="",
        help="Use a restarted running API (for example http://127.0.0.1:8000) and avoid local Qdrant lock.",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    observations = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "shadow_only": True,
        "complete": not bool(getattr(args, "aborted_reason", None)),
        "aborted_reason": getattr(args, "aborted_reason", None),
        "repetitions": args.repetitions,
        "observation_count": len(observations),
        "observations": observations,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "observation_count": len(observations),
        "errors": sum(item["status"] == "error" for item in observations),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
