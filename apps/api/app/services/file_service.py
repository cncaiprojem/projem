"""
Ultra-Enterprise File Service for Task 5.3

Implements secure file upload/download with:
- Presigned URL generation with constraints
- SHA256 verification
- Object tagging for audit trail
- Rate limiting and security validation
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from minio import Minio
from minio.error import S3Error
from minio.helpers import PostPolicy
from sqlalchemy.orm import Session

from app.core.bucket_config import (
    BucketConfigFactory,
)
from app.core.minio_config import (
    MinIOConfig,
    get_minio_client,
    get_minio_config,
    validate_object_key,
)
from app.core.utils import convert_user_id_to_int
from app.models.file import (
    FileMetadata,
    FileStatus,
    UploadSession,
)
from app.models.file import (
    FileType as FileTypeEnum,
)
from app.schemas.file_upload import (
    PRESIGNED_GET_TTL_SECONDS,
    PRESIGNED_PUT_TTL_SECONDS,
    FileDownloadResponse,
    UploadErrorCode,
    UploadFinalizeRequest,
    UploadFinalizeResponse,
    UploadInitRequest,
    UploadInitResponse,
)
from app.services.file_validation import (
    FileValidationService,
    get_file_validation_service,
)
from app.services.sha256_service import (
    SHA256StreamingError,
    SHA256StreamingService,
    get_sha256_streaming_service,
)
from app.services.clamav_service import (
    ClamAVError,
    ClamAVService,
    get_clamav_service,
)
from app.services.artefact_service import ArtefactService
from app.schemas.artefact import ArtefactCreate, ArtefactType

logger = structlog.get_logger(__name__)


class FileServiceError(Exception):
    """Custom exception for file service operations."""

    def __init__(
        self,
        code: str,
        message: str,
        turkish_message: str | None = None,
        details: dict | None = None,
        status_code: int = 400,
    ):
        self.code = code
        self.message = message
        self.turkish_message = turkish_message or message
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)


class FileService:
    """
    Enterprise-grade file service for Task 5.3.
    
    Handles:
    - Upload initialization with presigned URLs
    - Upload finalization with verification
    - Download with presigned URLs
    - Security validation and rate limiting
    """

    def __init__(
        self,
        client: Minio | None = None,
        config: MinIOConfig | None = None,
        db: Session | None = None,
        validation_service: FileValidationService | None = None,
        sha256_service: SHA256StreamingService | None = None,
        clamav_service: ClamAVService | None = None,
    ):
        """
        Initialize file service.
        
        Args:
            client: MinIO client instance
            config: MinIO configuration
            db: Database session
            validation_service: File validation service
            sha256_service: SHA256 streaming service
            clamav_service: ClamAV malware scanning service
        """
        self.client = client or get_minio_client()
        self.config = config or get_minio_config()
        self.bucket_configs = BucketConfigFactory.from_environment()
        self.db = db
        self.validation_service = validation_service or get_file_validation_service()
        self.sha256_service = sha256_service or get_sha256_streaming_service(self.client)
        self.clamav_service = clamav_service or get_clamav_service(db=db, minio_client=self.client)

        logger.info("File service initialized with validation, SHA256 streaming, and ClamAV scanning")


    def init_upload(
        self,
        request: UploadInitRequest,
        user_id: str | None = None,
        client_ip: str | None = None,
    ) -> UploadInitResponse:
        """
        Initialize file upload with presigned URL.
        Task 5.3: POST /files/upload/init
        
        Args:
            request: Upload initialization request
            user_id: Authenticated user ID
            client_ip: Client IP for optional binding
            
        Returns:
            UploadInitResponse with presigned URL
            
        Raises:
            FileServiceError: On validation or generation failure
        """
        try:
            # Convert user_id safely to int
            user_id_int = convert_user_id_to_int(user_id)
            
            # Step 1: Validate inputs with comprehensive security checks
            self._validate_upload_request(request)

            # Step 1.5: Perform Task 5.4 validation
            validation_result = self.validation_service.validate_upload_init(
                filename=request.filename or f"upload.{request.type.value}",
                size=request.size,
                mime_type=request.mime_type,
                content=None,  # No content available at init stage
            )

            if not validation_result.is_valid:
                # Build error message from validation errors
                error_msgs = [err.get("message", "") for err in validation_result.errors]
                turkish_msgs = [err.get("turkish_message", "") for err in validation_result.errors]

                raise FileServiceError(
                    code=UploadErrorCode.UNSUPPORTED_MEDIA_TYPE if validation_result.error_code == 415
                         else UploadErrorCode.PAYLOAD_TOO_LARGE if validation_result.error_code == 413
                         else UploadErrorCode.INVALID_INPUT,
                    message="; ".join(error_msgs),
                    turkish_message="; ".join(turkish_msgs),
                    details={"validation_errors": validation_result.errors},
                    status_code=validation_result.error_code,
                )

            # Log warnings if any
            if validation_result.warnings:
                logger.warning(
                    "Upload validation warnings",
                    warnings=validation_result.warnings,
                    filename=request.filename,
                )

            # Step 2: Determine bucket based on file type
            bucket_name = self._get_bucket_for_type(request.type)
            bucket_config = self.bucket_configs.get(bucket_name)

            if not bucket_config:
                raise FileServiceError(
                    code=UploadErrorCode.INVALID_INPUT,
                    message=f"Invalid bucket configuration for type: {request.type}",
                    turkish_message=f"Geçersiz depolama yapılandırması: {request.type}",
                    status_code=400,
                )

            # Step 3: Validate against bucket constraints
            is_valid, error_msg = BucketConfigFactory.validate_presigned_constraints(
                content_length=request.size,
                content_type=request.mime_type,
                bucket_config=bucket_config,
                tags=self._build_tags(request),
            )

            if not is_valid:
                raise FileServiceError(
                    code=UploadErrorCode.INVALID_INPUT,
                    message=error_msg,
                    turkish_message=error_msg,
                    status_code=400,
                )

            # Step 4: Generate server-side key using sanitized filename
            # Use the sanitized filename from validation service for security
            if validation_result.sanitized_filename:
                safe_filename = validation_result.sanitized_filename
            else:
                # Fallback to generating safe filename
                file_ext = self._get_file_extension(request.filename, request.mime_type)
                safe_filename = f"{uuid.uuid4()}.{file_ext}"

            object_key = f"{bucket_name}/{request.job_id}/{safe_filename}"
            object_key = validate_object_key(object_key)

            # Step 5: Create upload session
            upload_id = f"upload-{uuid.uuid4()}"
            expires_at = datetime.now(UTC) + timedelta(seconds=PRESIGNED_PUT_TTL_SECONDS)

            if self.db:
                session = UploadSession(
                    upload_id=upload_id,
                    object_key=object_key,
                    expected_size=request.size,
                    expected_sha256=request.sha256,
                    mime_type=request.mime_type,
                    job_id=request.job_id,
                    user_id=user_id_int,  # Safely converted user_id
                    client_ip=client_ip,
                    status="pending",
                    expires_at=expires_at,
                    metadata={
                        "machine_id": request.machine_id,
                        "post_processor": request.post_processor,
                        "filename": request.filename,
                        "type": request.type.value,  # Store file type in metadata
                    },
                )
                self.db.add(session)
                self.db.commit()

                logger.info(
                    "Upload session created",
                    upload_id=upload_id,
                    object_key=object_key,
                    expires_at=expires_at.isoformat(),
                )

            # Step 6: Build conditions for presigned URL
            conditions = [
                ["content-length-range", 1, request.size],
                ["eq", "$Content-Type", request.mime_type],
            ]

            # Add IP binding if configured
            if client_ip and bucket_config.bucket_policy:
                if bucket_config.bucket_policy.allowed_source_ips:
                    conditions.append(["eq", "$x-amz-meta-client-ip", client_ip])

            # Step 7: Build object tags
            tags = self._build_tags(request)
            tag_string = "&".join([f"{k}={v}" for k, v in tags.items()])

            # Step 8: Generate presigned POST policy for better constraint enforcement
            post_policy = PostPolicy(
                bucket_name,
                datetime.now(UTC) + timedelta(seconds=PRESIGNED_PUT_TTL_SECONDS),
            )

            # Add key constraint
            post_policy.add_starts_with_condition("key", object_key.replace(f"{bucket_name}/", ""))

            # Add content-length constraint
            post_policy.add_content_length_range_condition(1, request.size)

            # Add content-type constraint
            post_policy.add_eq_condition("Content-Type", request.mime_type)

            # Add tagging constraint
            post_policy.add_eq_condition("x-amz-tagging", tag_string)

            # Add client IP constraint if configured
            if client_ip and bucket_config.bucket_policy:
                if bucket_config.bucket_policy.allowed_source_ips:
                    post_policy.add_eq_condition("x-amz-meta-client-ip", client_ip)

            # Generate presigned POST policy
            form_data = self.client.presigned_post_policy(post_policy)
            presigned_url = form_data.get("url", "")

            # Step 9: Extract all form fields from presigned POST policy
            """
            CRITICAL: These form fields MUST be included in the multipart/form-data upload request.
            Clients that omit any of these fields will receive a 403 Forbidden error from MinIO.
            The fields include authentication tokens, metadata, and policy constraints that are
            essential for successful upload validation.
            """
            fields = {}
            if form_data and "fields" in form_data:
                fields = form_data["fields"]
            else:
                # Fallback if fields not properly returned
                fields = {
                    "key": object_key.replace(f"{bucket_name}/", ""),
                    "Content-Type": request.mime_type,
                    "x-amz-tagging": tag_string,
                }
                if client_ip:
                    fields["x-amz-meta-client-ip"] = client_ip

            # Step 10: Build response
            response = UploadInitResponse(
                key=object_key,
                upload_url=presigned_url,
                expires_in=PRESIGNED_PUT_TTL_SECONDS,
                fields=fields,  # CRITICAL: Client must send these as form fields
                headers=None,  # Deprecated - use fields instead
                upload_id=upload_id,
                conditions={
                    "content-length-range": [1, request.size],
                    "content-type": request.mime_type,
                    "tags": tags,
                },
            )

            logger.info(
                "Upload initialized successfully",
                upload_id=upload_id,
                object_key=object_key,
                bucket=bucket_name,
                size=request.size,
                mime_type=request.mime_type,
            )

            return response

        except FileServiceError:
            raise
        except Exception as e:
            logger.error(
                "Failed to initialize upload",
                error=str(e),
                exc_info=True,
            )
            raise FileServiceError(
                code=UploadErrorCode.STORAGE_ERROR,
                message=f"Failed to initialize upload: {str(e)}",
                turkish_message=f"Yükleme başlatılamadı: {str(e)}",
                status_code=500,
            )

    def finalize_upload(
        self,
        request: UploadFinalizeRequest,
        user_id: str | None = None,
    ) -> UploadFinalizeResponse:
        """
        Finalize file upload and verify integrity.
        Task 5.3: POST /files/upload/finalize
        
        Args:
            request: Upload finalization request
            user_id: Authenticated user ID
            
        Returns:
            UploadFinalizeResponse with verification results
            
        Raises:
            FileServiceError: On verification failure
        """
        try:
            # Convert user_id safely to int
            user_id_int = convert_user_id_to_int(user_id)
            
            # Step 1: Look up upload session - REQUIRED for security validation
            if (
                not self.db
                or not isinstance(request.upload_id, str)
                or not request.upload_id.strip()
            ):
                # CRITICAL SECURITY: Upload session is required for validation
                raise FileServiceError(
                    code=UploadErrorCode.INVALID_INPUT,
                    message="Upload session ID is required for finalization",
                    turkish_message="Tamamlama için yükleme oturum kimliği gereklidir",
                    status_code=400,
                )

            session = (
                self.db.query(UploadSession)
                .filter_by(upload_id=request.upload_id)
                .first()
            )

            if not session:
                raise FileServiceError(
                    code=UploadErrorCode.NOT_FOUND,
                    message=f"Upload session not found: {request.upload_id}",
                    turkish_message=f"Yükleme oturumu bulunamadı: {request.upload_id}",
                    status_code=404,
                )

            # Task 5.5: Check if already finalized (idempotent operation)
            if session.status == "completed":
                # Already finalized - return success idempotently
                logger.info(
                    "Upload already finalized, returning cached result",
                    upload_id=request.upload_id,
                    object_key=session.object_key,
                )

                # Get the existing file metadata
                if self.db:
                    file_metadata = (
                        self.db.query(FileMetadata)
                        .filter_by(object_key=session.object_key)
                        .first()
                    )

                    if file_metadata:
                        # Return success with existing metadata
                        return UploadFinalizeResponse(
                            success=True,
                            object_key=session.object_key,
                            size=file_metadata.size,
                            sha256=file_metadata.sha256,
                            etag=file_metadata.etag,
                            version_id=file_metadata.version_id,
                            metadata={
                                "filename": file_metadata.filename,
                                "content_type": file_metadata.mime_type,
                                "idempotent_response": True,
                            },
                            created_at=file_metadata.created_at,
                        )

                # Fallback if no metadata found - this indicates an inconsistent state
                logger.critical(
                    "Inconsistent state: Upload session is completed but no file metadata found",
                    upload_id=session.upload_id,
                    object_key=session.object_key,
                )
                raise FileServiceError(
                    code=UploadErrorCode.STORAGE_ERROR,
                    message="Inconsistent upload state. Please contact support.",
                    turkish_message="Tutarsız yükleme durumu. Lütfen destek ile iletişime geçin.",
                    status_code=500,
                )

            if session.is_expired:
                raise FileServiceError(
                    code=UploadErrorCode.UPLOAD_INCOMPLETE,
                    message="Upload session expired",
                    turkish_message="Yükleme oturumu süresi doldu",
                    status_code=409,
                )

            if session.object_key != request.key:
                raise FileServiceError(
                    code=UploadErrorCode.INVALID_INPUT,
                    message="Object key mismatch",
                    turkish_message="Nesne anahtarı uyuşmazlığı",
                    status_code=400,
                )

            # Step 2: Parse bucket and object from key
            parts = request.key.split("/", 1)
            if len(parts) != 2:
                raise FileServiceError(
                    code=UploadErrorCode.INVALID_INPUT,
                    message=f"Invalid object key format: {request.key}",
                    turkish_message=f"Geçersiz nesne anahtarı formatı: {request.key}",
                    status_code=400,
                )

            bucket_name = parts[0]
            object_name = parts[1]

            # Step 3: Check if object exists
            try:
                stat = self.client.stat_object(bucket_name, object_name)
                actual_size = stat.size
                etag = stat.etag
                version_id = stat.version_id

                logger.info(
                    "Object found in storage",
                    bucket=bucket_name,
                    object=object_name,
                    size=actual_size,
                    etag=etag,
                )

            except S3Error as e:
                if e.code == "NoSuchKey":
                    raise FileServiceError(
                        code=UploadErrorCode.NOT_FOUND,
                        message=f"Object not found: {request.key}",
                        turkish_message=f"Nesne bulunamadı: {request.key}",
                        status_code=404,
                    )
                raise

            # Step 4: Verify size (session is guaranteed to exist after validation)
            if actual_size != session.expected_size:
                raise FileServiceError(
                    code=UploadErrorCode.UPLOAD_INCOMPLETE,
                    message=f"Size mismatch: expected {session.expected_size}, got {actual_size}",
                    turkish_message=f"Boyut uyuşmazlığı: beklenen {session.expected_size}, alınan {actual_size}",
                    status_code=413,
                )

            # Step 4.5: Task 5.4 - Validate at finalization stage
            finalize_validation = self.validation_service.validate_upload_finalize(
                object_key=request.key,
                actual_size=actual_size,
                expected_size=session.expected_size,
                content_sample=None,  # Will get content sample later for deep validation
            )

            if not finalize_validation.is_valid:
                # Delete the object as it failed validation
                try:
                    self.client.remove_object(bucket_name, object_name)
                    logger.warning(
                        "Object deleted due to validation failure",
                        bucket=bucket_name,
                        object=object_name,
                        errors=finalize_validation.errors,
                    )
                except S3Error as e:
                    logger.error(
                        "Failed to delete object after validation failure",
                        error=str(e),
                        bucket=bucket_name,
                        object=object_name,
                    )

                # Build error message
                error_msgs = [err.get("message", "") for err in finalize_validation.errors]
                turkish_msgs = [err.get("turkish_message", "") for err in finalize_validation.errors]

                raise FileServiceError(
                    code=UploadErrorCode.UNSUPPORTED_MEDIA_TYPE if finalize_validation.error_code == 415
                         else UploadErrorCode.PAYLOAD_TOO_LARGE if finalize_validation.error_code == 413
                         else UploadErrorCode.INVALID_INPUT,
                    message="; ".join(error_msgs),
                    turkish_message="; ".join(turkish_msgs),
                    details={"validation_errors": finalize_validation.errors},
                    status_code=finalize_validation.error_code,
                )

            # Step 5: Task 5.5 - Verify SHA256 hash using streaming service
            # This implements memory-efficient streaming with 8MB chunks
            logger.info(
                "Starting SHA256 streaming verification",
                bucket=bucket_name,
                object=object_name,
                upload_id=request.upload_id,
            )

            try:
                # Use SHA256 streaming service for memory-efficient verification
                is_hash_valid, actual_sha256, hash_metadata, first_chunk = self.sha256_service.verify_object_hash(
                    bucket_name=bucket_name,
                    object_name=object_name,
                    expected_sha256=session.expected_sha256,
                    expected_size=session.expected_size,
                )

                # Log the verification metadata
                logger.info(
                    "SHA256 verification completed",
                    is_valid=is_hash_valid,
                    expected=session.expected_sha256,
                    actual=actual_sha256,
                    bytes_processed=hash_metadata.get("bytes_processed"),
                    chunks_processed=hash_metadata.get("chunks_processed"),
                )

                # Task 5.4: Validate magic bytes with first chunk if available
                # Note: first_chunk is now returned directly from verify_object_hash to avoid redundant network call
                if first_chunk:
                    # Extract extension from object key for magic bytes validation
                    extension = self._extract_extension_from_key(object_name)
                    if extension:
                        content_validation = self.validation_service.validate_upload_finalize(
                            object_key=request.key,
                            actual_size=actual_size,
                            expected_size=session.expected_size,
                            content_sample=first_chunk,  # First chunk for magic bytes
                        )

                        if not content_validation.is_valid:
                            # Critical: Content doesn't match declared type
                            logger.error(
                                "Content validation failed after upload",
                                object_key=request.key,
                                errors=content_validation.errors,
                            )

                            # Delete the malicious/invalid file with audit
                            self.sha256_service.delete_object_with_audit(
                                bucket_name=bucket_name,
                                object_name=object_name,
                                reason="Content validation failure - magic bytes mismatch",
                                details={
                                    "object_key": request.key,
                                    "validation_errors": content_validation.errors,
                                    "upload_id": request.upload_id,
                                },
                            )

                            raise FileServiceError(
                                code=UploadErrorCode.UNSUPPORTED_MEDIA_TYPE,
                                message="File content does not match declared type",
                                turkish_message="Dosya içeriği beyan edilen türle uyuşmuyor",
                                details={"content_errors": content_validation.errors},
                                status_code=415,
                            )

                # Handle hash mismatch (Task 5.5 requirement)
                if not is_hash_valid:
                    # Delete the object with comprehensive audit logging
                    self.sha256_service.delete_object_with_audit(
                        bucket_name=bucket_name,
                        object_name=object_name,
                        reason="SHA256 hash mismatch",
                        details={
                            "expected_sha256": session.expected_sha256,
                            "actual_sha256": actual_sha256,
                            "upload_id": request.upload_id,
                            "size": actual_size,
                            **hash_metadata,
                        },
                    )

                    raise FileServiceError(
                        code=UploadErrorCode.HASH_MISMATCH,
                        message=f"SHA256 hash mismatch: expected {session.expected_sha256}, got {actual_sha256}",
                        turkish_message=f"SHA256 özet uyuşmazlığı: beklenen {session.expected_sha256}, alınan {actual_sha256}",
                        details={
                            "expected_sha256": session.expected_sha256,
                            "actual_sha256": actual_sha256,
                            "upload_id": request.upload_id,
                            **hash_metadata,
                        },
                        status_code=422,
                    )

            except SHA256StreamingError as e:
                # Handle specific streaming errors
                logger.error(
                    "SHA256 streaming verification failed",
                    error=e.message,
                    code=e.code,
                    details=e.details,
                    bucket=bucket_name,
                    object=object_name,
                )

                # Map streaming errors to appropriate upload errors
                if e.code == "NOT_FOUND":
                    raise FileServiceError(
                        code=UploadErrorCode.NOT_FOUND,
                        message=e.message,
                        turkish_message="Dosya bulunamadı",
                        details=e.details,
                        status_code=404,
                    )
                elif e.code == "TIMEOUT":
                    raise FileServiceError(
                        code=UploadErrorCode.UPLOAD_INCOMPLETE,
                        message="Verification timeout - possible slowloris attack",
                        turkish_message="Doğrulama zaman aşımı - olası güvenlik tehdidi",
                        details=e.details,
                        status_code=408,
                    )
                else:
                    raise FileServiceError(
                        code=UploadErrorCode.STORAGE_ERROR,
                        message=f"Failed to verify file integrity: {e.message}",
                        turkish_message=f"Dosya bütünlüğü doğrulanamadı: {e.message}",
                        details=e.details,
                        status_code=500,
                    )
            except FileServiceError:
                raise
            except Exception as e:
                logger.error(
                    "Unexpected error during SHA256 verification",
                    error=str(e),
                    bucket=bucket_name,
                    object=object_name,
                    exc_info=True,
                )
                raise FileServiceError(
                    code=UploadErrorCode.STORAGE_ERROR,
                    message=f"Failed to verify file integrity: {str(e)}",
                    turkish_message=f"Dosya bütünlüğü doğrulanamadı: {str(e)}",
                    status_code=500,
                )

            # Step 6: Task 5.6 - ClamAV malware scanning
            # Scan file for malware using streaming from MinIO
            logger.info(
                "Starting ClamAV malware scan",
                bucket=bucket_name,
                object=object_name,
                upload_id=request.upload_id,
            )

            try:
                # Extract file type for ClamAV policy decisions
                file_type_str = session.metadata.get("type", "temp")
                
                # Perform synchronous malware scan (converted from async)
                # Note: The clamav_service provides a synchronous interface that handles the async internally
                scan_result = self.clamav_service.scan_object_sync(
                    bucket_name=bucket_name,
                    object_name=object_name,
                    mime_type=session.mime_type,
                    file_type=file_type_str,
                    max_size_bytes=100 * 1024 * 1024,  # 100MB limit
                )

                logger.info(
                    "ClamAV scan completed",
                    is_clean=scan_result.is_clean,
                    scan_time_ms=scan_result.scan_time_ms,
                    virus_name=scan_result.virus_name,
                    object_key=request.key,
                    scan_metadata=scan_result.scan_metadata,
                )

                # Handle malware detection - delete object immediately
                if not scan_result.is_clean:
                    # Delete the infected object with comprehensive audit logging
                    self.sha256_service.delete_object_with_audit(
                        bucket_name=bucket_name,
                        object_name=object_name,
                        reason=f"Malware detected: {scan_result.virus_name}",
                        details={
                            "virus_name": scan_result.virus_name,
                            "scan_time_ms": scan_result.scan_time_ms,
                            "upload_id": request.upload_id,
                            "object_key": request.key,
                            "scan_metadata": scan_result.scan_metadata,
                        },
                    )

                    # Raise malware detection error with remediation hint
                    raise FileServiceError(
                        code="MALWARE_DETECTED",
                        message=f"Malware detected and removed: {scan_result.virus_name}. "
                                f"Please ensure your file is clean and try again. "
                                f"If you believe this is a false positive, contact support.",
                        turkish_message=f"Kötü amaçlı yazılım tespit edildi ve kaldırıldı: {scan_result.virus_name}. "
                                       f"Lütfen dosyanızın temiz olduğundan emin olun ve tekrar deneyin. "
                                       f"Bu yanlış pozitif olduğuna inanıyorsanız, destek ile iletişime geçin.",
                        details={
                            "virus_name": scan_result.virus_name,
                            "scan_time_ms": scan_result.scan_time_ms,
                            "remediation": "Scan your file with updated antivirus software before re-uploading",
                            "remediation_tr": "Tekrar yüklemeden önce dosyanızı güncel antivirüs yazılımı ile tarayın",
                        },
                        status_code=422,
                    )

            except ClamAVError as e:
                # Handle specific ClamAV errors
                logger.error(
                    "ClamAV scan failed",
                    error=e.message,
                    code=e.code,
                    details=e.details,
                    bucket=bucket_name,
                    object=object_name,
                    upload_id=request.upload_id,
                )

                # Map ClamAV errors to appropriate FileServiceError codes
                if e.code == "SCAN_UNAVAILABLE":
                    # Fail closed - scanning is required but unavailable
                    raise FileServiceError(
                        code=UploadErrorCode.STORAGE_ERROR,
                        message=e.message,
                        turkish_message=e.turkish_message,
                        details=e.details,
                        status_code=e.status_code,
                    )
                else:
                    # Other scan errors (timeouts, connection issues)
                    raise FileServiceError(
                        code=UploadErrorCode.STORAGE_ERROR,
                        message=f"Malware scan failed: {e.message}",
                        turkish_message=f"Kötü amaçlı yazılım taraması başarısız: {e.turkish_message}",
                        details=e.details,
                        status_code=e.status_code,
                    )

            except FileServiceError:
                raise
            except Exception as e:
                logger.error(
                    "Unexpected error during ClamAV scan",
                    error=str(e),
                    bucket=bucket_name,
                    object=object_name,
                    exc_info=True,
                )
                raise FileServiceError(
                    code=UploadErrorCode.STORAGE_ERROR,
                    message=f"Failed to scan file for malware: {str(e)}",
                    turkish_message=f"Dosya kötü amaçlı yazılım taraması başarısız: {str(e)}",
                    status_code=500,
                )

            # Step 7: Create file metadata record
            if self.db:
                file_metadata = FileMetadata(
                    object_key=request.key,
                    bucket=bucket_name,
                    filename=session.metadata.get("filename"),
                    file_type=self._get_file_type_enum(session.metadata.get("type", "temp")),
                    mime_type=session.mime_type,
                    size=actual_size,
                    sha256=actual_sha256,
                    etag=etag,
                    version_id=version_id,
                    status=FileStatus.COMPLETED,
                    job_id=session.job_id,
                    user_id=user_id_int,  # Safely converted user_id
                    machine_id=session.metadata.get("machine_id"),
                    post_processor=session.metadata.get("post_processor"),
                    tags=self._get_object_tags(bucket_name, object_name),
                    client_ip=session.client_ip,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    verified_at=datetime.now(UTC),
                )

                self.db.add(file_metadata)

                # Update session status (session is guaranteed to exist)
                session.status = "completed"
                session.completed_at = datetime.now(UTC)

                self.db.commit()

                logger.info(
                    "File metadata created",
                    file_id=str(file_metadata.id),
                    object_key=request.key,
                    status=FileStatus.COMPLETED.value,
                )
                
                # Task 5.7: Create artefact record with S3 tagging
                try:
                    # Determine artefact type from file type
                    artefact_type = self._map_file_type_to_artefact_type(
                        session.metadata.get("type", "temp")
                    )
                    
                    # Create artefact service
                    artefact_service = ArtefactService(self.db)
                    
                    # Prepare artefact data
                    # Get the appropriate user ID - use session user_id if available, otherwise system user
                    effective_user_id = session.user_id if session.user_id else self._get_system_user_id()
                    
                    artefact_data = ArtefactCreate(
                        job_id=session.job_id,
                        type=artefact_type,
                        s3_bucket=bucket_name,
                        s3_key=object_name,
                        size_bytes=actual_size,
                        sha256=actual_sha256,
                        mime_type=session.mime_type,
                        created_by=effective_user_id,
                        machine_id=session.metadata.get("machine_id"),
                        post_processor=session.metadata.get("post_processor"),
                        version_id=version_id,
                        meta={
                            "filename": session.metadata.get("filename"),
                            "upload_id": request.upload_id,
                            "etag": etag,
                            "clamav_clean": True,  # File passed malware scan
                            "finalized_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    
                    # Create artefact with S3 tagging and audit logging
                    # Convert async method to sync since we're in a sync context
                    # This avoids blocking the event loop with asyncio.run()
                    artefact = artefact_service.create_artefact_sync(
                        artefact_data=artefact_data,
                        user_id=effective_user_id,
                        ip_address=session.client_ip,
                        user_agent=None,  # Not available in session
                    )
                    
                    logger.info(
                        "Artefact created successfully",
                        artefact_id=artefact.id,
                        job_id=artefact.job_id,
                        type=artefact.type,
                        s3_location=artefact.s3_full_path,
                    )
                    
                except Exception as e:
                    # Log error but don't fail the upload - artefact creation is supplementary
                    # However, we should track this failure for monitoring
                    logger.error(
                        "Failed to create artefact record",
                        error=str(e),
                        object_key=request.key,
                        job_id=session.job_id,
                        exc_info=True,
                    )
                    
                    # Store the error in file metadata for debugging
                    if file_metadata:
                        file_metadata.tags = file_metadata.tags or {}
                        file_metadata.tags['artefact_creation_failed'] = str(e)
                        file_metadata.tags['artefact_creation_failed_at'] = datetime.now(UTC).isoformat()
                        self.db.commit()
                    
                    # Continue without raising - upload is still successful

            # Step 8: Get object metadata for response
            metadata = self._get_object_metadata(bucket_name, object_name)

            # Step 9: Build response
            response = UploadFinalizeResponse(
                success=True,
                object_key=request.key,
                size=actual_size,
                sha256=actual_sha256,
                etag=etag,
                version_id=version_id,
                metadata=metadata,
                created_at=datetime.now(UTC),
            )

            logger.info(
                "Upload finalized successfully",
                object_key=request.key,
                size=actual_size,
                sha256=actual_sha256,
            )

            return response

        except FileServiceError:
            raise
        except Exception as e:
            logger.error(
                "Failed to finalize upload",
                error=str(e),
                exc_info=True,
            )
            raise FileServiceError(
                code=UploadErrorCode.STORAGE_ERROR,
                message=f"Failed to finalize upload: {str(e)}",
                turkish_message=f"Yükleme tamamlanamadı: {str(e)}",
                status_code=500,
            )

    def get_download_url(
        self,
        file_id: str,
        user_id: str | None = None,
        version_id: str | None = None,
    ) -> FileDownloadResponse:
        """
        Generate presigned GET URL for file download.
        Task 5.3: GET /files/:id
        
        Args:
            file_id: File ID or object key
            user_id: Authenticated user ID for authorization
            version_id: Specific version to download
            
        Returns:
            FileDownloadResponse with presigned URL
            
        Raises:
            FileServiceError: On authorization or generation failure
        """
        try:
            # Step 1: Get file metadata
            file_metadata = None
            if self.db:
                # Try to find by UUID first
                try:
                    file_uuid = uuid.UUID(file_id)
                    file_metadata = (
                        self.db.query(FileMetadata)
                        .filter_by(id=file_uuid)
                        .first()
                    )
                except ValueError:
                    # Not a UUID, try by object key
                    file_metadata = (
                        self.db.query(FileMetadata)
                        .filter_by(object_key=file_id)
                        .first()
                    )

                if not file_metadata:
                    raise FileServiceError(
                        code=UploadErrorCode.NOT_FOUND,
                        message=f"File not found: {file_id}",
                        turkish_message=f"Dosya bulunamadı: {file_id}",
                        status_code=404,
                    )

                # Step 2: Authorize access
                if not self._authorize_file_access(file_metadata, user_id):
                    raise FileServiceError(
                        code=UploadErrorCode.FORBIDDEN,
                        message="Access denied to file",
                        turkish_message="Dosyaya erişim reddedildi",
                        status_code=403,
                    )

                object_key = file_metadata.object_key
                bucket_name = file_metadata.bucket

            else:
                # No DB, use file_id as object key
                object_key = file_id
                parts = object_key.split("/", 1)
                if len(parts) != 2:
                    raise FileServiceError(
                        code=UploadErrorCode.INVALID_INPUT,
                        message=f"Invalid object key: {object_key}",
                        turkish_message=f"Geçersiz nesne anahtarı: {object_key}",
                        status_code=400,
                    )
                bucket_name = parts[0]

            # Step 3: Parse object name from key
            object_name = object_key.replace(f"{bucket_name}/", "")

            # Step 4: Check if object exists
            try:
                stat = self.client.stat_object(bucket_name, object_name, version_id=version_id)

            except S3Error as e:
                if e.code == "NoSuchKey":
                    raise FileServiceError(
                        code=UploadErrorCode.NOT_FOUND,
                        message=f"Object not found: {object_key}",
                        turkish_message=f"Nesne bulunamadı: {object_key}",
                        status_code=404,
                    )
                raise

            # Step 5: Special handling for invoices (respect object lock)
            if bucket_name == "invoices":
                # Check if object has legal hold or retention
                try:
                    retention = self.client.get_object_retention(bucket_name, object_name, version_id)
                    if retention:
                        logger.info(
                            "Invoice has retention policy",
                            object_key=object_key,
                            retention=retention,
                        )
                except S3Error:
                    pass  # No retention

            # Step 6: Generate presigned GET URL
            presigned_url = self.client.presigned_get_object(
                bucket_name=bucket_name,
                object_name=object_name,
                expires=timedelta(seconds=PRESIGNED_GET_TTL_SECONDS),
                version_id=version_id,
            )

            # Step 7: Log audit trail
            logger.info(
                "Download URL generated",
                object_key=object_key,
                user_id=user_id,
                expires_in=PRESIGNED_GET_TTL_SECONDS,
            )

            # Step 8: Build file info
            file_info = {
                "key": object_key,
                "size": stat.size,
                "content_type": stat.content_type or "application/octet-stream",
                "last_modified": stat.last_modified.isoformat(),
                "etag": stat.etag,
                "version_id": version_id or stat.version_id,
            }

            if file_metadata:
                file_info.update({
                    "filename": file_metadata.filename,
                    "sha256": file_metadata.sha256,
                    "job_id": file_metadata.job_id,
                    "tags": file_metadata.tags or {},
                })

            # Step 9: Build response
            response = FileDownloadResponse(
                download_url=presigned_url,
                expires_in=PRESIGNED_GET_TTL_SECONDS,
                file_info=file_info,
            )

            return response

        except FileServiceError:
            raise
        except Exception as e:
            logger.error(
                "Failed to generate download URL",
                error=str(e),
                exc_info=True,
            )
            raise FileServiceError(
                code=UploadErrorCode.STORAGE_ERROR,
                message=f"Failed to generate download URL: {str(e)}",
                turkish_message=f"İndirme URL'si oluşturulamadı: {str(e)}",
                status_code=500,
            )

    # Helper methods

    def _validate_upload_request(self, request: UploadInitRequest) -> None:
        """Validate upload request against security constraints."""
        # Size validation is handled by Pydantic
        # MIME type validation is handled by Pydantic
        # SHA256 format validation is handled by Pydantic
        pass

    def _get_bucket_for_type(self, file_type: str) -> str:
        """Map file type to bucket name."""
        mapping = {
            "model": "artefacts",
            "gcode": "artefacts",
            "report": "reports",
            "invoice": "invoices",
            "log": "logs",
            "temp": "temp",
        }
        return mapping.get(file_type, "temp")

    def _get_file_type_enum(self, type_str: str) -> FileTypeEnum:
        """Convert string to FileType enum."""
        try:
            return FileTypeEnum(type_str)
        except ValueError:
            return FileTypeEnum.TEMP

    def _get_file_extension(self, filename: str | None, mime_type: str) -> str:
        """Extract or determine file extension."""
        if filename and "." in filename:
            return filename.split(".")[-1].lower()

        # Fallback based on MIME type
        mime_extensions = {
            "application/sla": "stl",
            "application/step": "step",
            "model/iges": "igs",
            "model/obj": "obj",
            "text/plain": "txt",
            "application/pdf": "pdf",
            "application/json": "json",
            "text/csv": "csv",
            "application/xml": "xml",
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/svg+xml": "svg",
            "application/zip": "zip",
            "application/gzip": "gz",
        }

        return mime_extensions.get(mime_type, "bin")

    def _build_tags(self, request: UploadInitRequest) -> dict[str, str]:
        """Build object tags for audit trail."""
        tags = {
            "job_id": request.job_id,
        }

        if request.machine_id:
            tags["machine"] = request.machine_id

        if request.post_processor:
            tags["post"] = request.post_processor

        return tags

    def _get_object_tags(self, bucket: str, object_name: str) -> dict[str, str]:
        """Get tags from S3 object."""
        try:
            tags_obj = self.client.get_object_tags(bucket, object_name)
            if tags_obj:
                return {tag.key: tag.value for tag in tags_obj}
        except S3Error:
            pass
        return {}

    def _get_object_metadata(self, bucket: str, object_name: str) -> dict[str, str]:
        """Get metadata from S3 object."""
        try:
            response = self.client.stat_object(bucket, object_name)
            metadata = dict(response.metadata) if response.metadata else {}

            # Add standard metadata
            metadata.update({
                "content_type": response.content_type,
                "size": str(response.size),
                "etag": response.etag,
                "last_modified": response.last_modified.isoformat(),
            })

            # Add tags
            tags = self._get_object_tags(bucket, object_name)
            if tags:
                metadata.update(tags)

            return metadata

        except S3Error:
            return {}

    def _extract_extension_from_key(self, object_name: str) -> str | None:
        """Extract file extension from object key."""
        if not object_name:
            return None

        # Get the base filename
        if "/" in object_name:
            object_name = object_name.split("/")[-1]

        # Extract extension
        if "." in object_name:
            ext = object_name.rsplit(".", 1)[-1]
            return f".{ext.lower()}"

        return None

    def _authorize_file_access(self, file_metadata: FileMetadata, user_id: str | None) -> bool:
        """
        Authorize user access to file.
        
        For now, simple ownership check.
        Task 5.7 will implement full RBAC.
        """
        if not user_id:
            return False

        # Owner can always access
        if file_metadata.user_id and str(file_metadata.user_id) == user_id:
            return True

        # TODO: Add role-based access control in Task 5.7
        # For now, allow access to all authenticated users
        return True
    
    def _get_system_user_id(self) -> int:
        """
        Get the system user ID from the database.
        
        Returns:
            int: System user ID
            
        Raises:
            FileServiceError: If system user not found
        """
        if not self.db:
            raise FileServiceError(
                code="NO_DB_SESSION",
                message="Database session not available",
                turkish_message="Veritabanı oturumu mevcut değil",
                status_code=500,
            )
        
        from app.models.user import User
        
        # Try to get system user by known email
        system_user = self.db.query(User).filter(
            User.email == "system@localhost"
        ).order_by(User.id.asc()).first()
        
        if not system_user:
            # Fallback: try to get the first admin user (deterministic with ORDER BY)
            system_user = self.db.query(User).filter(
                User.role == "admin"
            ).order_by(User.id.asc()).first()
        
        if not system_user:
            # Last resort: get any user deterministically (should not happen in production)
            system_user = self.db.query(User).order_by(User.id.asc()).first()
        
        if not system_user:
            raise FileServiceError(
                code="SYSTEM_USER_NOT_FOUND",
                message="System user not found in database",
                turkish_message="Sistem kullanıcısı veritabanında bulunamadı",
                status_code=500,
            )
        
        return system_user.id
    
    def _map_file_type_to_artefact_type(self, file_type: str) -> ArtefactType:
        """
        Map file service file type to artefact type.
        
        Args:
            file_type: File type string from upload
            
        Returns:
            ArtefactType enum value
        """
        # Map common file types to artefact types
        type_mapping = {
            "model": ArtefactType.MODEL,
            "gcode": ArtefactType.GCODE,
            "report": ArtefactType.REPORT,
            "invoice": ArtefactType.INVOICE,
            "log": ArtefactType.LOG,
            "simulation": ArtefactType.SIMULATION,
            "analysis": ArtefactType.ANALYSIS,
            "drawing": ArtefactType.DRAWING,
            "toolpath": ArtefactType.TOOLPATH,
            "temp": ArtefactType.OTHER,
        }
        
        return type_mapping.get(file_type.lower(), ArtefactType.OTHER)


def get_file_service(db: Session | None = None) -> FileService:
    """
    Get file service instance for dependency injection.
    
    Args:
        db: Optional database session
        
    Returns:
        FileService: Configured file service
    """
    return FileService(db=db)


__all__ = [
    "FileService",
    "FileServiceError",
    "get_file_service",
]
