from pathlib import Path

from app.infrastructure.prompt_registry import PromptRegistry, sha256, toolset_contract
from scripts.diagnose_prompt_contract import compare_contracts, diagnose


def test_diagnosis_distinguishes_source_changes_from_line_endings(tmp_path):
    (tmp_path / "tools.py").write_bytes(b"print(1)\r\n")
    old = {"schema": 1, "source_files": {"tools.py": sha256(b"print(1)\n"), "removed.py": "old"}}
    new = {"schema": 1, "source_files": {"tools.py": sha256(b"print(1)\r\n"), "added.py": "new"}}
    report = compare_contracts(old, new, tmp_path)
    assert report["changed_files"] == [{"file": "tools.py", "difference": "line_endings_only"}]
    assert report["added_files"] == ["added.py"]
    assert report["removed_files"] == ["removed.py"]
    (tmp_path / "tools.py").write_bytes(b"print(2)\n")
    new["source_files"]["tools.py"] = sha256(b"print(2)\n")
    assert compare_contracts(old, new, tmp_path)["changed_files"][0]["difference"] == "content_changed"


def test_diagnosis_reads_version_identity_without_disclosing_prompt_text(tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / "registry.sqlite3"
    registry = PromptRegistry(path, toolset_contract(root))
    registry.bootstrap(root / "app/application/prompts/globex.yml")
    before = path.read_bytes()
    report = diagnose(path, root, web_search_enabled=False)
    assert report["read_only"]
    assert report["versions"][0]["contract_matches"]
    assert report["versions"][0]["version_integrity_ok"]
    assert "system_prompt" not in str(report)
    assert report["versions"][0]["prompt_roles"]["main"] == "commerce_concierge"
    assert before == path.read_bytes()
