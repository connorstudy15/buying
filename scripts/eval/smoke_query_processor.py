"""Minimal live smoke test for the configured QueryProcessor model."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.prompts.loader import load_prompts
from app.application.retrieval.query_processor import QueryProcessor
from app.infrastructure.llm import create_chat_model
from app.infrastructure.settings import load_settings


async def main() -> None:
    settings = load_settings()
    processor_settings = replace(
        settings,
        llm_base_url=settings.query_processor_base_url or settings.llm_base_url,
        llm_api_key=settings.query_processor_api_key or settings.llm_api_key,
        llm_model=settings.query_processor_model or settings.llm_model,
        llm_fallback_model="",
    )
    processor = QueryProcessor(
        create_chat_model(processor_settings, stream=False),
        load_prompts()["query_processor"]["system_prompt"],
        max_subqueries=settings.query_processor_max_subqueries,
        disable_thinking=settings.query_processor_disable_thinking,
    )
    print({
        "base_url": processor_settings.llm_base_url,
        "model": processor_settings.llm_model,
        "dedicated_key": bool(settings.query_processor_api_key),
        "disable_thinking": settings.query_processor_disable_thinking,
    })
    questions = (
        "我想买一个适合通勤的双肩包",
        "我要买个充电宝带着飞日本，需要注意什么",
    )
    for question in questions:
        plan, metadata = await processor.process_with_metadata(question)
        print({
            "mode": plan.mode,
            "subquery_count": len(plan.subqueries),
            "latency_ms": metadata["latency_ms"],
            "input_tokens": metadata["input_tokens"],
            "output_tokens": metadata["output_tokens"],
        })


if __name__ == "__main__":
    asyncio.run(main())
