# -*- coding: utf-8 -*-
"""Dual-Tower D0-role 权限冒烟测试；失败时不得继续后续实验。"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval.dual_tower_dashscope import (  # noqa: E402
    DashScopeEmbeddingConfig,
    DashScopeEmbeddingError,
    DashScopeRoleEmbeddingClient,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "eval" / "runs" / "dual-tower-d0-role" / "permission-smoke.json",
    )
    return parser.parse_args()


async def _run(output: Path) -> int:
    load_dotenv(ROOT / ".env", override=False)
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        config = DashScopeEmbeddingConfig.from_env()
        client = DashScopeRoleEmbeddingClient(config)
        query = await client.embed_queries(["轻量天幕为什么国际运费仍然可能很贵？"])
        document = await client.embed_documents([
            "国际运输通常比较实际重量与体积重量，并按其中较大者计费。"
        ])
        report = {
            "status": "passed",
            "generated_at": generated_at,
            "provider": "dashscope_native",
            "model": config.model,
            "dimension_expected": config.dimension,
            "query": {
                "request_mode": "dashscope_native:text_type=query",
                "dimension": len(query.vectors[0]),
                "latency_ms": round(query.latency_ms, 3),
                "attempts": query.attempts,
                "total_tokens": query.total_tokens,
            },
            "document": {
                "request_mode": "dashscope_native:text_type=document",
                "dimension": len(document.vectors[0]),
                "latency_ms": round(document.latency_ms, 3),
                "attempts": document.attempts,
                "total_tokens": document.total_tokens,
            },
            "fallback_used": False,
            "gate": "continue_to_endpoint_aa_check",
        }
        exit_code = 0
    except (DashScopeEmbeddingError, ValueError) as exc:
        error = exc.as_dict() if isinstance(exc, DashScopeEmbeddingError) else {
            "message": str(exc),
            "http_status": None,
            "provider_code": "configuration_error",
            "request_id": None,
            "request_mode": "dashscope_native",
            "retryable": False,
            "fallback_used": False,
        }
        report = {
            "status": "failed",
            "generated_at": generated_at,
            "provider": "dashscope_native",
            "model": "qwen3.7-text-embedding-flash",
            "error": error,
            "fallback_used": False,
            "gate": "stop_experiment",
        }
        exit_code = 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={output.resolve()}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_args().output)))
