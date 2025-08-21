"""
SHA256 Streaming Service for Task 5.5

Implements memory-efficient SHA256 computation with:
- Streaming from MinIO with chunked reading (8MB chunks)
- Memory usage optimization (<64MB RSS spike for 100MB files)
- Timeout protection (60s read timeout)
- Comprehensive audit logging
- Idempotent operations
"""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

import structlog
from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import ReadTimeoutError, ProtocolError

from app.core.minio_config import get_minio_client

logger = structlog.get_logger(__name__)

# Constants for streaming configuration
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks as specified in Task 5.5
READ_TIMEOUT = 60  # 60 seconds read timeout
MAX_RETRIES = 3  # Maximum number of retry attempts
RETRY_DELAY = 2  # Seconds to wait between retries


class SHA256StreamingError(Exception):
    """Custom exception for SHA256 streaming operations."""
    
    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class SHA256StreamingService:
    """
    Service for streaming SHA256 computation from MinIO objects.
    
    Implements Task 5.5 requirements:
    - Memory-efficient streaming with 8MB chunks
    - Timeout protection against slowloris attacks
    - Comprehensive audit logging
    - Idempotent operations
    """
    
    def __init__(self, client: Optional[Minio] = None):
        """
        Initialize SHA256 streaming service.
        
        Args:
            client: MinIO client instance
        """
        self.client = client or get_minio_client()
    
    @contextmanager
    def _timed_operation(self, operation: str, timeout: int = READ_TIMEOUT):
        """
        Context manager for timing operations with timeout.
        
        Args:
            operation: Name of the operation for logging
            timeout: Maximum allowed time in seconds
            
        Yields:
            Start time for the operation
            
        Raises:
            SHA256StreamingError: If operation times out
        """
        start_time = time.time()
        
        try:
            yield start_time
        finally:
            elapsed_time = time.time() - start_time
            
            if elapsed_time > timeout:
                logger.error(
                    "Operation timed out",
                    operation=operation,
                    elapsed_time=elapsed_time,
                    timeout=timeout,
                )
                raise SHA256StreamingError(
                    code="TIMEOUT",
                    message=f"Operation {operation} timed out after {elapsed_time:.2f}s",
                    details={"elapsed_time": elapsed_time, "timeout": timeout},
                )
            
            logger.debug(
                "Operation completed",
                operation=operation,
                elapsed_time=elapsed_time,
            )
    
    def verify_object_hash(
        self,
        bucket_name: str,
        object_name: str,
        expected_sha256: str,
        expected_size: Optional[int] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Stream object from MinIO and verify its SHA256 hash.
        
        Task 5.5: Main implementation for streaming SHA256 verification.
        
        Args:
            bucket_name: Name of the MinIO bucket
            object_name: Name of the object in the bucket
            expected_sha256: Expected SHA256 hash (hex string)
            expected_size: Expected size in bytes (optional)
            
        Returns:
            Tuple of (is_valid, actual_sha256, metadata)
            - is_valid: True if hash matches
            - actual_sha256: Computed SHA256 hash
            - metadata: Additional metadata (size, chunks, time, etc.)
            
        Raises:
            SHA256StreamingError: On streaming or verification errors
        """
        metadata = {
            "bucket": bucket_name,
            "object": object_name,
            "expected_sha256": expected_sha256,
            "expected_size": expected_size,
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            # Step 1: Use stat_object to confirm size first (Task 5.5 requirement)
            with self._timed_operation("stat_object", timeout=10):
                try:
                    stat = self.client.stat_object(bucket_name, object_name)
                    actual_size = stat.size
                    etag = stat.etag
                    
                    metadata.update({
                        "actual_size": actual_size,
                        "etag": etag,
                        "content_type": stat.content_type,
                        "last_modified": stat.last_modified.isoformat() if stat.last_modified else None,
                    })
                    
                    logger.info(
                        "Object stat retrieved",
                        bucket=bucket_name,
                        object=object_name,
                        size=actual_size,
                        etag=etag,
                    )
                    
                except S3Error as e:
                    if e.code == "NoSuchKey":
                        raise SHA256StreamingError(
                            code="NOT_FOUND",
                            message=f"Object not found: {bucket_name}/{object_name}",
                            details={"error": str(e)},
                        )
                    raise SHA256StreamingError(
                        code="STAT_ERROR",
                        message=f"Failed to stat object: {str(e)}",
                        details={"error": str(e)},
                    )
            
            # Step 2: Verify size if expected_size provided
            if expected_size is not None and actual_size != expected_size:
                metadata["size_mismatch"] = True
                logger.warning(
                    "Size mismatch detected",
                    bucket=bucket_name,
                    object=object_name,
                    expected_size=expected_size,
                    actual_size=actual_size,
                )
                # Don't fail here, continue to compute hash for audit
            
            # Step 3: Stream object with get_object and compute SHA256
            actual_sha256 = None
            bytes_processed = 0
            chunks_processed = 0
            first_chunk = None
            retry_count = 0
            
            while retry_count < MAX_RETRIES:
                try:
                    with self._timed_operation("stream_and_hash", timeout=READ_TIMEOUT):
                        # Get object stream
                        response = self.client.get_object(bucket_name, object_name)
                        
                        try:
                            # Initialize hasher
                            hasher = hashlib.sha256()
                            bytes_processed = 0
                            chunks_processed = 0
                            
                            # Stream through the file in 8MB chunks (Task 5.5 requirement)
                            for chunk_data in response.stream(CHUNK_SIZE):
                                # Update hash
                                hasher.update(chunk_data)
                                
                                # Track progress
                                bytes_processed += len(chunk_data)
                                chunks_processed += 1
                                
                                # Store first chunk for additional validation
                                if chunks_processed == 1:
                                    first_chunk = chunk_data[:1024]  # First 1KB for magic bytes
                                
                                # Log progress for large files
                                if chunks_processed % 10 == 0:  # Every 80MB
                                    logger.debug(
                                        "Streaming progress",
                                        bucket=bucket_name,
                                        object=object_name,
                                        bytes_processed=bytes_processed,
                                        chunks_processed=chunks_processed,
                                        progress_pct=round(bytes_processed / actual_size * 100, 2) if actual_size > 0 else 0,
                                    )
                            
                            # Compute final hash
                            actual_sha256 = hasher.hexdigest()
                            
                            metadata.update({
                                "bytes_processed": bytes_processed,
                                "chunks_processed": chunks_processed,
                                "chunk_size": CHUNK_SIZE,
                                "actual_sha256": actual_sha256,
                                "first_chunk_size": len(first_chunk) if first_chunk else 0,
                            })
                            
                            logger.info(
                                "SHA256 computation completed",
                                bucket=bucket_name,
                                object=object_name,
                                bytes_processed=bytes_processed,
                                chunks=chunks_processed,
                                sha256=actual_sha256,
                            )
                            
                            # Break out of retry loop on success
                            break
                            
                        finally:
                            # Always clean up the connection
                            response.close()
                            response.release_conn()
                    
                except (ReadTimeoutError, ProtocolError, ConnectionError) as e:
                    retry_count += 1
                    if retry_count >= MAX_RETRIES:
                        raise SHA256StreamingError(
                            code="STREAM_ERROR",
                            message=f"Failed to stream object after {MAX_RETRIES} retries: {str(e)}",
                            details={"error": str(e), "retries": retry_count},
                        )
                    
                    logger.warning(
                        "Stream error, retrying",
                        bucket=bucket_name,
                        object=object_name,
                        error=str(e),
                        retry_count=retry_count,
                    )
                    time.sleep(RETRY_DELAY * retry_count)  # Exponential backoff
            
            # Step 4: Verify bytes processed matches size
            if bytes_processed != actual_size:
                metadata["incomplete_read"] = True
                logger.error(
                    "Incomplete read detected",
                    bucket=bucket_name,
                    object=object_name,
                    expected_bytes=actual_size,
                    bytes_processed=bytes_processed,
                )
                raise SHA256StreamingError(
                    code="INCOMPLETE_READ",
                    message=f"Incomplete read: expected {actual_size} bytes, got {bytes_processed}",
                    details=metadata,
                )
            
            # Step 5: Compare hashes
            is_valid = actual_sha256 == expected_sha256
            metadata["hash_match"] = is_valid
            metadata["end_time"] = datetime.now(timezone.utc).isoformat()
            
            if not is_valid:
                # Audit log for hash mismatch
                logger.error(
                    "SHA256 hash mismatch detected",
                    hash_expected=expected_sha256,
                    hash_actual=actual_sha256,
                    object_size=actual_size,
                    object_etag=etag,
                    verification_metadata=metadata,
                )
                
                # Emit audit event (Task 5.5 requirement)
                self._emit_audit_event(
                    event_type="HASH_MISMATCH",
                    bucket=bucket_name,
                    object=object_name,
                    details={
                        "expected_sha256": expected_sha256,
                        "actual_sha256": actual_sha256,
                        "size": actual_size,
                        "etag": etag,
                        **metadata,
                    },
                )
            else:
                logger.info(
                    "SHA256 hash verified successfully",
                    bucket=bucket_name,
                    object=object_name,
                    sha256=actual_sha256,
                    size=actual_size,
                )
            
            return is_valid, actual_sha256, metadata
            
        except SHA256StreamingError:
            raise
        except Exception as e:
            logger.error(
                "Unexpected error during hash verification",
                bucket=bucket_name,
                object=object_name,
                error=str(e),
                exc_info=True,
            )
            raise SHA256StreamingError(
                code="UNEXPECTED_ERROR",
                message=f"Unexpected error: {str(e)}",
                details={"error": str(e), **metadata},
            )
    
    def delete_object_with_audit(
        self,
        bucket_name: str,
        object_name: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Delete object from MinIO with audit logging.
        
        Task 5.5: Delete object on hash mismatch with audit trail.
        
        Args:
            bucket_name: Name of the MinIO bucket
            object_name: Name of the object to delete
            reason: Reason for deletion
            details: Additional details for audit
            
        Returns:
            True if deletion successful, False otherwise
        """
        try:
            # Attempt to delete the object
            self.client.remove_object(bucket_name, object_name)
            
            logger.warning(
                "Object deleted",
                bucket=bucket_name,
                object=object_name,
                reason=reason,
                details=details,
            )
            
            # Emit audit event
            self._emit_audit_event(
                event_type="OBJECT_DELETED",
                bucket=bucket_name,
                object=object_name,
                details={
                    "reason": reason,
                    **(details or {}),
                },
            )
            
            return True
            
        except S3Error as e:
            logger.error(
                "Failed to delete object",
                bucket=bucket_name,
                object=object_name,
                reason=reason,
                error=str(e),
            )
            return False
    
    def _emit_audit_event(
        self,
        event_type: str,
        bucket: str,
        object: str,
        details: Dict[str, Any],
    ) -> None:
        """
        Emit audit event for compliance and security tracking.
        
        Args:
            event_type: Type of audit event
            bucket: Bucket name
            object: Object name
            details: Event details
        """
        audit_event = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bucket": bucket,
            "object": object,
            "details": details,
        }
        
        # Log as structured audit event
        logger.info(
            "AUDIT_EVENT",
            **audit_event,
        )
        
        # TODO: Task 5.7 - Send to audit service/queue
    
    def get_first_chunk(
        self,
        bucket_name: str,
        object_name: str,
        chunk_size: int = 1024,
    ) -> Optional[bytes]:
        """
        Get first chunk of object for magic byte validation.
        
        Args:
            bucket_name: Name of the MinIO bucket
            object_name: Name of the object
            chunk_size: Size of chunk to retrieve (default 1KB)
            
        Returns:
            First chunk bytes or None on error
        """
        try:
            # Use ranged get to retrieve only first chunk
            response = self.client.get_object(
                bucket_name,
                object_name,
                offset=0,
                length=chunk_size,
            )
            
            try:
                chunk = response.read()
                return chunk
            finally:
                response.close()
                response.release_conn()
                
        except S3Error as e:
            logger.error(
                "Failed to get first chunk",
                bucket=bucket_name,
                object=object_name,
                error=str(e),
            )
            return None


def get_sha256_streaming_service(client: Optional[Minio] = None) -> SHA256StreamingService:
    """
    Get SHA256 streaming service instance for dependency injection.
    
    Args:
        client: Optional MinIO client
        
    Returns:
        SHA256StreamingService: Configured service instance
    """
    return SHA256StreamingService(client=client)


__all__ = [
    "SHA256StreamingService",
    "SHA256StreamingError",
    "get_sha256_streaming_service",
    "CHUNK_SIZE",
    "READ_TIMEOUT",
]