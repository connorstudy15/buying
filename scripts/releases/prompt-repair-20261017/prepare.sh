#!/usr/bin/env bash
# Preparation and read-only validation only. Does not restart services.
set -Eeuo pipefail
umask 077
release=$(pwd -P)
repair=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
test -f "$release/RELEASE_COMMIT"
test -f "$release/.env"
test -f "$release/scripts/apply_operator_prompt_upgrade.py"
version=$(tr -d '\r\n' < "$release/RELEASE_COMMIT")
[[ "$version" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid RELEASE_COMMIT'; exit 1; }
image="globex-backend:$version"
docker image inspect "$image" >/dev/null
volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{if eq .Type "volume"}}{{.Name}}{{end}}{{end}}{{end}}' globex-app-1)
[[ "$volume" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || { echo 'Missing named app volume'; exit 1; }
if [[ -e "$release/prompt-upgrade" ]]; then
  echo 'prompt-upgrade already exists; preserve it and inspect before retrying.'
  exit 1
fi
stage=$(mktemp -d "$release/.prompt-repair.XXXXXX")
docker run --rm --network none --entrypoint python --env-file "$release/.env" \
  -e PYTHONPATH=/app \
  --mount "type=bind,source=$repair,target=/repair,readonly" \
  --mount "type=bind,source=$stage,target=/upgrade" \
  "$image" /repair/prepare.py
# Uses the existing upgrade validator with check=True and a read-only data mount.
docker run --rm --network none --entrypoint python --env-file "$release/.env" \
  -e DATA_DIR=/app/data \
  --mount "type=volume,source=$volume,target=/app/data,readonly" \
  --mount "type=bind,source=$stage,target=/upgrade,readonly" \
  "$image" -m scripts.apply_operator_prompt_upgrade --bundle /upgrade --operator-authorized --check
mv -- "$stage" "$release/prompt-upgrade"
echo 'Prepared and validated read-only. No live registry changes or service restart performed.'
echo 'Paired model evaluation is INCOMPLETE. If choosing operator release, execute:'
echo 'GLOBEX_CATALOG=abo GLOBEX_MANUAL_RELEASE=1 bash scripts/update_cloud.sh'
