#!/usr/bin/env python3
"""
Backup Monitor Dashboard
Lightweight Flask app to visualize homelab backup metrics

Adds:
- DB column: volume_bytes (auto-migrated)
- DB columns: error_category, error_message (auto-migrated)
- Import supports JSONL lines with optional volume_bytes, error_category, error_message
- Stats include separate avg rates:
    - overall (size_bytes / duration_total)
    - archive_rate (size_bytes / duration_archive)
    - upload_rate (size_bytes / duration_upload)
    - volumes_rate (volume_bytes / duration_volumes)
- /api/import returns inserted_count so the UI can show "X new datapoints"
- /api/failures returns last 10 failed backups with error details
- /api/failure-trends returns failure counts grouped by category and week
"""

from flask import Flask, render_template, jsonify
import sqlite3
import json
import os
import threading
import time
from datetime import datetime, timedelta

app = Flask(__name__)

# ----------------------------
# Config
# ----------------------------
def _parse_import_interval_seconds() -> int:
    """
    IMPORT_INTERVAL_HOURS:
      - default: 12h
      - minimum: 1 minute (0.0166h)
    """
    try:
        interval_hours = float(os.getenv('IMPORT_INTERVAL_HOURS', '12'))
        if interval_hours < 0.0166:
            print(f"Warning: IMPORT_INTERVAL_HOURS too small ({interval_hours}h), using minimum 1 minute")
            return 60
        return int(interval_hours * 60 * 60)
    except ValueError as e:
        print(f"Warning: Invalid IMPORT_INTERVAL_HOURS, using default 12h: {e}")
        return 12 * 60 * 60

IMPORT_INTERVAL_SECONDS = _parse_import_interval_seconds()

try:
    RETENTION_DAYS = int(os.getenv('RETENTION_DAYS', '90'))
    if RETENTION_DAYS < 1:
        print("Warning: RETENTION_DAYS must be positive, using default 90")
        RETENTION_DAYS = 90
except ValueError as e:
    print(f"Warning: Invalid RETENTION_DAYS, using default 90: {e}")
    RETENTION_DAYS = 90

DB_PATH = os.getenv('DB_PATH', '/data/backups.db')
METRICS_FILE = os.getenv('METRICS_FILE', '/data/metrics.jsonl')

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)

# ----------------------------
# DB schema + migration helpers
# ----------------------------
def _col_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in c.fetchall()]  # r[1] is column name
    return col in cols

def init_db():
    """Initialize SQLite database and auto-migrate schema changes."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            backup_id TEXT NOT NULL UNIQUE,
            success INTEGER NOT NULL,
            duration_total INTEGER NOT NULL,
            duration_snapshot INTEGER,
            duration_archive INTEGER,
            duration_volumes INTEGER,
            duration_upload INTEGER,
            size_bytes INTEGER NOT NULL,
            volume_bytes INTEGER DEFAULT 0,
            error_category TEXT,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON backups(timestamp)')
    conn.commit()

    # Auto-migrate older DBs
    if not _col_exists(conn, "backups", "volume_bytes"):
        print("Migrating DB: adding column backups.volume_bytes")
        c.execute('ALTER TABLE backups ADD COLUMN volume_bytes INTEGER DEFAULT 0')
        conn.commit()
    for col_def in ['error_category TEXT', 'error_message TEXT']:
        col_name = col_def.split()[0]
        if not _col_exists(conn, "backups", col_name):
            print(f"Migrating DB: adding column backups.{col_name}")
            c.execute(f'ALTER TABLE backups ADD COLUMN {col_def}')
            conn.commit()

    conn.close()

# ----------------------------
# Import
# ----------------------------
def import_metrics() -> int:
    """Import metrics from JSONL file into SQLite. Returns number of newly inserted rows."""
    if not os.path.exists(METRICS_FILE):
        return 0

    inserted = 0
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    with open(METRICS_FILE, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)

                # Required fields
                ts = data['timestamp']
                backup_id = data['backup_id']
                success = data['success']
                duration_total = int(data['duration_total'])
                size_bytes = int(data['size_bytes'])

                # Optional fields
                duration_snapshot = int(data.get('duration_snapshot', 0) or 0)
                duration_archive = int(data.get('duration_archive', 0) or 0)
                duration_volumes = int(data.get('duration_volumes', 0) or 0)
                duration_upload = int(data.get('duration_upload', 0) or 0)
                volume_bytes = int(data.get('volume_bytes', 0) or 0)

                # Error tracking (only meaningful when success=false)
                error_category = None
                error_message = None
                if not success:
                    error_category = data.get('error_category', 'unknown')
                    error_message = data.get('error_message')

                c.execute('''
                    INSERT OR IGNORE INTO backups
                    (timestamp, backup_id, success, duration_total, duration_snapshot,
                     duration_archive, duration_volumes, duration_upload, size_bytes,
                     volume_bytes, error_category, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ts,
                    backup_id,
                    1 if success else 0,
                    duration_total,
                    duration_snapshot,
                    duration_archive,
                    duration_volumes,
                    duration_upload,
                    size_bytes,
                    volume_bytes,
                    error_category,
                    error_message
                ))

                if c.rowcount == 1:
                    inserted += 1

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Skipping invalid line: {e}")
                continue

    conn.commit()

    # Cleanup old records beyond retention
    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).isoformat()
    c.execute('DELETE FROM backups WHERE timestamp < ?', (cutoff,))
    conn.commit()
    conn.close()

    return inserted

# ----------------------------
# Stats
# ----------------------------
def get_stats():
    """Get summary statistics (last 30 days)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()

    c.execute('''
        SELECT
            COUNT(*) as total_backups,
            AVG(duration_total) as avg_duration,
            MAX(duration_total) as max_duration,
            MIN(duration_total) as min_duration,
            AVG(size_bytes) as avg_size,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,

            -- overall throughput (bytes/sec): size_bytes / duration_total
            AVG(CASE WHEN duration_total > 0
                THEN CAST(size_bytes AS REAL) / duration_total
            END) as avg_overall_bps,

            -- archive "processing" rate (bytes/sec): size_bytes / duration_archive
            AVG(CASE WHEN duration_archive > 0
                THEN CAST(size_bytes AS REAL) / duration_archive
            END) as avg_archive_bps,

            -- upload rate (bytes/sec): size_bytes / duration_upload
            AVG(CASE WHEN duration_upload > 0
                THEN CAST(size_bytes AS REAL) / duration_upload
            END) as avg_upload_bps,

            -- volumes rate (bytes/sec): volume_bytes / duration_volumes
            AVG(CASE WHEN duration_volumes > 0
                THEN CAST(volume_bytes AS REAL) / duration_volumes
            END) as avg_volumes_bps

        FROM backups
        WHERE timestamp >= ? AND duration_total > 0
    ''', (thirty_days_ago,))

    row = c.fetchone()
    conn.close()

    if row and row[0]:
        total_backups = row[0]
        successful = row[5] or 0
        failed = total_backups - successful

        def bps_to_mbps(bps):
            return round((bps / 1024 / 1024), 2) if bps else 0.0

        return {
            'total_backups': total_backups,
            'avg_duration': int(row[1]) if row[1] else 0,
            'max_duration': row[2] or 0,
            'min_duration': row[3] or 0,
            'avg_size_mb': int((row[4] or 0) / 1024 / 1024),
            'success_rate': int((successful / total_backups) * 100) if total_backups else 0,
            'failed_backups': failed,

            'avg_throughput_mb_per_sec': bps_to_mbps(row[6]),
            'avg_overall_mb_per_sec': bps_to_mbps(row[6]),
            'avg_archive_mb_per_sec': bps_to_mbps(row[7]),
            'avg_upload_mb_per_sec': bps_to_mbps(row[8]),
            'avg_volumes_mb_per_sec': bps_to_mbps(row[9]),
        }

    return {
        'total_backups': 0,
        'avg_duration': 0,
        'max_duration': 0,
        'min_duration': 0,
        'avg_size_mb': 0,
        'success_rate': 0,
        'failed_backups': 0,
        'avg_throughput_mb_per_sec': 0.0,
        'avg_overall_mb_per_sec': 0.0,
        'avg_archive_mb_per_sec': 0.0,
        'avg_upload_mb_per_sec': 0.0,
        'avg_volumes_mb_per_sec': 0.0,
    }

# ----------------------------
# Routes
# ----------------------------
@app.route('/')
def dashboard():
    stats = get_stats()
    return render_template('dashboard.html', stats=stats)

@app.route('/api/metrics')
def api_metrics():
    """API endpoint for chart/table data."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT timestamp, backup_id, success, duration_total, duration_snapshot,
               duration_archive, duration_volumes, duration_upload,
               size_bytes, volume_bytes, error_category, error_message
        FROM backups
        ORDER BY timestamp DESC
        LIMIT 30
    ''')

    rows = c.fetchall()
    conn.close()

    metrics = []
    for row in reversed(rows):
        timestamp, backup_id = row[0], row[1]
        success = row[2]
        duration_total = row[3] or 0
        duration_archive = row[5] or 0
        duration_volumes = row[6] or 0
        duration_upload = row[7] or 0
        size_bytes = row[8] or 0
        volume_bytes = row[9] or 0

        overall_mb_s = (size_bytes / duration_total / 1024 / 1024) if duration_total > 0 else 0
        archive_mb_s = (size_bytes / duration_archive / 1024 / 1024) if duration_archive > 0 else 0
        upload_mb_s = (size_bytes / duration_upload / 1024 / 1024) if duration_upload > 0 else 0
        volumes_mb_s = (volume_bytes / duration_volumes / 1024 / 1024) if duration_volumes > 0 else 0

        metrics.append({
            'timestamp': timestamp,
            'backup_id': backup_id,
            'success': bool(success),
            'duration_total': duration_total,
            'duration_snapshot': row[4] or 0,
            'duration_archive': duration_archive,
            'duration_volumes': duration_volumes,
            'duration_upload': duration_upload,
            'size_bytes': size_bytes,
            'volume_bytes': volume_bytes,
            'throughput_mb_per_sec': round(overall_mb_s, 2),
            'archive_mb_per_sec': round(archive_mb_s, 2),
            'upload_mb_per_sec': round(upload_mb_s, 2),
            'volumes_mb_per_sec': round(volumes_mb_s, 2),
            'error_category': row[10],
            'error_message': row[11]
        })

    return jsonify(metrics)

@app.route('/api/failures')
def api_failures():
    """API endpoint for recent failures."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT timestamp, backup_id, error_category, error_message
        FROM backups
        WHERE success = 0
        ORDER BY timestamp DESC
        LIMIT 10
    ''')

    rows = c.fetchall()
    conn.close()

    failures = [{
        'timestamp': row[0],
        'backup_id': row[1],
        'error_category': row[2] or 'unknown',
        'error_message': row[3]
    } for row in rows]

    return jsonify(failures)

@app.route('/api/failure-trends')
def api_failure_trends():
    """API endpoint for failure trends by category per week."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()

    c.execute('''
        SELECT
            strftime('%Y-%W', timestamp) as week,
            error_category,
            COUNT(*) as count
        FROM backups
        WHERE success = 0 AND timestamp >= ?
        GROUP BY week, error_category
        ORDER BY week
    ''', (thirty_days_ago,))

    rows = c.fetchall()
    conn.close()

    trends = [{'week': row[0], 'error_category': row[1] or 'unknown', 'count': row[2]} for row in rows]
    return jsonify(trends)

@app.route('/api/import', methods=['POST'])
def api_import():
    inserted = import_metrics()
    return jsonify({
        'status': 'ok',
        'imported_at': datetime.now().isoformat(),
        'inserted': inserted
    })

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

# ----------------------------
# Background importer
# ----------------------------
def periodic_import():
    while True:
        try:
            print(f"[{datetime.now().isoformat()}] Running periodic metrics import...")
            inserted = import_metrics()
            print(f"[{datetime.now().isoformat()}] Metrics import completed (inserted={inserted})")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error during periodic import: {e}")
        time.sleep(IMPORT_INTERVAL_SECONDS)

if __name__ == '__main__':
    print("=" * 60)
    print("Backup Monitor Configuration:")
    print(f"  Database:        {DB_PATH}")
    print(f"  Metrics file:    {METRICS_FILE}")
    print(f"  Retention:       {RETENTION_DAYS} days")
    print(f"  Import interval: {IMPORT_INTERVAL_SECONDS / 3600} hours")
    print("=" * 60)

    init_db()
    import_metrics()

    import_thread = threading.Thread(target=periodic_import, daemon=True)
    import_thread.start()
    print(f"Started periodic import thread (every {IMPORT_INTERVAL_SECONDS / 3600} hours)")

    app.run(host='0.0.0.0', port=5001)
