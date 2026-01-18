#!/usr/bin/env python3
"""
Backup Monitor Dashboard
Lightweight Flask app to visualize homelab backup metrics
"""

from flask import Flask, render_template_string, jsonify
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

    html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backup Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            font-size: 2rem;
            margin-bottom: 10px;
            color: #f8fafc;
        }
        .subtitle {
            color: #94a3b8;
            margin-bottom: 30px;
            font-size: 0.95rem;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
        }
        .stat-label {
            color: #94a3b8;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .stat-value {
            font-size: 2rem;
            font-weight: 600;
            color: #f8fafc;
        }
        .stat-unit {
            font-size: 1rem;
            color: #64748b;
            margin-left: 4px;
        }
        .chart-container {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .chart-title {
            font-size: 1.1rem;
            margin-bottom: 15px;
            color: #f8fafc;
        }
        .canvas-wrapper {
            position: relative;
            height: 300px;
        }
        .success { color: #10b981; }
        .loading {
            text-align: center;
            padding: 40px;
            color: #64748b;
        }
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: 1fr; }
            h1 { font-size: 1.5rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏠 Homelab Backup Monitor</h1>
        <p class="subtitle">Nightly backup metrics • Last 30 days</p>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Backups</div>
                <div class="stat-value">{{ stats.total_backups }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Success Rate</div>
                <div class="stat-value success">{{ stats.success_rate }}<span class="stat-unit">%</span></div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Avg Duration</div>
                <div class="stat-value">{{ stats.avg_duration // 60 }}<span class="stat-unit">min</span></div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Avg Size</div>
                <div class="stat-value">{{ stats.avg_size_mb }}<span class="stat-unit">MB</span></div>
            </div>
        </div>

        <div class="chart-container">
            <div class="chart-title">Backup Duration Trend</div>
            <div class="canvas-wrapper">
                <canvas id="durationChart"></canvas>
            </div>
        </div>

        <div class="chart-container">
            <div class="chart-title">Backup Size Trend</div>
            <div class="canvas-wrapper">
                <canvas id="sizeChart"></canvas>
            </div>
        </div>

        <div class="chart-container">
            <div class="chart-title">Duration Breakdown (Last Backup)</div>
            <div class="canvas-wrapper">
                <canvas id="breakdownChart"></canvas>
            </div>
        </div>
    </div>

    <script>
        const chartColors = {
            primary: '#3b82f6',
            success: '#10b981',
            warning: '#f59e0b',
            danger: '#ef4444',
            grid: '#334155',
            text: '#94a3b8'
        };

        const chartDefaults = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: chartColors.text }
                }
            },
            scales: {
                x: {
                    grid: { color: chartColors.grid },
                    ticks: { color: chartColors.text }
                },
                y: {
                    grid: { color: chartColors.grid },
                    ticks: { color: chartColors.text }
                }
            }
        };

        async function loadCharts() {
            const response = await fetch('/api/metrics');
            const data = await response.json();

            // Duration chart
            new Chart(document.getElementById('durationChart'), {
                type: 'line',
                data: {
                    labels: data.map(d => new Date(d.timestamp).toLocaleDateString()),
                    datasets: [{
                        label: 'Total Duration (min)',
                        data: data.map(d => d.duration_total / 60),
                        borderColor: chartColors.primary,
                        backgroundColor: chartColors.primary + '20',
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: chartDefaults
            });

            // Size chart
            new Chart(document.getElementById('sizeChart'), {
                type: 'bar',
                data: {
                    labels: data.map(d => new Date(d.timestamp).toLocaleDateString()),
                    datasets: [{
                        label: 'Backup Size (MB)',
                        data: data.map(d => d.size_bytes / 1024 / 1024),
                        backgroundColor: chartColors.success
                    }]
                },
                options: chartDefaults
            });

            // Breakdown chart (last backup)
            if (data.length > 0) {
                const last = data[data.length - 1];
                new Chart(document.getElementById('breakdownChart'), {
                    type: 'doughnut',
                    data: {
                        labels: ['Snapshot', 'Archive', 'Volumes', 'Upload'],
                        datasets: [{
                            data: [
                                last.duration_snapshot,
                                last.duration_archive,
                                last.duration_volumes,
                                last.duration_upload
                            ],
                            backgroundColor: [
                                chartColors.primary,
                                chartColors.success,
                                chartColors.warning,
                                chartColors.danger
                            ]
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { labels: { color: chartColors.text } }
                        }
                    }
                });
            }
        }

        loadCharts();
    </script>
</body>
</html>
    '''
    return render_template_string(html, stats=stats)

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
