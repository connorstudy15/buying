"""Versioned operation-cost profiles and an offline builder."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .models import ResourceEstimate


@dataclass(frozen=True)
class OperationProfileKey:
    environment: str
    component: str
    operation: str
    model: str
    execution_path: str
    context_bucket: str
    candidate_bucket: str
    prompt_version: str
    policy_version: str
    execution_contract_hash: str


@dataclass(frozen=True)
class OperationProfile:
    key: OperationProfileKey
    sample_count: int
    p50: ResourceEstimate
    p80: ResourceEstimate
    p95: ResourceEstimate
    confidence: str
    profile_version: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def estimate(self, percentile: str = "p80") -> ResourceEstimate:
        if percentile not in {"p50", "p80", "p95"}:
            raise ValueError("percentile 仅支持 p50/p80/p95")
        return getattr(self, percentile)


def execution_contract_hash(
    *, component: str, operation: str, prompt_version: str,
    policy_version: str, relevant_code_version: str,
) -> str:
    raw = "\0".join((component, operation, prompt_version, policy_version, relevant_code_version))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class OperationProfileStore:
    def __init__(self) -> None:
        self._profiles: dict[OperationProfileKey, OperationProfile] = {}

    def put(self, profile: OperationProfile) -> None:
        self._profiles[profile.key] = profile

    def all(self) -> tuple[OperationProfile, ...]:
        return tuple(self._profiles.values())

    def resolve(self, key: OperationProfileKey) -> tuple[OperationProfile | None, str]:
        exact = self._profiles.get(key)
        if exact is not None:
            return exact, "exact"
        # Phase 2.5 fallback order is explicit. Prompt/policy/contract drift is
        # allowed only after the exact route profile misses, and confidence is
        # carried forward so policy can keep weak profiles shadow-only.
        candidates = [
            value for candidate, value in self._profiles.items()
            if candidate.component == key.component
            and candidate.operation == key.operation
            and candidate.model == key.model
            and candidate.context_bucket == key.context_bucket
        ]
        if candidates:
            return max(candidates, key=lambda item: item.sample_count), "operation_model_context_fallback"
        candidates = [
            value for candidate, value in self._profiles.items()
            if candidate.component == key.component and candidate.operation == key.operation
            and candidate.model == key.model
        ]
        if candidates:
            return max(candidates, key=lambda item: item.sample_count), "operation_model_fallback"
        candidates = [
            value for candidate, value in self._profiles.items()
            if candidate.component == key.component and candidate.model == key.model
        ]
        if candidates:
            return max(candidates, key=lambda item: item.sample_count), "component_model_fallback"
        return None, "bootstrap"

    def write_json(self, path: Path) -> None:
        rows = []
        for item in self.all():
            row = asdict(item)
            for name in ("p50", "p80", "p95"):
                row[name]["monetary_cost"] = (
                    str(row[name]["monetary_cost"])
                    if row[name]["monetary_cost"] is not None else None
                )
            rows.append(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


class OperationProfileBuilder:
    """Build profiles from normalized, content-free observation rows."""

    DIMENSIONS = (
        "chat_input_tokens", "chat_output_tokens", "embedding_tokens",
        "rerank_tokens", "api_calls", "latency_ms",
    )

    def build(
        self, key: OperationProfileKey, observations: Iterable[dict[str, Any]], *,
        git_commit: str = "", relevant_code_version: str = "",
    ) -> OperationProfile:
        rows = list(observations)
        if not rows:
            raise ValueError("至少需要一条 observation")

        def estimate(percentile: float) -> ResourceEstimate:
            values = {
                name: self._nearest_rank(
                    [max(0, int(row.get(name) or 0)) for row in rows], percentile,
                )
                for name in self.DIMENSIONS
            }
            costs = [Decimal(str(row["monetary_cost"])) for row in rows if row.get("monetary_cost") is not None]
            cost = self._nearest_rank(costs, percentile) if len(costs) == len(rows) else None
            return ResourceEstimate(**values, monetary_cost=cost)

        count = len(rows)
        confidence = "high" if count >= 50 else "medium" if count >= 15 else "low"
        built_at = datetime.now(timezone.utc).isoformat()
        profile_version = hashlib.sha256(json.dumps({
            "key": asdict(key), "count": count, "built_at": built_at,
        }, sort_keys=True).encode()).hexdigest()[:16]
        return OperationProfile(
            key=key,
            sample_count=count,
            p50=estimate(0.50),
            p80=estimate(0.80),
            p95=estimate(0.95),
            confidence=confidence,
            profile_version=profile_version,
            metadata={
                "built_at": built_at,
                "git_commit": git_commit,
                "relevant_code_version": relevant_code_version,
                "git_commit_is_audit_metadata_only": True,
            },
        )

    @staticmethod
    def _nearest_rank(values: list, percentile: float):
        if not values:
            return 0
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))]


def bootstrap_profiles(model: str) -> dict[str, ResourceEstimate]:
    """Trace-informed starting values, not claimed as proven optimal values."""
    return {
        "main.plan": ResourceEstimate(chat_input_tokens=16101, chat_output_tokens=658,
                                      api_calls=1, latency_ms=10250, monetary_cost=None),
        "main.final": ResourceEstimate(chat_input_tokens=23407, chat_output_tokens=1531,
                                       api_calls=1, latency_ms=18880, monetary_cost=None),
        "query_processor.direct": ResourceEstimate(chat_input_tokens=560, chat_output_tokens=78,
                                                    api_calls=1, latency_ms=1137, monetary_cost=None),
        "query_processor.decompose": ResourceEstimate(chat_input_tokens=600, chat_output_tokens=108,
                                                       api_calls=1, latency_ms=1627, monetary_cost=None),
        "query_processor.classify": ResourceEstimate(chat_input_tokens=600, chat_output_tokens=108,
                                                       api_calls=1, latency_ms=1627, monetary_cost=None),
        "search.plan": ResourceEstimate(chat_input_tokens=16101, chat_output_tokens=658,
                                         api_calls=1, latency_ms=10250, monetary_cost=None),
        "search.final": ResourceEstimate(chat_input_tokens=23407, chat_output_tokens=1531,
                                          api_calls=1, latency_ms=18880, monetary_cost=None),
        "reranker.knowledge.need": ResourceEstimate(rerank_tokens=13253, api_calls=1,
                                                     latency_ms=523, monetary_cost=None),
        "embedding.request": ResourceEstimate(embedding_tokens=512, api_calls=1,
                                               latency_ms=350, monetary_cost=None),
        "embedding.product_query": ResourceEstimate(embedding_tokens=40, api_calls=1,
                                                      latency_ms=350, monetary_cost=None),
        "reranker.product": ResourceEstimate(rerank_tokens=1250, api_calls=1,
                                               latency_ms=700, monetary_cost=None),
    }

