"""Build versioned operation profiles from content-free JSON/JSONL observations."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.infrastructure.resource_governance.profiles import (  # noqa: E402
    OperationProfileBuilder, OperationProfileKey, OperationProfileStore, execution_contract_hash,
)


KEY_FIELDS = tuple(OperationProfileKey.__dataclass_fields__)


def _rows(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    payload = json.loads(raw)
    return payload if isinstance(payload, list) else payload.get("observations", [])


def normalize_observation(row: dict) -> dict:
    """Accept explicit normalized rows or Langfuse/OTel-shaped metadata rows."""
    attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    attrs = {**metadata, **attributes}
    operation = str(row.get("operation") or attrs.get("globex.resource.operation") or "unknown")
    component = str(row.get("component") or attrs.get("globex.resource.component") or "unknown")
    prompt_version = str(row.get("prompt_version") or attrs.get("globex.prompt_version") or "unknown")
    policy_version = str(row.get("policy_version") or attrs.get("globex.context.policy_version") or "unknown")
    relevant_code = str(row.get("relevant_code_version") or attrs.get("globex.resource.relevant_code_version") or "unknown")
    usage = row.get("usageDetails") if isinstance(row.get("usageDetails"), dict) else {}
    normalized = {
        **row,
        "environment": str(row.get("environment") or attrs.get("deployment.environment") or "unknown"),
        "component": component,
        "operation": operation,
        "model": str(row.get("model") or attrs.get("gen_ai.request.model") or "unknown"),
        "execution_path": str(row.get("execution_path") or attrs.get("globex.resource.execution_path") or "default"),
        "context_bucket": str(row.get("context_bucket") or attrs.get("globex.resource.context_bucket") or "unknown"),
        "candidate_bucket": str(row.get("candidate_bucket") or attrs.get("globex.resource.candidate_bucket") or "unknown"),
        "prompt_version": prompt_version,
        "policy_version": policy_version,
        "execution_contract_hash": str(row.get("execution_contract_hash") or execution_contract_hash(
            component=component, operation=operation, prompt_version=prompt_version,
            policy_version=policy_version, relevant_code_version=relevant_code,
        )),
        "chat_input_tokens": int(row.get("chat_input_tokens") or usage.get("input") or 0),
        "chat_output_tokens": int(row.get("chat_output_tokens") or usage.get("output") or 0),
        "embedding_tokens": int(row.get("embedding_tokens") or attrs.get("globex.resource.embedding_tokens") or 0),
        "rerank_tokens": int(row.get("rerank_tokens") or attrs.get("globex.resource.rerank_tokens") or 0),
        "api_calls": int(row.get("api_calls") or attrs.get("globex.resource.api_calls") or 1),
        "latency_ms": int(row.get("latency_ms") or attrs.get("globex.resource.latency_ms") or 0),
    }
    return normalized


def build_profiles(rows: list[dict], *, git_commit: str = "") -> OperationProfileStore:
    grouped: dict[OperationProfileKey, list[dict]] = defaultdict(list)
    for source in rows:
        row = normalize_observation(source)
        key = OperationProfileKey(**{name: str(row.get(name) or "unknown") for name in KEY_FIELDS})
        grouped[key].append(row)
    builder, store = OperationProfileBuilder(), OperationProfileStore()
    for key, observations in grouped.items():
        store.put(builder.build(
            key, observations, git_commit=git_commit,
            relevant_code_version=key.execution_contract_hash,
        ))
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=False,
            capture_output=True, text=True,
        ).stdout.strip()
    except OSError:
        git_commit = ""
    store = build_profiles(_rows(args.input), git_commit=git_commit)
    store.write_json(args.output)
    print(json.dumps({"profiles": len(store.all()), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

