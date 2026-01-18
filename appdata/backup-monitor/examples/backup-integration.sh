#!/usr/bin/env bash
# Example: How to integrate backup metrics collection into your backup script

set -euo pipefail

METRICS_FILE="/path/to/backup-monitor/data/metrics.jsonl"
BACKUP_DIR="/path/to/backups"
BACKUP_ID="$(date +%F_%H%M%S)"

# Track overall timing
START_TIME=$(date +%s)
declare -A PHASE_TIMES

# Create metrics directory if needed
mkdir -p "$(dirname "${METRICS_FILE}")"

echo "==> Phase 1: Snapshot/metadata"
PHASE_START=$(date +%s)
# Your snapshot commands here...
# docker compose config > snapshot.yaml
# docker ps > containers.txt
PHASE_TIMES[snapshot]=$(($(date +%s) - PHASE_START))

echo "==> Phase 2: Create archive"
PHASE_START=$(date +%s)
# Your archive commands here...
# tar -czf backup.tgz /opt/myapp
PHASE_TIMES[archive]=$(($(date +%s) - PHASE_START))

echo "==> Phase 3: Backup volumes"
PHASE_START=$(date +%s)
# Your volume backup commands here...
# docker run --rm -v myvolume:/data alpine tar -czf /backup/myvolume.tgz /data
PHASE_TIMES[volumes]=$(($(date +%s) - PHASE_START))

echo "==> Phase 4: Upload to remote"
PHASE_START=$(date +%s)
# Your upload commands here...
# rclone copy ./backup remote:backups/
PHASE_TIMES[upload]=$(($(date +%s) - PHASE_START))

# Calculate final metrics
END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))
BACKUP_SIZE=$(du -sb "${BACKUP_DIR}" | cut -f1)

# Write metrics as JSONL
cat >> "${METRICS_FILE}" <<EOF
{"timestamp":"$(date -Iseconds)","backup_id":"${BACKUP_ID}","success":true,"duration_total":${TOTAL_DURATION},"duration_snapshot":${PHASE_TIMES[snapshot]},"duration_archive":${PHASE_TIMES[archive]},"duration_volumes":${PHASE_TIMES[volumes]},"duration_upload":${PHASE_TIMES[upload]},"size_bytes":${BACKUP_SIZE}}
EOF

echo "==> Done: ${BACKUP_ID} (${TOTAL_DURATION}s, $(numfmt --to=iec-i --suffix=B ${BACKUP_SIZE}))"
