#!/usr/bin/env bash
# Example: How to integrate backup metrics collection into your backup script

set -uo pipefail

METRICS_FILE="/path/to/backup-monitor/data/metrics.jsonl"
BACKUP_DIR="/path/to/backups"
BACKUP_ID="$(date +%F_%H%M%S)"

# Track overall timing
START_TIME=$(date +%s)
declare -A PHASE_TIMES

# Error tracking
SUCCESS=true
ERROR_CATEGORY=""
ERROR_MESSAGE=""

# Create metrics directory if needed
mkdir -p "$(dirname "${METRICS_FILE}")"

run_phase() {
    local phase_name="$1"
    local phase_label="$2"
    shift 2

    echo "==> ${phase_label}"
    local phase_start
    phase_start=$(date +%s)

    if "$@"; then
        PHASE_TIMES[${phase_name}]=$(($(date +%s) - phase_start))
    else
        PHASE_TIMES[${phase_name}]=$(($(date +%s) - phase_start))
        SUCCESS=false
        ERROR_CATEGORY="${phase_name}_failed"
        ERROR_MESSAGE="Phase '${phase_label}' failed with exit code $?"
        return 1
    fi
}

# Run backup phases — replace the example commands with your own
run_phase snapshot "Phase 1: Snapshot/metadata" true  # e.g. docker compose config > snapshot.yaml
run_phase archive  "Phase 2: Create archive"    true  # e.g. tar -czf backup.tgz /opt/myapp
run_phase volumes  "Phase 3: Backup volumes"    true  # e.g. docker run --rm -v vol:/data alpine tar czf ...
run_phase upload   "Phase 4: Upload to remote"  true  # e.g. rclone copy ./backup remote:backups/

# Calculate final metrics
END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))
BACKUP_SIZE=$(du -sb "${BACKUP_DIR}" 2>/dev/null | cut -f1 || echo 0)

# Build error fields for JSONL
ERROR_FIELDS=""
if [ "${SUCCESS}" = false ]; then
    ERROR_FIELDS="\"error_category\":\"${ERROR_CATEGORY}\",\"error_message\":\"${ERROR_MESSAGE}\","
fi

# Write metrics as JSONL
cat >> "${METRICS_FILE}" <<EOF
{"timestamp":"$(date -Iseconds)","backup_id":"${BACKUP_ID}","success":${SUCCESS},${ERROR_FIELDS}"duration_total":${TOTAL_DURATION},"duration_snapshot":${PHASE_TIMES[snapshot]:-0},"duration_archive":${PHASE_TIMES[archive]:-0},"duration_volumes":${PHASE_TIMES[volumes]:-0},"duration_upload":${PHASE_TIMES[upload]:-0},"size_bytes":${BACKUP_SIZE}}
EOF

echo "==> Done: ${BACKUP_ID} (${TOTAL_DURATION}s, $(numfmt --to=iec-i --suffix=B ${BACKUP_SIZE}))"
if [ "${SUCCESS}" = false ]; then
    echo "==> FAILED: [${ERROR_CATEGORY}] ${ERROR_MESSAGE}"
fi
