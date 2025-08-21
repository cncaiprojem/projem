"""
Unit tests for ClamAV service (Task 5.6)

Tests comprehensive ClamAV integration including:
- EICAR test string detection
- Daemon availability checks
- Streaming scan functionality
- Error handling and failure modes
- Rate limiting protection
- Security event logging
"""

import asyncio
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from io import BytesIO
from datetime import datetime, UTC

import clamd
from minio import Minio
from minio.error import S3Error
from sqlalchemy.orm import Session

from app.services.clamav_service import (
    ClamAVService,
    ClamAVError,
    ClamAVScanResult,
    get_clamav_service,
    EICAR_TEST_STRING,
    SCANNABLE_FILE_TYPES,
    SKIP_SCAN_EXTENSIONS,
)
from app.models.security_event import SecurityEvent, SecurityEventType, SeverityLevel


class TestClamAVService:
    """Test ClamAV service functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = Mock(spec=Session)
        self.mock_minio = Mock(spec=Minio)
        
        # Mock clamd client
        self.mock_clamd_client = Mock()
        self.mock_clamd_client.ping.return_value = "PONG"
        self.mock_clamd_client.version.return_value = "ClamAV 1.3.0"
        self.mock_clamd_client.timeout = 60.0
        
        # Create service with test configuration
        self.service = ClamAVService(
            host="test-clamd",
            port=3310,
            unix_socket=None,
            timeout_connect=5.0,
            timeout_scan=30.0,
            max_concurrent_scans=2,
            scan_enabled=True,
            db=self.mock_db,
            minio_client=self.mock_minio,
        )

    def test_clamav_service_initialization(self):
        """Test ClamAV service initialization with proper configuration."""
        assert self.service.host == "test-clamd"
        assert self.service.port == 3310
        assert self.service.timeout_connect == 5.0
        assert self.service.timeout_scan == 30.0
        assert self.service.scan_enabled is True
        assert self.service.rate_limiter is not None

    @patch('app.services.clamav_service.clamd.ClamdNetworkSocket')
    def test_ping_success(self, mock_clamd_network):
        """Test successful daemon ping."""
        mock_client = Mock()
        mock_client.ping.return_value = "PONG"
        mock_clamd_network.return_value = mock_client
        
        result = self.service.ping()
        
        assert result is True
        mock_clamd_network.assert_called_once_with(
            host="test-clamd",
            port=3310,
            timeout=5.0,
        )
        mock_client.ping.assert_called_once()

    @patch('app.services.clamav_service.clamd.ClamdNetworkSocket')
    def test_ping_failure(self, mock_clamd_network):
        """Test daemon ping failure."""
        mock_client = Mock()
        mock_client.ping.side_effect = clamd.ConnectionError("Connection refused")
        mock_clamd_network.return_value = mock_client
        
        result = self.service.ping()
        
        assert result is False

    @patch('app.services.clamav_service.clamd.ClamdUnixSocket')
    def test_unix_socket_connection(self, mock_clamd_unix):
        """Test Unix socket connection preference over TCP."""
        mock_client = Mock()
        mock_client.ping.return_value = "PONG"
        mock_clamd_unix.return_value = mock_client
        
        service = ClamAVService(
            host="test-clamd",
            port=3310,
            unix_socket="/var/run/clamd/clamd.sock",
            scan_enabled=True,
        )
        
        result = service.ping()
        
        assert result is True
        mock_clamd_unix.assert_called_once_with(
            path="/var/run/clamd/clamd.sock",
            timeout=10.0,  # Default timeout
        )

    @patch('app.services.clamav_service.clamd.ClamdNetworkSocket')
    def test_get_version(self, mock_clamd_network):
        """Test getting ClamAV daemon version."""
        mock_client = Mock()
        mock_client.version.return_value = "ClamAV 1.3.0/27014/Mon Aug 21 10:31:20 2025"
        mock_clamd_network.return_value = mock_client
        
        version = self.service.get_version()
        
        assert version == "ClamAV 1.3.0/27014/Mon Aug 21 10:31:20 2025"
        mock_client.version.assert_called_once()

    def test_should_scan_file_policies(self):
        """Test file scanning policy decisions."""
        # Test scannable file types
        assert self.service._should_scan_file("bucket/job/model.stl", "application/sla", "model") is True
        assert self.service._should_scan_file("bucket/job/archive.zip", "application/zip", "temp") is True
        
        # Test skip extensions (G-code files)
        assert self.service._should_scan_file("bucket/job/part.gcode", "text/plain", "temp") is False
        assert self.service._should_scan_file("bucket/job/program.nc", "text/plain", "temp") is False
        
        # Test non-scannable MIME types  
        assert self.service._should_scan_file("bucket/job/data.json", "application/json", "temp") is False
        
        # Test scanning disabled
        service_disabled = ClamAVService(scan_enabled=False)
        assert service_disabled._should_scan_file("bucket/job/model.stl", "application/sla", "model") is False

    @patch('app.services.clamav_service.clamd.ClamdNetworkSocket')
    def test_eicar_test_success(self, mock_clamd_network):
        """Test EICAR test string detection."""
        mock_client = Mock()
        mock_client.instream.return_value = {"stream": ("FOUND", "Eicar-Test-Signature")}
        mock_clamd_network.return_value = mock_client
        
        result = self.service.scan_eicar_test()
        
        assert isinstance(result, ClamAVScanResult)
        assert result.is_clean is False
        assert result.virus_name == "Eicar-Test-Signature"
        assert result.scan_time_ms > 0
        assert result.scan_metadata["test_type"] == "eicar"
        
        # Verify instream was called with EICAR test string
        args, kwargs = mock_client.instream.call_args
        buffer = args[0]
        assert buffer.read() == EICAR_TEST_STRING.encode()

    @patch('app.services.clamav_service.clamd.ClamdNetworkSocket')
    def test_eicar_test_failure_not_detected(self, mock_clamd_network):
        """Test EICAR test failure when virus is not detected."""
        mock_client = Mock()
        mock_client.instream.return_value = {"stream": ("OK", None)}
        mock_clamd_network.return_value = mock_client
        
        with pytest.raises(ClamAVError) as exc_info:
            self.service.scan_eicar_test()
        
        assert exc_info.value.code == "EICAR_NOT_DETECTED"
        assert "should be detected" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_scan_object_stream_clean_file(self):
        """Test scanning a clean file via streaming."""
        # Mock MinIO stat and get_object
        mock_stat = Mock()
        mock_stat.size = 1024
        self.mock_minio.stat_object.return_value = mock_stat
        
        mock_response = Mock()
        mock_response.stream.return_value = [b"clean file content"]
        mock_response.close = Mock()
        mock_response.release_conn = Mock()
        self.mock_minio.get_object.return_value = mock_response
        
        # Mock clamd client
        with patch.object(self.service, '_get_clamd_client') as mock_get_client:
            mock_client = Mock()
            mock_client.instream.return_value = {"stream": ("OK", None)}
            mock_client.timeout = 30.0
            mock_get_client.return_value = mock_client
            
            with patch.object(self.service, 'ping', return_value=True):
                result = await self.service.scan_object_stream(
                    bucket_name="test-bucket",
                    object_name="test-file.txt",
                    mime_type="text/plain",
                    file_type="temp",
                )
        
        assert isinstance(result, ClamAVScanResult)
        assert result.is_clean is True
        assert result.virus_name is None
        assert result.scan_time_ms > 0
        assert result.scan_metadata["scan_method"] == "instream"

    @pytest.mark.asyncio
    async def test_scan_object_stream_malware_detected(self):
        """Test scanning an infected file via streaming."""
        # Mock MinIO stat and get_object
        mock_stat = Mock()
        mock_stat.size = 1024
        self.mock_minio.stat_object.return_value = mock_stat
        
        mock_response = Mock()
        mock_response.stream.return_value = [EICAR_TEST_STRING.encode()]
        mock_response.close = Mock()
        mock_response.release_conn = Mock()
        self.mock_minio.get_object.return_value = mock_response
        
        # Mock clamd client to detect EICAR
        with patch.object(self.service, '_get_clamd_client') as mock_get_client:
            mock_client = Mock()
            mock_client.instream.return_value = {"stream": ("FOUND", "Eicar-Test-Signature")}
            mock_client.timeout = 30.0
            mock_get_client.return_value = mock_client
            
            with patch.object(self.service, 'ping', return_value=True):
                # Mock security event logging
                with patch.object(self.service, '_log_security_event') as mock_log_event:
                    result = await self.service.scan_object_stream(
                        bucket_name="test-bucket",
                        object_name="infected-file.exe",
                        mime_type="application/x-executable",
                        file_type="temp",
                    )
        
        assert isinstance(result, ClamAVScanResult)
        assert result.is_clean is False
        assert result.virus_name == "Eicar-Test-Signature"
        
        # Verify security event was logged
        mock_log_event.assert_called_once()
        call_args = mock_log_event.call_args
        assert call_args[1]["event_type"] == SecurityEventType.MALWARE_DETECTED
        assert call_args[1]["severity"] == SeverityLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_scan_object_stream_file_too_large(self):
        """Test handling of oversized files."""
        # Mock MinIO stat with large file
        mock_stat = Mock()
        mock_stat.size = 200 * 1024 * 1024  # 200MB
        self.mock_minio.stat_object.return_value = mock_stat
        
        with patch.object(self.service, 'ping', return_value=True):
            result = await self.service.scan_object_stream(
                bucket_name="test-bucket",
                object_name="large-file.zip",
                mime_type="application/zip",
                file_type="temp",
                max_size_bytes=100 * 1024 * 1024,  # 100MB limit
            )
        
        assert isinstance(result, ClamAVScanResult)
        assert result.is_clean is True  # Assume clean for oversized files
        assert result.scan_metadata["scan_skipped"] is True
        assert result.scan_metadata["reason"] == "oversized"

    @pytest.mark.asyncio
    async def test_scan_object_stream_object_not_found(self):
        """Test handling of missing objects."""
        # Mock MinIO stat to raise S3Error
        self.mock_minio.stat_object.side_effect = S3Error(
            "NoSuchKey", "The specified key does not exist.", "test-bucket", "missing-file.txt"
        )
        
        with patch.object(self.service, 'ping', return_value=True):
            with pytest.raises(ClamAVError) as exc_info:
                await self.service.scan_object_stream(
                    bucket_name="test-bucket",
                    object_name="missing-file.txt",
                    mime_type="text/plain",
                    file_type="temp",
                )
        
        assert exc_info.value.code == "OBJECT_NOT_FOUND"
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_scan_object_stream_daemon_unavailable_fail_closed(self):
        """Test fail-closed behavior when daemon is unavailable and scanning is required."""
        # Mock ping to return False (daemon unavailable)
        with patch.object(self.service, 'ping', return_value=False):
            with patch.object(self.service, '_log_security_event') as mock_log_event:
                with pytest.raises(ClamAVError) as exc_info:
                    await self.service.scan_object_stream(
                        bucket_name="test-bucket",
                        object_name="suspicious-file.exe",
                        mime_type="application/x-executable", 
                        file_type="temp",
                    )
        
        assert exc_info.value.code == "SCAN_UNAVAILABLE"
        assert exc_info.value.status_code == 503
        
        # Verify security event was logged
        mock_log_event.assert_called_once()
        call_args = mock_log_event.call_args
        assert call_args[1]["event_type"] == SecurityEventType.MALWARE_SCAN_FAILURE

    @pytest.mark.asyncio
    async def test_scan_object_stream_scan_timeout(self):
        """Test scan timeout handling."""
        # Mock MinIO stat and get_object
        mock_stat = Mock()
        mock_stat.size = 1024
        self.mock_minio.stat_object.return_value = mock_stat
        
        mock_response = Mock()
        mock_response.stream.return_value = [b"timeout test content"]
        mock_response.close = Mock()
        mock_response.release_conn = Mock()
        self.mock_minio.get_object.return_value = mock_response
        
        # Mock clamd client to timeout
        with patch.object(self.service, '_get_clamd_client') as mock_get_client:
            mock_client = Mock()
            mock_client.instream.side_effect = socket.timeout("Scan timeout")
            mock_client.timeout = 30.0
            mock_get_client.return_value = mock_client
            
            with patch.object(self.service, 'ping', return_value=True):
                with patch.object(self.service, '_log_security_event') as mock_log_event:
                    with pytest.raises(ClamAVError) as exc_info:
                        await self.service.scan_object_stream(
                            bucket_name="test-bucket",
                            object_name="timeout-file.zip",
                            mime_type="application/zip",
                            file_type="temp",
                        )
        
        assert exc_info.value.code == "SCAN_TIMEOUT"
        assert exc_info.value.status_code == 408
        
        # Verify security event was logged
        mock_log_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limiting_protection(self):
        """Test rate limiting prevents resource exhaustion."""
        # Create service with very low concurrency limit
        service = ClamAVService(
            max_concurrent_scans=1,
            scan_enabled=True,
            minio_client=self.mock_minio,
        )
        
        # Mock successful ping and scan
        with patch.object(service, 'ping', return_value=True):
            with patch.object(service, '_get_clamd_client') as mock_get_client:
                mock_client = Mock()
                mock_client.instream.return_value = {"stream": ("OK", None)}
                mock_client.timeout = 30.0
                mock_get_client.return_value = mock_client
                
                # Mock MinIO operations
                mock_stat = Mock()
                mock_stat.size = 1024
                service.minio_client.stat_object.return_value = mock_stat
                
                mock_response = Mock()
                mock_response.stream.return_value = [b"test content"]
                mock_response.close = Mock()
                mock_response.release_conn = Mock()
                service.minio_client.get_object.return_value = mock_response
                
                # Start concurrent scans
                async def scan_task(file_num):
                    return await service.scan_object_stream(
                        bucket_name="test-bucket",
                        object_name=f"file-{file_num}.txt",
                        mime_type="text/plain",
                        file_type="temp",
                    )
                
                # Run multiple concurrent scans - only 1 should run at a time
                tasks = [scan_task(i) for i in range(3)]
                results = await asyncio.gather(*tasks)
                
                # All should complete successfully due to rate limiting
                assert len(results) == 3
                for result in results:
                    assert result.is_clean is True

    def test_get_stats(self):
        """Test service statistics collection."""
        with patch.object(self.service, 'ping', return_value=True):
            with patch.object(self.service, 'get_version', return_value="ClamAV 1.3.0"):
                stats = self.service.get_stats()
        
        assert stats["scan_enabled"] is True
        assert stats["connection"]["host"] == "test-clamd"
        assert stats["connection"]["port"] == 3310
        assert stats["daemon"]["daemon_reachable"] is True
        assert stats["daemon"]["daemon_version"] == "ClamAV 1.3.0"
        assert "rate_limiter" in stats
        assert "scannable_types" in stats
        assert "skip_extensions" in stats

    def test_log_security_event(self):
        """Test security event logging."""
        # Test with database session
        with patch('app.services.clamav_service.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 8, 21, 12, 0, 0, tzinfo=UTC)
            
            self.service._log_security_event(
                event_type=SecurityEventType.MALWARE_DETECTED,
                description="Test malware detection",
                details={"virus_name": "Test-Virus"},
                severity=SeverityLevel.CRITICAL,
            )
        
        # Verify database event creation
        self.mock_db.add.assert_called_once()
        self.mock_db.commit.assert_called_once()
        
        # Get the security event that was added
        security_event = self.mock_db.add.call_args[0][0]
        assert isinstance(security_event, SecurityEvent)
        assert security_event.event_type == SecurityEventType.MALWARE_DETECTED
        assert security_event.description == "Test malware detection"
        assert security_event.severity == SeverityLevel.CRITICAL

    def test_log_security_event_no_db(self):
        """Test security event logging without database session."""
        service = ClamAVService(scan_enabled=True, db=None)
        
        # Should not raise exception even without DB
        service._log_security_event(
            event_type=SecurityEventType.MALWARE_DETECTED,
            description="Test without DB",
        )
        
        # No database operations should occur
        assert True  # Test passes if no exception raised


class TestClamAVServiceFactory:
    """Test ClamAV service factory function."""

    @patch('app.services.clamav_service.environment')
    def test_get_clamav_service_with_environment_defaults(self, mock_environment):
        """Test factory function uses environment configuration."""
        # Mock environment configuration
        mock_environment.CLAMAV_HOST = "env-clamd"
        mock_environment.CLAMAV_PORT = 3311
        mock_environment.CLAMAV_UNIX_SOCKET = "/env/socket"
        mock_environment.CLAMAV_TIMEOUT_CONNECT = 15.0
        mock_environment.CLAMAV_TIMEOUT_SCAN = 90.0
        mock_environment.CLAMAV_MAX_CONCURRENT_SCANS = 5
        mock_environment.CLAMAV_SCAN_ENABLED = False
        
        service = get_clamav_service()
        
        assert service.host == "env-clamd"
        assert service.port == 3311
        assert service.unix_socket == "/env/socket"
        assert service.timeout_connect == 15.0
        assert service.timeout_scan == 90.0
        assert service.rate_limiter._semaphore._value == 5  # max_concurrent_scans
        assert service.scan_enabled is False

    @patch('app.services.clamav_service.environment')
    def test_get_clamav_service_with_parameter_overrides(self, mock_environment):
        """Test factory function parameter overrides."""
        # Mock environment defaults
        mock_environment.CLAMAV_HOST = "env-clamd"
        mock_environment.CLAMAV_PORT = 3311
        mock_environment.CLAMAV_SCAN_ENABLED = False
        
        service = get_clamav_service(
            host="override-clamd",
            port=9999,
            scan_enabled=True,
        )
        
        # Overrides should take precedence
        assert service.host == "override-clamd"
        assert service.port == 9999
        assert service.scan_enabled is True


# Import socket for timeout exception
import socket