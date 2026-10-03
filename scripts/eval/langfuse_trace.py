# -*- coding: utf-8 -*-
"""评测专用的安全 OTel span；不上传 query、证据正文或候选内容。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode


def _present(attributes: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attributes.items() if value is not None}


@dataclass
class EvaluationCaseTrace:
    enabled: bool
    run_id: str
    case_id: str
    strategy: str
    dataset_hash: str
    answerability: str
    missing_reason: str | None
    repetition: int
    top_k: int
    rrf_k: int

    def __post_init__(self) -> None:
        self._span = None
        self._scope = None
        if not self.enabled:
            return
        self._span = trace.get_tracer("globex.eval.knowledge").start_span(
            "eval.knowledge.retrieval",
            attributes=_present({
                "langfuse.session.id": self.run_id,
                "langfuse.observation.type": "span",
                "globex.eval.run_id": self.run_id,
                "globex.eval.case_id": self.case_id,
                "globex.eval.strategy": self.strategy,
                "globex.eval.dataset_hash": self.dataset_hash,
                "globex.eval.answerability": self.answerability,
                "globex.eval.missing_reason": self.missing_reason,
                "globex.eval.repetition": self.repetition,
                "globex.eval.top_k": self.top_k,
                "globex.eval.rrf_k": self.rrf_k,
            }),
            record_exception=False,
            set_status_on_exception=False,
        )
        self._scope = trace.use_span(self._span, end_on_exit=False)
        self._scope.__enter__()

    @property
    def trace_id(self) -> str | None:
        if self._span is None:
            return None
        span_context = self._span.get_span_context()
        return f"{span_context.trace_id:032x}" if span_context.is_valid else None

    def finish(self, attributes: dict[str, Any] | None = None, error: BaseException | None = None) -> str | None:
        if self._span is None:
            return None
        if attributes:
            self._span.set_attributes(_present(attributes))
        if error is not None:
            self._span.set_attribute("error.type", type(error).__name__)
            self._span.set_status(Status(StatusCode.ERROR))
        trace_id = self.trace_id
        if self._scope is not None:
            self._scope.__exit__(None, None, None)
        self._span.end()
        self._scope = None
        self._span = None
        return trace_id


def result_attributes(observation: dict[str, Any]) -> dict[str, Any]:
    rerank_calls = observation.get("per_need_rerank_calls") or []
    rerank_latencies = [float(call.get("latency_ms") or 0) for call in rerank_calls]
    rerank_tokens = sum(int((call.get("usage") or {}).get("total_tokens") or 0) for call in rerank_calls)
    degraded_count = sum(bool(call.get("degraded")) for call in rerank_calls)
    processor_usage = observation.get("query_processor_usage") or {}
    return {
        "globex.eval.latency_ms": observation.get("latency_ms"),
        "globex.eval.retrieval_mode": observation.get("retrieval_mode"),
        "globex.eval.processor_plan_mode": observation.get("processor_plan_mode"),
        "globex.eval.effective_plan_mode": observation.get("effective_plan_mode"),
        "globex.eval.processor_fallback": bool(observation.get("processor_fallback_reason")),
        "globex.eval.candidate_count": observation.get("candidate_count"),
        "globex.eval.evidence_recall": observation.get("evidence_recall"),
        "globex.eval.all_evidence_recall": observation.get("all_evidence_recall"),
        "globex.eval.available_evidence_recall": observation.get("available_evidence_recall"),
        "globex.eval.information_need_coverage": observation.get("post_fusion_information_need_coverage"),
        "globex.eval.fusion_need_loss": observation.get("fusion_information_need_loss"),
        "globex.eval.hard_negative_hit": observation.get("hard_negative_hit"),
        "globex.eval.unanswerable_pass": observation.get("unanswerable_pass"),
        "globex.eval.query_processor_latency_ms": observation.get("query_processor_latency_ms"),
        "globex.eval.query_processor_input_tokens": int(processor_usage.get("input_tokens") or 0),
        "globex.eval.query_processor_output_tokens": int(processor_usage.get("output_tokens") or 0),
        "globex.eval.reranker_call_count": len(rerank_calls),
        "globex.eval.reranker_wall_ms": max(rerank_latencies, default=0.0),
        "globex.eval.reranker_total_tokens": rerank_tokens,
        "globex.eval.reranker_degraded_count": degraded_count,
    }
