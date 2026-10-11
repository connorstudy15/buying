#!/usr/bin/env bash
# Run from the extracted release directory with: bash scripts/update_cloud.sh
set -Eeuo pipefail
umask 077
release=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
live=/home/admin/globex
catalog=${GLOBEX_CATALOG:-default}
ready_timeout=${GLOBEX_READY_TIMEOUT_SECONDS:-1200}
[[ "$ready_timeout" =~ ^[0-9]+$ ]] && (( ready_timeout >= 2 && ready_timeout <= 3600 )) || { echo 'Readiness timeout must be 2..3600 seconds'; exit 1; }
[[ "$catalog" == default || "$catalog" == abo ]] || { echo 'GLOBEX_CATALOG must be default or abo'; exit 1; }
catalog_env=''
if [[ "$catalog" == abo ]]; then
  catalog_env=$'    environment:\n      PRODUCT_CATALOG_PATH: /app/catalog/catalog-abo-demo.jsonl\n      QDRANT_COLLECTION: globex_products_abo_demo_v1'
fi
old_config="$live/docker/docker-compose.cloud.yaml"
new_config="$release/docker/docker-compose.cloud.yaml"
version=$(cat "$release/RELEASE_COMMIT")
[[ "$version" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release commit'; exit 1; }
[[ "$release" != "$live" ]] || { echo 'Extract into a separate release directory'; exit 1; }
sudo -v
# Compose records every active config, including the rollback volume override.
config_list=$(sudo docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' globex-app-1)
IFS=',' read -r -a active_configs <<< "$config_list"
(( ${#active_configs[@]} > 0 )) || { echo 'Cannot discover active Compose configuration'; exit 1; }
old=(sudo docker compose -p globex)
for config in "${active_configs[@]}"; do
  config=$(realpath -- "$config")
  case "$config" in /home/admin/globex/*|/home/admin/globex-releases/*|/home/admin/globex-backups/*) ;; *) echo 'Unexpected active config path'; exit 1 ;; esac
  test -f "$config"
  old+=(-f "$config")
done
old_config=${active_configs[0]}
active_env="$(dirname -- "$(dirname -- "$old_config")")/.env"
test -f "$active_env"
"${old[@]}" config --quiet
declare -A active_volumes
for component in app redis qdrant; do
  target=/app/data
  [[ "$component" != redis ]] || target=/data
  [[ "$component" != qdrant ]] || target=/qdrant/storage
  volume=$(sudo docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$target\"}}{{if eq .Type \"volume\"}}{{.Name}}{{end}}{{end}}{{end}}" "globex-$component-1")
  [[ "$volume" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || { echo "Missing named volume for $component"; exit 1; }
  active_volumes[$component]=$volume
  sudo docker volume inspect "$volume" >/dev/null
done
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="/home/admin/globex-backups/$stamp"
mkdir -p "$backup"
chmod 700 /home/admin/globex-backups "$backup"
app_id=$(sudo docker inspect --format '{{.Image}}' globex-app-1)
worker_id=$(sudo docker inspect --format '{{.Image}}' globex-worker-1)
frontend_id=$(sudo docker inspect --format '{{.Image}}' globex-frontend-1)
sudo docker tag "$app_id" "globex-backend:rollback-$stamp"
sudo docker tag "$worker_id" "globex-worker:rollback-$stamp"
sudo docker tag "$frontend_id" "globex-frontend:rollback-$stamp"
cp "$active_env" "$release/.env"
chmod 600 "$release/.env"
cat > "$release/docker/release.override.yaml" <<EOF
services:
  app:
    image: globex-backend:$version
$catalog_env
  worker:
    image: globex-backend:$version
$catalog_env
  frontend:
    image: globex-frontend:$version
EOF
printf '\nvolumes:\n' >> "$release/docker/release.override.yaml"
for component in app redis qdrant; do
  printf '  %s-data:\n    name: %s\n    external: true\n' "$component" "${active_volumes[$component]}" >> "$release/docker/release.override.yaml"
done
new=(sudo docker compose -p globex -f "$new_config" -f "$release/docker/release.override.yaml")
"${new[@]}" config --quiet
echo '[1/5] Building versioned images; current service remains running.'
sudo docker build -f "$release/Dockerfile.cloud" -t "globex-backend:$version" "$release"
sudo docker build -f "$release/frontend/Dockerfile.beta" -t "globex-frontend:$version" "$release/frontend"
echo 'Validating Prompt upgrade evidence before stopping any service.'
prompt_upgrade=0
if [[ -f "$release/prompt-upgrade/upgrade.json" ]]; then
  prompt_upgrade=1
  sudo docker run --rm --network none --entrypoint python \
    --env-file "$release/.env" -e DATA_DIR=/app/data \
    --mount "type=volume,source=${active_volumes[app]},target=/app/data,readonly" \
    --mount "type=bind,source=$release/prompt-upgrade,target=/upgrade,readonly" \
    "globex-backend:$version" -m scripts.apply_prompt_upgrade --bundle /upgrade --check
else
  sudo docker run --rm --network none --entrypoint python \
    --env-file "$release/.env" -e DATA_DIR=/app/data \
    --mount "type=volume,source=${active_volumes[app]},target=/app/data,readonly" \
    "globex-backend:$version" -m scripts.check_prompt_compatibility
fi
mkdir -p "$backup/docker"
cp "$old_config" "$backup/docker/docker-compose.cloud.yaml"
: > "$backup/compose-overrides.txt"
for (( index=1; index<${#active_configs[@]}; index++ )); do
  name="active-$index.yaml"
  cp "${active_configs[$index]}" "$backup/docker/$name"
  printf '%s\n' "$name" >> "$backup/compose-overrides.txt"
done
cp "$active_env" "$backup/.env"
cat > "$backup/rollback.override.yaml" <<EOF
services:
  app:
    image: globex-backend:rollback-$stamp
  worker:
    image: globex-worker:rollback-$stamp
  frontend:
    image: globex-frontend:rollback-$stamp
EOF
"${old[@]}" ps > "$backup/containers.previous.txt"
printf '%s\n' "$release" > "$backup/release-path.txt"
printf '%s\n' "$version" > "$backup/release-commit.txt"
stopped=0
starting_new=0
on_exit() {
  result=$?
  if (( result != 0 )); then
    if (( stopped == 1 && starting_new == 0 )); then
      echo 'Backup failed before new startup; restarting the old service.'
      "${old[@]}" up -d --no-build --pull never || true
    elif (( starting_new == 1 )); then
      echo "New startup/check failed. Backup: $backup"
      echo 'Do not roll back images alone: the new version may have migrated data.'
    fi
  fi
}
trap on_exit EXIT
echo '[2/5] Stopping services for a consistent backup of all three volumes.'
stopped=1
"${old[@]}" stop
for component in app redis qdrant; do
  volume=${active_volumes[$component]}
  sudo docker run --rm --network none --entrypoint python \
    --mount "type=volume,source=$volume,target=/state,readonly" \
    --mount "type=bind,source=$backup,target=/backup" \
    "$app_id" -c 'import os,sys,tarfile,shutil; p="/backup/"+sys.argv[1]+".tar.gz"; t=tarfile.open(p,"w:gz"); t.add("/state",arcname="."); t.close(); t=tarfile.open(p); sink=open(os.devnull,"wb"); [shutil.copyfileobj(t.extractfile(m),sink,1024*1024) for m in t if m.isfile()]; sink.close(); t.close(); os.chmod(p,0o600)' "globex_${component}-data"
done
sudo sha256sum "$backup"/*.tar.gz > "$backup/SHA256SUMS"
if (( prompt_upgrade == 1 )); then
  # No old process may write while the approved deployment is appended.
  starting_new=1
  sudo docker run --rm --network none --entrypoint python \
    --env-file "$release/.env" -e DATA_DIR=/app/data \
    --mount "type=volume,source=${active_volumes[app]},target=/app/data" \
    --mount "type=bind,source=$release/prompt-upgrade,target=/upgrade,readonly" \
    "globex-backend:$version" -m scripts.apply_prompt_upgrade --bundle /upgrade
fi
echo '[3/5] Backup complete. Starting the new release with the existing volumes.'
starting_new=1
"${new[@]}" up -d --no-build --pull never
echo "[4/5] Waiting for frontend and backend readiness (up to $ready_timeout seconds; initial indexing can take several minutes)."
ready=0
for attempt in $(seq 1 "$((ready_timeout / 2))"); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:5173/health >/dev/null && \
     curl --fail --silent --max-time 3 http://127.0.0.1:5173/commerce/auth >/dev/null; then
    ready=1
    break
  fi
  if (( attempt % 30 == 0 )); then
    echo 'Still waiting for startup. Recent application output:'
    "${new[@]}" logs --tail=3 app worker
  fi
  sleep 2
done
"${new[@]}" ps
if (( ready == 0 )); then
  echo 'Readiness check timed out. Inspect logs before proceeding.'
  exit 1
fi
printf '%s\n' "$release" > /home/admin/globex-active-release.txt
echo '[5/5] Server responds. Browser acceptance checks are still required.'
echo "Release: $release"
echo "Backup: $backup"
echo 'Auth status:'
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5173/commerce/auth
printf '\n'
