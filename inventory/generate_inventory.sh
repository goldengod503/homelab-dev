#!/usr/bin/env bash
set -euo pipefail

# ===== Configuration =====
RETENTION_COUNT=14   # number of snapshots to keep
# =========================

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INV_ROOT="$ROOT/inventory"
TS="$(date -Iseconds)"
OUT="$INV_ROOT/$TS"
LATEST="$INV_ROOT/latest"

echo "=== Homelab inventory generation @ $TS ==="

# Create snapshot directory
mkdir -p "$OUT/containers"

# High-level Docker state
docker ps --format '{{json .}}' | jq -s . > "$OUT/docker_ps.json"
docker images --format '{{json .}}' | jq -s . > "$OUT/docker_images.json"
docker volume ls --format '{{json .}}' | jq -s . > "$OUT/docker_volumes.json"
docker network ls --format '{{json .}}' | jq -s . > "$OUT/docker_networks.json"

# Full container inspections
for id in $(docker ps -q); do
  name=$(docker inspect "$id" --format '{{.Name}}' | sed 's#^/##')
  docker inspect "$id" > "$OUT/containers/${name}.json"
done

# Rendered compose (what Docker actually runs)
docker compose config > "$OUT/docker-compose.rendered.yaml"

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

# ===== Retention enforcement =====
echo "Applying retention policy (keep last $RETENTION_COUNT snapshots)"

cd "$INV_ROOT"

# List timestamped directories only, sorted oldest -> newest
SNAPSHOTS=$(ls -1d 20*-*-* 2>/dev/null | sort)

COUNT=$(echo "$SNAPSHOTS" | wc -l)

if [ "$COUNT" -gt "$RETENTION_COUNT" ]; then
  REMOVE_COUNT=$((COUNT - RETENTION_COUNT))
  echo "$SNAPSHOTS" | head -n "$REMOVE_COUNT" | while read -r old; do
    echo "Removing old snapshot: $old"
    rm -rf "$old"
  done
else
  echo "No old snapshots to remove ($COUNT/$RETENTION_COUNT)"
fi

echo "Inventory snapshot complete."
echo "Latest snapshot:"
echo "  $LATEST"
echo "=============================="
echo "See /opt/homelab/KNOWLEDGE.md for rationale and design intent." \
  >> "$OUT/README.md"
echo "=============================="