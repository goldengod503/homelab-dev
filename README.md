# Homelab Backup Monitor

A lightweight, self-hosted dashboard for tracking backup metrics and trends. Built for homelabs running on resource-constrained hardware like Raspberry Pi.

![Dashboard Preview](https://img.shields.io/badge/status-beta-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Minimal Resource Usage**: ~64MB RAM, runs on Raspberry Pi
- **Simple Metrics**: Track backup duration (by phase), size, and success rate
- **Trend Analysis**: 90-day retention with visual charts
- **Easy Integration**: Drop-in JSONL metrics format
- **Self-Contained**: SQLite backend, no external dependencies
- **Clean UI**: Modern dark theme with Chart.js visualizations

## Dashboard

The dashboard displays:
- **Summary Cards**: Total backups, success rate, avg duration, avg size (last 30 days)
- **Duration Trend Chart**: Line chart showing backup times over time
- **Size Trend Chart**: Bar chart showing backup sizes
- **Phase Breakdown**: Doughnut chart breaking down the most recent backup by phase

## Quick Start

### Using Docker Compose

1. Create a directory for the monitor:
```bash
mkdir -p /opt/backup-monitor
```

2. Create a `docker-compose.yml`:
```yaml
version: '3'

services:
  backup-monitor:
    image: ghcr.io/yourusername/homelab-backup-monitor:latest
    # Or build locally:
    # build: .
    container_name: backup-monitor
    restart: unless-stopped
    ports:
      - "5001:5001"
    volumes:
      - ./data:/data
    environment:
      TZ: America/Los_Angeles  # Set your timezone
    mem_limit: 128m
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:5001/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
```

3. Start the container:
```bash
docker compose up -d
```

4. Access the dashboard at `http://your-server:5001`

### Building from Source

```bash
git clone https://github.com/yourusername/homelab-backup-monitor.git
cd homelab-backup-monitor
docker build -t backup-monitor .
docker run -d -p 5001:5001 -v ./data:/data backup-monitor
```

## Metrics Integration

The monitor expects metrics in JSONL format (one JSON object per line) at `/data/metrics.jsonl`.

### Metric Format

Each backup run should append a JSON line with this structure:

```json
{
  "timestamp": "2026-01-07T02:00:00-08:00",
  "backup_id": "2026-01-07_020000",
  "success": true,
  "duration_total": 1265,
  "duration_snapshot": 5,
  "duration_archive": 318,
  "duration_volumes": 485,
  "duration_upload": 457,
  "size_bytes": 2912345678
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 timestamp |
| `backup_id` | string | Unique identifier for this backup |
| `success` | boolean | Whether backup succeeded |
| `duration_total` | integer | Total backup time (seconds) |
| `duration_snapshot` | integer | Time to snapshot metadata (seconds) |
| `duration_archive` | integer | Time to create archive (seconds) |
| `duration_volumes` | integer | Time to backup volumes (seconds) |
| `duration_upload` | integer | Time to upload (seconds) |
| `size_bytes` | integer | Total backup size (bytes) |

### Example Bash Integration

Add this to the end of your backup script:

```bash
#!/bin/bash
METRICS_FILE="/path/to/data/metrics.jsonl"
START_TIME=$(date +%s)
BACKUP_ID="$(date +%F_%H%M%S)"

# Your backup commands here...

# Calculate metrics
END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))
BACKUP_SIZE=$(du -sb /path/to/backup | cut -f1)

# Write metrics
cat >> "${METRICS_FILE}" <<EOF
{"timestamp":"$(date -Iseconds)","backup_id":"${BACKUP_ID}","success":true,"duration_total":${TOTAL_DURATION},"duration_snapshot":0,"duration_archive":0,"duration_volumes":0,"duration_upload":0,"size_bytes":${BACKUP_SIZE}}
EOF
```

For phase-level timing, see the [integration example](examples/backup-integration.sh).

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | UTC | Timezone for timestamps |
| `RETENTION_DAYS` | 90 | How long to keep metrics |

### Data Retention

The monitor automatically prunes metrics older than `RETENTION_DAYS` on each import. To manually clean up:

```bash
# Keep last 100 entries in JSONL
tail -n 100 data/metrics.jsonl > data/metrics.jsonl.tmp
mv data/metrics.jsonl.tmp data/metrics.jsonl

# Rebuild database from JSONL
rm data/backups.db
docker compose restart backup-monitor
```

## API Endpoints

- `GET /` - Dashboard UI
- `GET /api/metrics` - JSON array of recent metrics (last 30)
- `GET /health` - Health check endpoint

## Resource Usage

Tested on Raspberry Pi 4 (8GB):
- **Memory**: 64MB typical, 128MB limit
- **CPU**: Minimal (only during page loads)
- **Storage**: ~100KB SQLite database for 90 days of daily backups
- **Container Size**: ~45MB

## Architecture

- **Backend**: Python Flask (lightweight, minimal dependencies)
- **Database**: SQLite (serverless, no daemon overhead)
- **Frontend**: Vanilla JavaScript with Chart.js
- **Styling**: Custom CSS (no frameworks)

## Development

### Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5001`

### Adding Sample Data

```bash
cat > data/metrics.jsonl <<EOF
{"timestamp":"2026-01-07T02:00:00-08:00","backup_id":"2026-01-07_020000","success":true,"duration_total":1265,"duration_snapshot":5,"duration_archive":318,"duration_volumes":485,"duration_upload":457,"size_bytes":2912345678}
EOF

# Restart to import
docker compose restart backup-monitor
```

## Roadmap

- [ ] Alert notifications for failed backups
- [ ] Email/webhook integration
- [ ] Comparison to remote backup inventory
- [ ] Restore time estimates
- [ ] Multi-backup job support
- [ ] Dark/light theme toggle

## Contributing

Contributions welcome! Please open an issue or PR.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

Built for the self-hosted/homelab community. Optimized for Raspberry Pi and resource-constrained environments.
