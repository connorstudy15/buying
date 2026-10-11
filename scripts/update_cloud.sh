#!/usr/bin/env bash
# Run from the extracted release directory with: bash scripts/update_cloud.sh
set -Eeuo pipefail
umask 077
release=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
live=/home/admin/globex
catalog=${GLOBEX_CATALOG:-default}
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
test -f "$old_config"
test -f "$live/.env"
sudo -v
old=(sudo docker compose -p globex -f "$old_config")
"${old[@]}" config --quiet
current_app_volume=$(sudo docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Name}}{{end}}{{end}}' globex-app-1)
[[ "$current_app_volume" == globex_app-data ]] || { echo 'Active data volume differs from the original deployment. Resolve the active Compose configuration before updating; no services were stopped.'; exit 1; }
for volume in globex_app-data globex_redis-data globex_qdrant-data; do
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
cp "$live/.env" "$release/.env"
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
new=(sudo docker compose -p globex -f "$new_config" -f "$release/docker/release.override.yaml")
"${new[@]}" config --quiet
echo '[1/5] Building versioned images; current service remains running.'
sudo docker build -f "$release/Dockerfile.cloud" -t "globex-backend:$version" "$release"
sudo docker build -f "$release/frontend/Dockerfile.beta" -t "globex-frontend:$version" "$release/frontend"
echo 'Checking active Prompt compatibility before stopping any service.'
sudo docker run --rm --network none --entrypoint python \
  --env-file "$release/.env" -e DATA_DIR=/app/data \
  --mount 'type=volume,source=globex_app-data,target=/app/data,readonly' \
  "globex-backend:$version" -m scripts.check_prompt_compatibility
mkdir -p "$backup/docker"
cp "$old_config" "$backup/docker/docker-compose.cloud.yaml"
cp "$live/.env" "$backup/.env"
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
for volume in globex_app-data globex_redis-data globex_qdrant-data; do
  sudo docker run --rm --network none --entrypoint python \
    --mount "type=volume,source=$volume,target=/state,readonly" \
    --mount "type=bind,source=$backup,target=/backup" \
    "$app_id" -c 'import os,sys,tarfile,shutil; p="/backup/"+sys.argv[1]+".tar.gz"; t=tarfile.open(p,"w:gz"); t.add("/state",arcname="."); t.close(); t=tarfile.open(p); sink=open(os.devnull,"wb"); [shutil.copyfileobj(t.extractfile(m),sink,1024*1024) for m in t if m.isfile()]; sink.close(); t.close(); os.chmod(p,0o600)' "$volume"
done
sudo sha256sum "$backup"/*.tar.gz > "$backup/SHA256SUMS"
echo '[3/5] Backup complete. Starting the new release with the existing volumes.'
starting_new=1
"${new[@]}" up -d --no-build --pull never
echo '[4/5] Waiting for frontend and backend readiness (up to 180 seconds).'
ready=0
for attempt in $(seq 1 90); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:5173/health >/dev/null && \
     curl --fail --silent --max-time 3 http://127.0.0.1:5173/commerce/auth >/dev/null; then
    ready=1
    break
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
