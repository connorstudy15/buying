"""A single commerce turn's evidence and lifecycle projection for tracing.

The projection deliberately keeps only bounded, non-authoritative diagnostics.  In
particular, a knowledge tool result means that evidence was *supplied* to the
agent; it does not prove that the final prose adopted that evidence.  Product IDs
are the only adoption signal we can currently verify explicitly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.infrastructure.eventbus import TradeEvent


_PRODUCT_ID = re.compile(r"(?<![A-Za-z0-9])P\d+(?:-S\d+)?(?![A-Za-z0-9])")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_strings(item))
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            result.extend(_strings(item))
        return result
    return []


def _product_ids(value: Any) -> set[str]:
    return {match for text in _strings(value) for match in _PRODUCT_ID.findall(text)}


def _evidence_refs(payload: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key in ("result_ref", "summary_ref"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            refs.add(value)
    for value in payload.get("result_refs", []):
        if isinstance(value, str) and value:
            refs.add(value)
    return refs


@dataclass
class TurnTraceCollector:
    """Reduce TradeEventBus events to a stable end-to-end trace summary."""

    session_id: str
    dispatch_agents: list[str] = field(default_factory=list)
    invoked_tools: list[str] = field(default_factory=list)
    completed_tools: list[str] = field(default_factory=list)
    evidence_refs: set[str] = field(default_factory=set)
    verified_product_ids: set[str] = field(default_factory=set)
    degraded_steps: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    context_compactions: list[dict[str, Any]] = field(default_factory=list)
    cache_hit: bool = False
    model_fallback: bool = False
    knowledge_results: int = 0

    def observe(self, event: TradeEvent) -> None:
        if event.shopping_session_id != self.session_id:
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.type == "agent.dispatch":
            agent = payload.get("agent")
            if isinstance(agent, str):
                self.dispatch_agents.append(agent)
        elif event.type == "tool.invoke":
            tool = payload.get("tool")
            if isinstance(tool, str):
                self.invoked_tools.append(tool)
        elif event.type == "tool.result":
            tool = payload.get("tool")
            if isinstance(tool, str):
                self.completed_tools.append(tool)
            self.evidence_refs.update(_evidence_refs(payload))
            self.verified_product_ids.update(_product_ids(payload.get("hits", [])))
            self.verified_product_ids.update(_product_ids(payload.get("verified_product_ids", [])))
            if tool == "category_insight_tool":
                self.knowledge_results += 1
            reason = payload.get("degraded_reason")
            circuit = payload.get("circuit")
            if reason or circuit:
                self.degraded_steps.append({
                    "step": str(tool or "tool"),
                    "reason": str(reason or circuit),
                })
            if payload.get("error"):
                self.errors.append(str(tool or "tool"))
        elif event.type == "context.compressed":
            self.context_compactions.append({
                key: payload[key]
                for key in (
                    "status", "reason", "before_tokens", "after_tokens",
                    "archived_results", "summary_changed", "elapsed_ms",
                )
                if key in payload
            })
        elif event.type == "cache.hit":
            self.cache_hit = True
        elif event.type == "model.fallback":
            self.model_fallback = True
            self.degraded_steps.append({"step": "model", "reason": "fallback"})
        elif event.type == "error" and not payload.get("retrying"):
            self.errors.append(str(payload.get("code") or "turn"))

    def summary(self, final_text: str, *, error_code: str | None = None) -> dict[str, Any]:
        mentioned = set(_PRODUCT_ID.findall(final_text or ""))
        explicit = mentioned & self.verified_product_ids
        unverified = mentioned - self.verified_product_ids
        knowledge_observable = False
        return {
            "status": "error" if error_code else "completed",
            "error_code": error_code,
            "dispatch_count": len(self.dispatch_agents),
            "dispatch_agents": self.dispatch_agents,
            "tool_invoke_count": len(self.invoked_tools),
            "tool_result_count": len(self.completed_tools),
            "invoked_tools": self.invoked_tools,
            "completed_tools": self.completed_tools,
            "evidence_refs_supplied": sorted(self.evidence_refs),
            "verified_product_ids": sorted(self.verified_product_ids),
            "explicitly_referenced_product_ids": sorted(explicit),
            "unverified_product_ids": sorted(unverified),
            "knowledge_result_count": self.knowledge_results,
            "knowledge_adoption_observable": knowledge_observable,
            "knowledge_adoption_status": (
                "not_observable" if self.knowledge_results else "not_applicable"
            ),
            "degraded_steps": self.degraded_steps,
            "degraded_count": len(self.degraded_steps),
            "error_steps": self.errors,
            "cache_hit": self.cache_hit,
            "model_fallback": self.model_fallback,
            "context_compactions": self.context_compactions,
            "final_text": final_text,
        }
