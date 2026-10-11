"""Explicit operator release without claiming paired evaluation PASS."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.infrastructure.prompt_registry import PromptRegistry, PromptRegistryError, canonical, read_prompt, sha256, toolset_contract
from app.infrastructure.runtime_version import app_source_fingerprint


def apply_operator_upgrade(path: Path, contract: dict, bundle: Path, *, authorized: bool = False, check: bool = False) -> dict:
    if not authorized:
        raise PromptRegistryError("人工发布必须由操作员明确授权")
    spec = json.loads((bundle / "operator-release.json").read_text(encoding="utf-8"))
    if spec.get("evaluation_status") != "INCOMPLETE" or not spec.get("authorization"):
        raise PromptRegistryError("人工发布必须如实记录未完成评测和授权")
    if spec["app_source_sha256"] != app_source_fingerprint() or spec["toolset_sha256"] != sha256(canonical(contract)):
        raise PromptRegistryError("人工发布包代码或工具契约不匹配")
    document, yaml_hash = read_prompt(bundle / "candidate.yml")
    candidate = "p-" + sha256(canonical({"prompts": document, "toolset": contract}))
    if candidate != spec["candidate"]:
        raise PromptRegistryError("人工发布候选内容不匹配")
    registry = PromptRegistry(path, contract)

    def inspect(db):
        current = db.execute("SELECT * FROM prompt_deployments ORDER BY sequence DESC LIMIT 1").fetchone()
        if current is None:
            raise PromptRegistryError("人工升级需要已有部署")
        effective = current["candidate"] if current["candidate"] and current["candidate_bps"] == 10000 else current["baseline"]
        if effective == candidate:
            registry._version(db, candidate)
            return current, None
        if current["candidate"] and 0 < current["candidate_bps"] < 10000:
            raise PromptRegistryError("现有灰度未结束")
        if effective != spec["source_version"]:
            raise PromptRegistryError("当前部署与人工升级来源不一致")
        return current, registry._version(db, effective, check_contract=False)

    if check:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            current, source = inspect(db)
        return {"status": "validated_read_only" if source else "already_applied", "evaluation_status": "INCOMPLETE", "candidate": candidate}
    with registry._transaction() as db:
        current, source = inspect(db)
        if source is None:
            return {"status": "already_applied", "deployment_id": current["deployment_id"]}
        baseline = registry._import_document(db, source["document"], source["yaml_sha256"])
        imported = registry._import_document(db, document, yaml_hash)
        deployment = registry._deploy(db, baseline["version_id"], imported["version_id"], 10000,
            "operator-direct-release", "operator_publish", {"evaluation_status": "INCOMPLETE",
                "authorization": spec["authorization"], "source_version": spec["source_version"],
                "spec_sha256": sha256((bundle / "operator-release.json").read_bytes())})
    return {"status": "operator_published", "deployment_id": deployment, "evaluation_status": "INCOMPLETE", "existing_assignments_changed": False}


def main():
    from app.infrastructure.settings import load_settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--operator-authorized", action="store_true", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    if settings.prompt_pin_version:
        parser.error("人工生产发布也不允许使用 PROMPT_PIN_VERSION")
    try:
        result = apply_operator_upgrade(settings.data_dir / "prompts/registry.sqlite3",
            toolset_contract(Path(__file__).resolve().parents[1], web_search_enabled=bool(settings.tavily_api_key)),
            args.bundle, authorized=args.operator_authorized, check=args.check)
    except (ValueError, OSError, sqlite3.Error, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
