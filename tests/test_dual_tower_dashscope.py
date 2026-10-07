from __future__ import annotations

import httpx
import pytest

from scripts.eval.dual_tower_dashscope import (
    DashScopeEmbeddingConfig,
    DashScopeEmbeddingError,
    DashScopeRoleEmbeddingClient,
    native_endpoint_from_compatible_url,
)


def _config() -> DashScopeEmbeddingConfig:
    return DashScopeEmbeddingConfig(
        endpoint="https://workspace.example/api/v1/services/embeddings/text-embedding/text-embedding",
        api_key="secret",
        dimension=3,
        max_retries=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("text_type", ["query", "document"])
async def test_native_payload_has_explicit_role(text_type: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        assert body["parameters"] == {"text_type": text_type, "dimension": 3}
        assert "instruct" not in body["parameters"]
        return httpx.Response(
            200,
            json={
                "output": {"embeddings": [{"text_index": 0, "embedding": [0.1, 0.2, 0.3]}]},
                "usage": {"total_tokens": 7},
            },
        )

    client = DashScopeRoleEmbeddingClient(_config(), transport=httpx.MockTransport(handler))
    result = await client.embed(["hello"], text_type=text_type)  # type: ignore[arg-type]
    assert result.vectors == [[0.1, 0.2, 0.3]]
    assert result.total_tokens == 7


@pytest.mark.asyncio
async def test_403_is_reported_without_fallback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"code": "AccessDenied.Unpurchased", "message": "not purchased", "request_id": "r1"},
        )

    client = DashScopeRoleEmbeddingClient(_config(), transport=httpx.MockTransport(handler))
    with pytest.raises(DashScopeEmbeddingError) as raised:
        await client.embed_queries(["hello"])
    error = raised.value.as_dict()
    assert error["http_status"] == 403
    assert error["provider_code"] == "AccessDenied.Unpurchased"
    assert error["request_mode"] == "dashscope_native:text_type=query"
    assert error["fallback_used"] is False


def test_native_endpoint_is_derived_from_workspace_compatible_url() -> None:
    assert native_endpoint_from_compatible_url(
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    ) == (
        "https://workspace.cn-beijing.maas.aliyuncs.com/"
        "api/v1/services/embeddings/text-embedding/text-embedding"
    )
