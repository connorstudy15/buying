# -*- coding: utf-8 -*-
"""DashScope 原生 embedding 客户端，仅用于 Dual-Tower D0-role 实验。

与正式 ``OpenAIEmbeddingClient`` 完全隔离。这里不提供兼容接口 fallback，
从而避免原生 API 失败时把旧 embedding 冒充成 D0-role 结果。
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

TextType = Literal["query", "document"]


class DashScopeEmbeddingError(RuntimeError):
    """保留可诊断、但不包含密钥的原生 API 错误。"""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        provider_code: str | None = None,
        request_id: str | None = None,
        request_mode: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.provider_code = provider_code
        self.request_id = request_id
        self.request_mode = request_mode
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "http_status": self.http_status,
            "provider_code": self.provider_code,
            "request_id": self.request_id,
            "request_mode": self.request_mode,
            "retryable": self.retryable,
            "fallback_used": False,
        }


@dataclass(frozen=True)
class DashScopeEmbeddingConfig:
    endpoint: str
    api_key: str
    model: str = "qwen3.7-text-embedding-flash"
    dimension: int = 1024
    max_batch: int = 20
    timeout_seconds: float = 30.0
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "DashScopeEmbeddingConfig":
        endpoint = os.getenv("DUAL_TOWER_NATIVE_ENDPOINT", "").strip()
        if not endpoint:
            base = (
                os.getenv("DUAL_TOWER_BASE_URL", "").strip()
                or os.getenv("EMBEDDING_BASE_URL", "").strip()
                or os.getenv("LLM_BASE_URL", "").strip()
            )
            endpoint = native_endpoint_from_compatible_url(base)
        api_key = (
            os.getenv("DUAL_TOWER_API_KEY", "").strip()
            or os.getenv("EMBEDDING_API_KEY", "").strip()
            or os.getenv("LLM_API_KEY", "").strip()
        )
        if not endpoint:
            raise ValueError("缺少 DUAL_TOWER_NATIVE_ENDPOINT（或可推导的 BASE_URL）")
        if not api_key:
            raise ValueError("缺少 DUAL_TOWER_API_KEY（或 EMBEDDING_API_KEY / LLM_API_KEY）")
        return cls(
            endpoint=endpoint,
            api_key=api_key,
            model=os.getenv("DUAL_TOWER_MODEL", "qwen3.7-text-embedding-flash"),
            dimension=int(os.getenv("DUAL_TOWER_DIMENSION", "1024")),
            max_batch=int(os.getenv("DUAL_TOWER_MAX_BATCH", "20")),
            timeout_seconds=float(os.getenv("DUAL_TOWER_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("DUAL_TOWER_MAX_RETRIES", "2")),
        )


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: list[list[float]]
    latency_ms: float
    attempts: int
    request_count: int
    total_tokens: int | None
    text_type: TextType


def native_endpoint_from_compatible_url(url: str) -> str:
    """从当前工作空间兼容网关推导同一工作空间的原生 embedding endpoint。"""
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"无法识别 BASE_URL：{url!r}")
    path = "/api/v1/services/embeddings/text-embedding/text-embedding"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class DashScopeRoleEmbeddingClient:
    def __init__(
        self,
        config: DashScopeEmbeddingConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    async def embed_queries(self, texts: list[str]) -> EmbeddingBatchResult:
        return await self.embed(texts, text_type="query")

    async def embed_documents(self, texts: list[str]) -> EmbeddingBatchResult:
        return await self.embed(texts, text_type="document")

    async def embed(self, texts: list[str], *, text_type: TextType) -> EmbeddingBatchResult:
        if not texts:
            return EmbeddingBatchResult([], 0.0, 0, 0, 0, text_type)
        vectors: list[list[float]] = []
        total_attempts = 0
        request_count = 0
        token_total: int | None = 0
        started = time.perf_counter()
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            transport=self._transport,
        ) as client:
            for start in range(0, len(texts), self.config.max_batch):
                chunk = texts[start : start + self.config.max_batch]
                chunk_vectors, attempts, tokens = await self._embed_chunk(
                    client, chunk, text_type=text_type,
                )
                vectors.extend(chunk_vectors)
                total_attempts += attempts
                request_count += 1
                if tokens is None:
                    token_total = None
                elif token_total is not None:
                    token_total += tokens
        return EmbeddingBatchResult(
            vectors=vectors,
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=total_attempts,
            request_count=request_count,
            total_tokens=token_total,
            text_type=text_type,
        )

    async def _embed_chunk(
        self,
        client: httpx.AsyncClient,
        texts: list[str],
        *,
        text_type: TextType,
    ) -> tuple[list[list[float]], int, int | None]:
        mode = f"dashscope_native:text_type={text_type}"
        payload = {
            "model": self.config.model,
            "input": {"texts": texts},
            "parameters": {
                "text_type": text_type,
                "dimension": self.config.dimension,
            },
        }
        attempts = 0
        while True:
            attempts += 1
            try:
                response = await client.post(
                    self.config.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.RequestError as exc:
                if attempts <= self.config.max_retries:
                    await asyncio.sleep(0.25 * (2 ** (attempts - 1)))
                    continue
                raise DashScopeEmbeddingError(
                    f"DashScope 原生 embedding 网络错误：{type(exc).__name__}: {exc}",
                    request_mode=mode,
                    retryable=True,
                ) from exc

            body = _safe_json(response)
            if response.is_success:
                vectors = _extract_vectors(body)
                if len(vectors) != len(texts):
                    raise DashScopeEmbeddingError(
                        f"embedding 数量不一致：请求 {len(texts)}，返回 {len(vectors)}",
                        http_status=response.status_code,
                        provider_code=_provider_code(body),
                        request_id=_request_id(body, response),
                        request_mode=mode,
                    )
                dimensions = {len(vector) for vector in vectors}
                if dimensions != {self.config.dimension}:
                    raise DashScopeEmbeddingError(
                        f"embedding 维度不一致：期望 {self.config.dimension}，返回 {sorted(dimensions)}",
                        http_status=response.status_code,
                        provider_code=_provider_code(body),
                        request_id=_request_id(body, response),
                        request_mode=mode,
                    )
                return vectors, attempts, _usage_tokens(body)

            retryable = response.status_code in {408, 429} or response.status_code >= 500
            if retryable and attempts <= self.config.max_retries:
                await asyncio.sleep(0.25 * (2 ** (attempts - 1)))
                continue
            message = _provider_message(body) or response.text[:500] or response.reason_phrase
            raise DashScopeEmbeddingError(
                f"DashScope 原生 embedding 调用失败：HTTP {response.status_code}: {message}",
                http_status=response.status_code,
                provider_code=_provider_code(body),
                request_id=_request_id(body, response),
                request_mode=mode,
                retryable=retryable,
            )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
        return body if isinstance(body, dict) else {"raw": body}
    except ValueError:
        return {}


def _extract_vectors(body: dict[str, Any]) -> list[list[float]]:
    output = body.get("output") or {}
    embeddings = output.get("embeddings") or body.get("embeddings") or []
    ordered = sorted(
        embeddings,
        key=lambda item: item.get("text_index", item.get("index", 0)),
    )
    return [item["embedding"] for item in ordered if isinstance(item, dict) and "embedding" in item]


def _usage_tokens(body: dict[str, Any]) -> int | None:
    usage = body.get("usage") or {}
    for key in ("total_tokens", "input_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            return value
    return None


def _provider_code(body: dict[str, Any]) -> str | None:
    value = body.get("code") or body.get("error", {}).get("code")
    return str(value) if value is not None else None


def _provider_message(body: dict[str, Any]) -> str | None:
    value = body.get("message") or body.get("error", {}).get("message")
    return str(value)[:500] if value is not None else None


def _request_id(body: dict[str, Any], response: httpx.Response) -> str | None:
    value = body.get("request_id") or response.headers.get("x-request-id")
    return str(value) if value is not None else None
