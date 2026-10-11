"""Apply an evaluated tool/Prompt upgrade; --check never writes the live registry."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.infrastructure.prompt_registry import PromptRegistry, PromptRegistryError, canonical, read_prompt, sha256, toolset_contract
from app.infrastructure.prompt_release import compare_release_manifests
from app.infrastructure.runtime_version import app_source_fingerprint


def apply_upgrade(path: Path, contract: dict, bundle: Path, *, check: bool = False) -> dict:
    spec = json.loads((bundle / "upgrade.json").read_text(encoding="utf-8"))
    baseline_report, candidate_report = bundle / "baseline.manifest.json", bundle / "candidate.manifest.json"
    evidence = compare_release_manifests(baseline_report, candidate_report, spec["baseline"], spec["candidate"])
    for report in (baseline_report, candidate_report):
        manifest = json.loads(report.read_text(encoding="utf-8"))
        if manifest["service_runtime"]["server_app_source_sha256"] != app_source_fingerprint():
            raise PromptRegistryError("评测代码与待部署镜像不一致")
    if any(evidence[label]["toolset_sha256"] != sha256(canonical(contract)) for label in ("baseline", "candidate")):
        raise PromptRegistryError("评测工具契约与待部署镜像不一致")
    registry = PromptRegistry(path, contract)
    document, _ = read_prompt(bundle / "candidate.yml")
    candidate_id = "p-" + sha256(canonical({"prompts": document, "toolset": contract}))
    if candidate_id != spec["candidate"]:
        raise PromptRegistryError("升级包候选 Prompt 与评测版本不一致")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        current = db.execute("SELECT * FROM prompt_deployments ORDER BY sequence DESC LIMIT 1").fetchone()
        if current is None:
            raise PromptRegistryError("升级需要已有 Prompt 部署")
        effective = current["candidate"] if current["candidate"] and current["candidate_bps"] == 10000 else current["baseline"]
        if effective == spec["candidate"]:
            registry._version(db, effective)
            return {"status": "already_applied", "deployment_id": current["deployment_id"]}
        if current["candidate"] and 0 < current["candidate_bps"] < 10000:
            raise PromptRegistryError("现有灰度尚未结束")
        if effective != spec["source_version"]:
            raise PromptRegistryError("升级来源与当前部署不一致")
        source = registry._version(db, effective, check_contract=False)
        baseline_id = "p-" + sha256(canonical({"prompts": source["document"], "toolset": contract}))
        if baseline_id != spec["baseline"]:
            raise PromptRegistryError("评测基线与当前 Prompt 正文不一致")
        deployment_id = current["deployment_id"]
    if check:
        return {"status": "validated_read_only", "source_version": effective, "candidate": candidate_id}
    stage = registry.prepare_upgrade(bundle / "candidate.yml", expected_source_version=effective)
    if stage["source_deployment"] != deployment_id:
        raise PromptRegistryError("检查后部署已变化，拒绝升级")
    result = registry.publish(baseline=baseline_id, candidate=candidate_id, candidate_bps=10000,
        experiment="cloud-tool-upgrade", baseline_manifest=baseline_report, candidate_manifest=candidate_report,
        expected_deployment=deployment_id)
    return {"status": "published", "deployment_id": result["deployment_id"], "existing_assignments_changed": False}


def main():
    from app.infrastructure.settings import load_settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    if settings.prompt_pin_version:
        parser.error("生产升级前需移除 PROMPT_PIN_VERSION 评测固定配置")
    try:
        result = apply_upgrade(settings.data_dir / "prompts/registry.sqlite3",
            toolset_contract(Path(__file__).resolve().parents[1], web_search_enabled=bool(settings.tavily_api_key)),
            args.bundle, check=args.check)
    except (ValueError, OSError, sqlite3.Error, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
