"""
Comprehensive tests for MinIO configuration module.

Tests cover:
- Environment variable validation
- Connection pooling and retry logic
- Thread safety
- Resource cleanup
- Error handling
"""

import os
import pytest
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from app.core.minio_config import (
    MinIOConfig,
    MinIOClientFactory,
    ResilientHTTPClient,
    StorageErrorCode,
    validate_object_key,
)


class TestMinIOConfig:
    """Test MinIO configuration handling."""
    
    def test_from_environment_success(self, monkeypatch):
        """Test successful configuration from environment."""
        monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
        monkeypatch.setenv("MINIO_ACCESS_KEY", "test_access_key")
        monkeypatch.setenv("MINIO_SECRET_KEY", "test_secret_key_123")
        monkeypatch.setenv("ENV", "development")
        
        config = MinIOConfig.from_environment()
        
        assert config.endpoint == "minio:9000"
        assert config.access_key == "test_access_key"
        assert config.secret_key == "test_secret_key_123"
        assert config.secure is True  # Default
    
    def test_from_environment_missing_required(self, monkeypatch):
        """Test error when required environment variables are missing."""
        monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
        
        with pytest.raises(ValueError) as exc_info:
            MinIOConfig.from_environment()
        
        assert "Eksik ortam değişkenleri" in str(exc_info.value)
    
    def test_validate_endpoint_format(self):
        """Test endpoint format validation."""
        # Valid formats
        assert MinIOConfig._validate_endpoint_format("minio:9000")
        assert MinIOConfig._validate_endpoint_format("s3.amazonaws.com:443")
        assert MinIOConfig._validate_endpoint_format("localhost:9000")
        
        # Invalid formats
        assert not MinIOConfig._validate_endpoint_format("")
        assert not MinIOConfig._validate_endpoint_format("minio")
        assert not MinIOConfig._validate_endpoint_format("minio:")
        assert not MinIOConfig._validate_endpoint_format(":9000")
    
    def test_validate_credentials_security_production(self, monkeypatch):
        """Test credential security validation in production."""
        monkeypatch.setenv("ENV", "production")
        
        # Weak credentials should fail in production
        with pytest.raises(ValueError) as exc_info:
            MinIOConfig._validate_credentials_security(
                access_key="admin",
                secret_key="password",
                env_type="production"
            )
        
        assert "Güvenlik İhlali" in str(exc_info.value)
    
    def test_validate_credentials_security_development(self, monkeypatch):
        """Test credential security validation in development."""
        monkeypatch.setenv("ENV", "development")
        
        # Weak credentials allowed in development
        MinIOConfig._validate_credentials_security(
            access_key="admin",
            secret_key="password",
            env_type="development"
        )  # Should not raise
    
    def test_timeout_validation(self, monkeypatch):
        """Test timeout parameter validation."""
        monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
        monkeypatch.setenv("MINIO_ACCESS_KEY", "test_key")
        monkeypatch.setenv("MINIO_SECRET_KEY", "test_secret_123")
        monkeypatch.setenv("MINIO_CONNECT_TIMEOUT", "999")  # Out of range
        monkeypatch.setenv("MINIO_READ_TIMEOUT", "-1")  # Invalid
        monkeypatch.setenv("ENV", "development")
        
        config = MinIOConfig.from_environment()
        
        # Should use defaults for invalid values
        assert config.connect_timeout == 10  # DEFAULT_CONNECT_TIMEOUT
        assert config.read_timeout == 60  # DEFAULT_READ_TIMEOUT


class TestResilientHTTPClient:
    """Test resilient HTTP client."""
    
    def test_initialization(self):
        """Test HTTP client initialization."""
        config = Mock(spec=MinIOConfig)
        config.max_retries = 3
        config.retry_backoff_factor = Decimal("0.5")
        config.secure = True
        config.cert_check = True
        config.ca_bundle = None
        config.pool_connections = 10
        config.pool_maxsize = 10
        config.connect_timeout = 10
        
        client = ResilientHTTPClient(config)
        
        assert client.config == config
        assert client.pool_manager is not None
        assert client._closed is False
    
    def test_cleanup(self):
        """Test resource cleanup."""
        config = Mock(spec=MinIOConfig)
        config.max_retries = 3
        config.retry_backoff_factor = Decimal("0.5")
        config.secure = False
        config.pool_connections = 10
        config.pool_maxsize = 10
        config.connect_timeout = 10
        
        client = ResilientHTTPClient(config)
        mock_pool = Mock()
        client.pool_manager = mock_pool
        
        client.cleanup()
        
        mock_pool.clear.assert_called_once()
        assert client._closed is True
    
    def test_thread_safety(self):
        """Test thread-safe cleanup."""
        config = Mock(spec=MinIOConfig)
        config.max_retries = 3
        config.retry_backoff_factor = Decimal("0.5")
        config.secure = False
        config.pool_connections = 10
        config.pool_maxsize = 10
        config.connect_timeout = 10
        
        client = ResilientHTTPClient(config)
        cleanup_count = 0
        
        def cleanup_thread():
            nonlocal cleanup_count
            client.cleanup()
            cleanup_count += 1
        
        threads = [threading.Thread(target=cleanup_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Cleanup should only happen once due to lock
        assert client._closed is True


class TestMinIOClientFactory:
    """Test MinIO client factory."""
    
    @patch('app.core.minio_config.MinIOConfig.from_environment')
    @patch('app.core.minio_config.Minio')
    def test_get_client_singleton(self, mock_minio, mock_config):
        """Test singleton pattern for client creation."""
        mock_config.return_value = Mock(
            endpoint="minio:9000",
            access_key="test",
            secret_key="secret",
            secure=False,
            region=None,
            max_retries=3,
            retry_backoff_factor=Decimal("0.5")
        )
        
        # Reset factory state
        MinIOClientFactory.reset()
        
        # First call creates client
        client1 = MinIOClientFactory.get_client()
        
        # Second call returns same instance
        client2 = MinIOClientFactory.get_client()
        
        assert client1 is client2
        assert mock_minio.call_count == 1
    
    @patch('app.core.minio_config.MinIOConfig.from_environment')
    @patch('app.core.minio_config.Minio')
    def test_get_client_force_new(self, mock_minio, mock_config):
        """Test forcing new client creation."""
        mock_config.return_value = Mock(
            endpoint="minio:9000",
            access_key="test",
            secret_key="secret",
            secure=False,
            region=None,
            max_retries=3,
            retry_backoff_factor=Decimal("0.5")
        )
        
        MinIOClientFactory.reset()
        
        # First client
        client1 = MinIOClientFactory.get_client()
        
        # Force new client
        client2 = MinIOClientFactory.get_client(force_new=True)
        
        # Should create new instance
        assert mock_minio.call_count == 2
    
    def test_thread_safety_get_client(self):
        """Test thread-safe client retrieval."""
        with patch('app.core.minio_config.MinIOConfig.from_environment'):
            with patch('app.core.minio_config.Minio'):
                MinIOClientFactory.reset()
                
                clients = []
                
                def get_client_thread():
                    client = MinIOClientFactory.get_client()
                    clients.append(client)
                
                threads = [threading.Thread(target=get_client_thread) for _ in range(10)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                
                # All threads should get the same instance
                assert all(c is clients[0] for c in clients)


class TestValidateObjectKey:
    """Test object key validation function."""
    
    def test_valid_keys(self):
        """Test validation of valid object keys."""
        assert validate_object_key("file.txt") == "file.txt"
        assert validate_object_key("path/to/file.txt") == "path/to/file.txt"
        assert validate_object_key("2024/01/file.pdf") == "2024/01/file.pdf"
    
    def test_empty_key(self):
        """Test rejection of empty keys."""
        with pytest.raises(ValueError) as exc_info:
            validate_object_key("")
        
        assert "Nesne anahtarı boş olamaz" in str(exc_info.value)
    
    def test_path_traversal(self):
        """Test prevention of path traversal."""
        assert validate_object_key("../../../etc/passwd") == "etc/passwd"
        assert validate_object_key("path/../file.txt") == "path/file.txt"
    
    def test_invalid_characters(self):
        """Test rejection of invalid characters."""
        with pytest.raises(ValueError) as exc_info:
            validate_object_key("file<name>.txt")
        
        assert "geçersiz karakter" in str(exc_info.value)
    
    def test_control_characters(self):
        """Test rejection of control characters."""
        with pytest.raises(ValueError) as exc_info:
            validate_object_key("file\x00name.txt")
        
        assert "kontrol karakteri" in str(exc_info.value)
    
    def test_max_length(self):
        """Test maximum key length enforcement."""
        long_key = "a" * 1025  # Over default max
        
        with pytest.raises(ValueError) as exc_info:
            validate_object_key(long_key)
        
        assert "çok uzun" in str(exc_info.value)
    
    def test_sanitization(self):
        """Test key sanitization."""
        assert validate_object_key("  /path/to/file.txt  ") == "path/to/file.txt"
        assert validate_object_key("//path//to//file.txt") == "path/to/file.txt"


class TestStorageErrorCode:
    """Test storage error codes."""
    
    def test_error_codes_defined(self):
        """Test all error codes are defined."""
        expected_codes = [
            "STORAGE_UNAVAILABLE",
            "STORAGE_TLS_ERROR",
            "STORAGE_AUTH_ERROR",
            "STORAGE_TIMEOUT",
            "STORAGE_NOT_FOUND",
            "STORAGE_PERMISSION_DENIED",
            "STORAGE_QUOTA_EXCEEDED",
            "STORAGE_INVALID_KEY",
            "STORAGE_OPERATION_FAILED",
            "STORAGE_INVALID_CONTENT",
            "STORAGE_CHECKSUM_MISMATCH",
            "STORAGE_VERSION_CONFLICT",
            "STORAGE_RATE_LIMITED",
        ]
        
        for code in expected_codes:
            assert hasattr(StorageErrorCode, code)
    
    def test_error_codes_immutable(self):
        """Test error codes are immutable."""
        with pytest.raises(AttributeError):
            StorageErrorCode.STORAGE_UNAVAILABLE = "CHANGED"


@pytest.fixture
def cleanup_factory():
    """Fixture to cleanup factory after tests."""
    yield
    MinIOClientFactory.reset()