"""Explicit evaluation clicks through the same AG-UI resume API as the browser."""
from __future__ import annotations

import json
import uuid

from scripts.eval.http_actions import matches_expected


def validate_memory_actions(case):
    actions = case.get("memory_actions", [])
    if not isinstance(actions, list):
        raise ValueError("memory_actions 必须是显式动作列表")
    for action in actions:
        if not isinstance(action, dict) or set(action) != {"after_turn", "tool", "expected_input", "approved"}:
            raise ValueError("记忆确认必须绑定轮次、工具、输入和明确布尔决议")
        if action["tool"] != "remember_preference_tool" or type(action["approved"]) is not bool:
            raise ValueError("不支持的记忆确认动作")
        if type(action["after_turn"]) is not int or not 1 <= action["after_turn"] <= len(case["queries"]):
            raise ValueError("记忆确认轮次无效")
        if (not isinstance(action["expected_input"], dict)
                or set(action["expected_input"]) != {"kind", "statement"}
                or action["expected_input"]["kind"] not in {"like", "dislike"}
                or not isinstance(action["expected_input"]["statement"], str)
                or not action["expected_input"]["statement"].strip()):
            raise ValueError("记忆确认需完整偏好输入")
    return actions


async def agui_turn(client, base_url, buyer_id, session_id, query, *, resume=None):
    run = "eval-" + uuid.uuid4().hex
    body = {"threadId": session_id, "runId": run,
        "messages": [{"id": "user-" + run, "role": "user", "content": query}],
        "state": {}, "tools": [], "context": [], "forwardedProps": {"buyerId": buyer_id, "locale": "zh-CN", "currency": "CNY"}}
    if resume:
        body["resume"] = resume
    response = await client.post(base_url + "/commerce/ag-ui/run", json=body, timeout=600)
    response.raise_for_status()
    final, state, finished = "", {}, False
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        event = json.loads(line[5:].strip())
        if event["type"] == "RUN_ERROR":
            raise ValueError("AG-UI 运行失败：" + str(event.get("message")))
        if event["type"] == "STATE_SNAPSHOT":
            state = event["snapshot"]
        if event["type"] == "MESSAGES_SNAPSHOT":
            replies = [m for m in event["messages"] if m.get("role") == "assistant"]
            if replies:
                final = replies[-1].get("content", "")
        if event["type"] == "RUN_FINISHED":
            finished = True
    if not finished:
        raise ValueError("AG-UI 未返回完整终态")
    return final, state


async def execute_memory_action(client, base_url, buyer_id, session_id, action, state, events):
    matches = []
    for item in state.get("toolApprovals", []):
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if item.get("tool") == action["tool"] and matches_expected(arguments, action["expected_input"]):
            matches.append(item)
    if len(matches) != 1:
        raise ValueError("没有唯一、输入完整匹配的待确认记忆；不会批准其他操作")
    identifier = matches[0]["id"]
    events.append({"type": "eval.memory_action.invoke", "payload": {**action, "interrupt_id": identifier}})
    final, result = await agui_turn(client, base_url, buyer_id, session_id, "处理本次记忆确认",
        resume=[{"interruptId": identifier, "status": "resolved", "payload": {"approved": action["approved"]}}])
    if result.get("toolApprovals"):
        raise ValueError("记忆确认后仍存在待审批操作，不能视为已完成")
    events.append({"type": "eval.memory_action.result", "payload": {"interrupt_id": identifier, "approved": action["approved"]}})
    return final
