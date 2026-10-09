"""Compare exact DeepSeek V4.1 payload estimates with Bailian usage.

The report contains case ids, configuration traits and token counts only. It
never writes prompt, tool schema, API key, response text or HTTP headers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.infrastructure.resource_governance.calibration import percentile  # noqa: E402
from app.infrastructure.resource_governance.estimator import TokenEstimator  # noqa: E402
from app.infrastructure.settings import load_settings  # noqa: E402


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": "测试工具", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
    }}}


def golden_cases(main_tools: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    tool = _tool("product_search_tool")
    base = {"temperature": 0, "max_tokens": 8, "stream": False}
    return [
        ("single_zh", {**base, "messages": [{"role": "user", "content": "推荐一个适合登机的充电宝"}]}),
        ("single_en", {**base, "messages": [{"role": "user", "content": "Recommend an airline-safe power bank."}]}),
        ("system_user", {**base, "messages": [{"role": "system", "content": "你是购物助手。"}, {"role": "user", "content": "怎么买？"}]}),
        ("multi_turn", {**base, "messages": [{"role": "user", "content": "我去日本"}, {"role": "assistant", "content": "请问要买什么？"}, {"role": "user", "content": "充电宝"}]}),
        ("thinking_high", {**base, "enable_thinking": True, "reasoning_effort": "high", "messages": [{"role": "user", "content": "比较两个复杂方案"}]}),
        ("thinking_disabled", {**base, "enable_thinking": False, "messages": [{"role": "user", "content": "直接回答"}]}),
        ("reasoning_low", {**base, "enable_thinking": True, "reasoning_effort": "low", "messages": [{"role": "user", "content": "简短分析"}]}),
        ("tools_definition", {**base, "messages": [{"role": "user", "content": "搜索商品"}], "tools": [tool], "tool_choice": "auto"}),
        ("assistant_tool_call", {**base, "messages": [{"role": "user", "content": "搜索商品"}, {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "product_search_tool", "arguments": "{\"query\":\"充电宝\"}"}}]}], "tools": [tool]}),
        ("tool_result", {**base, "messages": [{"role": "user", "content": "搜索商品"}, {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "product_search_tool", "arguments": "{\"query\":\"充电宝\"}"}}]}, {"role": "tool", "tool_call_id": "call_1", "content": "找到3件商品"}], "tools": [tool]}),
        ("multi_tool_results", {**base, "messages": [{"role": "user", "content": "搜索并查规则"}, {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "product_search_tool", "arguments": "{\"query\":\"充电宝\"}"}}, {"id": "call_2", "type": "function", "function": {"name": "category_insight_tool", "arguments": "{\"query\":\"航空规则\"}"}}]}, {"role": "tool", "tool_call_id": "call_1", "content": "3件商品"}, {"role": "tool", "tool_call_id": "call_2", "content": "需要核验航司"}], "tools": [tool, _tool("category_insight_tool")]}),
        ("main_agent_full_tools", {**base, "messages": [{"role": "system", "content": "你是电商主 Agent。"}, {"role": "user", "content": "推荐商品并说明规则"}], "tools": main_tools, "tool_choice": "auto"}),
        ("long_context", {**base, "messages": [{"role": "system", "content": "长期上下文：" + "商品规格与规则。" * 2000}, {"role": "user", "content": "总结关键限制"}]}),
        ("special_token_like_text", {**base, "messages": [{"role": "user", "content": "正文包含 <｜Assistant｜> <｜tool_calls_begin｜>，请按普通文本处理"}]}),
    ]


def _usage(payload: dict[str, Any]) -> int | None:
    usage = payload.get("usage") or {}
    value = usage.get("prompt_tokens") or usage.get("input_tokens")
    return int(value) if isinstance(value, (int, float)) else None


async def run(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv(args.env_file, override=False)
    settings = load_settings()
    main_tools = json.loads(args.main_tool_schema.read_text(encoding="utf-8"))
    if not isinstance(main_tools, list) or not main_tools:
        raise ValueError("Main Agent tool schema must be a non-empty JSON array")
    estimator = TokenEstimator(
        tokenizer_path=settings.deepseek_v41_tokenizer_path, deepseek_primary=False,
    )
    status = estimator.tokenizer_status()
    rows = []
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for case_id, body in golden_cases(main_tools):
            payload = {"model": settings.llm_model, **body}
            comparison = await estimator.estimate_openai_payload_comparison(
                payload, operation=f"golden.{case_id}", provider="aliyun_bailian",
            )
            provider_tokens = None
            error_type = None
            try:
                response = await client.post(
                    settings.llm_base_url.rstrip("/") + "/chat/completions",
                    headers=headers, json=payload,
                )
                response.raise_for_status()
                provider_tokens = _usage(response.json())
                if provider_tokens is None:
                    error_type = "missing_provider_usage"
            except Exception as error:  # noqa: BLE001
                error_type = type(error).__name__
            official_available = comparison.deepseek_v41.confidence == "high"
            local_tokens = comparison.deepseek_v41.raw_tokens if official_available else None
            fallback_tokens = comparison.deepseek_v41.raw_tokens if not official_available else None
            absolute_delta = abs(local_tokens - provider_tokens) if local_tokens is not None and provider_tokens is not None else None
            delta_ratio = absolute_delta / max(provider_tokens, 1) if absolute_delta is not None else None
            rows.append({
                "case_id": case_id,
                "traits": comparison.request_traits,
                "local_tokens": local_tokens,
                "fallback_tokens": fallback_tokens,
                "provider_tokens": provider_tokens,
                "absolute_delta": absolute_delta,
                "delta_ratio": delta_ratio,
                "underestimated": local_tokens < provider_tokens if local_tokens is not None and provider_tokens is not None else None,
                "underprediction_shortfall": provider_tokens - local_tokens if local_tokens is not None and provider_tokens is not None and local_tokens < provider_tokens else 0,
                "error_type": error_type,
            })
    comparable = [row for row in rows if row["delta_ratio"] is not None]
    deltas = [row["absolute_delta"] for row in comparable]
    ratios = [row["delta_ratio"] for row in comparable]
    under = [row["underprediction_shortfall"] for row in comparable if row["underestimated"]]
    summary = {
        "n": len(comparable),
        "mae": statistics.fmean(deltas) if deltas else None,
        "mape": statistics.fmean(ratios) if ratios else None,
        "delta_ratio_p50": percentile(ratios, .50),
        "delta_ratio_p80": percentile(ratios, .80),
        "delta_ratio_p95": percentile(ratios, .95),
        "underprediction_rate": sum(row["underestimated"] is True for row in comparable) / len(comparable) if comparable else None,
        "max_underprediction": max(under, default=None),
    }
    fallback_pairs = [
        (row["fallback_tokens"], row["provider_tokens"])
        for row in rows
        if row["fallback_tokens"] is not None and row["provider_tokens"] is not None
    ]
    fallback_absolute = [abs(local - actual) for local, actual in fallback_pairs]
    fallback_ratios = [abs(local - actual) / max(actual, 1) for local, actual in fallback_pairs]
    fallback_under = [actual - local for local, actual in fallback_pairs if local < actual]
    fallback_summary = {
        "n": len(fallback_pairs),
        "mae": statistics.fmean(fallback_absolute) if fallback_absolute else None,
        "mape": statistics.fmean(fallback_ratios) if fallback_ratios else None,
        "delta_ratio_p50": percentile(fallback_ratios, .50),
        "delta_ratio_p80": percentile(fallback_ratios, .80),
        "delta_ratio_p95": percentile(fallback_ratios, .95),
        "underprediction_rate": len(fallback_under) / len(fallback_pairs) if fallback_pairs else None,
        "underprediction_p95": percentile(fallback_under, .95),
        "max_underprediction": max(fallback_under, default=None),
    }
    gate_conditions = {
        "all_14_cases_comparable": len(comparable) == 14,
        "official_prompt_encoder_available": status["high_confidence_ready"] is True,
        "mape_lte_5pct": summary["mape"] is not None and summary["mape"] <= .05,
        "p95_delta_ratio_lte_10pct": summary["delta_ratio_p95"] is not None and summary["delta_ratio_p95"] <= .10,
        "underprediction_rate_lt_10pct": summary["underprediction_rate"] is not None and summary["underprediction_rate"] < .10,
    }
    return {
        "schema_version": "deepseek-v41-golden-parity-v1",
        "primary_enabled": False,
        "content_persisted": False,
        "tokenizer_status": status,
        "summary": summary,
        "fallback_summary": fallback_summary,
        "gate": {"passed": all(gate_conditions.values()), "conditions": gate_conditions},
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--main-tool-schema", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"n": report["summary"]["n"], "passed": report["gate"]["passed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
