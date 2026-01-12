#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="/opt/homelab"
BACKUP_ROOT="/opt/homelab/backups"
REMOTE="gdrive_crypt:pi-homelab"
TS="$(date +%F_%H%M%S)"
STAGE="${BACKUP_ROOT}/stage_${TS}"
VOL_DIR="${STAGE}/volumes"

# Metrics collection
METRICS_DIR="/opt/homelab/appdata/backup-monitor"
METRICS_FILE="${METRICS_DIR}/metrics.jsonl"
START_TIME=$(date +%s)
declare -A PHASE_TIMES

# Re-downloadable model blobs we do NOT want inside homelab_files.tgz
EXCLUDE_OLLAMA_MODELS="${COMPOSE_DIR}/appdata/ollama/models"
EXCLUDE_MODELS_DIR="${COMPOSE_DIR}/appdata/models"

# Volumes to SKIP (rebuildable / not needed for DR restore)
# Netdata cache (dbengine) can be large; config/lib are enough to restore the stack.
SKIP_VOLUMES=(
  "homelab_netdatacache"
)

mkdir -p "${STAGE}" "${VOL_DIR}" "${METRICS_DIR}"
cd "${COMPOSE_DIR}"

echo "==> Snapshot: compose + runtime"
PHASE_START=$(date +%s)
docker compose config > "${STAGE}/compose.resolved.yaml"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' > "${STAGE}/docker_ps.txt"
docker volume ls > "${STAGE}/docker_volumes.txt"
docker network ls > "${STAGE}/docker_networks.txt"
PHASE_TIMES[snapshot]=$(($(date +%s) - PHASE_START))

echo "==> Archive: bind-mounted homelab data"
PHASE_START=$(date +%s)

# Estimate size for pv progress (try excluding huge model dirs so ETA is sane).
# If this du build doesn't support --exclude, fall back to full appdata size.
SIZE_BYTES=""
if sudo du --help 2>/dev/null | grep -q -- '--exclude'; then
  SIZE_BYTES="$(sudo du -sb \
    --exclude="${EXCLUDE_OLLAMA_MODELS}" \
    --exclude="${EXCLUDE_MODELS_DIR}" \
    "${COMPOSE_DIR}/appdata" 2>/dev/null | cut -f1 || true)"
fi
if [[ -z "${SIZE_BYTES}" || "${SIZE_BYTES}" == "0" ]]; then
  SIZE_BYTES="$(sudo du -sb "${COMPOSE_DIR}/appdata" | cut -f1)"
fi

# Stream tar through pv so you get progress/%/ETA.
sudo tar -cf - \
  --exclude="${EXCLUDE_OLLAMA_MODELS}" \
  --exclude="${EXCLUDE_MODELS_DIR}" \
  "${COMPOSE_DIR}/docker-compose.yaml" \
  "${COMPOSE_DIR}/appdata" \
  "${COMPOSE_DIR}/.env" 2>/dev/null \
| pv --force -s "${SIZE_BYTES}" -p -t -e -r -a \
| gzip -1 > "${STAGE}/homelab_files.tgz"

PHASE_TIMES[archive]=$(($(date +%s) - PHASE_START))

echo "==> Discovering docker volumes used by this compose project"
mapfile -t CIDS < <(docker compose ps -q)

VOLS=()
for cid in "${CIDS[@]}"; do
  while IFS= read -r v; do
    [[ -n "${v}" ]] && VOLS+=("${v}")
  done < <(docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{"\n"}}{{end}}{{end}}' "${cid}")
done
mapfile -t VOLS < <(printf "%s\n" "${VOLS[@]}" | sort -u)

# helper: returns 0 if $1 is in SKIP_VOLUMES
should_skip_volume() {
  local vol="$1"
  local s
  for s in "${SKIP_VOLUMES[@]}"; do
    [[ "$vol" == "$s" ]] && return 0
  done
  return 1
}

echo "==> Backing up volumes (${#VOLS[@]} found)"
PHASE_START=$(date +%s)
for v in "${VOLS[@]}"; do
  if should_skip_volume "$v"; then
    echo "  -> ${v} (skipping: rebuildable)"
    continue
  fi

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
PHASE_TIMES[volumes]=$(($(date +%s) - PHASE_START))

echo "==> Uploading to Google Drive (encrypted)"
PHASE_START=$(date +%s)
rclone mkdir "${REMOTE}" >/dev/null 2>&1 || true
rclone copy "${STAGE}" "${REMOTE}/${TS}" --transfers 4 --checkers 8 --stats 30s
PHASE_TIMES[upload]=$(($(date +%s) - PHASE_START))

# -------------------------
# Remote prune: keep only the last 5 days on Google Drive
# -------------------------
KEEP_DAYS=5
CUTOFF_EPOCH="$(date -d "${KEEP_DAYS} days ago" +%s)"

echo "==> Pruning remote backups (keep last ${KEEP_DAYS} days)"
echo "    Cutoff: $(date -d "@${CUTOFF_EPOCH}" -Iseconds)"

mapfile -t REMOTE_DIRS < <(
  rclone lsf "${REMOTE}" --dirs-only --max-depth 1 \
  | sed 's:/$::' \
  | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}$' \
  | sort
)

DELETED=0
SKIPPED=0

for d in "${REMOTE_DIRS[@]}"; do
  # Convert "YYYY-MM-DD_HHMMSS" -> "YYYY-MM-DD HHMMSS" for date parsing
  if ! DIR_EPOCH="$(date -d "${d/_/ }" +%s 2>/dev/null)"; then
    echo "    Skipping (unparseable): ${d}"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  if (( DIR_EPOCH < CUTOFF_EPOCH )); then
    echo "    Deleting (older than cutoff): ${REMOTE}/${d}"
    # Don't use Drive trash; actually free space
    rclone purge "${REMOTE}/${d}" --drive-use-trash=false
    DELETED=$((DELETED + 1))
  fi
done

echo "    Remote prune done: deleted=${DELETED}, skipped=${SKIPPED}"

# -------------------------
# Local cleanup: keep newest 2 stages
# -------------------------
echo "==> Cleanup: keep last 2 local stages"
ls -1dt "${BACKUP_ROOT}"/stage_* 2>/dev/null | tail -n +3 | xargs -r rm -rf

# Calculate final metrics
END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))
BACKUP_SIZE=$(du -sb "${STAGE}" | cut -f1)

# Write metrics as JSON line
cat >> "${METRICS_FILE}" <<EOF
{"timestamp":"$(date -Iseconds)","backup_id":"${TS}","success":true,"duration_total":${TOTAL_DURATION},"duration_snapshot":${PHASE_TIMES[snapshot]},"duration_archive":${PHASE_TIMES[archive]},"duration_volumes":${PHASE_TIMES[volumes]},"duration_upload":${PHASE_TIMES[upload]},"size_bytes":${BACKUP_SIZE}}
EOF

echo "==> Done: ${TS} (${TOTAL_DURATION}s, $(numfmt --to=iec-i --suffix=B ${BACKUP_SIZE}))"
