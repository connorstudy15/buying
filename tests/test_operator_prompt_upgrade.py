import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from app.infrastructure.prompt_registry import PromptRegistry, PromptRegistryError, canonical, read_prompt, sha256, toolset_contract
from app.infrastructure.runtime_version import app_source_fingerprint
from scripts.apply_operator_prompt_upgrade import apply_operator_upgrade


@pytest.mark.parametrize("tamper", [None, "code", "source", "candidate", "unauthorized"])
def test_explicit_operator_upgrade_is_checked_atomic_and_does_not_fake_evidence(tmp_path, tamper):
    root = Path(__file__).resolve().parents[1]
    candidate_path = root / "app/application/prompts/globex.yml"
    path = tmp_path / "registry.sqlite3"
    old = PromptRegistry(path, {"schema": 1, "old_tools": True})
    source = old.bootstrap(candidate_path)["effective_version"]["version_id"]
    previous = asyncio.run(old.assign("old-session", "synthetic"))
    contract = toolset_contract(root)
    document, _ = read_prompt(candidate_path)
    candidate = "p-" + sha256(canonical({"prompts": document, "toolset": contract}))
    (tmp_path / "candidate.yml").write_bytes(candidate_path.read_bytes())
    spec = {"source_version": source, "candidate": candidate, "app_source_sha256": app_source_fingerprint(),
        "toolset_sha256": sha256(canonical(contract)), "evaluation_status": "INCOMPLETE", "authorization": "explicit synthetic operator test"}
    if tamper in ("code", "source", "candidate"):
        spec[{"code": "app_source_sha256", "source": "source_version", "candidate": "candidate"}[tamper]] = "mismatch"
    (tmp_path / "operator-release.json").write_text(json.dumps(spec))
    before = path.read_bytes()
    if tamper:
        with pytest.raises(PromptRegistryError):
            apply_operator_upgrade(path, contract, tmp_path, authorized=tamper != "unauthorized", check=True)
        assert path.read_bytes() == before
        return
    assert apply_operator_upgrade(path, contract, tmp_path, authorized=True, check=True)["status"] == "validated_read_only"
    assert path.read_bytes() == before
    assert apply_operator_upgrade(path, contract, tmp_path, authorized=True)["status"] == "operator_published"
    assert apply_operator_upgrade(path, contract, tmp_path, authorized=True)["status"] == "already_applied"
    with sqlite3.connect(path) as db:
        action, evidence = db.execute("SELECT action,evidence FROM prompt_deployments ORDER BY sequence DESC LIMIT 1").fetchone()
        assert action == "operator_publish"
        assert json.loads(evidence)["evaluation_status"] == "INCOMPLETE"
        assert "gate" not in json.loads(evidence)
        assert db.execute("SELECT version_id FROM prompt_assignments WHERE session_id='old-session'").fetchone()[0] == previous["version_id"]
    assert asyncio.run(PromptRegistry(path, contract).assign("new-session", "synthetic"))["version_id"] == candidate
