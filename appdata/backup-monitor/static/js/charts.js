// Chart.js configuration and initialization

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

    // Throughput chart
    new Chart(document.getElementById('throughputChart'), {
        type: 'line',
        data: {
            labels: data.map(d => new Date(d.timestamp).toLocaleDateString()),
            datasets: [{
                label: 'Throughput (MB/s)',
                data: data.map(d => d.throughput_mb_per_sec),
                borderColor: chartColors.warning,
                backgroundColor: chartColors.warning + '20',
                tension: 0.3,
                fill: true
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

// Load charts when page loads
loadCharts();
