"""将模型提取的购物需求交给买家核对，复用持久表单和会话事件。"""
import json

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk
from app.infrastructure.context import ShoppingContext


def build_shopping_requirements_tool(store, bus):
    async def show_shopping_requirements(title: str, fields: list[dict], context: str = "") -> ToolChunk:
        """展示可编辑的购物需求确认卡，帮助买家核对 AI 对自然语言的理解。

        新选购目标包含预算、用途、尺寸、重量等多个条件，或买家要求整理/修改需求时调用。
        fields 每项提供 id、label、value、status、source_quote、constraint_kind。
        第一项必须包含想买的商品/选购目标，其他项按相关性列预算、用途、尺寸、重量及其他限制。
        status=extracted 表示来自买家明确表达，source_quote 必须逐字引用买家原话；
        inferred 表示你的推测，必须让用户核对；unknown 表示尚未明确，value 留空。
        constraint_kind=hard 仅用于明确硬约束，preference 用于偏好，否则 unspecified。
        金额在 value 中保留币种与单件/总预算/含税运范围；模糊的“轻一点”不能变成重量上限。
        按品类整理相关字段，禁止补造品牌、币种、尺寸或预算；所有字段在提交前均未确认。
        调用后结束本轮，等待用户修改并点击确认。收到 requirements_confirmed 后沿用答案继续
        检索，不重复生成同一确认卡；空字段保持未知。本卡不批准订单或写入长期偏好。

        Args:
            title: 本次购物需求标题。
            fields: 按展示顺序排列的需求字段及原话、来源状态、硬约束或偏好类型。
            context: 当前选购目标的简短背景。
        """
        ctx = ShoppingContext.current()
        if ctx is None:
            return ToolChunk(content=[TextBlock(text="缺少买家会话")], state=ToolResultState.ERROR)
        try:
            form = await store.create_review(ctx.buyer_id, ctx.shopping_session_id, title, fields, context)
        except ValueError as error:
            return ToolChunk(content=[TextBlock(text=str(error))], state=ToolResultState.ERROR)
        bus.publish(ctx.shopping_session_id, "ui.surface", {"buyer_id": ctx.buyer_id, "form": form})
        return ToolChunk(content=[TextBlock(text=json.dumps({
            "form_id": form["form_id"], "status": "awaiting_confirmation",
            "notice": "需求卡已展示。结束本轮等待买家确认，当前提取结果不是已确认条件。",
        }, ensure_ascii=False))], state=ToolResultState.SUCCESS)
    return show_shopping_requirements
