# -*- coding: utf-8 -*-
"""OpenAIEmbeddingClient

OpenAI 兼容 /v1/embeddings 客户端（httpx 直连，不引入 openai SDK 的 embedding 封装，
便于对接任意兼容网关）。模型默认 text-embedding-v4。
"""
from __future__ import annotations

import os
import logging
import time
import uuid

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.domain.catalog.ports.retrieval_ports import EmbeddingClient
from app.infrastructure.settings import Settings
from app.infrastructure.resource_governance.governor import current_governor
from app.infrastructure.resource_governance.models import ContextScope, ResourceEstimate
from app.infrastructure.resource_governance.operation import current_operation, current_execution

# 单次请求最多带多少条文本。
#
# 实测坑：内部 OpenAI 兼容网关在 input 超过 10 条时，会返回
# **HTTP 200 + content-type: application/json + 空 body**——
# `raise_for_status()` 因为状态码是 200 而放行，最终在 `response.json()` 处
# 抛出 `JSONDecodeError: Expecting value`，报错信息完全指不到真因。
#
# 更隐蔽的是：商品种子库原本恰好 10 个 SPU，正好卡在上限内，所以这个问题一直没暴露；
# 直到商品库扩到 60 个做召回评测，建库才开始整批失败——而 `bootstrap_product_index`
# 会吞掉异常降级到关键词召回，于是表现为「向量检索静默失效」而不是报错。
_MAX_BATCH = int(os.getenv("EMBEDDING_MAX_BATCH", "10"))
logger = logging.getLogger(__name__)


class OpenAIEmbeddingClient(EmbeddingClient):
    def __init__(self, settings: Settings, timeout_seconds: float = 15.0) -> None:
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._timeout = timeout_seconds

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # 分片串行请求：批量上限是网关侧约束，超限不会报错只会返回空 body
            for start in range(0, len(texts), _MAX_BATCH):
                chunk = texts[start : start + _MAX_BATCH]
                vectors.extend(await self._embed_chunk(client, chunk))
        return vectors

    async def _embed_chunk(
        self, client: httpx.AsyncClient, chunk: list[str],
    ) -> list[list[float]]:
        parent = current_operation()
        logical_id = f"{parent.logical_call_id}:embedding:{uuid.uuid4().hex[:8]}" if parent else uuid.uuid4().hex
        operation = parent.operation if parent and parent.operation.startswith("embedding.") else "embedding.request"
        governor = current_governor()
        if governor is not None:
            try:
                await governor.observe_started_operation(operation, logical_call_id=logical_id)
            except Exception as observation_error:
                logger.warning("embedding shadow start failed error_type=%s", type(observation_error).__name__)
        started = time.perf_counter()
        estimated_tokens = max(1, sum(len(text.encode("utf-8")) for text in chunk) // 3)
        with trace.get_tracer(__name__).start_as_current_span(
            "resource.embedding",
            attributes={
                "langfuse.observation.type": "embedding",
                "globex.trace.stage": "resource_operation",
                "globex.resource.logical_call_id": logical_id,
                "globex.resource.flow_id": current_execution().flow_id,
                "globex.resource.tool_call_id": current_execution().tool_call_id or "",
                "globex.resource.operation": operation,
                "globex.resource.component": "embedding_client",
                "globex.resource.context_scope": parent.context_scope.value if parent else ContextScope.SYSTEM.value,
                "globex.resource.embedding_tokens": estimated_tokens,
                "globex.resource.api_calls": 1,
                "globex.resource.shadow_only": True,
                "gen_ai.request.model": self._model,
            },
            record_exception=False, set_status_on_exception=False,
        ) as span:
            try:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": chunk},
                )
                response.raise_for_status()
                if not response.content:
                    # 明确指向批量上限，不要让调用方对着 JSONDecodeError 猜
                    raise RuntimeError(
                        f"embedding 网关返回空 body（HTTP {response.status_code}，本批 {len(chunk)} 条）："
                        f"通常是单次批量超过网关上限，可调小 EMBEDDING_MAX_BATCH（当前 {_MAX_BATCH}）",
                    )
                body = response.json()
                if "data" not in body:
                    raise RuntimeError(f"embedding 响应异常：{str(body)[:200]}")
                usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
                actual_tokens = int(usage.get("total_tokens") or usage.get("prompt_tokens") or estimated_tokens)
                span.set_attributes({
                    "globex.resource.embedding_tokens": actual_tokens,
                    "globex.resource.usage_source": "actual" if usage else "estimated_missing_usage",
                })
                if governor is not None:
                    try:
                        context = span.get_span_context()
                        governor.record_observed_usage(
                            logical_call_id=logical_id, attempt=1, operation=operation,
                            estimate=ResourceEstimate(
                                embedding_tokens=actual_tokens, api_calls=1, monetary_cost=None,
                                latency_ms=round((time.perf_counter() - started) * 1000),
                            ),
                            usage_source="actual" if usage else "estimated_missing_usage",
                            trace_id=f"{context.trace_id:032x}" if context.is_valid else "",
                            span_id=f"{context.span_id:016x}" if context.is_valid else "",
                        )
                        await governor.observe_completed_operation(operation, logical_call_id=logical_id)
                    except Exception as observation_error:
                        logger.warning("embedding shadow usage failed error_type=%s", type(observation_error).__name__)
                # 按 index 回位，避免网关乱序
                ordered = sorted(body["data"], key=lambda item: item["index"])
                return [item["embedding"] for item in ordered]
            except BaseException as error:
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                span.set_attribute("globex.resource.latency_ms", round((time.perf_counter() - started) * 1000, 3))
