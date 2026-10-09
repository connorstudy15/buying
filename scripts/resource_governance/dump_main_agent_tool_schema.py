"""Export the real Main Agent tool schema for the Golden parity fixture."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

async def run(output: Path, capture: Path | None = None) -> None:
    if capture is not None:
        payload = json.loads(capture.read_text(encoding="utf-8"))
        schemas = payload.get("request", {}).get("tools")
        if not isinstance(schemas, list) or not schemas:
            raise ValueError("capture does not contain a non-empty request.tools")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(schemas, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"tool_count": len(schemas), "output": str(output), "source": "captured_final_request"}))
        return
    from app.composition import build_container
    container = await build_container()
    try:
        factory = container.orchestrator._sessions._main_factory
        agent = factory.build()
        schemas = await agent.toolkit.get_tool_schemas()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(schemas, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"tool_count": len(schemas), "output": str(output)}))
    finally:
        await container.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", type=Path, default=None)
    args = parser.parse_args(argv)
    asyncio.run(run(args.output, args.capture))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
