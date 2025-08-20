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
from decimal import Decimal
from typing import Any, Dict, Optional, TYPE_CHECKING

import structlog
from minio import Minio
from minio.error import S3Error
from urllib3 import HTTPSConnectionPool, PoolManager
from urllib3.exceptions import MaxRetryError, TimeoutError
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from urllib3.response import HTTPResponse

logger = structlog.get_logger(__name__)


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
    connect_timeout: int = 10
    read_timeout: int = 60
    max_retries: int = 3
    retry_backoff_factor: Decimal = Decimal("0.5")
    pool_connections: int = 10
    pool_maxsize: int = 10
    
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
        
        # Validate required variables
        if not endpoint:
            raise ValueError(
                "MINIO_ENDPOINT ortam değişkeni tanımlanmamış. "
                "MinIO sunucu adresi gerekli. (ör: minio:9000)"
            )
        if not access_key:
            raise ValueError(
                "MINIO_ACCESS_KEY ortam değişkeni tanımlanmamış. "
                "MinIO erişim anahtarı gerekli."
            )
        if not secret_key:
            raise ValueError(
                "MINIO_SECRET_KEY ortam değişkeni tanımlanmamış. "
                "MinIO gizli anahtarı gerekli."
            )
        
        # Security check: Prevent root credentials in non-local environments
        env_type = os.getenv("ENV", "development")
        if env_type not in ["development", "local", "test"]:
            if access_key in ["minioadmin", "admin", "root"]:
                raise ValueError(
                    f"Güvenlik İhlali: {env_type} ortamında root kimlik bilgileri kullanılamaz. "
                    "Lütfen least-privilege service kullanıcısı oluşturun."
                )
        
        # Optional environment variables with defaults
        secure = os.getenv("MINIO_SECURE", "true").lower() == "true"
        region = os.getenv("MINIO_REGION", "us-east-1")
        cert_check = os.getenv("MINIO_CERT_CHECK", "true").lower() == "true"
        ca_bundle = os.getenv("MINIO_CA_BUNDLE")
        
        # Timeout configurations
        connect_timeout = int(os.getenv("MINIO_CONNECT_TIMEOUT", "10"))
        read_timeout = int(os.getenv("MINIO_READ_TIMEOUT", "60"))
        
        # Retry configurations
        max_retries = int(os.getenv("MINIO_MAX_RETRIES", "3"))
        retry_backoff = Decimal(os.getenv("MINIO_RETRY_BACKOFF", "0.5"))
        
        # Connection pool configurations
        pool_connections = int(os.getenv("MINIO_POOL_CONNECTIONS", "10"))
        pool_maxsize = int(os.getenv("MINIO_POOL_MAXSIZE", "10"))
        
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


class ResilientHTTPClient:
    """
    HTTP client with retry logic and exponential backoff for MinIO operations.
    """
    
    def __init__(self, config: MinIOConfig):
        """
        Initialize resilient HTTP client.
        
        Args:
            config: MinIO configuration
        """
        self.config = config
        self._setup_retry_strategy()
        self._setup_connection_pool()
    
    def _setup_retry_strategy(self) -> None:
        """Configure retry strategy with exponential backoff."""
        self.retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=float(self.config.retry_backoff_factor),
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "POST", "DELETE"],
            raise_on_status=False
        )
    
    def _setup_connection_pool(self) -> None:
        """Configure connection pool with TLS/SSL settings."""
        # SSL context configuration
        ssl_context = None
        if self.config.secure:
            ssl_context = ssl.create_default_context()
            
            if self.config.ca_bundle:
                ssl_context.load_verify_locations(self.config.ca_bundle)
            
            if not self.config.cert_check:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
        
        # Create pool manager with retry strategy
        self.pool_manager = PoolManager(
            num_pools=self.config.pool_connections,
            maxsize=self.config.pool_maxsize,
            retries=self.retry_strategy,
            timeout=self.config.connect_timeout,
            ssl_context=ssl_context if self.config.secure else None
        )


class MinIOClientFactory:
    """
    Factory for creating configured MinIO client instances.
    """
    
    _instance: Optional[Minio] = None
    _config: Optional[MinIOConfig] = None
    _last_connection_check: float = 0
    _connection_check_interval: float = 60.0  # Check connection every 60 seconds
    
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
                    raise ConnectionError(
                        f"MinIO erişim reddedildi: Kimlik bilgileri hatalı. "
                        f"Kod: {e.code}, Mesaj: {e.message}"
                    )
                
                logger.warning(
                    "MinIO connection attempt failed",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error_code=e.code,
                    error_message=e.message
                )
                
            except (MaxRetryError, TimeoutError) as e:
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
            
            # Exponential backoff before retry
            if attempt < max_attempts:
                wait_time = float(cls._config.retry_backoff_factor) * (2 ** (attempt - 1))
                logger.info(f"Retrying in {wait_time} seconds...")
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
        cls._instance = None
        cls._config = None
        cls._last_connection_check = 0
        logger.info("MinIO client factory reset")


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
    
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    STORAGE_TLS_ERROR = "STORAGE_TLS_ERROR"
    STORAGE_AUTH_ERROR = "STORAGE_AUTH_ERROR"
    STORAGE_TIMEOUT = "STORAGE_TIMEOUT"
    STORAGE_NOT_FOUND = "STORAGE_NOT_FOUND"
    STORAGE_PERMISSION_DENIED = "STORAGE_PERMISSION_DENIED"
    STORAGE_QUOTA_EXCEEDED = "STORAGE_QUOTA_EXCEEDED"
    STORAGE_INVALID_KEY = "STORAGE_INVALID_KEY"
    STORAGE_OPERATION_FAILED = "STORAGE_OPERATION_FAILED"


__all__ = [
    "MinIOConfig",
    "MinIOClientFactory",
    "get_minio_client",
    "get_minio_config",
    "StorageErrorCode",
]