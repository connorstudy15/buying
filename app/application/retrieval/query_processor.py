"""知识检索 Query Rewrite / Decomposition（V1）。

只负责把一个可回答的问题转换为结构化检索计划；证据边界判断仍由
``unsupported_fact_reason`` 在调用本组件之前完成。
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from agentscope.message import Msg, TextBlock


@dataclass(frozen=True)
class QueryVariant:
    query_id: str
    text: str
    information_need_id: str
    kind: str


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    rewritten_query: str
    subqueries: tuple[QueryVariant, ...]

    def variants(self) -> tuple[QueryVariant, ...]:
        values = [QueryVariant("original", self.original_query, "overall", "original")]
        if self.rewritten_query and self.rewritten_query.casefold() != self.original_query.casefold():
            values.append(QueryVariant("rewrite", self.rewritten_query, "overall", "rewrite"))
        values.extend(self.subqueries)
        return tuple(values)


class QueryProcessorError(RuntimeError):
    """模型输出不可用；上层必须原样退回 legacy 检索。"""


class QueryProcessor:
    def __init__(
        self, model, prompt: str, *, max_subqueries: int = 3,
        timeout_seconds: float = 30.0, disable_thinking: bool = False,
    ):
        self._model = model
        self._prompt = prompt
        self._max_subqueries = max(1, min(int(max_subqueries), 5))
        self._timeout_seconds = timeout_seconds
        self._disable_thinking = disable_thinking

    async def process(self, question: str) -> QueryPlan:
        """恰好调用模型一次，并严格校验结构与原问题语义锚点。"""
        try:
            request_kwargs = {"max_tokens": 1000}
            if self._disable_thinking:
                # 阿里云兼容网关的混合推理模型支持此开关；其他网关默认不发送该扩展字段。
                request_kwargs["extra_body"] = {"enable_thinking": False}
            response = await asyncio.wait_for(
                self._model(messages=[
                    Msg(name="system", role="system", content=[TextBlock(text=self._prompt)]),
                    Msg(name="user", role="user", content=[TextBlock(text=json.dumps({
                        "question": question,
                        "max_subqueries": self._max_subqueries,
                    }, ensure_ascii=False))]),
                ], **request_kwargs),
                timeout=self._timeout_seconds,
            )
            raw = "".join(
                str(text) for block in response.content
                if (text := getattr(block, "text", None)) is not None
            ).strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            raw = re.sub(r"^json\s*", "", raw.strip(), flags=re.IGNORECASE)
            payload = json.loads(raw)
            return self._validate(question, payload)
        except QueryProcessorError:
            raise
        except Exception as err:  # noqa: BLE001 - 任何模型/格式故障均触发精确 legacy fallback
            raise QueryProcessorError("query_processor_unavailable") from err

    def _validate(self, original: str, payload: object) -> QueryPlan:
        if not isinstance(payload, dict):
            raise QueryProcessorError("query_processor_invalid_object")
        rewritten = str(payload.get("rewritten_query") or "").strip()
        if not 2 <= len(rewritten) <= 240:
            raise QueryProcessorError("query_processor_invalid_rewrite")
        raw_subqueries = payload.get("subqueries") or []
        if not isinstance(raw_subqueries, list) or len(raw_subqueries) > self._max_subqueries:
            raise QueryProcessorError("query_processor_invalid_subqueries")
        subqueries: list[QueryVariant] = []
        seen_text = {original.casefold(), rewritten.casefold()}
        seen_need: set[str] = set()
        for index, item in enumerate(raw_subqueries, 1):
            if not isinstance(item, dict):
                raise QueryProcessorError("query_processor_invalid_subquery")
            text = str(item.get("query") or "").strip()
            need = re.sub(r"[^0-9A-Za-z_-]", "_", str(item.get("information_need_id") or "").strip())[:64]
            if not 2 <= len(text) <= 200 or not need or text.casefold() in seen_text or need in seen_need:
                raise QueryProcessorError("query_processor_duplicate_or_invalid_subquery")
            seen_text.add(text.casefold())
            seen_need.add(need)
            subqueries.append(QueryVariant(f"subquery_{index}", text, need, "subquery"))
        plan = QueryPlan(original, rewritten, tuple(subqueries))
        combined = " ".join([plan.rewritten_query, *(variant.text for variant in plan.subqueries)]).casefold()
        # 只做可确定的防漂移检查：数字/型号不能消失；强否定与“任意范围”不能被弱化。
        anchors = set(re.findall(r"(?i)\b[a-z]+[-_]?\d[\w.-]*\b|\d+(?:\.\d+)?", original))
        if any(anchor.casefold() not in combined for anchor in anchors):
            raise QueryProcessorError("query_processor_anchor_drift")
        constraint_groups = (
            ({"不要", "不能", "不含", "没有", "不得", "禁止"}, {"不要", "不能", "不含", "没有", "不得", "禁止"}),
            ({"任意", "任何", "所有", "全部", "全球"}, {"任意", "任何", "所有", "全部", "全球"}),
        )
        for triggers, equivalents in constraint_groups:
            if any(word in original for word in triggers) and not any(word in combined for word in equivalents):
                raise QueryProcessorError("query_processor_constraint_drift")
        return plan
