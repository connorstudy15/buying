#!/usr/bin/env bash
# Restore pre-update data into NEW volumes, preserving the failed release data.
set -Eeuo pipefail
umask 077
backup=$(realpath -- "${1:?Usage: bash scripts/rollback_cloud.sh /home/admin/globex-backups/TIMESTAMP}")
[[ "$backup" == /home/admin/globex-backups/* ]] || exit 1
stamp=$(basename "$backup")
[[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || exit 1
test -f "$backup/docker/docker-compose.cloud.yaml"
test -f "$backup/.env"
sudo -v
sudo sha256sum --check "$backup/SHA256SUMS"
for component in backend worker frontend; do
  sudo docker image inspect "globex-$component:rollback-$stamp" >/dev/null
done
restore_stamp=$(date -u +%Y%m%dT%H%M%SZ)
override="$backup/restore-$restore_stamp.yaml"
cp "$backup/rollback.override.yaml" "$override"
printf '\nvolumes:\n' >> "$override"
for component in app redis qdrant; do
  volume="globex_restore_${component}_${restore_stamp}"
  if sudo docker volume inspect "$volume" >/dev/null 2>&1; then
    echo "Restore destination already exists: $volume"
    exit 1
  fi
  sudo docker volume create "$volume" >/dev/null
  sudo docker run --rm --network none --entrypoint python \
    --mount "type=volume,source=$volume,target=/restore" \
    --mount "type=bind,source=$backup,target=/backup,readonly" \
    "globex-backend:rollback-$stamp" -c \
    'import sys,tarfile; t=tarfile.open("/backup/globex_"+sys.argv[1]+"-data.tar.gz"); t.extractall("/restore",filter="data"); t.close()' "$component"
  printf '  %s-data:\n    name: %s\n' "$component" "$volume" >> "$override"
done
old=(sudo docker compose -p globex -f "$backup/docker/docker-compose.cloud.yaml" -f "$override")
"${old[@]}" config --quiet
"${old[@]}" stop
"${old[@]}" up -d --no-build --pull never
"${old[@]}" ps
echo "Restored pre-update data into new volumes. Original volumes were preserved."
echo "Rollback override: $override"
