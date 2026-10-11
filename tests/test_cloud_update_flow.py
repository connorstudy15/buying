"""Exercise shell orchestration with fake Docker; no real volumes or credentials."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("blocked,manual", [(False, False), (True, False), (False, True)])
def test_update_uses_restored_volumes_and_blocks_before_stop(tmp_path, blocked, manual):
    bash = shutil.which("bash")
    if os.name == "nt":
        bash = "C:/Program Files/Git/bin/bash.exe"
    if not bash or not Path(bash).exists():
        pytest.skip("Bash unavailable")
    posix = subprocess.check_output([bash, "-c", 'cd "$1" && pwd', "test", str(tmp_path)], text=True).strip()
    root = Path(__file__).resolve().parents[1]
    for directory in ("globex", "globex-backups/prior/docker", "globex-releases/new/docker", "bin"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    prior = tmp_path / "globex-backups/prior"
    (prior / ".env").write_text("SYNTHETIC_TEST=1\n")
    (prior / "docker/docker-compose.cloud.yaml").write_text("services: {}\n")
    (prior / "restore.yaml").write_text("volumes: {}\n")
    release = tmp_path / "globex-releases/new"
    (release / "RELEASE_COMMIT").write_text("a" * 40)
    (release / "docker/docker-compose.cloud.yaml").write_text("services: {}\n")
    (release / "prompt-upgrade").mkdir()
    (release / "prompt-upgrade/upgrade.json").write_text("{}")
    if manual:
        (release / "prompt-upgrade/operator-release.json").write_text("{}")
    (release / "scripts").mkdir()
    source = (root / "scripts/update_cloud.sh").read_text().replace("/home/admin/", posix + "/")
    script = release / "scripts/update_cloud.sh"
    script.write_text(source, newline="\n")
    fake = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_ROOT/calls.log"
[[ "$1" != -v ]] || exit 0
shift
if [[ "$1" == inspect ]]; then
  if [[ "$3" == *project.config_files* ]]; then
    printf '%s/globex-backups/prior/docker/docker-compose.cloud.yaml,%s/globex-backups/prior/restore.yaml\n' "$FAKE_ROOT" "$FAKE_ROOT"
  elif [[ "$3" == *Mounts* ]]; then
    component=${4#globex-}; component=${component%-1}
    echo "globex_restore_${component}_20261011T103852Z"
  else echo sha256:oldimage; fi
elif [[ "$1" == run ]]; then
  if [[ "$*" == *scripts.apply_prompt_upgrade* && "$*" == *--check* && "$FAKE_BLOCK" == 1 ]]; then exit 42; fi
  if [[ "$*" == *target=/backup* && "$*" != *target=/upgrade* ]]; then
    for arg in "$@"; do
      if [[ "$arg" == type=bind,source=*,target=/backup ]]; then
        destination=${arg#type=bind,source=}; destination=${destination%,target=/backup}
      fi
    done
    printf 'synthetic backup\n' > "$destination/${!#}.tar.gz"
  fi
fi
'''
    (tmp_path / "bin/sudo").write_text(fake, newline="\n")
    (tmp_path / "bin/curl").write_text("#!/usr/bin/env bash\nexit 0\n", newline="\n")
    env = {**os.environ, "FAKE_ROOT": posix, "FAKE_BLOCK": "1" if blocked else "0", "GLOBEX_MANUAL_RELEASE": "1" if manual else "0"}
    result = subprocess.run([bash, "-c", 'export PATH="$FAKE_ROOT/bin:$PATH"; chmod +x "$FAKE_ROOT/bin/"*; bash "$FAKE_ROOT/globex-releases/new/scripts/update_cloud.sh"'], env=env, capture_output=True, text=True)
    calls = (tmp_path / "calls.log").read_text()
    assert "source=globex_restore_app_20261011T103852Z,target=/app/data,readonly" in calls
    if blocked:
        assert result.returncode == 42, result.stderr
        assert " stop\n" not in calls
        assert "target=/state" not in calls
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        if manual:
            assert "scripts.apply_operator_prompt_upgrade --bundle /upgrade --operator-authorized --check" in calls
        for component in ("app", "redis", "qdrant"):
            assert f"source=globex_restore_{component}_20261011T103852Z,target=/state,readonly" in calls
        override = (release / "docker/release.override.yaml").read_text()
        assert "name: globex_restore_app_20261011T103852Z" in override
        backups = [p for p in (tmp_path / "globex-backups").iterdir() if p.name != "prior"]
        assert len(backups) == 1
        assert (backups[0] / "compose-overrides.txt").read_text().strip() == "active-1.yaml"
        assert (backups[0] / "docker/active-1.yaml").read_bytes() == (prior / "restore.yaml").read_bytes()
