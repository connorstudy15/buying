# -*- coding: utf-8 -*-
"""HttpReranker

HTTP 精排客户端（对接 Qwen3-Reranker 通用协议及百炼 text-rerank 协议）。
RERANKER_BASE_URL 未配置时组装根不会实例化本类；调用失败抛异常，
由 CatalogSearchUseCase 降级为按向量分排序并标注 rerank_applied=false。
"""
from __future__ import annotations

import httpx

from app.domain.catalog.ports.retrieval_ports import Reranker
from app.infrastructure.settings import Settings


class HttpReranker(Reranker):
    def __init__(self, settings: Settings, timeout_seconds: float = 3.0) -> None:
        endpoint = settings.reranker_base_url.rstrip("/")
        self._dashscope_text_rerank = "/services/rerank/text-rerank/text-rerank" in endpoint
        # 内部网关给出的是完整 /services/reranker endpoint；通用服务若只给根地址，
        # 仍兼容补上 /rerank。
        self._url = (
            endpoint
            if self._dashscope_text_rerank or endpoint.endswith(("/rerank", "/reranker", "/reranks"))
            else f"{endpoint}/rerank"
        )
        self._api_key = settings.reranker_api_key or settings.llm_api_key
        self._model = settings.reranker_model
        self._timeout = timeout_seconds
        self.last_usage: dict[str, int] = {}

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        scores, usage = await self.rerank_with_metadata(query, documents)
        self.last_usage = usage
        return scores

    async def rerank_with_metadata(
        self, query: str, documents: list[str],
    ) -> tuple[list[float], dict[str, int]]:
        if not documents:
            usage = {"prompt_tokens": 0, "total_tokens": 0, "document_count": 0}
            self.last_usage = usage
            return [], usage
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            payload = (
                {
                    "model": self._model,
                    "input": {"query": query, "documents": documents},
                    "parameters": {"top_n": len(documents)},
                }
                if self._dashscope_text_rerank
                else {"model": self._model, "query": query, "documents": documents}
            )
            response = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        usage_data = {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or usage.get("prompt_tokens") or 0),
            "document_count": len(documents),
        }
        self.last_usage = usage_data
        # 兼容 {results:[{index, relevance_score}]} 协议（Jina/TEI/vLLM rerank 通用形态）
        results = (body.get("output") or {}).get("results") if self._dashscope_text_rerank else body.get("results")
        if not isinstance(results, list) or len(results) != len(documents):
            raise RuntimeError(f"rerank 响应异常：{str(body)[:200]}")
        scores = [0.0] * len(documents)
        for item in results:
            scores[item["index"]] = float(item.get("relevance_score", item.get("score", 0.0)))
        return scores, usage_data
