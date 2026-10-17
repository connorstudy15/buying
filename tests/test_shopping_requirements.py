import json

import pytest

from app.infrastructure.shopping_forms import ShoppingFormStore, RequirementReviewRequest, FormConflict


FIELDS = [
    {"id": "budget", "label": "预算", "value": "单件不超过500元，运税范围未明确",
     "status": "extracted", "source_quote": "预算500元以内", "constraint_kind": "hard"},
    {"id": "purpose", "label": "用途", "value": "通勤", "status": "extracted", "source_quote": "上班背"},
    {"id": "laptop_size", "label": "电脑尺寸", "status": "unknown"},
    {"id": "weight", "label": "重量偏好", "value": "尽量轻", "status": "inferred", "constraint_kind": "preference"},
]


async def test_review_edit_clear_restore_and_confirm(tmp_path):
    path = tmp_path / "forms.db"
    store = ShoppingFormStore(path)
    form = await store.create_review("b", "s", "通勤背包需求", FIELDS, "旧预算500元，尽量轻")
    assert "laptop_size" not in form["defaults"]
    assert form["submission"] is None
    assert form["messages"][1]["updateComponents"]["components"][0]["review"] == form["review"]
    values = {"budget": "单件不超过300元，不含运税", "purpose": "通勤", "laptop_size": "14英寸", "weight": ""}
    result = await store.submit("b", "s", form["form_id"], 1, "r", values)
    payload = json.loads(result["query"].split("\n", 1)[1])
    assert payload["requirements_confirmed"] is True
    assert payload["requirements"][0]["value"] == values["budget"]
    assert payload["requirements"][0]["constraint_kind"] == "unspecified"
    assert payload["agent_context"] == ""
    assert all(f["status"] == "confirmed" for f in payload["requirements"])
    assert payload["unanswered"] == [{"id": "weight", "question": "重量偏好"}]
    assert "500" not in result["query"] and "尽量轻" not in result["query"]
    assert await store.submit("b", "s", form["form_id"], 1, "r", values) == result
    assert (await ShoppingFormStore(path).get("b", "s", form["form_id"]))["submission"] == result
    with pytest.raises(FormConflict):
        await store.submit("b", "s", form["form_id"], 1, "r2", values)
    with pytest.raises(LookupError):
        await store.submit("other", "s", form["form_id"], 1, "r", values)


@pytest.mark.parametrize("field", [
    {"id": "a", "label": "预算", "value": "500", "status": "unknown"},
    {"id": "a", "label": "预算", "value": "500", "status": "extracted"},
    {"id": "constructor", "label": "字段"},
    {"id": "a", "label": "预算", "status": "inferred"},
    {"id": "a", "label": "预算", "value": 500},
])
async def test_invalid_extraction_never_saved(tmp_path, field):
    store = ShoppingFormStore(tmp_path / "forms.db")
    with pytest.raises(ValueError):
        await store.create_review("b", "s", "需求", [field])
    assert await store.latest("b", "s") is None


async def test_empty_confirmation_rejected(tmp_path):
    store = ShoppingFormStore(tmp_path / "forms.db")
    form = await store.create_review("b", "s", "需求", FIELDS)
    with pytest.raises(ValueError, match="至少保留"):
        await store.submit("b", "s", form["form_id"], 1, "r", {})
    assert (await store.get("b", "s", form["form_id"]))["submission"] is None


async def test_agent_calls_review_tool_and_projects_card(tmp_path):
    from agentscope.agent import Agent
    from agentscope.message import TextBlock, ToolCallBlock, UserMsg
    from agentscope.model import ChatResponse
    from agentscope.tool import FunctionTool, Toolkit
    from app.application.agents.permissions import allow_business_tools
    from app.application.tools.shopping_requirements_tool import build_shopping_requirements_tool
    from app.infrastructure.context import ShoppingContext, ShoppingContextSnapshot
    from app.infrastructure.eventbus import TradeEventBus, observe_run_events
    from app.application.agents.ag_ui_adapter import AGUIRunAdapter
    from ag_ui.core import RunAgentInput
    from tests.test_ag_ui import request_data
    from tests.test_native_memory_confirmation import Model

    class ReviewingModel(Model):
        async def _invoke_upstream(self, *args, **kwargs):
            self.calls += 1
            blocks = [ToolCallBlock(id="review", name="show_shopping_requirements", input=json.dumps({
                "title": "通勤背包需求", "fields": FIELDS,
            }, ensure_ascii=False))] if self.calls == 1 else [TextBlock(text="请核对需求卡")]
            return ChatResponse(content=blocks, is_last=True)

    model = ReviewingModel()
    store = ShoppingFormStore(tmp_path / "forms.db")
    tool = FunctionTool(build_shopping_requirements_tool(store, TradeEventBus()), input_schema=RequirementReviewRequest)
    agent = allow_business_tools(Agent("test", "整理需求", model, toolkit=Toolkit(tools=[tool])))
    adapter = AGUIRunAdapter(RunAgentInput(**request_data()), lambda e: None)
    token = ShoppingContext.set(ShoppingContextSnapshot("session-test", "buyer-test", "zh-CN", "CNY"))
    try:
        with observe_run_events(adapter.on_trade_event):
            _ = [e async for e in agent.reply_stream(UserMsg("buyer", "预算500元以内，买个上班背的包"))]
        assert adapter.state["shoppingForm"]["review"][0]["value"].startswith("单件不超过500")
        form = await store.latest("buyer-test", "session-test")
        result = await store.submit("buyer-test", "session-test", form["form_id"], 1, "r", {"budget": "300元"})
        _ = [e async for e in agent.reply_stream(UserMsg("buyer", result["query"]))]
        assert model.calls == 3
        assert any(block.get("text") == result["query"] for message in agent.state.model_dump()["context"] for block in message["content"])
    finally:
        ShoppingContext.reset(token)
        await model.client.close()
