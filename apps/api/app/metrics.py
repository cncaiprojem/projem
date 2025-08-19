from __future__ import annotations

from prometheus_client import Counter, Histogram

# Histogram buckets: seconds
_latency_buckets = (
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    900.0,
    1800.0,
)

job_latency_seconds = Histogram(
    name="job_latency_seconds",
    documentation="E2E iş süresi (started->finished)",
    labelnames=("type", "status"),
    buckets=_latency_buckets,
)

queue_wait_seconds = Histogram(
    name="queue_wait_seconds",
    documentation="Kuyruk bekleme süresi (created->started)",
    labelnames=("queue",),
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

failures_total = Counter(
    name="failures_total",
    documentation="Görev hata sayacı",
    labelnames=("task", "reason"),
)

# M18 metrikleri
cam3d_duration_seconds = Histogram(
    name="cam3d_duration_seconds",
    documentation="CAM 3D build süresi",
    labelnames=("status",),
    buckets=_latency_buckets,
)

simulate3d_duration_seconds = Histogram(
    name="simulate3d_duration_seconds",
    documentation="Simülasyon 3D süresi",
    labelnames=("status",),
    buckets=_latency_buckets,
)

m18_holder_collisions_total = Counter(
    name="m18_holder_collisions_total",
    documentation="Holder çarpışma ihlalleri",
    labelnames=("severity",),
)

retried_total = Counter(
    name="retried_total",
    documentation="Görev retry sayacı",
    labelnames=("task",),
)

# M17 metrikleri
report_build_duration_seconds = Histogram(
    name="report_build_duration_seconds",
    documentation="Atölye paketi PDF üretim süresi",
    labelnames=("status",),
    buckets=(0.5, 1, 2, 5, 10, 30, 60),
)

tool_scan_count_total = Counter(
    name="tool_scan_count_total",
    documentation="ToolBit tarama ile eklenen/tespit edilen kayıt sayısı",
)

cutting_import_rows_total = Counter(
    name="cutting_import_rows_total",
    documentation="Cutting Data import edilen satır sayısı",
)
