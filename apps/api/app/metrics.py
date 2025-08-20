"""
Ultra-Enterprise Observability Metrics for Task 4.10
Comprehensive metrics across licensing, billing, payments, notifications with Turkish compliance
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge, Info
from typing import Optional

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

# Financial operation buckets (optimized for payment processing)
_financial_latency_buckets = (
    0.1,    # Card tokenization
    0.5,    # Quick validation
    1.0,    # Standard processing
    2.0,    # Payment gateway call
    5.0,    # Webhook processing
    10.0,   # Batch operations
    30.0,   # Heavy reconciliation
    60.0    # Timeout scenarios
)

# ============================================================================
# EXISTING METRICS (Enhanced)
# ============================================================================

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

# ============================================================================
# TASK 4.10: LICENSING METRICS
# ============================================================================

# License state tracking
licenses_active_total = Gauge(
    name="licenses_active_total",
    documentation="Aktif lisans sayısı",
    labelnames=("license_type", "environment")
)

license_operations_total = Counter(
    name="license_operations_total",
    documentation="Lisans işlem sayacı",
    labelnames=("operation", "license_type", "status", "user_type")
)

license_expired_events_total = Counter(
    name="license_expired_events_total",
    documentation="Lisans süresi dolma olayları",
    labelnames=("license_type", "notification_sent", "sessions_revoked")
)

license_assignment_duration_seconds = Histogram(
    name="license_assignment_duration_seconds",
    documentation="Lisans atama işlem süresi",
    labelnames=("license_type", "status"),
    buckets=_latency_buckets
)

license_validation_duration_seconds = Histogram(
    name="license_validation_duration_seconds",
    documentation="Lisans doğrulama süresi",
    labelnames=("middleware", "cache_hit"),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

# ============================================================================
# TASK 4.10: BILLING & INVOICE METRICS
# ============================================================================

invoices_created_total = Counter(
    name="invoices_created_total", 
    documentation="Oluşturulan fatura sayısı",
    labelnames=("currency", "invoice_type", "user_type")
)

invoice_generation_duration_seconds = Histogram(
    name="invoice_generation_duration_seconds",
    documentation="Fatura oluşturma süresi",
    labelnames=("format", "complexity", "status"),
    buckets=_latency_buckets
)

invoice_pdf_generation_duration_seconds = Histogram(
    name="invoice_pdf_generation_duration_seconds", 
    documentation="PDF fatura üretim süresi",
    labelnames=("template", "page_count_range", "status"),
    buckets=(1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0)
)

invoice_amounts_cents = Histogram(
    name="invoice_amounts_cents",
    documentation="Fatura tutarları (kuruş)",
    labelnames=("currency", "invoice_type"),
    buckets=(1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000, 2500000)  # 10₺ to 25,000₺
)

# ============================================================================
# TASK 4.10: PAYMENT METRICS  
# ============================================================================

payments_total = Counter(
    name="payments_total",
    documentation="Toplam ödeme işlemleri",
    labelnames=("provider", "method", "status", "currency")
)

payments_succeeded_total = Counter(
    name="payments_succeeded_total",
    documentation="Başarılı ödeme sayısı",
    labelnames=("provider", "method", "currency", "amount_range")
)

payments_failed_total = Counter(
    name="payments_failed_total",
    documentation="Başarısız ödeme sayısı", 
    labelnames=("provider", "method", "failure_reason", "retry_eligible")
)

payment_processing_duration_seconds = Histogram(
    name="payment_processing_duration_seconds",
    documentation="Ödeme işlem süresi",
    labelnames=("provider", "method", "status"),
    buckets=_financial_latency_buckets
)

payment_webhook_processing_duration_seconds = Histogram(
    name="payment_webhook_processing_duration_seconds",
    documentation="Webhook işlem süresi", 
    labelnames=("provider", "event_type", "status"),
    buckets=_financial_latency_buckets
)

payment_amounts_cents = Histogram(
    name="payment_amounts_cents",
    documentation="Ödeme tutarları (kuruş)",
    labelnames=("provider", "currency", "method"),
    buckets=(1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000, 2500000)
)

payment_retries_total = Counter(
    name="payment_retries_total",
    documentation="Ödeme retry sayısı",
    labelnames=("provider", "failure_reason", "attempt_number")
)

# ============================================================================
# TASK 4.10: NOTIFICATION METRICS
# ============================================================================

notifications_sent_total = Counter(
    name="notifications_sent_total",
    documentation="Gönderilen bildirim sayısı",
    labelnames=("channel", "template", "priority", "status")
)

notifications_failed_total = Counter(
    name="notifications_failed_total", 
    documentation="Başarısız bildirim sayısı",
    labelnames=("channel", "failure_reason", "retry_eligible")
)

notification_delivery_duration_seconds = Histogram(
    name="notification_delivery_duration_seconds",
    documentation="Bildirim teslimat süresi",
    labelnames=("channel", "priority", "status"),
    buckets=_latency_buckets
)

notification_queue_size = Gauge(
    name="notification_queue_size",
    documentation="Bildirim kuyruğundaki mesaj sayısı",
    labelnames=("priority", "channel")
)

# ============================================================================
# TASK 4.10: AUDIT & SECURITY METRICS
# ============================================================================

audit_logs_created_total = Counter(
    name="audit_logs_created_total",
    documentation="Oluşturulan audit log sayısı",
    labelnames=("event_type", "scope_type", "actor_type", "classification")
)

audit_chain_verification_duration_seconds = Histogram(
    name="audit_chain_verification_duration_seconds",
    documentation="Audit zincir doğrulama süresi",
    labelnames=("verification_scope", "status"),
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

audit_chain_integrity_violations_total = Counter(
    name="audit_chain_integrity_violations_total",
    documentation="Audit zincir bütünlük ihlalleri",
    labelnames=("violation_type", "severity")
)

correlation_id_propagation_total = Counter(
    name="correlation_id_propagation_total",
    documentation="Correlation ID propagation sayısı",
    labelnames=("service", "direction", "success")
)

# ============================================================================
# TASK 4.10: BUSINESS KPI METRICS
# ============================================================================

active_user_sessions = Gauge(
    name="active_user_sessions",
    documentation="Aktif kullanıcı oturumları",
    labelnames=("license_type", "authentication_method")
)

financial_transaction_value_total = Counter(
    name="financial_transaction_value_total",
    documentation="Toplam finansal işlem değeri (kuruş)",
    labelnames=("transaction_type", "currency")
)

compliance_checks_total = Counter(
    name="compliance_checks_total",
    documentation="Uyumluluk kontrol sayısı",
    labelnames=("check_type", "regulation", "result")
)

system_health_status = Info(
    name="system_health_status",
    documentation="Sistem sağlık durumu"
)

# ============================================================================
# TASK 4.10: ERROR & PERFORMANCE TRACKING
# ============================================================================

request_correlation_success_rate = Gauge(
    name="request_correlation_success_rate",
    documentation="İstek korelasyon başarı oranı",
    labelnames=("service", "time_window")
)

trace_sampling_rate = Gauge(
    name="trace_sampling_rate",
    documentation="Trace örnekleme oranı",
    labelnames=("environment", "service")
)

pii_redaction_operations_total = Counter(
    name="pii_redaction_operations_total",
    documentation="KİŞİSEL VERİ maskeleme işlemleri",
    labelnames=("data_type", "masking_level", "regulation")
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


