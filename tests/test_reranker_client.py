# -*- coding: utf-8 -*-
"""Reranker HTTP 契约回归。"""
from __future__ import annotations

import pytest

from app.infrastructure.rerank import http_reranker
from app.infrastructure.rerank.http_reranker import HttpReranker
from app.infrastructure.settings import load_settings


@pytest.mark.asyncio
async def test_full_reranker_endpoint_is_used_with_gateway_authorization(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.1},
                ],
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url: str, **kwargs):
            captured.update(url=url, **kwargs)
            return FakeResponse()

    monkeypatch.setenv("LLM_API_KEY", "test-gateway-key")
    monkeypatch.delenv("RERANKER_API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "RERANKER_BASE_URL",
        "https://1688openai.alibaba-inc.com/v1/services/reranker",
    )
    monkeypatch.setenv("RERANKER_MODEL", "qwen-text-rerank")
    monkeypatch.setattr(http_reranker.httpx, "AsyncClient", lambda **_: FakeClient())

    scores = await HttpReranker(load_settings()).rerank(
        "轻便旅行背包",
        ["20L 轻量旅行背包", "陶瓷咖啡杯"],
    )

    assert scores == [0.9, 0.1]
    assert captured["url"] == "https://1688openai.alibaba-inc.com/v1/services/reranker"
    assert captured["headers"] == {"Authorization": "Bearer test-gateway-key"}
    assert captured["json"] == {
        "model": "qwen-text-rerank",
        "query": "轻便旅行背包",
        "documents": ["20L 轻量旅行背包", "陶瓷咖啡杯"],
    }


@pytest.mark.asyncio
async def test_dashscope_text_rerank_uses_independent_key_and_nested_contract(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "usage": {"prompt_tokens": 321, "total_tokens": 321},
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.2},
                        {"index": 0, "relevance_score": 0.8},
                    ],
                },
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url: str, **kwargs):
            captured.update(url=url, **kwargs)
            return FakeResponse()

    endpoint = "https://workspace.example/api/v1/services/rerank/text-rerank/text-rerank"
    monkeypatch.setenv("LLM_API_KEY", "llm-key")
    monkeypatch.setenv("RERANKER_API_KEY", "reranker-key")
    monkeypatch.setenv("RERANKER_BASE_URL", endpoint)
    monkeypatch.setenv("RERANKER_MODEL", "qwen3.7-text-rerank")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(http_reranker.httpx, "AsyncClient", lambda **_: FakeClient())

    scores, usage = await HttpReranker(load_settings()).rerank_with_metadata("办公电脑", ["轻薄本", "游戏本"])

    assert scores == [0.8, 0.2]
    assert usage == {"prompt_tokens": 321, "total_tokens": 321, "document_count": 2}
    assert captured["url"] == endpoint
    assert captured["headers"] == {"Authorization": "Bearer reranker-key"}
    assert captured["json"] == {
        "model": "qwen3.7-text-rerank",
        "input": {"query": "办公电脑", "documents": ["轻薄本", "游戏本"]},
        "parameters": {"top_n": 2},
    }
