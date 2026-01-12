# Homelab Encrypted Backup Pipeline (Current Script Design)

This document explains **the exact backup pipeline** implemented by:

- **Script:** `/opt/homelab/scripts/backup_to_gdrive.sh`
- **Homelab root:** `/opt/homelab`
- **Local backup root:** `/opt/homelab/backups`
- **Remote target:** `gdrive_crypt:pi-homelab`

> Key detail: **Encryption is provided by `rclone crypt`** via the `gdrive_crypt:` remote (not by gpg/age/openssl in the script).

---

## What this pipeline produces

Each run creates a timestamp `TS` like `YYYY-MM-DD_HHMMSS` and:

1. Creates a local staging folder:
   - `/opt/homelab/backups/stage_<TS>/`

2. Writes snapshot metadata into staging:
   - `compose.resolved.yaml`
   - `docker_ps.txt`
   - `docker_volumes.txt`
   - `docker_networks.txt`

3. Creates a compressed archive of the homelab files:
   - `homelab_files.tgz`

4. Discovers **named Docker volumes used by your Compose services**, and backs each one up into:
   - `stage_<TS>/volumes/<volume_name>.tgz`

   With specific exclusions/skip rules (details below).

5. Uploads the entire staging folder to Google Drive via `rclone copy` into:
   - `gdrive_crypt:pi-homelab/<TS>/...`

6. Prunes old remote backups on Google Drive:
   - **Keeps only backups from the last 5 days** (rolling window; details below)

7. Prunes old local staging folders:
   - keeps newest **2** `stage_*` folders on the Pi

8. Appends one JSON metrics line describing the run to:
   - `/opt/homelab/appdata/backup-monitor/metrics.jsonl`

---

## Why it’s encrypted (and what “encrypted” means here)

Your script uploads to:

- `REMOTE="gdrive_crypt:pi-homelab"`

That **`gdrive_crypt:`** remote is an **rclone crypt remote** layered on top of a real Google Drive remote.

What that means:

- File names are encrypted/obfuscated (on the Drive side).
- File contents are encrypted.
- Google Drive only sees ciphertext.
- **The decryption keys live in your rclone config** (usually `~/.config/rclone/rclone.conf` for your user).

If you restore on a new machine, you must bring over (or recreate) the same `rclone crypt` remote config.

---

## Step-by-step: what the script does

### 1) Setup and staging

- Sets `COMPOSE_DIR="/opt/homelab"`
- Sets `BACKUP_ROOT="/opt/homelab/backups"`
- Sets:
  - `TS="$(date +%F_%H%M%S)"`
  - `STAGE="${BACKUP_ROOT}/stage_${TS}"`
  - `VOL_DIR="${STAGE}/volumes"`

Creates required directories and `cd` into `/opt/homelab`.

---

### 2) Snapshot: Compose + runtime

Creates:

- `compose.resolved.yaml` via:

```bash
docker compose config > "${STAGE}/compose.resolved.yaml"
```

Also captures runtime state:

- `docker_ps.txt` from `docker ps --format ...`
- `docker_volumes.txt` from `docker volume ls`
- `docker_networks.txt` from `docker network ls`

These are restore/debug breadcrumbs (especially useful when you’re rebuilding on a fresh machine).

---

### 3) Archive: homelab files (compose + appdata + .env), with model exclusions

The archive **does include**:

- `/opt/homelab/docker-compose.yaml`
- `/opt/homelab/appdata/`
- `/opt/homelab/.env` (included if present; missing errors suppressed)

But the archive **does NOT include** re-downloadable model blobs:

- `/opt/homelab/appdata/ollama/models`
- `/opt/homelab/appdata/models`

This keeps backups smaller and avoids re-uploading huge artifacts that can be recreated later.

#### Progress estimation (pv sizing)

The script estimates the archive size for progress output. If `du` supports `--exclude`, it estimates size **excluding** those model directories; otherwise it falls back to full `appdata` size.

#### Archive pipeline

The script streams tar through `pv` (forced progress output) and compresses with `gzip -1`:

```bash
sudo tar -cf -   --exclude="/opt/homelab/appdata/ollama/models"   --exclude="/opt/homelab/appdata/models"   "/opt/homelab/docker-compose.yaml"   "/opt/homelab/appdata"   "/opt/homelab/.env" 2>/dev/null | pv --force -s "${SIZE_BYTES}" -p -t -e -r -a | gzip -1 > "${STAGE}/homelab_files.tgz"
```

Notes:
- `pv --force ... -p -t -e -r -a` ensures you see percent/ETA/rate even on finicky terminals.
- `gzip -1` is fast compression (good for the Pi).
- `.env` is included if present; tar warnings about missing `.env` are suppressed.

---

### 4) Backup: Docker named volumes used by this Compose project

This saves you when a service uses **named volumes** rather than bind mounts.

Process:

1. Get compose container IDs:

```bash
docker compose ps -q
```

2. Inspect each container’s mounts and collect **volume names** (`.Mounts` where `.Type == "volume"`).
3. Deduplicate.
4. For each named volume `v`, create a backup archive in:

- `stage_<TS>/volumes/<volume_name>.tgz`

#### Volume skip rules

Some volumes are **intentionally skipped** because they are rebuildable and not required for disaster recovery restore.

Current skip list:

- `homelab_netdatacache`  
  Rationale: Netdata’s cache/dbengine can be large; **config + lib** volumes are enough to restore the monitoring stack (historical metrics will be lost, but the service will come back).

The script prints a line like:

- `-> homelab_netdatacache (skipping: rebuildable)`

#### OpenWebUI volume special handling

For `homelab_open-webui`, the backup **excludes rebuildable cache directories** (these can get large):

- `./cache/embedding`
- `./cache/whisper`
- `./cache/tiktoken`
- `./cache/audio`
- `./cache/image`

This keeps the volume backup focused on essential state, while leaving caches to be regenerated.

Other named volumes are backed up in full (read-only mount into an Alpine container, tarred into the staging folder).

---

### 5) Upload: Google Drive (encrypted via rclone crypt)

Uploads the entire stage folder to a remote folder named by timestamp:

```bash
rclone mkdir "${REMOTE}" >/dev/null 2>&1 || true
rclone copy "${STAGE}" "${REMOTE}/${TS}" --transfers 4 --checkers 8 --stats 30s
```

Remote layout:

- `gdrive_crypt:pi-homelab/<TS>/compose.resolved.yaml`
- `gdrive_crypt:pi-homelab/<TS>/homelab_files.tgz`
- `gdrive_crypt:pi-homelab/<TS>/volumes/<volume>.tgz`
- plus the other snapshot files

---

### 6) Retention: remote prune (keep last 5 days)

**This is the key change from earlier versions.**  
Remote retention is no longer “keep newest N folders.” It is now **time-based**:

- Keep backups whose folder timestamp is within the last **5 days** (rolling window).
- Delete anything older than the cutoff.

Implementation details:

1. Compute a cutoff epoch:
   - `CUTOFF_EPOCH="$(date -d "5 days ago" +%s)"`

2. List remote directories (top level only), and filter to timestamp-shaped folder names:

```bash
rclone lsf "${REMOTE}" --dirs-only --max-depth 1   | sed 's:/$::'   | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}$'   | sort
```

3. For each remote backup folder name `d` (example: `2026-01-12_061530`):
   - Convert it to an epoch time using `date -d "${d/_/ }" +%s`
   - If it’s older than `CUTOFF_EPOCH`, delete it.

4. Deletion uses:

- `rclone purge "${REMOTE}/${d}" --drive-use-trash=false`

Important implications:
- `rclone purge` removes the entire folder tree (not just the files).
- `--drive-use-trash=false` avoids Google Drive “Trash,” so **space is reclaimed immediately** (no recycle-bin safety net).

**What “last 5 days” means here:**  
This is a rolling “now minus 5 days” window (roughly the last 120 hours), not “the last 5 calendar dates at midnight.”

---

### 7) Retention: local prune (keep newest 2)

Deletes older local staging folders beyond the newest **2**:

```bash
ls -1dt "${BACKUP_ROOT}"/stage_* 2>/dev/null | tail -n +3 | xargs -r rm -rf
```

So the Pi does not accumulate staging data indefinitely.

---

### 8) Metrics logging (backup-monitor)

After the run completes, the script writes one JSON line to:

- `/opt/homelab/appdata/backup-monitor/metrics.jsonl`

It captures:
- `timestamp` (ISO)
- `backup_id` (TS)
- `success` (true)
- `duration_total`
- per-phase durations:
  - `duration_snapshot`
  - `duration_archive`
  - `duration_volumes`
  - `duration_upload`
- `size_bytes` (size of the local staging folder)

This is used by your backup monitoring/dashboard tooling to trend backup size and duration over time.

---

## What you must preserve for disaster recovery

1. **Your rclone config** that defines `gdrive_crypt:` (and its underlying drive remote)
   - Typically: `~/.config/rclone/rclone.conf`

2. Any required environment variables/secrets
   - `.env` is included in the archive if it existed at backup time, but make sure you understand what secrets live where.

3. This runbook so restore steps are deterministic

---

## Recommended end-to-end test cadence

- Monthly: `rclone ls/lsl/size` checks + spot-check a backup’s contents (fast)
- Quarterly: full restore rehearsal into a temporary directory (real confidence)

---

## Practical restore implications of the exclusions

- **Ollama models and other downloaded models are excluded** from `homelab_files.tgz`.  
  After a restore, you’ll need to re-pull/re-download them (or restore them separately if you decide they’re worth backing up later).

- **Netdata cache is skipped** (if the skip list is functioning).  
  After a restore, Netdata will run but historic metrics will not be present.

- **OpenWebUI caches are excluded** from the volume archive.  
  After a restore, OpenWebUI may regenerate embeddings/whisper/tiktoken caches over time.
