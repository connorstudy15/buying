"""Read-only diagnosis of persisted Prompt contracts. No prompts or secrets are printed."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from app.infrastructure.prompt_registry import canonical, sha256, toolset_contract


def compare_contracts(stored: dict, current: dict, root: Path) -> dict:
    old_files = {name.replace("\\", "/"): digest for name, digest in stored.get("source_files", {}).items()}
    new_files = {name.replace("\\", "/"): digest for name, digest in current.get("source_files", {}).items()}
    changed = []
    for name in sorted(old_files.keys() & new_files.keys()):
        if old_files[name] == new_files[name]:
            continue
        hint = "content_changed"
        candidate = root / name
        if candidate.is_file():
            raw = candidate.read_bytes()
            lf = raw.replace(b"\r\n", b"\n")
            if old_files[name] in {sha256(lf), sha256(lf.replace(b"\n", b"\r\n"))}:
                hint = "line_endings_only"
        changed.append({"file": name, "difference": hint})
    return {
        "contract_matches": sha256(canonical(stored)) == sha256(canonical(current)),
        "configuration_changes": {
            key: {"stored": stored.get(key), "current": current.get(key)}
            for key in ("schema", "web_search_enabled") if stored.get(key) != current.get(key)
        },
        "added_files": sorted(new_files.keys() - old_files.keys()),
        "removed_files": sorted(old_files.keys() - new_files.keys()),
        "changed_files": changed,
        "path_separator_difference": set(stored.get("source_files", {})) != set(current.get("source_files", {})) and set(old_files) == set(new_files),
    }


def diagnose(database: Path, root: Path, *, web_search_enabled: bool, pinned_version: str = "") -> dict:
    if not database.is_file():
        raise ValueError("Prompt registry file not found at the selected data volume")
    current = toolset_contract(root, web_search_enabled=web_search_enabled)
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        deployment = connection.execute("SELECT * FROM prompt_deployments ORDER BY sequence DESC LIMIT 1").fetchone()
        if deployment is None:
            raise ValueError("No Prompt deployment found")
        selected = {pinned_version: "pinned"} if pinned_version else {deployment["baseline"]: "baseline"}
        if not pinned_version and deployment["candidate"] and deployment["candidate_bps"] > 0:
            selected[deployment["candidate"]] = "candidate"
        versions = []
        for version_id, role in selected.items():
            row = connection.execute("SELECT * FROM prompt_versions WHERE version_id=?", (version_id,)).fetchone()
            if row is None:
                versions.append({"version_id": version_id, "error": "version_missing"})
                continue
            payload = json.loads(row["payload"])
            prompts = payload.get("prompts", {})
            versions.append({"role": role, "version_id": version_id,
                "version_integrity_ok": "p-" + sha256(canonical(payload)) == version_id,
                "contract_metadata_integrity_ok": sha256(canonical(payload.get("toolset"))) == row["toolset_sha256"],
                "revoked": bool(connection.execute("SELECT 1 FROM prompt_revocations WHERE version_id=?", (version_id,)).fetchone()),
                "prompt_roles": {"main": prompts.get("main_agent", {}).get("name"),
                    **{key: value.get("name") for key, value in prompts.get("sub_agents", {}).items() if isinstance(value, dict)}},
                **compare_contracts(payload["toolset"], current, root)})
        return {"read_only": True, "deployment_id": deployment["deployment_id"], "versions": versions}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path, default=Path("/app/data/prompts/registry.sqlite3"))
    args = parser.parse_args()
    result = diagnose(args.database, args.root, web_search_enabled=bool(os.getenv("TAVILY_API_KEY", "")),
                      pinned_version=os.getenv("PROMPT_PIN_VERSION", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
