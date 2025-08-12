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
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 30 * 24 * 60

    dev_auth_bypass: bool = True

    database_url: str
    redis_url: str = "redis://redis:6379/0"

    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_s3_endpoint: str | None = None
    aws_s3_region: str | None = "us-east-1"
    s3_bucket_name: str = "artefacts"

    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "freecad-api"
    sentry_dsn: str | None = None

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

    # Branding / PDF / Public URL
    brand_name: str = "CNC AI Suite"
    brand_logo_path: str | None = None
    pdf_max_mb: int = 20
    public_web_base_url: str | None = None

    # Not: Pydantic v2'de hem model_config hem Config birlikte kullanılamaz.


settings = Settings()  # type: ignore[call-arg]


