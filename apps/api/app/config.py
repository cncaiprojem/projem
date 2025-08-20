from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # 'model_' prefixini korumalı isim olmaktan çıkarıyoruz; 'model_policy' alanı için uyarıyı bastırır
        protected_namespaces=(),
    )
    env: str = "development"
    secret_key: str
    
    # Task 3.3: Ultra Enterprise JWT Configuration
    jwt_secret_key: str | None = None  # Separate key for JWT signing
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30  # 30 minutes
    jwt_refresh_token_expire_days: int = 7  # 7 days
    jwt_issuer: str = "freecad-api"
    jwt_audience: str = "freecad-users"
    
    # Refresh token security configuration
    refresh_token_length: int = 64  # 512 bit entropy (64 bytes)
    refresh_token_cookie_name: str = "rt"
    refresh_token_cookie_domain: str | None = None  # Set in production
    refresh_token_cookie_secure: bool = True  # HTTPS only
    refresh_token_cookie_samesite: str = "strict"
    
    # Legacy settings (for backward compatibility during migration)
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 30 * 24 * 60

    dev_auth_bypass: bool = True

    database_url: str
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_url: str = "amqp://freecad:freecad@rabbitmq:5672/"

    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_s3_endpoint: str | None = None
    aws_s3_region: str | None = "us-east-1"
    s3_bucket_name: str = "artefacts"

    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "freecad-api"
    otel_trace_sampler: str = "always_on"  # always_on or ratio_based
    otel_trace_sampler_ratio: float = 1.0  # Sampling ratio for ratio_based sampler (0.0-1.0)
    otel_exporter_insecure: bool = True  # Use TLS if False (set to False in production)
    sentry_dsn: str | None = None
    
    # Logging configuration
    pii_redaction_enabled: bool = True  # Enable PII redaction in logs (default to true for security)

    freecadcmd_path: str | None = None
    freecad_timeout_seconds: int = 1200
    freecad_asm4_required: bool = True

    # Model yönetişimi
    model_policy: str = "quality_first"  # quality_first | cost_first
    default_model: str = "gpt-5"
    fallback_model: str = "o4-mini"
    allowed_models: str = "gpt-5,o4-mini"

    # LLM
    openai_api_key: str | None = None

    # Toolbits
    toolbits_root: str | None = None

    # Celery & Queue Configuration
    celery_task_always_eager: bool = False
    celery_task_eager_propagates: bool = True
    celery_worker_prefetch_multiplier: int = 1
    celery_task_acks_late: bool = True
    celery_task_reject_on_worker_lost: bool = True
    celery_broker_pool_limit: int = 10
    
    # Queue priorities (1-10, higher = more priority)
    queue_priority_urgent: int = 9
    queue_priority_high: int = 7
    queue_priority_normal: int = 5
    queue_priority_low: int = 3
    queue_priority_background: int = 1

    # Branding / PDF / Public URL
    brand_name: str = "CNC AI Suite"
    brand_logo_path: str | None = None
    pdf_max_mb: int = 20
    public_web_base_url: str | None = None

    # Not: Pydantic v2'de hem model_config hem Config birlikte kullanılamaz.


settings = Settings()  # type: ignore[call-arg]


