"""真实装配与 HTTP 路由集成；外部模型和向量灌库使用隔离替身。"""
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import composition
from app.infrastructure.settings import load_settings
from app.presentation import server


@pytest.mark.asyncio
async def test_integrated_features_start_with_signed_identity_and_isolated_storage(tmp_path, monkeypatch):
    settings = replace(
        load_settings(require_llm_key=False),
        data_dir=tmp_path, database_url=f"sqlite+aiosqlite:///{tmp_path / 'globex.db'}",
        llm_api_key="synthetic-key", llm_base_url="https://model.example/v1",
        llm_model="synthetic-model", llm_fallback_model="",
        embedding_api_key="synthetic-key", embedding_base_url="https://embedding.example/v1",
        reranker_api_key="synthetic-key", reranker_base_url="",
        redis_url="", qdrant_url="", queue_enabled=False,
        identity_mode="hmac", identity_hmac_secret="integration-secret-" * 3,
        prompt_pin_version="", model_master_key="", model_admin_buyers=("owner",),
        knowledge_query_transform_enabled=False, automation_worker_mode="embedded",
    )
    monkeypatch.setattr(composition, "load_settings", lambda: settings)
    monkeypatch.setattr(composition, "setup_tracing", lambda *_: None)
    monkeypatch.setattr(composition, "shutdown_tracing", lambda: None)
    monkeypatch.setattr(composition, "bootstrap_product_index", AsyncMock())
    monkeypatch.setattr(composition, "bootstrap_category_knowledge", AsyncMock())
    container = await composition.build_container()
    monkeypatch.setattr(server, "build_container", AsyncMock(return_value=container))
    api = server.build_app()
    async with api.router.lifespan_context(api):
        assert container.automation_task is not None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
            assert (await client.get("/commerce/auth")).json() == {"mode": "hmac", "authenticated": False}
            headers = {"Authorization": "Bearer " + container.identity_policy.issue("owner")}
            assert (await client.get("/commerce/auth", headers=headers)).json()["buyer_id"] == "owner"
            for path in ("/commerce/models", "/commerce/automations", "/commerce/ag-ui/sessions"):
                params = {"buyer_id": "owner", "session_id": "integration-session"}
                assert (await client.get(path, params=params)).status_code == 401
                result = await client.get(path, params=params, headers=headers)
                assert result.status_code == 200, result.text
                assert (await client.get(path, params={**params, "buyer_id": "other"}, headers=headers)).status_code == 403
    assert container.automation_task.done()
