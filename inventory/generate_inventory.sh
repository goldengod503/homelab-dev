#!/usr/bin/env bash
set -euo pipefail

# ===== Configuration =====
RETENTION_COUNT=14   # number of snapshots to keep
LOG_FILE_NAME="inventory.log"
# =========================

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INV_ROOT="$ROOT/inventory"

# filesystem-safe timestamp (no ':' like date -Iseconds)
TS="$(date '+%Y-%m-%dT%H%M%S%z')"
OUT="$INV_ROOT/$TS"
LATEST="$INV_ROOT/latest"
LOG_FILE="$INV_ROOT/$LOG_FILE_NAME"

# Ensure dirs exist
mkdir -p "$OUT/containers"

# Log everything to file + console (safe: does not print your env values)
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== Homelab inventory generation @ $TS ==="
echo "ROOT=$ROOT"
echo "OUT=$OUT"
echo "LOG_FILE=$LOG_FILE"

# Dependencies
command -v docker >/dev/null
command -v jq >/dev/null

# Make compose deterministic, regardless of cwd/cron environment
COMPOSE_FILE_PATH="$ROOT/docker-compose.yaml"
export COMPOSE_FILE="$COMPOSE_FILE_PATH"
cd "$ROOT"

# High-level Docker state
docker ps -a --format '{{json .}}' | jq -s . > "$OUT/docker_ps.json"
docker images --format '{{json .}}' | jq -s . > "$OUT/docker_images.json"
docker volume ls --format '{{json .}}' | jq -s . > "$OUT/docker_volumes.json"
docker network ls --format '{{json .}}' | jq -s . > "$OUT/docker_networks.json"

# Full container inspections (include stopped containers) + redact secrets inside Env
while IFS= read -r id; do
  name="$(docker inspect "$id" --format '{{.Name}}' | sed 's#^/##')"
  tmp="$OUT/containers/${name}.json.tmp"
  out="$OUT/containers/${name}.json"

  docker inspect "$id" | jq '
    map(
      .Config.Env |= (
        if . == null then . else
          map(
            if test("^OPENAI_API_KEY=") then "OPENAI_API_KEY=<redacted>"
            else .
            end
          )
        end
      )
    )
  ' > "$tmp"

  mv "$tmp" "$out"
done < <(docker ps -aq)

# Rendered compose (what Docker actually runs) — REDACT secrets
docker compose config | sed -E \
  's/(OPENAI_API_KEY:).*/\1 <redacted>/' \
  > "$OUT/docker-compose.rendered.yaml"

# Metadata
cat > "$OUT/README.md" <<EOF
# Homelab Inventory Snapshot

Generated: $TS

⚠️ This directory is auto-generated.
Do not edit files manually.

Source of truth:
- docker-compose.yaml
- bind-mounted data under /opt/homelab
EOF

# Update stable pointer
rm -rf "$LATEST"
ln -s "$OUT" "$LATEST"

# ===== Retention enforcement (robust) =====
echo "Applying retention policy (keep last $RETENTION_COUNT snapshots)"
cd "$INV_ROOT"

mapfile -t snapshots < <(find . -maxdepth 1 -type d -name '20*' -printf '%P\n' | sort)
count="${#snapshots[@]}"
echo "Found $count snapshot(s)."

if (( count > RETENTION_COUNT )); then
  remove_count=$((count - RETENTION_COUNT))
  echo "Removing $remove_count old snapshot(s)..."
  for ((i=0; i<remove_count; i++)); do
    old="${snapshots[$i]}"
    echo "Removing old snapshot: $old"
    rm -rf -- "$old"
  done
else
  echo "No old snapshots to remove ($count/$RETENTION_COUNT)"
fi

echo "Inventory snapshot complete."
echo "Latest snapshot:"
echo "  $LATEST"
echo "=============================="
echo "See /opt/homelab/KNOWLEDGE.md for rationale and design intent." >> "$OUT/README.md"
