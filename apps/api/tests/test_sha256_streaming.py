"""
Comprehensive tests for Task 5.5: SHA256 Streaming Service

Tests:
- Memory-efficient streaming with 8MB chunks
- Timeout protection (60s read timeout)
- Hash mismatch detection and deletion
- Idempotent operations
- Audit logging
- Large file handling (100MB+)
"""

import hashlib
import io
import time
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, call
from urllib3.exceptions import ReadTimeoutError

import pytest
from minio.error import S3Error

from app.services.sha256_service import (
    SHA256StreamingService,
    SHA256StreamingError,
    CHUNK_SIZE,
    READ_TIMEOUT,
)


@pytest.fixture
def mock_minio_client():
    """Create mock MinIO client."""
    client = MagicMock()
    return client


@pytest.fixture
def sha256_service(mock_minio_client):
    """Create SHA256 streaming service with mock client."""
    return SHA256StreamingService(client=mock_minio_client)


class TestSHA256StreamingService:
    """Test SHA256 streaming service functionality."""
    
    def test_verify_object_hash_success(self, sha256_service, mock_minio_client):
        """Test successful hash verification with correct SHA256."""
        # Setup
        test_data = b"Hello, World!" * 1000  # ~13KB of data
        expected_sha256 = hashlib.sha256(test_data).hexdigest()
        
        # Mock stat_object
        mock_stat = MagicMock()
        mock_stat.size = len(test_data)
        mock_stat.etag = "test-etag"
        mock_stat.content_type = "text/plain"
        mock_stat.last_modified = datetime.now(timezone.utc)
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock get_object with streaming
        mock_response = MagicMock()
        mock_response.stream.return_value = [test_data[i:i+CHUNK_SIZE] for i in range(0, len(test_data), CHUNK_SIZE)]
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute
        is_valid, actual_sha256, metadata = sha256_service.verify_object_hash(
            bucket_name="test-bucket",
            object_name="test-object",
            expected_sha256=expected_sha256,
            expected_size=len(test_data),
        )
        
        # Assert
        assert is_valid is True
        assert actual_sha256 == expected_sha256
        assert metadata["actual_size"] == len(test_data)
        assert metadata["hash_match"] is True
        assert metadata["bytes_processed"] == len(test_data)
        assert metadata["chunks_processed"] == 1  # Small data fits in one chunk
        
        # Verify proper resource cleanup
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()
    
    def test_verify_object_hash_mismatch(self, sha256_service, mock_minio_client):
        """Test hash mismatch detection."""
        # Setup
        test_data = b"Hello, World!" * 1000
        wrong_sha256 = "0" * 64  # Incorrect hash
        correct_sha256 = hashlib.sha256(test_data).hexdigest()
        
        # Mock stat_object
        mock_stat = MagicMock()
        mock_stat.size = len(test_data)
        mock_stat.etag = "test-etag"
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock get_object
        mock_response = MagicMock()
        mock_response.stream.return_value = [test_data]
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute
        is_valid, actual_sha256, metadata = sha256_service.verify_object_hash(
            bucket_name="test-bucket",
            object_name="test-object",
            expected_sha256=wrong_sha256,
            expected_size=len(test_data),
        )
        
        # Assert
        assert is_valid is False
        assert actual_sha256 == correct_sha256
        assert metadata["hash_match"] is False
        
        # Verify audit event would be logged
        assert metadata["expected_sha256"] == wrong_sha256
        assert metadata["actual_sha256"] == correct_sha256
    
    def test_verify_large_file_streaming(self, sha256_service, mock_minio_client):
        """Test streaming of large file (100MB) with memory efficiency."""
        # Setup - simulate 100MB file
        chunk_data = b"X" * CHUNK_SIZE  # 8MB chunk
        num_chunks = 13  # ~104MB total
        test_chunks = [chunk_data] * (num_chunks - 1) + [b"Y" * (CHUNK_SIZE // 2)]  # Last chunk is smaller
        
        # Calculate expected hash
        hasher = hashlib.sha256()
        for chunk in test_chunks:
            hasher.update(chunk)
        expected_sha256 = hasher.hexdigest()
        
        total_size = sum(len(chunk) for chunk in test_chunks)
        
        # Mock stat_object
        mock_stat = MagicMock()
        mock_stat.size = total_size
        mock_stat.etag = "large-file-etag"
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock get_object with streaming
        mock_response = MagicMock()
        mock_response.stream.return_value = iter(test_chunks)
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute
        is_valid, actual_sha256, metadata = sha256_service.verify_object_hash(
            bucket_name="test-bucket",
            object_name="large-file.bin",
            expected_sha256=expected_sha256,
            expected_size=total_size,
        )
        
        # Assert
        assert is_valid is True
        assert actual_sha256 == expected_sha256
        assert metadata["bytes_processed"] == total_size
        assert metadata["chunks_processed"] == num_chunks
        assert metadata["chunk_size"] == CHUNK_SIZE
        
        # Verify streaming was called with correct chunk size
        mock_response.stream.assert_called_once_with(CHUNK_SIZE)
    
    def test_timeout_protection(self, sha256_service, mock_minio_client):
        """Test timeout protection against slowloris attacks."""
        # Setup
        mock_stat = MagicMock()
        mock_stat.size = 1000
        mock_minio_client.stat_object.return_value = mock_stat
        
        # Mock slow streaming that would timeout
        def slow_stream(chunk_size):
            time.sleep(READ_TIMEOUT + 1)  # Exceed timeout
            yield b"data"
        
        mock_response = MagicMock()
        mock_response.stream = slow_stream
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute and expect timeout error
        with pytest.raises(SHA256StreamingError) as exc_info:
            sha256_service.verify_object_hash(
                bucket_name="test-bucket",
                object_name="slow-object",
                expected_sha256="abc123",
            )
        
        # Assert
        assert exc_info.value.code == "TIMEOUT"
        assert "timed out" in exc_info.value.message
    
    def test_retry_on_network_error(self, sha256_service, mock_minio_client):
        """Test retry mechanism on transient network errors."""
        # Setup
        test_data = b"Test data"
        expected_sha256 = hashlib.sha256(test_data).hexdigest()
        
        mock_stat = MagicMock()
        mock_stat.size = len(test_data)
        mock_minio_client.stat_object.return_value = mock_stat
        
        # First call fails with network error, second succeeds
        mock_response_fail = MagicMock()
        mock_response_fail.stream.side_effect = ReadTimeoutError(None, None, "Read timeout")
        
        mock_response_success = MagicMock()
        mock_response_success.stream.return_value = [test_data]
        
        mock_minio_client.get_object.side_effect = [
            mock_response_fail,
            mock_response_success,
        ]
        
        # Execute
        is_valid, actual_sha256, metadata = sha256_service.verify_object_hash(
            bucket_name="test-bucket",
            object_name="test-object",
            expected_sha256=expected_sha256,
        )
        
        # Assert
        assert is_valid is True
        assert actual_sha256 == expected_sha256
        assert mock_minio_client.get_object.call_count == 2  # Retried once
    
    def test_object_not_found(self, sha256_service, mock_minio_client):
        """Test handling of non-existent object."""
        # Setup
        error = S3Error(
            code="NoSuchKey",
            message="The specified key does not exist",
            resource="test-object",
            request_id="test-request",
            host_id="test-host",
            response=None,
        )
        mock_minio_client.stat_object.side_effect = error
        
        # Execute and expect not found error
        with pytest.raises(SHA256StreamingError) as exc_info:
            sha256_service.verify_object_hash(
                bucket_name="test-bucket",
                object_name="missing-object",
                expected_sha256="abc123",
            )
        
        # Assert
        assert exc_info.value.code == "NOT_FOUND"
        assert "not found" in exc_info.value.message.lower()
    
    def test_incomplete_read_detection(self, sha256_service, mock_minio_client):
        """Test detection of incomplete reads."""
        # Setup
        expected_size = 1000
        actual_data = b"X" * 500  # Only half the expected data
        
        mock_stat = MagicMock()
        mock_stat.size = expected_size
        mock_minio_client.stat_object.return_value = mock_stat
        
        mock_response = MagicMock()
        mock_response.stream.return_value = [actual_data]
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute and expect incomplete read error
        with pytest.raises(SHA256StreamingError) as exc_info:
            sha256_service.verify_object_hash(
                bucket_name="test-bucket",
                object_name="truncated-object",
                expected_sha256="abc123",
                expected_size=expected_size,
            )
        
        # Assert
        assert exc_info.value.code == "INCOMPLETE_READ"
        assert "Incomplete read" in exc_info.value.message
        assert exc_info.value.details["bytes_processed"] == 500
    
    def test_delete_object_with_audit(self, sha256_service, mock_minio_client):
        """Test object deletion with audit logging."""
        # Setup
        mock_minio_client.remove_object.return_value = None
        
        # Execute
        result = sha256_service.delete_object_with_audit(
            bucket_name="test-bucket",
            object_name="bad-object",
            reason="Hash mismatch",
            details={"expected": "abc", "actual": "def"},
        )
        
        # Assert
        assert result is True
        mock_minio_client.remove_object.assert_called_once_with("test-bucket", "bad-object")
    
    def test_get_first_chunk(self, sha256_service, mock_minio_client):
        """Test retrieving first chunk for magic byte validation."""
        # Setup
        test_data = b"PNG\x89\x50\x4E\x47" + b"X" * 1017  # PNG magic bytes (7 + 1017 = 1024)
        
        mock_response = MagicMock()
        mock_response.read.return_value = test_data
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute
        chunk = sha256_service.get_first_chunk(
            bucket_name="test-bucket",
            object_name="image.png",
            chunk_size=1024,
        )
        
        # Assert
        assert chunk == test_data
        assert len(chunk) == 1024
        mock_minio_client.get_object.assert_called_once_with(
            "test-bucket",
            "image.png",
            offset=0,
            length=1024,
        )
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()
    
    def test_size_mismatch_warning(self, sha256_service, mock_minio_client):
        """Test size mismatch detection (warning but continue)."""
        # Setup
        test_data = b"Test data"
        expected_sha256 = hashlib.sha256(test_data).hexdigest()
        
        mock_stat = MagicMock()
        mock_stat.size = len(test_data)
        mock_minio_client.stat_object.return_value = mock_stat
        
        mock_response = MagicMock()
        mock_response.stream.return_value = [test_data]
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute with wrong expected size
        is_valid, actual_sha256, metadata = sha256_service.verify_object_hash(
            bucket_name="test-bucket",
            object_name="test-object",
            expected_sha256=expected_sha256,
            expected_size=999,  # Wrong size
        )
        
        # Assert
        assert is_valid is True  # Hash still matches
        assert metadata["size_mismatch"] is True
        assert metadata["expected_size"] == 999
        assert metadata["actual_size"] == len(test_data)


class TestIntegrationScenarios:
    """Integration test scenarios for Task 5.5."""
    
    def test_finalize_idempotency(self, sha256_service, mock_minio_client):
        """Test idempotent finalization (can be called multiple times)."""
        # Setup
        test_data = b"Idempotent test"
        expected_sha256 = hashlib.sha256(test_data).hexdigest()
        
        mock_stat = MagicMock()
        mock_stat.size = len(test_data)
        mock_minio_client.stat_object.return_value = mock_stat
        
        mock_response = MagicMock()
        mock_response.stream.return_value = [test_data]
        mock_minio_client.get_object.return_value = mock_response
        
        # Execute multiple times
        results = []
        for _ in range(3):
            is_valid, actual_sha256, metadata = sha256_service.verify_object_hash(
                bucket_name="test-bucket",
                object_name="test-object",
                expected_sha256=expected_sha256,
            )
            results.append((is_valid, actual_sha256))
            
            # Reset mock for next iteration
            mock_response = MagicMock()
            mock_response.stream.return_value = [test_data]
            mock_minio_client.get_object.return_value = mock_response
        
        # Assert all results are identical
        assert all(r == results[0] for r in results)
        assert results[0] == (True, expected_sha256)
    
    def test_concurrent_verification_handling(self, sha256_service, mock_minio_client):
        """Test handling of concurrent verification requests."""
        # This would require threading in a real scenario
        # For now, just verify the service handles sequential calls correctly
        
        test_data1 = b"File 1"
        test_data2 = b"File 2"
        sha256_1 = hashlib.sha256(test_data1).hexdigest()
        sha256_2 = hashlib.sha256(test_data2).hexdigest()
        
        # Setup for two different files
        mock_stat1 = MagicMock()
        mock_stat1.size = len(test_data1)
        
        mock_stat2 = MagicMock()
        mock_stat2.size = len(test_data2)
        
        mock_minio_client.stat_object.side_effect = [mock_stat1, mock_stat2]
        
        mock_response1 = MagicMock()
        mock_response1.stream.return_value = [test_data1]
        
        mock_response2 = MagicMock()
        mock_response2.stream.return_value = [test_data2]
        
        mock_minio_client.get_object.side_effect = [mock_response1, mock_response2]
        
        # Execute
        is_valid1, hash1, _ = sha256_service.verify_object_hash(
            bucket_name="bucket1",
            object_name="file1",
            expected_sha256=sha256_1,
        )
        
        is_valid2, hash2, _ = sha256_service.verify_object_hash(
            bucket_name="bucket2",
            object_name="file2",
            expected_sha256=sha256_2,
        )
        
        # Assert
        assert is_valid1 is True
        assert hash1 == sha256_1
        assert is_valid2 is True
        assert hash2 == sha256_2