import json
from types import SimpleNamespace

import pytest
from agentscope.message import UserMsg

from app.infrastructure.local_context_capture import LocalContextCaptureMiddleware
from app.infrastructure.tracing import build_agent_middlewares


pytestmark = pytest.mark.asyncio


async def test_captures_exact_pre_call_request_locally(tmp_path):
    middleware = LocalContextCaptureMiddleware(tmp_path, session_id="session-1")
    agent = SimpleNamespace(
        name="Main Agent",
        state=SimpleNamespace(session_id="session-1"),
        model=SimpleNamespace(model="test-model"),
    )
    messages = [UserMsg("buyer", "完整上下文中的敏感测试文本")]
    tools = [{"type": "function", "function": {"name": "lookup", "description": "完整工具说明"}}]
    marker = object()
    observed = {}

    async def next_handler(**kwargs):
        observed.update(kwargs)
        return marker

    result = await middleware.on_model_call(agent, {
        "current_model": agent.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }, next_handler)

    assert result is marker
    assert observed["messages"] is messages
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["capture_mode"] == "local_only"
    assert payload["session_id"] == "session-1"
    assert payload["model_name"] == "test-model"
    # AgentScope serializes text as structured content blocks; keep that exact wire shape.
    assert payload["request"]["messages"][0]["content"][0]["text"] == "完整上下文中的敏感测试文本"
    assert payload["request"]["tools"] == tools
    assert "current_model" not in payload["request"]


async def test_session_filter_skips_other_sessions(tmp_path):
    middleware = LocalContextCaptureMiddleware(tmp_path, session_id="wanted")
    agent = SimpleNamespace(name="agent", state=SimpleNamespace(session_id="other"))

    async def next_handler(**_kwargs):
        return "ok"

    assert await middleware.on_model_call(agent, {"messages": []}, next_handler) == "ok"
    assert not list(tmp_path.rglob("*.json"))


async def test_middleware_is_only_installed_for_local_only(tmp_path):
    from dataclasses import replace
    from tests.test_retrieval import _settings

    disabled = build_agent_middlewares(_settings(tmp_path))
    enabled = build_agent_middlewares(replace(
        _settings(tmp_path),
        trace_context_capture="local_only",
        trace_context_capture_dir=tmp_path,
    ))
    assert not any(isinstance(item, LocalContextCaptureMiddleware) for item in disabled)
    assert isinstance(enabled[-1], LocalContextCaptureMiddleware)
