"""
Comprehensive tests for S3 service module.

Tests cover:
- Stream I/O operations
- Error handling with Turkish localization
- Presigned URL generation
- File upload/download
- Resource cleanup
- Memory efficiency
"""

import io
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path

from app.services.s3_service import (
    S3Service,
    AsyncS3Service,
    StorageError,
    StreamingResponseWrapper,
    get_s3_service,
    get_s3_service_async,
)
from app.schemas.file_schemas import (
    BucketType,
    FileType,
    PresignedUrlResponse,
)
from app.core.minio_config import StorageErrorCode


class TestS3Service:
    """Test S3 service operations."""
    
    @pytest.fixture
    def mock_client(self):
        """Create mock MinIO client."""
        client = Mock()
        client.bucket_exists.return_value = True
        return client
    
    @pytest.fixture
    def mock_config(self):
        """Create mock MinIO config."""
        config = Mock()
        config.bucket_artefacts = "artefacts"
        config.bucket_logs = "logs"
        config.bucket_reports = "reports"
        config.bucket_invoices = "invoices"
        config.bucket_temp = "temp"
        return config
    
    @pytest.fixture
    def s3_service(self, mock_client, mock_config):
        """Create S3 service with mocks."""
        return S3Service(client=mock_client, config=mock_config)
    
    def test_initialization(self, mock_client, mock_config):
        """Test S3 service initialization."""
        service = S3Service(client=mock_client, config=mock_config)
        
        assert service.client == mock_client
        assert service.config == mock_config
        assert service._bucket_cache == {}
    
    def test_ensure_buckets_creates_missing(self, mock_client, mock_config):
        """Test bucket creation for missing buckets."""
        mock_client.bucket_exists.side_effect = [False, True, False, True, False]
        
        service = S3Service(client=mock_client, config=mock_config)
        
        # Should create 3 missing buckets
        assert mock_client.make_bucket.call_count == 3
    
    def test_generate_object_key_artefacts(self, s3_service):
        """Test object key generation for artefacts bucket."""
        key = s3_service._generate_object_key(
            bucket_type=BucketType.ARTEFACTS,
            job_id="job_123",
            filename="model.stl"
        )
        
        assert key.startswith("job_123/")
        assert key.endswith(".stl")
    
    def test_generate_object_key_logs(self, s3_service):
        """Test object key generation for logs bucket."""
        key = s3_service._generate_object_key(
            bucket_type=BucketType.LOGS
        )
        
        # Should have date prefix
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        assert key.startswith(f"{date_str}/")
        assert key.endswith(".log")
    
    def test_sanitize_object_key(self, s3_service):
        """Test object key sanitization."""
        # Valid key passes through
        assert s3_service._sanitize_object_key("path/to/file.txt") == "path/to/file.txt"
        
        # Path traversal removed
        sanitized = s3_service._sanitize_object_key("../../../etc/passwd")
        assert ".." not in sanitized
        
        # Invalid characters replaced
        sanitized = s3_service._sanitize_object_key("file<name>.txt")
        assert "<" not in sanitized
        assert ">" not in sanitized
    
    @pytest.mark.asyncio
    async def test_upload_file_stream_small_file(self, s3_service, mock_client):
        """Test uploading a small file (buffered in memory)."""
        # Create small test file
        file_data = b"test content"
        file_stream = io.BytesIO(file_data)
        
        mock_client.put_object.return_value = None
        
        with patch.object(s3_service, 'generate_presigned_url') as mock_presigned:
            mock_presigned.return_value = PresignedUrlResponse(
                url="https://example.com/download",
                expires_at=datetime.utcnow() + timedelta(hours=1),
                operation="download",
                bucket="artefacts",
                object_key="test.txt"
            )
            
            key, url_response = await s3_service.upload_file_stream(
                file_stream=file_stream,
                bucket="artefacts",
                filename="test.txt"
            )
        
        assert mock_client.put_object.called
        assert url_response.url == "https://example.com/download"
    
    @pytest.mark.asyncio
    async def test_upload_file_stream_large_file(self, s3_service, mock_client):
        """Test uploading a large file (streamed directly)."""
        # Create large test file (>5MB)
        file_size = 6 * 1024 * 1024  # 6MB
        file_stream = io.BytesIO(b"x" * file_size)
        
        mock_client.put_object.return_value = None
        
        with patch.object(s3_service, 'generate_presigned_url') as mock_presigned:
            mock_presigned.return_value = PresignedUrlResponse(
                url="https://example.com/download",
                expires_at=datetime.utcnow() + timedelta(hours=1),
                operation="download",
                bucket="artefacts",
                object_key="large.bin"
            )
            
            key, url_response = await s3_service.upload_file_stream(
                file_stream=file_stream,
                bucket="artefacts",
                filename="large.bin"
            )
        
        # Should stream directly without buffering
        assert mock_client.put_object.called
        put_call = mock_client.put_object.call_args
        assert put_call[1]['length'] == file_size
    
    @pytest.mark.asyncio
    async def test_upload_file_stream_size_limit(self, s3_service, mock_client):
        """Test file size limit enforcement."""
        # Create file exceeding size limit
        oversized = 6 * 1024 * 1024 * 1024  # 6GB
        file_stream = Mock()
        file_stream.seek.return_value = None
        file_stream.tell.return_value = oversized
        
        with pytest.raises(StorageError) as exc_info:
            await s3_service.upload_file_stream(
                file_stream=file_stream,
                bucket="artefacts",
                filename="huge.bin"
            )
        
        assert exc_info.value.code == StorageErrorCode.STORAGE_QUOTA_EXCEEDED
        assert "Dosya çok büyük" in exc_info.value.turkish_message
    
    @pytest.mark.asyncio
    async def test_download_file_stream(self, s3_service, mock_client):
        """Test file download to stream."""
        file_data = b"downloaded content"
        mock_response = Mock()
        mock_response.read.return_value = file_data
        mock_response.close.return_value = None
        mock_response.release_conn.return_value = None
        
        mock_client.get_object.return_value = mock_response
        
        stream = await s3_service.download_file_stream(
            bucket="artefacts",
            object_key="test.txt"
        )
        
        # Should return StreamingResponseWrapper
        assert isinstance(stream, StreamingResponseWrapper)
        
        # Can read the data
        with stream as s:
            content = s.read()
            assert content == file_data
    
    @pytest.mark.asyncio
    async def test_download_file_not_found(self, s3_service, mock_client):
        """Test download of non-existent file."""
        from minio.error import S3Error
        
        mock_client.get_object.side_effect = S3Error(
            code="NoSuchKey",
            message="The specified key does not exist",
            resource="test.txt",
            request_id="123",
            host_id="456",
            response="Not Found"
        )
        
        with pytest.raises(StorageError) as exc_info:
            await s3_service.download_file_stream(
                bucket="artefacts",
                object_key="nonexistent.txt"
            )
        
        assert exc_info.value.code == StorageErrorCode.STORAGE_NOT_FOUND
        assert "Dosya bulunamadı" in exc_info.value.turkish_message
    
    @pytest.mark.asyncio
    async def test_generate_presigned_url_download(self, s3_service, mock_client):
        """Test presigned URL generation for download."""
        mock_client.presigned_get_object.return_value = "https://example.com/download"
        
        response = await s3_service.generate_presigned_url(
            bucket="artefacts",
            object_key="test.txt",
            operation="download",
            expires_in=3600
        )
        
        assert response.url == "https://example.com/download"
        assert response.operation == "download"
        assert response.bucket == "artefacts"
        assert response.object_key == "test.txt"
    
    @pytest.mark.asyncio
    async def test_generate_presigned_url_upload(self, s3_service, mock_client):
        """Test presigned URL generation for upload."""
        mock_client.presigned_put_object.return_value = "https://example.com/upload"
        
        response = await s3_service.generate_presigned_url(
            bucket="artefacts",
            object_key="new.txt",
            operation="upload",
            expires_in=1800
        )
        
        assert response.url == "https://example.com/upload"
        assert response.operation == "upload"
    
    @pytest.mark.asyncio
    async def test_list_objects(self, s3_service, mock_client):
        """Test listing objects in bucket."""
        mock_obj = Mock()
        mock_obj.object_name = "test.txt"
        mock_obj.size = 1024
        mock_obj.content_type = "text/plain"
        mock_obj.last_modified = datetime.utcnow()
        mock_obj.etag = "abc123"
        mock_obj.metadata = {"key": "value"}
        
        mock_client.list_objects.return_value = [mock_obj]
        
        objects = await s3_service.list_objects(
            bucket="artefacts",
            prefix="test/",
            max_results=10
        )
        
        assert len(objects) == 1
        assert objects[0].object_key == "test.txt"
        assert objects[0].size == 1024
    
    @pytest.mark.asyncio
    async def test_delete_object(self, s3_service, mock_client):
        """Test object deletion."""
        mock_client.remove_object.return_value = None
        
        result = await s3_service.delete_object(
            bucket="artefacts",
            object_key="old.txt"
        )
        
        assert result is True
        mock_client.remove_object.assert_called_with("artefacts", "old.txt")
    
    @pytest.mark.asyncio
    async def test_get_object_info_exists(self, s3_service, mock_client):
        """Test getting info for existing object."""
        mock_stat = Mock()
        mock_stat.size = 2048
        mock_stat.content_type = "application/pdf"
        mock_stat.last_modified = datetime.utcnow()
        mock_stat.etag = "xyz789"
        mock_stat.metadata = {}
        mock_stat.version_id = "v1.0"
        
        mock_client.stat_object.return_value = mock_stat
        
        info = await s3_service.get_object_info(
            bucket="reports",
            object_key="report.pdf"
        )
        
        assert info is not None
        assert info.size == 2048
        assert info.content_type == "application/pdf"
        assert info.version_id == "v1.0"
    
    @pytest.mark.asyncio
    async def test_get_object_info_not_found(self, s3_service, mock_client):
        """Test getting info for non-existent object."""
        from minio.error import S3Error
        
        mock_client.stat_object.side_effect = S3Error(
            code="NoSuchKey",
            message="Not found",
            resource="missing.txt",
            request_id="123",
            host_id="456",
            response="Not Found"
        )
        
        info = await s3_service.get_object_info(
            bucket="artefacts",
            object_key="missing.txt"
        )
        
        assert info is None


class TestStreamingResponseWrapper:
    """Test streaming response wrapper."""
    
    def test_read(self):
        """Test reading from wrapper."""
        mock_response = Mock()
        mock_response.read.return_value = b"test data"
        
        wrapper = StreamingResponseWrapper(mock_response)
        data = wrapper.read()
        
        assert data == b"test data"
        mock_response.read.assert_called_once_with(-1)
    
    def test_read_closed(self):
        """Test reading from closed wrapper."""
        mock_response = Mock()
        wrapper = StreamingResponseWrapper(mock_response)
        wrapper.close()
        
        with pytest.raises(ValueError) as exc_info:
            wrapper.read()
        
        assert "closed stream" in str(exc_info.value)
    
    def test_close(self):
        """Test closing wrapper."""
        mock_response = Mock()
        wrapper = StreamingResponseWrapper(mock_response)
        
        wrapper.close()
        
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()
        assert wrapper._closed is True
    
    def test_context_manager(self):
        """Test wrapper as context manager."""
        mock_response = Mock()
        mock_response.read.return_value = b"data"
        
        with StreamingResponseWrapper(mock_response) as wrapper:
            data = wrapper.read()
            assert data == b"data"
        
        # Should be closed after context
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()
    
    def test_garbage_collection(self):
        """Test cleanup on garbage collection."""
        mock_response = Mock()
        wrapper = StreamingResponseWrapper(mock_response)
        
        # Simulate garbage collection
        wrapper.__del__()
        
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()


class TestStorageError:
    """Test storage error handling."""
    
    def test_storage_error_creation(self):
        """Test creating storage error."""
        error = StorageError(
            code=StorageErrorCode.STORAGE_NOT_FOUND,
            message="File not found",
            turkish_message="Dosya bulunamadı",
            details={"key": "test.txt"}
        )
        
        assert error.code == StorageErrorCode.STORAGE_NOT_FOUND
        assert error.message == "File not found"
        assert error.turkish_message == "Dosya bulunamadı"
        assert error.details == {"key": "test.txt"}
    
    def test_storage_error_defaults(self):
        """Test storage error with defaults."""
        error = StorageError(
            code=StorageErrorCode.STORAGE_OPERATION_FAILED,
            message="Operation failed"
        )
        
        assert error.turkish_message == "Operation failed"  # Falls back to message
        assert error.details == {}


@pytest.mark.asyncio
class TestAsyncContextManager:
    """Test async context manager for S3 service."""
    
    async def test_get_s3_service_async(self):
        """Test async context manager."""
        async with get_s3_service_async() as service:
            assert isinstance(service, AsyncS3Service)
            assert service.sync_service.client is not None
            assert service.sync_service.config is not None
    
    async def test_get_s3_service_async_cleanup(self):
        """Test cleanup in async context manager."""
        async with get_s3_service_async() as service:
            # Use service
            pass
        
        # Service should be cleaned up after context
        # (cleanup logic would be in the finally block)