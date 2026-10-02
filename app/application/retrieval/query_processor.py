"""知识检索 Query Rewrite / Decomposition（V2）。

只负责把一个可回答的问题转换为结构化检索计划；证据边界判断仍由
``unsupported_fact_reason`` 在调用本组件之前完成。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass

from agentscope.message import Msg, TextBlock


@dataclass(frozen=True)
class QueryVariant:
    query_id: str
    text: str
    information_need_id: str
    kind: str
    intent_group_id: str = "overall"


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    rewritten_query: str
    subqueries: tuple[QueryVariant, ...]
    mode: str = "DIRECT"
    rewrite_similarity: float | None = None
    rewrite_decision: str = "not_applicable"

    def variants(self) -> tuple[QueryVariant, ...]:
        # DIRECT 完全沿用原查询；REWRITE 的两条查询属于同一意图组，融合时只能取最大贡献，
        # 不能因为同一个意思说了两遍就获得双倍分数。DECOMPOSE 不使用全局改写，
        # 原问题仅作 global 补充，每个独立信息需求拥有自己的分组。
        values = [QueryVariant("original", self.original_query, "overall", "original", "global")]
        if self.mode == "REWRITE":
            values[0] = QueryVariant("original", self.original_query, "overall", "original", "overall")
            values.append(QueryVariant("rewrite", self.rewritten_query, "overall", "rewrite", "overall"))
        elif self.mode == "DECOMPOSE":
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
        """兼容旧调用；需要调用计量时使用 ``process_with_metadata``。"""
        plan, _ = await self.process_with_metadata(question)
        return plan

    async def process_with_metadata(self, question: str) -> tuple[QueryPlan, dict]:
        """恰好调用模型一次，并返回延迟与 API usage，不把计量混入检索计划。"""
        started = time.perf_counter()
        try:
            request_kwargs = {"max_tokens": 1000, "temperature": 0}
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
            usage = getattr(response, "usage", None)
            if isinstance(usage, dict):
                usage_data = usage
            else:
                usage_data = {
                    key: getattr(usage, key, None)
                    for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens", "total_tokens")
                } if usage is not None else {}
            input_tokens = int(usage_data.get("input_tokens") or usage_data.get("prompt_tokens") or 0)
            output_tokens = int(usage_data.get("output_tokens") or usage_data.get("completion_tokens") or 0)
            total_tokens = int(usage_data.get("total_tokens") or input_tokens + output_tokens)
            return self._validate(question, payload), {
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }
        except QueryProcessorError:
            raise
        except Exception as err:  # noqa: BLE001 - 任何模型/格式故障均触发精确 legacy fallback
            raise QueryProcessorError("query_processor_unavailable") from err

    def _validate(self, original: str, payload: object) -> QueryPlan:
        if not isinstance(payload, dict):
            raise QueryProcessorError("query_processor_invalid_object")
        mode = str(payload.get("mode") or "").strip().upper()
        if mode not in {"DIRECT", "REWRITE", "DECOMPOSE"}:
            raise QueryProcessorError("query_processor_invalid_mode")
        rewritten = str(payload.get("rewritten_query") or "").strip()
        if rewritten and not 2 <= len(rewritten) <= 240:
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
            subqueries.append(QueryVariant(f"subquery_{index}", text, need, "subquery", need))

        if mode == "DIRECT" and (subqueries or (rewritten and rewritten.casefold() != original.casefold())):
            raise QueryProcessorError("query_processor_direct_has_transform")
        if mode == "REWRITE" and (not rewritten or rewritten.casefold() == original.casefold() or subqueries):
            raise QueryProcessorError("query_processor_invalid_rewrite_mode")
        if mode == "DECOMPOSE" and len(subqueries) < 2:
            raise QueryProcessorError("query_processor_decompose_requires_multiple_needs")

        similarity = _character_bigram_dice(original, rewritten) if mode == "REWRITE" else None
        decision = "used"
        # 只拦截几乎逐字相同的改写，避免为了这个判断再调用一次 embedding。
        # 阈值保守固定，不在冻结评测集上反复调参。
        if mode == "REWRITE" and similarity >= 0.92:
            mode, rewritten, decision = "DIRECT", "", "skipped_near_duplicate"
        elif mode != "REWRITE":
            decision = "not_applicable"

        plan = QueryPlan(original, rewritten, tuple(subqueries), mode, similarity, decision)
        transformed = [plan.rewritten_query] if plan.mode == "REWRITE" else [v.text for v in plan.subqueries]
        combined = " ".join(transformed).casefold()
        # 只做可确定的防漂移检查：数字/型号不能消失；强否定与“任意范围”不能被弱化。
        anchors = set(re.findall(r"(?i)\b[a-z]+[-_]?\d[\w.-]*\b|\d+(?:\.\d+)?", original))
        if plan.mode != "DIRECT" and any(anchor.casefold() not in combined for anchor in anchors):
            raise QueryProcessorError("query_processor_anchor_drift")
        constraint_groups = (
            ({"不要", "不能", "不含", "没有", "不得", "禁止"}, {"不要", "不能", "不含", "没有", "不得", "禁止"}),
            ({"任意", "任何", "所有", "全部", "全球"}, {"任意", "任何", "所有", "全部", "全球"}),
        )
        for triggers, equivalents in constraint_groups:
            if plan.mode != "DIRECT" and any(word in original for word in triggers) and not any(word in combined for word in equivalents):
                raise QueryProcessorError("query_processor_constraint_drift")
        return plan


def _character_bigram_dice(left: str, right: str) -> float:
    """确定性近重复判断：归一化字符二元组 Dice，相同文本为 1。"""
    def grams(value: str) -> set[str]:
        normalized = "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]+", value.casefold()))
        if len(normalized) < 2:
            return {normalized} if normalized else set()
        return {normalized[index:index + 2] for index in range(len(normalized) - 1)}

    left_grams, right_grams = grams(left), grams(right)
    if not left_grams and not right_grams:
        return 1.0
    if not left_grams or not right_grams:
        return 0.0
    return 2 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))
