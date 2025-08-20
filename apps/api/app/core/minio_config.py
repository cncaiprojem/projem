"""
Ultra-Enterprise MinIO Client Configuration Module

Provides secure, resilient MinIO client configuration with:
- Environment-based configuration management
- Connection pooling with retries and exponential backoff
- TLS/SSL certificate validation
- Configurable timeouts for network operations
- Least-privilege service user enforcement
- Turkish localization for error messages

Task 5.1: MinIO client configuration and credentials management
Dependencies: Tasks 1-4 (Database infrastructure ready)
"""

from __future__ import annotations

import os
import ssl
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, TYPE_CHECKING, Final

import hashlib
import structlog
from contextlib import contextmanager
from minio import Minio
from minio.error import S3Error
from urllib3 import HTTPSConnectionPool, PoolManager
from urllib3.exceptions import MaxRetryError, TimeoutError, HTTPError
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from urllib3.response import HTTPResponse

logger = structlog.get_logger(__name__)

# Constants for improved maintainability
DEFAULT_CONNECT_TIMEOUT: Final[int] = 10
DEFAULT_READ_TIMEOUT: Final[int] = 60
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_RETRY_BACKOFF: Final[Decimal] = Decimal("0.5")
DEFAULT_POOL_SIZE: Final[int] = 10
CONNECTION_CHECK_INTERVAL: Final[float] = 60.0
MAX_OBJECT_KEY_LENGTH: Final[int] = 1024
MIN_PASSWORD_LENGTH: Final[int] = 8


@dataclass
class MinIOConfig:
    """
    MinIO client configuration with enterprise-grade settings.
    
    Attributes:
        endpoint: MinIO server endpoint (host:port format)
        access_key: MinIO access key (service user, never root)
        secret_key: MinIO secret key (service user credentials)
        secure: Whether to use HTTPS/TLS (default: True for production)
        region: S3 region (optional, default: us-east-1)
        cert_check: Whether to verify SSL certificates
        ca_bundle: Path to custom CA bundle for certificate validation
        connect_timeout: Connection timeout in seconds
        read_timeout: Read operation timeout in seconds
        max_retries: Maximum number of retry attempts
        retry_backoff_factor: Exponential backoff multiplier
        pool_connections: Maximum connection pool size
        pool_maxsize: Maximum pool size per host
    """
    
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool = True
    region: Optional[str] = None
    cert_check: bool = True
    ca_bundle: Optional[str] = None
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    read_timeout: int = DEFAULT_READ_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_factor: Decimal = DEFAULT_RETRY_BACKOFF
    pool_connections: int = DEFAULT_POOL_SIZE
    pool_maxsize: int = DEFAULT_POOL_SIZE
    
    # Bucket names for different purposes
    bucket_artefacts: str = "artefacts"
    bucket_logs: str = "logs"
    bucket_reports: str = "reports"
    bucket_invoices: str = "invoices"
    bucket_temp: str = "temp"
    
    @classmethod
    def from_environment(cls) -> MinIOConfig:
        """
        Create configuration from environment variables.
        
        Returns:
            MinIOConfig: Configuration instance
            
        Raises:
            ValueError: If required environment variables are missing
        """
        # Required environment variables
        endpoint = os.getenv("MINIO_ENDPOINT")
        access_key = os.getenv("MINIO_ACCESS_KEY")
        secret_key = os.getenv("MINIO_SECRET_KEY")
        
        # Validate required variables with enhanced error messages
        missing_vars = []
        if not endpoint:
            missing_vars.append("MINIO_ENDPOINT")
        if not access_key:
            missing_vars.append("MINIO_ACCESS_KEY")
        if not secret_key:
            missing_vars.append("MINIO_SECRET_KEY")
        
        if missing_vars:
            raise ValueError(
                f"Eksik ortam değişkenleri: {', '.join(missing_vars)}. "
                f"MinIO yapılandırması için gerekli değişkenler tanımlanmalıdır. "
                f"Lütfen .env dosyanızı kontrol edin."
            )
        
        # Validate endpoint format
        if not cls._validate_endpoint_format(endpoint):
            raise ValueError(
                f"Geçersiz MINIO_ENDPOINT formatı: {endpoint}. "
                f"Format: host:port (örn: minio:9000 veya s3.amazonaws.com)"
            )
        
        # Enhanced security validation
        env_type = os.getenv("ENV", "development")
        cls._validate_credentials_security(
            access_key=access_key,
            secret_key=secret_key,
            env_type=env_type
        )
        
        # Optional environment variables with defaults
        secure = os.getenv("MINIO_SECURE", "true").lower() == "true"
        region = os.getenv("MINIO_REGION", "us-east-1")
        cert_check = os.getenv("MINIO_CERT_CHECK", "true").lower() == "true"
        ca_bundle = os.getenv("MINIO_CA_BUNDLE")
        
        # Timeout configurations with validation
        try:
            connect_timeout = int(os.getenv("MINIO_CONNECT_TIMEOUT", str(DEFAULT_CONNECT_TIMEOUT)))
            read_timeout = int(os.getenv("MINIO_READ_TIMEOUT", str(DEFAULT_READ_TIMEOUT)))
            
            # Validate timeout ranges
            if connect_timeout < 1 or connect_timeout > 300:
                logger.warning(
                    "Connect timeout out of range, using default",
                    provided=connect_timeout,
                    default=DEFAULT_CONNECT_TIMEOUT
                )
                connect_timeout = DEFAULT_CONNECT_TIMEOUT
            
            if read_timeout < 1 or read_timeout > 3600:
                logger.warning(
                    "Read timeout out of range, using default",
                    provided=read_timeout,
                    default=DEFAULT_READ_TIMEOUT
                )
                read_timeout = DEFAULT_READ_TIMEOUT
                
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid timeout configuration, using defaults",
                error=str(e)
            )
            connect_timeout = DEFAULT_CONNECT_TIMEOUT
            read_timeout = DEFAULT_READ_TIMEOUT
        
        # Retry configurations with validation
        try:
            max_retries = int(os.getenv("MINIO_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
            if max_retries < 0 or max_retries > 10:
                logger.warning(
                    "Max retries out of range, using default",
                    provided=max_retries,
                    default=DEFAULT_MAX_RETRIES
                )
                max_retries = DEFAULT_MAX_RETRIES
                
            retry_backoff = Decimal(os.getenv("MINIO_RETRY_BACKOFF", str(DEFAULT_RETRY_BACKOFF)))
            if retry_backoff < Decimal("0.1") or retry_backoff > Decimal("5.0"):
                logger.warning(
                    "Retry backoff out of range, using default",
                    provided=retry_backoff,
                    default=DEFAULT_RETRY_BACKOFF
                )
                retry_backoff = DEFAULT_RETRY_BACKOFF
                
        except (ValueError, TypeError, InvalidOperation) as e:
            logger.warning(
                "Invalid retry configuration, using defaults",
                error=str(e)
            )
            max_retries = DEFAULT_MAX_RETRIES
            retry_backoff = DEFAULT_RETRY_BACKOFF
        
        # Connection pool configurations with validation
        try:
            pool_connections = int(os.getenv("MINIO_POOL_CONNECTIONS", str(DEFAULT_POOL_SIZE)))
            pool_maxsize = int(os.getenv("MINIO_POOL_MAXSIZE", str(DEFAULT_POOL_SIZE)))
            
            # Validate pool sizes
            if pool_connections < 1 or pool_connections > 100:
                logger.warning(
                    "Pool connections out of range, using default",
                    provided=pool_connections,
                    default=DEFAULT_POOL_SIZE
                )
                pool_connections = DEFAULT_POOL_SIZE
                
            if pool_maxsize < pool_connections:
                logger.warning(
                    "Pool maxsize less than connections, adjusting",
                    connections=pool_connections,
                    maxsize=pool_maxsize
                )
                pool_maxsize = pool_connections
                
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid pool configuration, using defaults",
                error=str(e)
            )
            pool_connections = DEFAULT_POOL_SIZE
            pool_maxsize = DEFAULT_POOL_SIZE
        
        # Bucket names
        bucket_artefacts = os.getenv("MINIO_BUCKET_ARTEFACTS", "artefacts")
        bucket_logs = os.getenv("MINIO_BUCKET_LOGS", "logs")
        bucket_reports = os.getenv("MINIO_BUCKET_REPORTS", "reports")
        bucket_invoices = os.getenv("MINIO_BUCKET_INVOICES", "invoices")
        bucket_temp = os.getenv("MINIO_BUCKET_TEMP", "temp")
        
        logger.info(
            "MinIO configuration loaded from environment",
            endpoint=endpoint,
            secure=secure,
            region=region,
            cert_check=cert_check,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            max_retries=max_retries,
            env_type=env_type
        )
        
        return cls(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
            cert_check=cert_check,
            ca_bundle=ca_bundle,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            max_retries=max_retries,
            retry_backoff_factor=retry_backoff,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            bucket_artefacts=bucket_artefacts,
            bucket_logs=bucket_logs,
            bucket_reports=bucket_reports,
            bucket_invoices=bucket_invoices,
            bucket_temp=bucket_temp
        )
    
    @classmethod
    def _validate_endpoint_format(cls, endpoint: str) -> bool:
        """Validate endpoint format."""
        if not endpoint or ":" not in endpoint:
            return False
        
        parts = endpoint.split(":")
        if len(parts) != 2:
            return False
            
        host, port = parts
        if not host:
            return False
            
        # Check if port is numeric (unless it's a domain like s3.amazonaws.com)
        if port and not port.isdigit() and "." not in host:
            return False
            
        return True
    
    @classmethod
    def _validate_credentials_security(
        cls,
        access_key: str,
        secret_key: str,
        env_type: str
    ) -> None:
        """Validate credentials meet security requirements."""
        # Check for weak/default credentials
        weak_credentials = [
            "minioadmin", "admin", "root", "password",
            "123456", "test", "demo", "default"
        ]
        
        if env_type not in ["development", "local", "test"]:
            # Production environment checks
            if access_key.lower() in weak_credentials:
                raise ValueError(
                    f"Güvenlik İhlali: {env_type} ortamında zayıf erişim anahtarı '{access_key}' kullanılamaz. "
                    f"Lütfen güçlü, rastgele oluşturulmuş kimlik bilgileri kullanın."
                )
            
            if len(secret_key) < MIN_PASSWORD_LENGTH:
                raise ValueError(
                    f"Güvenlik İhlali: {env_type} ortamında gizli anahtar en az {MIN_PASSWORD_LENGTH} karakter olmalıdır. "
                    f"Mevcut uzunluk: {len(secret_key)}"
                )
            
            # Check for complexity
            if secret_key.lower() == secret_key or secret_key.upper() == secret_key:
                logger.warning(
                    "Gizli anahtar karmaşıklığı düşük",
                    env_type=env_type,
                    recommendation="Büyük/küçük harf, rakam ve özel karakterler kullanın"
                )
        
        # Log security audit
        logger.info(
            "Kimlik bilgileri güvenlik kontrolü tamamlandı",
            env_type=env_type,
            access_key_length=len(access_key),
            secret_key_length=len(secret_key),
            access_key_hash=hashlib.sha256(access_key.encode()).hexdigest()[:8]
        )


class ResilientHTTPClient:
    """
    HTTP client with retry logic and exponential backoff for MinIO operations.
    
    Features:
    - Automatic retry with exponential backoff
    - Connection pooling for performance
    - TLS/SSL support with certificate validation
    - Graceful error handling
    """
    
    def __init__(self, config: MinIOConfig):
        """
        Initialize resilient HTTP client.
        
        Args:
            config: MinIO configuration
            
        Raises:
            ValueError: If configuration is invalid
        """
        if not config:
            raise ValueError("MinIO configuration is required")
            
        self.config = config
        self.pool_manager: Optional[PoolManager] = None
        self._setup_retry_strategy()
        self._setup_connection_pool()
    
    def _setup_retry_strategy(self) -> None:
        """Configure retry strategy with exponential backoff."""
        self.retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=float(self.config.retry_backoff_factor),
            status_forcelist=[408, 429, 500, 502, 503, 504, 507],  # Added 507 Insufficient Storage
            allowed_methods=["HEAD", "GET", "PUT", "POST", "DELETE", "OPTIONS"],
            raise_on_status=False,
            respect_retry_after_header=True,  # Honor Retry-After headers
            remove_headers_on_redirect=["Authorization"]  # Security: Remove auth on redirect
        )
    
    def _setup_connection_pool(self) -> None:
        """Configure connection pool with TLS/SSL settings."""
        try:
            # SSL context configuration
            ssl_context = None
            if self.config.secure:
                ssl_context = ssl.create_default_context()
                
                # Configure SSL/TLS version (use TLS 1.2 minimum)
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                
                if self.config.ca_bundle:
                    if not os.path.exists(self.config.ca_bundle):
                        logger.warning(
                            "CA bundle file not found, using system defaults",
                            ca_bundle=self.config.ca_bundle
                        )
                    else:
                        ssl_context.load_verify_locations(self.config.ca_bundle)
                
                if not self.config.cert_check:
                    logger.warning(
                        "SSL certificate verification disabled - security risk!",
                        endpoint=self.config.endpoint
                    )
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
            
            # Create pool manager with retry strategy
            self.pool_manager = PoolManager(
                num_pools=self.config.pool_connections,
                maxsize=self.config.pool_maxsize,
                retries=self.retry_strategy,
                timeout=self.config.connect_timeout,
                ssl_context=ssl_context if self.config.secure else None,
                block=False  # Non-blocking pool
            )
            
            logger.info(
                "HTTP connection pool configured",
                secure=self.config.secure,
                cert_check=self.config.cert_check,
                pool_size=self.config.pool_maxsize
            )
            
        except Exception as e:
            logger.error(
                "Failed to setup connection pool",
                error=str(e),
                exc_info=True
            )
            raise
    
    def cleanup(self) -> None:
        """Clean up connection pool resources."""
        if self.pool_manager:
            try:
                self.pool_manager.clear()
                logger.info("HTTP connection pool cleaned up")
            except Exception as e:
                logger.warning(
                    "Error cleaning up connection pool",
                    error=str(e)
                )


class MinIOClientFactory:
    """
    Factory for creating configured MinIO client instances.
    """
    
    _instance: Optional[Minio] = None
    _config: Optional[MinIOConfig] = None
    _last_connection_check: float = 0
    _connection_check_interval: float = CONNECTION_CHECK_INTERVAL
    _cleanup_registered: bool = False
    
    @classmethod
    def get_client(cls, force_new: bool = False) -> Minio:
        """
        Get or create MinIO client instance with connection pooling.
        
        Args:
            force_new: Force creation of new client instance
            
        Returns:
            Minio: Configured MinIO client
            
        Raises:
            ConnectionError: If connection to MinIO fails after retries
        """
        current_time = time.time()
        
        # Check if we need to recreate the client
        should_recreate = (
            force_new or
            cls._instance is None or
            cls._config is None or
            (current_time - cls._last_connection_check) > cls._connection_check_interval
        )
        
        if should_recreate:
            cls._create_client()
            cls._verify_connection()
            cls._last_connection_check = current_time
            
            # Register cleanup handler if not already done
            if not cls._cleanup_registered:
                import atexit
                atexit.register(cls._cleanup)
                cls._cleanup_registered = True
        
        return cls._instance
    
    @classmethod
    def _create_client(cls) -> None:
        """Create new MinIO client instance."""
        cls._config = MinIOConfig.from_environment()
        
        # Create HTTP client with custom settings
        http_client = ResilientHTTPClient(cls._config)
        
        try:
            cls._instance = Minio(
                endpoint=cls._config.endpoint,
                access_key=cls._config.access_key,
                secret_key=cls._config.secret_key,
                secure=cls._config.secure,
                region=cls._config.region,
                http_client=http_client.pool_manager
            )
            
            logger.info(
                "MinIO client created successfully",
                endpoint=cls._config.endpoint,
                secure=cls._config.secure,
                region=cls._config.region
            )
            
        except Exception as e:
            logger.error(
                "Failed to create MinIO client",
                endpoint=cls._config.endpoint,
                error=str(e),
                exc_info=True
            )
            raise ConnectionError(
                f"MinIO bağlantısı kurulamadı: {str(e)}"
            )
    
    @classmethod
    def _verify_connection(cls) -> None:
        """
        Verify connection to MinIO server.
        
        Raises:
            ConnectionError: If connection verification fails
        """
        if not cls._instance:
            raise ConnectionError("MinIO client henüz oluşturulmamış")
        
        max_attempts = cls._config.max_retries if cls._config else 3
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                # Try to list buckets as a connection test
                _ = cls._instance.list_buckets()
                
                logger.info(
                    "MinIO connection verified successfully",
                    attempt=attempt,
                    endpoint=cls._config.endpoint if cls._config else "unknown"
                )
                return
                
            except S3Error as e:
                last_error = e
                if e.code == "AccessDenied":
                    # Access denied means connection works but credentials are wrong
                    logger.error(
                        "MinIO access denied",
                        error_code=e.code,
                        error_message=e.message,
                        endpoint=cls._config.endpoint if cls._config else "unknown"
                    )
                    raise ConnectionError(
                        f"MinIO erişim reddedildi: Kimlik bilgileri hatalı veya yetkisiz. "
                        f"Kod: {e.code}, Mesaj: {e.message}"
                    )
                
                logger.warning(
                    "MinIO connection attempt failed",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error_code=e.code,
                    error_message=e.message
                )
                
            except (MaxRetryError, TimeoutError, HTTPError) as e:
                last_error = e
                logger.warning(
                    "MinIO connection timeout",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(e)
                )
                
            except Exception as e:
                last_error = e
                logger.warning(
                    "Unexpected error during MinIO connection",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(e),
                    exc_info=True
                )
            
            # Exponential backoff before retry with jitter
            if attempt < max_attempts:
                base_wait = float(cls._config.retry_backoff_factor) * (2 ** (attempt - 1))
                # Add jitter to prevent thundering herd
                import random
                jitter = random.uniform(0, base_wait * 0.1)
                wait_time = min(base_wait + jitter, 30.0)  # Cap at 30 seconds
                
                logger.info(
                    "Retrying MinIO connection",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    wait_time=wait_time
                )
                time.sleep(wait_time)
        
        # All attempts failed
        error_msg = (
            f"MinIO bağlantısı {max_attempts} deneme sonrasında başarısız oldu. "
            f"Son hata: {str(last_error)}"
        )
        logger.error(
            "MinIO connection failed after all retries",
            max_attempts=max_attempts,
            last_error=str(last_error),
            endpoint=cls._config.endpoint if cls._config else "unknown"
        )
        raise ConnectionError(error_msg)
    
    @classmethod
    def get_config(cls) -> MinIOConfig:
        """
        Get current MinIO configuration.
        
        Returns:
            MinIOConfig: Current configuration
        """
        if cls._config is None:
            cls._config = MinIOConfig.from_environment()
        return cls._config
    
    @classmethod
    def reset(cls) -> None:
        """Reset client instance and configuration."""
        cls._cleanup()
        cls._instance = None
        cls._config = None
        cls._last_connection_check = 0
        logger.info("MinIO client factory reset")
    
    @classmethod
    def _cleanup(cls) -> None:
        """Clean up resources."""
        if cls._instance:
            try:
                # Clean up HTTP client if it has our custom client
                if hasattr(cls._instance, "_http") and hasattr(cls._instance._http, "cleanup"):
                    cls._instance._http.cleanup()
                logger.info("MinIO client resources cleaned up")
            except Exception as e:
                logger.warning(
                    "Error during MinIO client cleanup",
                    error=str(e)
                )


@contextmanager
def get_minio_client_context():
    """
    Context manager for MinIO client with automatic cleanup.
    
    Yields:
        Minio: Configured MinIO client
        
    Example:
        with get_minio_client_context() as client:
            client.list_buckets()
    """
    client = MinIOClientFactory.get_client()
    try:
        yield client
    finally:
        # Cleanup is handled by factory
        pass

def get_minio_client() -> Minio:
    """
    Get configured MinIO client instance for dependency injection.
    
    Returns:
        Minio: Configured MinIO client
        
    Raises:
        ConnectionError: If connection to MinIO fails
    """
    return MinIOClientFactory.get_client()


def get_minio_config() -> MinIOConfig:
    """
    Get MinIO configuration for dependency injection.
    
    Returns:
        MinIOConfig: Current MinIO configuration
    """
    return MinIOClientFactory.get_config()


# Export error codes for consistent error handling
class StorageErrorCode:
    """Storage service error codes for consistent error handling."""
    
    STORAGE_UNAVAILABLE: Final[str] = "STORAGE_UNAVAILABLE"
    STORAGE_TLS_ERROR: Final[str] = "STORAGE_TLS_ERROR"
    STORAGE_AUTH_ERROR: Final[str] = "STORAGE_AUTH_ERROR"
    STORAGE_TIMEOUT: Final[str] = "STORAGE_TIMEOUT"
    STORAGE_NOT_FOUND: Final[str] = "STORAGE_NOT_FOUND"
    STORAGE_PERMISSION_DENIED: Final[str] = "STORAGE_PERMISSION_DENIED"
    STORAGE_QUOTA_EXCEEDED: Final[str] = "STORAGE_QUOTA_EXCEEDED"
    STORAGE_INVALID_KEY: Final[str] = "STORAGE_INVALID_KEY"
    STORAGE_OPERATION_FAILED: Final[str] = "STORAGE_OPERATION_FAILED"
    STORAGE_INVALID_CONTENT: Final[str] = "STORAGE_INVALID_CONTENT"
    STORAGE_CHECKSUM_MISMATCH: Final[str] = "STORAGE_CHECKSUM_MISMATCH"
    STORAGE_VERSION_CONFLICT: Final[str] = "STORAGE_VERSION_CONFLICT"
    STORAGE_RATE_LIMITED: Final[str] = "STORAGE_RATE_LIMITED"


__all__ = [
    "MinIOConfig",
    "MinIOClientFactory",
    "ResilientHTTPClient",
    "get_minio_client",
    "get_minio_client_context",
    "get_minio_config",
    "StorageErrorCode",
]