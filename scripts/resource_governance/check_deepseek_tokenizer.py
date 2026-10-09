"""Check DeepSeek V4.1 estimator readiness without reading prompts or keys."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.infrastructure.resource_governance.estimator import TokenEstimator  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", type=Path, default=None)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    status = TokenEstimator(tokenizer_path=args.tokenizer).tokenizer_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 1 if args.require_ready and not status["high_confidence_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
