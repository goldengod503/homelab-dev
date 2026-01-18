#!/usr/bin/env python3
"""
Backup Monitor Dashboard
Lightweight Flask app to visualize homelab backup metrics
"""

from flask import Flask, render_template, jsonify
import sqlite3
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

app = Flask(__name__)

# Config - load from environment with sensible defaults
try:
    interval_hours = float(os.getenv('IMPORT_INTERVAL_HOURS', '6'))
    if interval_hours < 0.0166:  # Minimum 1 minute
        print(f"Warning: IMPORT_INTERVAL_HOURS too small ({interval_hours}h), using minimum 1 minute")
        IMPORT_INTERVAL_SECONDS = 60
    else:
        IMPORT_INTERVAL_SECONDS = int(interval_hours * 60 * 60)
except ValueError as e:
    print(f"Warning: Invalid IMPORT_INTERVAL_HOURS, using default 6h: {e}")
    IMPORT_INTERVAL_SECONDS = 6 * 60 * 60

try:
    RETENTION_DAYS = int(os.getenv('RETENTION_DAYS', '90'))
    if RETENTION_DAYS < 1:
        print(f"Warning: RETENTION_DAYS must be positive, using default 90")
        RETENTION_DAYS = 90
except ValueError as e:
    print(f"Warning: Invalid RETENTION_DAYS, using default 90: {e}")
    RETENTION_DAYS = 90

DB_PATH = os.getenv('DB_PATH', '/data/backups.db')
METRICS_FILE = os.getenv('METRICS_FILE', '/data/metrics.jsonl')

# Ensure parent directories exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)

def init_db():
    """Initialize SQLite database with schema"""
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON backups(timestamp)')
    conn.commit()
    conn.close()

def import_metrics():
    """Import metrics from JSONL file into SQLite"""
    if not os.path.exists(METRICS_FILE):
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    with open(METRICS_FILE, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                c.execute('''
                    INSERT OR IGNORE INTO backups
                    (timestamp, backup_id, success, duration_total, duration_snapshot,
                     duration_archive, duration_volumes, duration_upload, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['timestamp'],
                    data['backup_id'],
                    1 if data['success'] else 0,
                    data['duration_total'],
                    data.get('duration_snapshot', 0),
                    data.get('duration_archive', 0),
                    data.get('duration_volumes', 0),
                    data.get('duration_upload', 0),
                    data['size_bytes']
                ))
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Skipping invalid line: {e}")
                continue

    conn.commit()

    # Cleanup old records beyond retention
    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).isoformat()
    c.execute('DELETE FROM backups WHERE timestamp < ?', (cutoff,))
    conn.commit()
    conn.close()

def get_stats():
    """Get summary statistics"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Last 30 days stats
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()

    c.execute('''
        SELECT
            COUNT(*) as total_backups,
            AVG(duration_total) as avg_duration,
            MAX(duration_total) as max_duration,
            MIN(duration_total) as min_duration,
            AVG(size_bytes) as avg_size,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
        FROM backups
        WHERE timestamp >= ?
    ''', (thirty_days_ago,))

    row = c.fetchone()
    conn.close()

    if row and row[0]:
        return {
            'total_backups': row[0],
            'avg_duration': int(row[1]) if row[1] else 0,
            'max_duration': row[2] or 0,
            'min_duration': row[3] or 0,
            'avg_size_mb': int(row[4] / 1024 / 1024) if row[4] else 0,
            'success_rate': int((row[5] / row[0]) * 100) if row[0] else 0
        }
    return {
        'total_backups': 0,
        'avg_duration': 0,
        'max_duration': 0,
        'min_duration': 0,
        'avg_size_mb': 0,
        'success_rate': 0
    }

@app.route('/')
def dashboard():
    """Main dashboard page"""
    stats = get_stats()
    return render_template('dashboard.html', stats=stats)

@app.route('/api/metrics')
def api_metrics():
    """API endpoint for metrics data"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get last 30 backups
    c.execute('''
        SELECT timestamp, backup_id, duration_total, duration_snapshot,
               duration_archive, duration_volumes, duration_upload, size_bytes
        FROM backups
        ORDER BY timestamp DESC
        LIMIT 30
    ''')

    rows = c.fetchall()
    conn.close()

    metrics = []
    for row in reversed(rows):
        metrics.append({
            'timestamp': row[0],
            'backup_id': row[1],
            'duration_total': row[2],
            'duration_snapshot': row[3] or 0,
            'duration_archive': row[4] or 0,
            'duration_volumes': row[5] or 0,
            'duration_upload': row[6] or 0,
            'size_bytes': row[7]
        })

    return jsonify(metrics)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

def periodic_import():
    """Background thread to periodically import new metrics"""
    while True:
        try:
            time.sleep(IMPORT_INTERVAL_SECONDS)
            print(f"[{datetime.now().isoformat()}] Running periodic metrics import...")
            import_metrics()
            print(f"[{datetime.now().isoformat()}] Metrics import completed")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error during periodic import: {e}")

if __name__ == '__main__':
    # Print startup configuration
    print("=" * 60)
    print("Backup Monitor Configuration:")
    print(f"  Database:        {DB_PATH}")
    print(f"  Metrics file:    {METRICS_FILE}")
    print(f"  Retention:       {RETENTION_DAYS} days")
    print(f"  Import interval: {IMPORT_INTERVAL_SECONDS / 3600} hours")
    print("=" * 60)

    # Initialize database
    init_db()

    # Import any existing metrics
    import_metrics()

    # Start background thread for periodic imports
    import_thread = threading.Thread(target=periodic_import, daemon=True)
    import_thread.start()
    print(f"Started periodic import thread (every {IMPORT_INTERVAL_SECONDS / 3600} hours)")

    # Run Flask
    app.run(host='0.0.0.0', port=5001)
