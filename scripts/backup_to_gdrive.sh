#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="/opt/homelab"
BACKUP_ROOT="/opt/homelab/backups"
REMOTE="gdrive_crypt:pi-homelab"
TS="$(date +%F_%H%M%S)"
STAGE="${BACKUP_ROOT}/stage_${TS}"
VOL_DIR="${STAGE}/volumes"

# Paths we do NOT want inside homelab_files.tgz (re-downloadable model blobs)
EXCLUDE_APPDATA_PATHS=(
  "${COMPOSE_DIR}/appdata/ollama/models"
  "${COMPOSE_DIR}/appdata/models"
)

mkdir -p "${STAGE}" "${VOL_DIR}"
cd "${COMPOSE_DIR}"

echo "==> Snapshot: compose + runtime"
docker compose config > "${STAGE}/compose.resolved.yaml"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' > "${STAGE}/docker_ps.txt"
docker volume ls > "${STAGE}/docker_volumes.txt"
docker network ls > "${STAGE}/docker_networks.txt"

echo "==> Archive: bind-mounted homelab data"

# Estimate size for pv progress (try to exclude the huge model dirs so ETA is sane).
# Some du builds may not support --exclude, so we fall back.
SIZE_BYTES=""
if sudo du --help 2>/dev/null | grep -q -- '--exclude'; then
  # shellcheck disable=SC2068
  SIZE_BYTES="$(sudo du -sb "${COMPOSE_DIR}/appdata" \
    $(printf -- ' --exclude=%q' "${EXCLUDE_APPDATA_PATHS[@]}") \
    2>/dev/null | cut -f1 || true)"
fi

if [[ -z "${SIZE_BYTES}" || "${SIZE_BYTES}" == "0" ]]; then
  SIZE_BYTES="$(sudo du -sb "${COMPOSE_DIR}/appdata" | cut -f1)"
fi

# Stream tar through pv so you get progress/ETA.
# Note: we only estimate based on appdata size; compression changes final file size.
sudo tar -cf - \
  "$(printf -- ' --exclude=%q' "${EXCLUDE_APPDATA_PATHS[@]}")" \
  "${COMPOSE_DIR}/docker-compose.yaml" \
  "${COMPOSE_DIR}/appdata" \
  "${COMPOSE_DIR}/.env" 2>/dev/null \
| pv -s "${SIZE_BYTES}" \
| gzip -1 > "${STAGE}/homelab_files.tgz"

echo "==> Discovering docker volumes used by this compose project"
mapfile -t CIDS < <(docker compose ps -q)

VOLS=()
for cid in "${CIDS[@]}"; do
  while IFS= read -r v; do
    [[ -n "${v}" ]] && VOLS+=("${v}")
  done < <(docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{"\n"}}{{end}}{{end}}' "${cid}")
done
mapfile -t VOLS < <(printf "%s\n" "${VOLS[@]}" | sort -u)

echo "==> Backing up volumes (${#VOLS[@]} found)"
for v in "${VOLS[@]}"; do
  echo "  -> ${v}"

  if [[ "${v}" == "homelab_open-webui" ]]; then
    # OpenWebUI cache dirs are rebuildable and can be large; keep the important bits.
    docker run --rm \
      -v "${v}:/volume:ro" \
      -v "${VOL_DIR}:/backup" \
      alpine:3.20 sh -lc '
        cd /volume
        tar -czf "/backup/'"${v}"'.tgz" \
          --exclude="./cache/embedding" \
          --exclude="./cache/whisper" \
          --exclude="./cache/tiktoken" \
          --exclude="./cache/audio" \
          --exclude="./cache/image" \
          .
      '
  else
    docker run --rm \
      -v "${v}:/volume:ro" \
      -v "${VOL_DIR}:/backup" \
      alpine:3.20 sh -lc "cd /volume && tar -czf /backup/${v}.tgz ."
  fi
done

echo "==> Uploading to Google Drive (encrypted)"
rclone mkdir "${REMOTE}" >/dev/null 2>&1 || true
rclone copy "${STAGE}" "${REMOTE}/${TS}" --transfers 4 --checkers 8 --stats 30s

# -------------------------
# Remote prune: keep newest 15 backups
# -------------------------
KEEP_REMOTE=15
echo "==> Pruning remote backups (keep newest ${KEEP_REMOTE})"

# Timestamp folder names sort correctly (lexical == chronological)
mapfile -t REMOTE_DIRS < <(
  rclone lsf "${REMOTE}" --dirs-only --max-depth 1 \
  | sed 's:/$::' \
  | sort
)

COUNT="${#REMOTE_DIRS[@]}"
if (( COUNT <= KEEP_REMOTE )); then
  echo "    Nothing to prune (found ${COUNT})"
else
  TO_DELETE=$((COUNT - KEEP_REMOTE))
  echo "    Found ${COUNT}; deleting oldest ${TO_DELETE}"

  for d in "${REMOTE_DIRS[@]:0:TO_DELETE}"; do
    echo "    Deleting: ${REMOTE}/${d}"
    rclone purge "${REMOTE}/${d}"
  done
fi

echo "==> Cleanup: keep last 7 local stages"
ls -1dt "${BACKUP_ROOT}"/stage_* 2>/dev/null | tail -n +8 | xargs -r rm -rf

echo "==> Done: ${TS}"
