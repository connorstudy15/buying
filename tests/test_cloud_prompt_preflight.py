from pathlib import Path

import pytest

from app.infrastructure.prompt_registry import PromptContractChanged, PromptRegistry
from scripts.check_prompt_compatibility import check_registry


def test_preflight_uses_active_contract_without_mutating_database(tmp_path):
    path = tmp_path / "registry.sqlite3"
    contract = {"schema": 1, "source_files": {"tools.py": "old"}}
    registry = PromptRegistry(path, contract)
    registry.bootstrap(Path(__file__).resolve().parents[1] / "app/application/prompts/globex.yml")
    before = path.read_bytes()
    check_registry(path, contract)
    assert path.read_bytes() == before
    with pytest.raises(PromptContractChanged):
        check_registry(path, {"schema": 1, "source_files": {"tools.py": "new"}})
    assert path.read_bytes() == before


def test_first_install_does_not_create_registry_during_preflight(tmp_path):
    path = tmp_path / "missing.sqlite3"
    check_registry(path, {"schema": 1})
    assert not path.exists()
