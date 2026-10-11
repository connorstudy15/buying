"""Read-only preflight: refuse a code deployment that cannot load its active Prompt."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.infrastructure.prompt_registry import PromptRegistry, PromptRegistryError, toolset_contract


def check_registry(path: Path, contract: dict, *, pinned_version: str = "") -> None:
    if not path.exists():
        return  # First installation bootstraps the packaged version.
    registry = PromptRegistry(path, contract, pinned_version=pinned_version)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "prompt_deployments" not in tables:
            raise PromptRegistryError("已有 Prompt 数据库缺少部署表，拒绝自动初始化")
        current = connection.execute("SELECT * FROM prompt_deployments ORDER BY sequence DESC LIMIT 1").fetchone()
        if current is None:
            return
        versions = {pinned_version} if pinned_version else {current["baseline"]}
        if not pinned_version and current["candidate"] and current["candidate_bps"] > 0:
            versions.add(current["candidate"])
        for version_id in versions:
            registry._version(connection, version_id)


def main() -> None:
    from app.infrastructure.settings import load_settings

    settings = load_settings()
    root = Path(__file__).resolve().parents[1]
    try:
        check_registry(settings.data_dir / "prompts/registry.sqlite3",
                       toolset_contract(root, web_search_enabled=bool(settings.tavily_api_key)),
                       pinned_version=settings.prompt_pin_version)
    except (PromptRegistryError, sqlite3.Error) as error:
        raise SystemExit(f"Prompt preflight blocked deployment: {error}. Current service must remain running; evaluate and publish a compatible Prompt before updating.") from error
    print("Prompt compatibility preflight passed (read-only).")


if __name__ == "__main__":
    main()
