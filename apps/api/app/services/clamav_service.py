"""
Ultra-Enterprise ClamAV Service for Task 5.6

Implements malware scanning for uploaded files with:
- ClamAV daemon integration via TCP/Unix sockets
- Streaming scan from MinIO without disk storage
- Robust error handling and rate limiting
- Security event logging and audit trail
- Configurable file type scanning policies
- Enterprise-grade timeouts and failure modes
"""

from __future__ import annotations

import asyncio
import socket
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Union

import clamd
import structlog
from minio import Minio
from minio.error import S3Error
from sqlalchemy.orm import Session

from app.models.security_event import SecurityEvent, SecurityEventType, SeverityLevel
from app.schemas.file_upload import UploadErrorCode

logger = structlog.get_logger(__name__)

# EICAR test string for testing purposes
EICAR_TEST_STRING = (
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)

# File types that should be scanned (non-G-code CAD and videos)
SCANNABLE_FILE_TYPES = {
    "model",  # CAD files
    "temp",   # Temporary uploads
    "report", # Reports might contain embedded content
}

# MIME types that require scanning
SCANNABLE_MIME_TYPES = {
    # CAD/3D model formats
    "application/sla",
    "application/step", 
    "model/iges",
    "model/obj",
    "application/x-3ds",
    "application/x-blend",
    "application/x-freecad",
    # Archive formats that might contain malware
    "application/zip",
    "application/x-zip-compressed",
    "application/gzip",
    "application/x-gzip",
    "application/x-tar",
    "application/x-7z-compressed",
    # Document formats
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Image formats (can contain embedded malware)
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    # Video formats
    "video/mp4",
    "video/avi", 
    "video/mkv",
    "video/webm",
    # Executable formats (high risk)
    "application/x-executable",
    "application/x-msdownload",
    "application/x-msdos-program",
}

# File extensions to skip scanning (G-code and safe text files)
SKIP_SCAN_EXTENSIONS = {
    ".nc",    # G-code
    ".gcode", # G-code
    ".txt",   # Plain text G-code
    ".json",  # JSON configuration
    ".xml",   # XML configuration
    ".csv",   # CSV data
    ".log",   # Log files
}


class ClamAVError(Exception):
    """Base exception for ClamAV service operations."""

    def __init__(
        self,
        code: str,
        message: str,
        turkish_message: str | None = None,
        details: dict | None = None,
        status_code: int = 500,
    ):
        self.code = code
        self.message = message
        self.turkish_message = turkish_message or message
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)


class ClamAVScanResult:
    """Result of a ClamAV scan operation."""

    def __init__(
        self,
        is_clean: bool,
        scan_time_ms: float,
        virus_name: str | None = None,
        scan_metadata: dict | None = None,
        error_message: str | None = None,
    ):
        self.is_clean = is_clean
        self.scan_time_ms = scan_time_ms
        self.virus_name = virus_name
        self.scan_metadata = scan_metadata or {}
        self.error_message = error_message

    def __repr__(self) -> str:
        status = "CLEAN" if self.is_clean else f"INFECTED({self.virus_name})"
        return f"ClamAVScanResult(status={status}, time={self.scan_time_ms:.2f}ms)"


class ClamAVRateLimiter:
    """Rate limiter for concurrent ClamAV scans."""

    def __init__(self, max_concurrent_scans: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent_scans)
        self._active_scans = 0
        self._total_scans = 0
        self._lock = threading.Lock()

    @asynccontextmanager
    async def acquire_scan_slot(self):
        """Acquire a scan slot with rate limiting."""
        try:
            # Wait for available slot
            async with self._semaphore:
                with self._lock:
                    self._active_scans += 1
                    self._total_scans += 1
                
                logger.info(
                    "ClamAV scan slot acquired",
                    active_scans=self._active_scans,
                    total_scans=self._total_scans,
                )
                
                yield
        finally:
            with self._lock:
                self._active_scans -= 1
            
            logger.info(
                "ClamAV scan slot released",
                active_scans=self._active_scans,
                total_scans=self._total_scans,
            )

    def get_stats(self) -> dict:
        """Get current rate limiter statistics."""
        with self._lock:
            return {
                "active_scans": self._active_scans,
                "total_scans": self._total_scans,
                "available_slots": self._semaphore._value,
            }


class ClamAVService:
    """
    Ultra-Enterprise ClamAV service for Task 5.6.
    
    Features:
    - TCP and Unix socket connections to clamd
    - Streaming scan from MinIO objects
    - Rate limiting for resource protection  
    - Comprehensive error handling and audit logging
    - Security event tracking
    - Configurable scanning policies
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3310,
        unix_socket: str | None = None,
        timeout_connect: float = 10.0,
        timeout_scan: float = 60.0,
        max_concurrent_scans: int = 3,
        scan_enabled: bool = True,
        db: Session | None = None,
        minio_client: Minio | None = None,
    ):
        """
        Initialize ClamAV service.
        
        Args:
            host: ClamAV daemon host (default: localhost)
            port: ClamAV daemon port (default: 3310) 
            unix_socket: Unix socket path (preferred over TCP)
            timeout_connect: Connection timeout in seconds
            timeout_scan: Scan timeout in seconds
            max_concurrent_scans: Maximum concurrent scans
            scan_enabled: Whether scanning is enabled
            db: Database session for audit logging
            minio_client: MinIO client for streaming
        """
        self.host = host
        self.port = port  
        self.unix_socket = unix_socket
        self.timeout_connect = timeout_connect
        self.timeout_scan = timeout_scan
        self.scan_enabled = scan_enabled
        self.db = db
        self.minio_client = minio_client
        
        # Initialize rate limiter
        self.rate_limiter = ClamAVRateLimiter(max_concurrent_scans)
        
        # Connection instance (lazy initialized)
        self._clamd_client: clamd.ClamdNetworkSocket | clamd.ClamdUnixSocket | None = None
        
        logger.info(
            "ClamAV service initialized",
            host=self.host,
            port=self.port,
            unix_socket=self.unix_socket,
            timeout_connect=self.timeout_connect,
            timeout_scan=self.timeout_scan,
            scan_enabled=self.scan_enabled,
            max_concurrent_scans=max_concurrent_scans,
        )

    def _get_clamd_client(self) -> clamd.ClamdNetworkSocket | clamd.ClamdUnixSocket:
        """Get ClamAV daemon client with connection priority: Unix socket > TCP."""
        if self._clamd_client is None:
            if self.unix_socket:
                # Prefer Unix socket connection
                logger.debug(
                    "Initializing ClamAV Unix socket connection",
                    unix_socket=self.unix_socket,
                )
                self._clamd_client = clamd.ClamdUnixSocket(
                    path=self.unix_socket,
                    timeout=self.timeout_connect,
                )
            else:
                # Fallback to TCP connection
                logger.debug(
                    "Initializing ClamAV TCP connection",
                    host=self.host,
                    port=self.port,
                )
                self._clamd_client = clamd.ClamdNetworkSocket(
                    host=self.host,
                    port=self.port,
                    timeout=self.timeout_connect,
                )
        
        return self._clamd_client

    def _log_security_event(
        self,
        event_type: SecurityEventType,
        description: str,
        details: dict | None = None,
        severity: SeverityLevel = SeverityLevel.HIGH,
    ) -> None:
        """Log security event to database and structured logs."""
        try:
            # Structured logging (always happens)
            logger.warning(
                "ClamAV security event",
                event_type=event_type.value,
                description=description,
                details=details or {},
                severity=severity.value,
            )

            # Database logging (if available)
            if self.db:
                security_event = SecurityEvent(
                    event_type=event_type,
                    description=description,
                    details=details or {},
                    severity=severity,
                    source_ip="system",  # Internal scan
                    user_agent="ClamAV-Service/1.0",
                    occurred_at=datetime.now(UTC),
                )
                self.db.add(security_event)
                self.db.commit()

        except Exception as e:
            logger.error(
                "Failed to log ClamAV security event",
                error=str(e),
                event_type=event_type.value if event_type else None,
                description=description,
            )

    def ping(self) -> bool:
        """
        Test connection to ClamAV daemon.
        
        Returns:
            bool: True if daemon is reachable, False otherwise
        """
        try:
            client = self._get_clamd_client()
            response = client.ping()
            is_alive = response == "PONG"
            
            logger.info(
                "ClamAV daemon ping result",
                is_alive=is_alive,
                response=response,
            )
            
            return is_alive
        except Exception as e:
            logger.error(
                "ClamAV daemon ping failed",
                error=str(e),
                host=self.host,
                port=self.port,
                unix_socket=self.unix_socket,
            )
            return False

    def get_version(self) -> str | None:
        """
        Get ClamAV daemon version.
        
        Returns:
            str | None: Version string or None if unavailable
        """
        try:
            client = self._get_clamd_client()
            version = client.version()
            
            logger.info("ClamAV daemon version", version=version)
            return version
            
        except Exception as e:
            logger.error("Failed to get ClamAV version", error=str(e))
            return None

    def _should_scan_file(
        self,
        object_key: str,
        mime_type: str | None = None,
        file_type: str | None = None,
    ) -> bool:
        """
        Determine if file should be scanned based on policies.
        
        Args:
            object_key: S3 object key
            mime_type: MIME type of the file
            file_type: File type enum value
            
        Returns:
            bool: True if file should be scanned
        """
        if not self.scan_enabled:
            return False

        # Extract file extension
        if "." in object_key:
            extension = "." + object_key.rsplit(".", 1)[-1].lower()
            if extension in SKIP_SCAN_EXTENSIONS:
                logger.debug(
                    "Skipping scan for safe file extension",
                    object_key=object_key,
                    extension=extension,
                )
                return False

        # Check file type
        if file_type and file_type not in SCANNABLE_FILE_TYPES:
            logger.debug(
                "Skipping scan for file type",
                object_key=object_key,
                file_type=file_type,
            )
            return False

        # Check MIME type
        if mime_type and mime_type not in SCANNABLE_MIME_TYPES:
            logger.debug(
                "Skipping scan for MIME type",
                object_key=object_key,
                mime_type=mime_type,
            )
            return False

        return True

    async def scan_object_stream(
        self,
        bucket_name: str,
        object_name: str,
        mime_type: str | None = None,
        file_type: str | None = None,
        max_size_bytes: int = 100 * 1024 * 1024,  # 100MB default limit
    ) -> ClamAVScanResult:
        """
        Stream scan an S3 object using ClamAV without storing to disk.
        
        Args:
            bucket_name: S3 bucket name
            object_name: S3 object name  
            mime_type: MIME type for policy decisions
            file_type: File type for policy decisions
            max_size_bytes: Maximum file size to scan
            
        Returns:
            ClamAVScanResult: Scan result with metadata
            
        Raises:
            ClamAVError: On scan failure or daemon unavailable
        """
        object_key = f"{bucket_name}/{object_name}"
        
        # Check scan policy
        if not self._should_scan_file(object_key, mime_type, file_type):
            logger.debug(
                "File scan skipped by policy",
                object_key=object_key,
                mime_type=mime_type,
                file_type=file_type,
            )
            return ClamAVScanResult(
                is_clean=True,
                scan_time_ms=0.0,
                scan_metadata={"scan_skipped": True, "reason": "policy"},
            )

        # Fail closed if scanning is enabled but daemon is unreachable
        if self.scan_enabled and not self.ping():
            self._log_security_event(
                event_type=SecurityEventType.MALWARE_SCAN_FAILURE,
                description="ClamAV daemon unavailable but scan_enabled=true",
                details={
                    "object_key": object_key,
                    "host": self.host,
                    "port": self.port,
                    "unix_socket": self.unix_socket,
                },
                severity=SeverityLevel.HIGH,
            )
            raise ClamAVError(
                code="SCAN_UNAVAILABLE",
                message="Malware scanning unavailable",
                turkish_message="Kötü amaçlı yazılım taraması kullanılamıyor",
                details={
                    "object_key": object_key,
                    "daemon_status": "unreachable",
                },
                status_code=503,
            )

        # Rate limiting
        async with self.rate_limiter.acquire_scan_slot():
            start_time = datetime.now(UTC)
            
            try:
                if not self.minio_client:
                    raise ClamAVError(
                        code="MINIO_CLIENT_UNAVAILABLE",
                        message="MinIO client not available for streaming",
                        turkish_message="MinIO istemcisi mevcut değil",
                        status_code=500,
                    )

                # Check object size before streaming
                try:
                    stat = self.minio_client.stat_object(bucket_name, object_name)
                    if stat.size > max_size_bytes:
                        logger.warning(
                            "Object too large for ClamAV scanning",
                            object_key=object_key,
                            size=stat.size,
                            max_size=max_size_bytes,
                        )
                        return ClamAVScanResult(
                            is_clean=True,  # Assume clean for oversized files
                            scan_time_ms=0.0,
                            scan_metadata={
                                "scan_skipped": True,
                                "reason": "oversized",
                                "size": stat.size,
                                "max_size": max_size_bytes,
                            },
                        )
                except S3Error as e:
                    raise ClamAVError(
                        code="OBJECT_NOT_FOUND",
                        message=f"Object not found for scanning: {object_key}",
                        turkish_message=f"Taranacak nesne bulunamadı: {object_key}",
                        details={"s3_error": str(e)},
                        status_code=404,
                    )

                # Stream object from MinIO in chunks to avoid memory issues
                logger.info(
                    "Starting ClamAV streaming scan",
                    object_key=object_key,
                    size=stat.size,
                    mime_type=mime_type,
                )

                # Create BytesIO buffer for streaming
                buffer = BytesIO()
                
                try:
                    # Stream object from MinIO
                    response = self.minio_client.get_object(bucket_name, object_name)
                    
                    # Read in chunks to avoid memory exhaustion
                    chunk_size = 8 * 1024 * 1024  # 8MB chunks
                    total_bytes = 0
                    
                    for chunk in response.stream(chunk_size):
                        if not chunk:
                            break
                        buffer.write(chunk)
                        total_bytes += len(chunk)
                        
                        # Safety check to prevent runaway memory usage
                        if total_bytes > max_size_bytes:
                            break
                    
                    # Reset buffer position for scanning
                    buffer.seek(0)
                    
                finally:
                    response.close()
                    response.release_conn()

                # Perform ClamAV scan using instream
                client = self._get_clamd_client()
                scan_start_time = datetime.now(UTC)
                
                try:
                    # Set scan-specific timeout
                    client.timeout = self.timeout_scan
                    
                    # Perform streaming scan
                    scan_result = client.instream(buffer)
                    
                    scan_end_time = datetime.now(UTC)
                    scan_time_ms = (scan_end_time - scan_start_time).total_seconds() * 1000
                    
                    # Parse scan result
                    # Result format: {'stream': ('FOUND', 'Virus-Name')} or {'stream': ('OK', None)}
                    stream_result = scan_result.get("stream")
                    if not stream_result:
                        raise ClamAVError(
                            code="SCAN_RESULT_INVALID",
                            message="Invalid scan result format",
                            turkish_message="Geçersiz tarama sonucu formatı",
                            status_code=500,
                        )
                    
                    status, virus_name = stream_result
                    is_clean = status == "OK"
                    
                    # Log scan result
                    logger.info(
                        "ClamAV scan completed",
                        object_key=object_key,
                        is_clean=is_clean,
                        virus_name=virus_name,
                        scan_time_ms=scan_time_ms,
                        bytes_scanned=total_bytes,
                    )
                    
                    # Security event for malware detection
                    if not is_clean:
                        self._log_security_event(
                            event_type=SecurityEventType.MALWARE_DETECTED,
                            description=f"Malware detected in uploaded file: {virus_name}",
                            details={
                                "object_key": object_key,
                                "virus_name": virus_name,
                                "scan_time_ms": scan_time_ms,
                                "file_size": total_bytes,
                                "mime_type": mime_type,
                            },
                            severity=SeverityLevel.CRITICAL,
                        )
                    
                    return ClamAVScanResult(
                        is_clean=is_clean,
                        scan_time_ms=scan_time_ms,
                        virus_name=virus_name if not is_clean else None,
                        scan_metadata={
                            "bytes_scanned": total_bytes,
                            "object_size": stat.size,
                            "mime_type": mime_type,
                            "file_type": file_type,
                            "scan_method": "instream",
                        },
                    )
                    
                except socket.timeout:
                    scan_time_ms = (datetime.now(UTC) - scan_start_time).total_seconds() * 1000
                    self._log_security_event(
                        event_type=SecurityEventType.MALWARE_SCAN_FAILURE,
                        description=f"ClamAV scan timeout after {scan_time_ms:.0f}ms",
                        details={
                            "object_key": object_key,
                            "timeout_ms": self.timeout_scan * 1000,
                            "scan_time_ms": scan_time_ms,
                        },
                        severity=SeverityLevel.MEDIUM,
                    )
                    raise ClamAVError(
                        code="SCAN_TIMEOUT",
                        message=f"Scan timeout after {self.timeout_scan}s",
                        turkish_message=f"{self.timeout_scan}s sonra tarama zaman aşımı",
                        details={"timeout_seconds": self.timeout_scan},
                        status_code=408,
                    )
                    
                except clamd.ConnectionError as e:
                    self._log_security_event(
                        event_type=SecurityEventType.MALWARE_SCAN_FAILURE,
                        description=f"ClamAV connection error: {str(e)}",
                        details={
                            "object_key": object_key,
                            "connection_error": str(e),
                            "host": self.host,
                            "port": self.port,
                        },
                        severity=SeverityLevel.HIGH,
                    )
                    raise ClamAVError(
                        code="CLAMD_CONNECTION_ERROR",
                        message=f"ClamAV daemon connection failed: {str(e)}",
                        turkish_message=f"ClamAV daemon bağlantısı başarısız: {str(e)}",
                        details={"connection_error": str(e)},
                        status_code=503,
                    )
                    
                except Exception as e:
                    scan_time_ms = (datetime.now(UTC) - scan_start_time).total_seconds() * 1000
                    self._log_security_event(
                        event_type=SecurityEventType.MALWARE_SCAN_FAILURE,
                        description=f"ClamAV scan error: {str(e)}",
                        details={
                            "object_key": object_key,
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "scan_time_ms": scan_time_ms,
                        },
                        severity=SeverityLevel.HIGH,
                    )
                    raise ClamAVError(
                        code="SCAN_ERROR",
                        message=f"Scan failed: {str(e)}",
                        turkish_message=f"Tarama başarısız: {str(e)}",
                        details={"error": str(e)},
                        status_code=500,
                    )

            except ClamAVError:
                raise
            except Exception as e:
                total_time_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                logger.error(
                    "Unexpected error during ClamAV scan",
                    object_key=object_key,
                    error=str(e),
                    total_time_ms=total_time_ms,
                    exc_info=True,
                )
                raise ClamAVError(
                    code="UNEXPECTED_SCAN_ERROR",
                    message=f"Unexpected scan error: {str(e)}",
                    turkish_message=f"Beklenmeyen tarama hatası: {str(e)}",
                    details={"error": str(e)},
                    status_code=500,
                )

    def scan_eicar_test(self) -> ClamAVScanResult:
        """
        Test ClamAV functionality using EICAR test string.
        
        Returns:
            ClamAVScanResult: Should detect EICAR test signature
            
        Raises:
            ClamAVError: On scan failure
        """
        logger.info("Running ClamAV EICAR test")
        
        try:
            client = self._get_clamd_client()
            buffer = BytesIO(EICAR_TEST_STRING.encode())
            
            start_time = datetime.now(UTC)
            result = client.instream(buffer)
            end_time = datetime.now(UTC)
            
            scan_time_ms = (end_time - start_time).total_seconds() * 1000
            
            stream_result = result.get("stream")
            if not stream_result:
                raise ClamAVError(
                    code="EICAR_TEST_FAILED",
                    message="EICAR test failed - no scan result",
                    turkish_message="EICAR testi başarısız - tarama sonucu yok",
                    status_code=500,
                )
            
            status, virus_name = stream_result
            is_clean = status == "OK"
            expected_virus = "Eicar-Test-Signature"
            
            # EICAR should be detected as infected
            if is_clean:
                logger.error("EICAR test failed - should be detected as infected")
                raise ClamAVError(
                    code="EICAR_NOT_DETECTED",
                    message="EICAR test string was not detected - ClamAV may be misconfigured",
                    turkish_message="EICAR test dizesi tespit edilmedi - ClamAV yanlış yapılandırılmış olabilir",
                    status_code=500,
                )
            
            logger.info(
                "EICAR test successful",
                virus_name=virus_name,
                scan_time_ms=scan_time_ms,
                expected_virus=expected_virus,
            )
            
            return ClamAVScanResult(
                is_clean=False,
                scan_time_ms=scan_time_ms,
                virus_name=virus_name,
                scan_metadata={
                    "test_type": "eicar",
                    "expected_virus": expected_virus,
                    "test_passed": virus_name == expected_virus,
                },
            )
            
        except ClamAVError:
            raise
        except Exception as e:
            logger.error("EICAR test failed with exception", error=str(e), exc_info=True)
            raise ClamAVError(
                code="EICAR_TEST_ERROR",
                message=f"EICAR test error: {str(e)}",
                turkish_message=f"EICAR test hatası: {str(e)}",
                details={"error": str(e)},
                status_code=500,
            )

    def get_stats(self) -> dict:
        """Get ClamAV service statistics."""
        daemon_stats = {
            "daemon_reachable": self.ping(),
            "daemon_version": self.get_version(),
        }
        
        rate_limiter_stats = self.rate_limiter.get_stats()
        
        return {
            "scan_enabled": self.scan_enabled,
            "connection": {
                "host": self.host,
                "port": self.port,
                "unix_socket": self.unix_socket,
                "timeout_connect": self.timeout_connect,
                "timeout_scan": self.timeout_scan,
            },
            "daemon": daemon_stats,
            "rate_limiter": rate_limiter_stats,
            "scannable_types": list(SCANNABLE_FILE_TYPES),
            "skip_extensions": list(SKIP_SCAN_EXTENSIONS),
        }


def get_clamav_service(
    host: str | None = None,
    port: int | None = None,
    unix_socket: str | None = None,
    timeout_connect: float | None = None,
    timeout_scan: float | None = None,
    max_concurrent_scans: int | None = None,
    scan_enabled: bool | None = None,
    db: Session | None = None,
    minio_client: Minio | None = None,
) -> ClamAVService:
    """
    Get ClamAV service instance for dependency injection with environment configuration.
    
    Args:
        host: ClamAV daemon host (overrides env var)
        port: ClamAV daemon port (overrides env var)
        unix_socket: Unix socket path (overrides env var)
        timeout_connect: Connection timeout (overrides env var)
        timeout_scan: Scan timeout (overrides env var)
        max_concurrent_scans: Max concurrent scans (overrides env var)
        scan_enabled: Whether scanning is enabled (overrides env var)
        db: Database session
        minio_client: MinIO client for streaming
        
    Returns:
        ClamAVService: Configured service instance
    """
    # Import environment configuration
    from app.core.environment import environment
    
    # Use environment variables as defaults, allow parameter overrides
    return ClamAVService(
        host=host or environment.CLAMAV_HOST,
        port=port or environment.CLAMAV_PORT,
        unix_socket=unix_socket or environment.CLAMAV_UNIX_SOCKET,
        timeout_connect=timeout_connect or environment.CLAMAV_TIMEOUT_CONNECT,
        timeout_scan=timeout_scan or environment.CLAMAV_TIMEOUT_SCAN,
        max_concurrent_scans=max_concurrent_scans or environment.CLAMAV_MAX_CONCURRENT_SCANS,
        scan_enabled=scan_enabled if scan_enabled is not None else environment.CLAMAV_SCAN_ENABLED,
        db=db,
        minio_client=minio_client,
    )


__all__ = [
    "ClamAVService",
    "ClamAVError", 
    "ClamAVScanResult",
    "get_clamav_service",
    "EICAR_TEST_STRING",
    "SCANNABLE_FILE_TYPES",
    "SCANNABLE_MIME_TYPES",
    "SKIP_SCAN_EXTENSIONS",
]