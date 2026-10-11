"""Approval comes from frozen test actions, never inferred from model text."""
import json
from pathlib import Path

import httpx
import pytest
import yaml

from scripts.eval.memory_actions import agui_turn, execute_memory_action, validate_memory_actions


def action():
    return {"after_turn": 1, "tool": "remember_preference_tool",
        "expected_input": {"kind": "dislike", "statement": "不要合成聚合物材质"}, "approved": True}


def test_v2_keeps_all_original_questions_and_rubrics():
    root = Path(__file__).resolve().parents[1]
    before = yaml.safe_load((root / "eval/v1/agent_cases.yaml").read_text(encoding="utf-8"))
    after = yaml.safe_load((root / "eval/v2/agent_cases.yaml").read_text(encoding="utf-8"))
    for case in after["cases"]:
        if case.get("scenario") == "memory_multiturn":
            assert case.pop("memory_actions") == [action()]
    assert before == after


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_approval_requires_literal_bool(value):
    with pytest.raises(ValueError):
        validate_memory_actions({"queries": ["remember"], "memory_actions": [{**action(), "approved": value}]})


async def test_memory_resume_matches_input_and_uses_only_server_interrupt_id():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        events = [{"type": "STATE_SNAPSHOT", "snapshot": {"toolApprovals": []}},
            {"type": "MESSAGES_SNAPSHOT", "messages": [{"role": "assistant", "content": "已保存"}]},
            {"type": "RUN_FINISHED"}]
        return httpx.Response(200, text="\n\n".join("data: " + json.dumps(e) for e in events))
    state = {"toolApprovals": [{"id": "server-reply:server-call", "tool": action()["tool"], "arguments": json.dumps(action()["expected_input"])}]}
    events = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        final = await execute_memory_action(client, "http://test", "buyer", "session", action(), state, events)
        assert final == "已保存"
        assert requests[0]["resume"] == [{"interruptId": "server-reply:server-call", "status": "resolved", "payload": {"approved": True}}]
        with pytest.raises(ValueError, match="唯一"):
            await execute_memory_action(client, "http://test", "buyer", "session",
                {**action(), "expected_input": {"kind": "like", "statement": "其他偏好"}}, state, events)
        assert len(requests) == 1


async def test_incomplete_agui_stream_cannot_count_as_success():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='data: {"type":"STATE_SNAPSHOT","snapshot":{}}\n\n'))) as client:
        with pytest.raises(ValueError, match="完整终态"):
            await agui_turn(client, "http://test", "buyer", "session", "查询")
