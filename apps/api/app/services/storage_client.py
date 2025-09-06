"""
Enterprise-grade S3/MinIO storage client for Task 7.11.

Comprehensive object storage implementation with:
- AWS S3 and MinIO support with configurable endpoints
- Multipart upload with automatic chunking
- Versioning and retention policies
- Lifecycle rules and cost optimization
- Turkish localization for error messages
- Security and compliance features
"""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import boto3
import structlog
from boto3.s3.transfer import TransferConfig
from botocore.client import Config
from botocore.exceptions import ClientError, NoCredentialsError
from minio import Minio
from minio.commonconfig import ENABLED, Filter, Tags
from minio.datatypes import Object as MinioObject
from minio.deleteobjects import DeleteObject
from minio.error import S3Error
from minio.lifecycleconfig import (
    Expiration,
    LifecycleConfig,
    NoncurrentVersionExpiration,
    NoncurrentVersionTransition,
    Rule as LifecycleRule,
    Transition,
)
from minio.versioningconfig import VersioningConfig

logger = structlog.get_logger(__name__)

# Content-Type mappings per Task 7.11
CONTENT_TYPE_MAPPINGS = {
    ".fcstd": "application/zip",
    ".step": "model/step",
    ".stp": "model/step",
    ".stl": "model/stl",
    ".glb": "model/gltf-binary",
    ".nc": "text/plain; charset=utf-8",
    ".tap": "text/plain; charset=utf-8",
    ".gcode": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".zip": "application/zip",
}

# Content-Disposition settings
INLINE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".mp4", ".pdf", ".txt", ".json"}
ATTACHMENT_EXTENSIONS = {
    ".fcstd",
    ".step",
    ".stp",
    ".stl",
    ".glb",
    ".nc",
    ".tap",
    ".gcode",
    ".zip",
}


class StorageClientError(Exception):
    """Custom exception for storage operations."""

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


class StorageClient:
    """
    Enterprise-grade S3/MinIO storage client for Task 7.11.
    
    Features:
    - Configurable endpoint support (AWS S3 or MinIO)
    - Multipart upload with automatic chunking
    - Versioning and retention management
    - Lifecycle policies for cost optimization
    - Comprehensive error handling with Turkish localization
    - Security features including SSE-S3 encryption
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
        secure: bool = True,
        use_minio: bool = False,
        connect_timeout: int = 5,
        read_timeout: int = 60,
        max_retries: int = 3,
    ):
        """
        Initialize storage client.
        
        Args:
            endpoint: S3/MinIO endpoint URL
            access_key: AWS/MinIO access key
            secret_key: AWS/MinIO secret key
            region: AWS region or MinIO region
            secure: Use HTTPS/TLS
            use_minio: Use MinIO client instead of boto3
            connect_timeout: Connection timeout in seconds
            read_timeout: Read timeout in seconds
            max_retries: Maximum retry attempts
        """
        # Load from environment if not provided
        self.endpoint = endpoint or os.getenv("AWS_S3_ENDPOINT", "http://minio:9000")
        self.access_key = access_key or os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
        self.secret_key = secret_key or os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
        self.region = region or os.getenv("AWS_S3_REGION", "us-east-1")
        self.secure = secure
        self.use_minio = use_minio or "minio" in self.endpoint.lower()

        # Timeouts and retries
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries

        # Multipart upload configuration
        self.multipart_threshold = 32 * 1024 * 1024  # 32 MiB
        self.multipart_chunksize = 16 * 1024 * 1024  # 16 MiB
        self.max_concurrency = 8  # Parallel upload threads

        # Initialize client
        if self.use_minio:
            self._init_minio_client()
        else:
            self._init_boto3_client()

        logger.info(
            "Storage client initialized",
            endpoint=self.endpoint,
            region=self.region,
            use_minio=self.use_minio,
            secure=self.secure,
        )

    def _init_minio_client(self):
        """Initialize MinIO client."""
        try:
            parsed = urlparse(self.endpoint)
            self.minio_client = Minio(
                endpoint=parsed.netloc,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
                region=self.region,
            )
        except Exception as e:
            logger.error("Failed to initialize MinIO client", error=str(e))
            raise StorageClientError(
                code="MINIO_INIT_ERROR",
                message=f"Failed to initialize MinIO client: {str(e)}",
                turkish_message=f"MinIO istemcisi başlatılamadı: {str(e)}",
            )

    def _init_boto3_client(self):
        """Initialize boto3 S3 client."""
        try:
            config = Config(
                region_name=self.region,
                signature_version="s3v4",
                retries={"max_attempts": self.max_retries, "mode": "adaptive"},
                s3={"addressing_style": "path" if self.use_minio else "auto"},
                connect_timeout=self.connect_timeout,
                read_timeout=self.read_timeout,
            )

            # Parse endpoint for boto3
            endpoint_url = self.endpoint if self.endpoint != "s3.amazonaws.com" else None

            self.s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=config,
            )

            self.transfer_config = TransferConfig(
                multipart_threshold=self.multipart_threshold,
                multipart_chunksize=self.multipart_chunksize,
                max_concurrency=self.max_concurrency,
                use_threads=True,
            )
        except Exception as e:
            logger.error("Failed to initialize boto3 client", error=str(e))
            raise StorageClientError(
                code="BOTO3_INIT_ERROR",
                message=f"Failed to initialize S3 client: {str(e)}",
                turkish_message=f"S3 istemcisi başlatılamadı: {str(e)}",
            )

    def enable_bucket_versioning(self, bucket: str) -> bool:
        """
        Enable versioning on a bucket.
        
        Args:
            bucket: Bucket name
            
        Returns:
            True if successful
            
        Raises:
            StorageClientError: If operation fails
        """
        try:
            if self.use_minio:
                config = VersioningConfig(ENABLED)
                self.minio_client.set_bucket_versioning(bucket, config)
            else:
                self.s3_client.put_bucket_versioning(
                    Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
                )

            logger.info("Bucket versioning enabled", bucket=bucket)
            return True

        except (S3Error, ClientError) as e:
            logger.error("Failed to enable versioning", bucket=bucket, error=str(e))
            raise StorageClientError(
                code="VERSIONING_ERROR",
                message=f"Failed to enable versioning: {str(e)}",
                turkish_message=f"Sürümleme etkinleştirilemedi: {str(e)}",
            )

    def setup_lifecycle_rules(self, bucket: str) -> bool:
        """
        Setup lifecycle rules for cost optimization per Task 7.11.
        
        Rules:
        - Abort incomplete multipart uploads after 7 days
        - Transition noncurrent versions to STANDARD_IA after 30 days
        - Expire noncurrent versions after 180 days
        - Expire transient artefacts after 90 days
        
        Args:
            bucket: Bucket name
            
        Returns:
            True if successful
        """
        try:
            if self.use_minio:
                # MinIO lifecycle configuration
                config = LifecycleConfig(
                    [
                        # Abort incomplete multipart uploads
                        LifecycleRule(
                            rule_id="abort-incomplete-multipart",
                            status=ENABLED,
                            abort_incomplete_multipart_upload_days=7,
                        ),
                        # Expire old noncurrent versions
                        LifecycleRule(
                            rule_id="expire-noncurrent-versions",
                            status=ENABLED,
                            noncurrent_version_expiration=NoncurrentVersionExpiration(
                                noncurrent_days=180
                            ),
                        ),
                        # Expire transient files (previews, temp)
                        LifecycleRule(
                            rule_id="expire-transient",
                            status=ENABLED,
                            rule_filter=Filter(prefix="transient/"),
                            expiration=Expiration(days=90),
                        ),
                    ]
                )
                self.minio_client.set_bucket_lifecycle(bucket, config)

            else:
                # AWS S3 lifecycle configuration
                lifecycle_config = {
                    "Rules": [
                        {
                            "ID": "abort-incomplete-multipart",
                            "Status": "Enabled",
                            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
                        },
                        {
                            "ID": "transition-noncurrent",
                            "Status": "Enabled",
                            "NoncurrentVersionTransitions": [
                                {"NoncurrentDays": 30, "StorageClass": "STANDARD_IA"}
                            ],
                            "NoncurrentVersionExpiration": {"NoncurrentDays": 180},
                        },
                        {
                            "ID": "expire-transient",
                            "Status": "Enabled",
                            "Filter": {"Prefix": "transient/"},
                            "Expiration": {"Days": 90},
                        },
                    ]
                }
                self.s3_client.put_bucket_lifecycle_configuration(
                    Bucket=bucket, LifecycleConfiguration=lifecycle_config
                )

            logger.info("Lifecycle rules configured", bucket=bucket)
            return True

        except (S3Error, ClientError) as e:
            logger.error("Failed to setup lifecycle rules", bucket=bucket, error=str(e))
            # Not critical, log but don't fail
            return False

    def detect_content_type(self, file_path: str) -> tuple[str, str]:
        """
        Detect content type and disposition for a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Tuple of (content_type, content_disposition)
        """
        ext = Path(file_path).suffix.lower()

        # Get content type from mapping or mimetypes
        content_type = CONTENT_TYPE_MAPPINGS.get(ext)
        if not content_type:
            content_type, _ = mimetypes.guess_type(file_path)
            content_type = content_type or "application/octet-stream"

        # Determine disposition
        filename = Path(file_path).name
        if ext in INLINE_EXTENSIONS:
            disposition = f'inline; filename="{filename}"'
        else:
            disposition = f'attachment; filename="{filename}"'

        return content_type, disposition

    def compute_sha256(self, file_obj: BinaryIO) -> str:
        """
        Compute SHA256 hash of file.
        
        Args:
            file_obj: File-like object
            
        Returns:
            SHA256 hex digest
        """
        sha256 = hashlib.sha256()
        file_obj.seek(0)

        for chunk in iter(lambda: file_obj.read(8192), b""):
            sha256.update(chunk)

        file_obj.seek(0)  # Reset for reading
        return sha256.hexdigest()

    def upload_file(
        self,
        file_path: str | Path | BinaryIO,
        bucket: str,
        key: str,
        metadata: dict | None = None,
        tags: dict | None = None,
        content_type: str | None = None,
        content_disposition: str | None = None,
        storage_class: str = "STANDARD",
        server_side_encryption: str = "AES256",
        compute_hash: bool = True,
    ) -> dict:
        """
        Upload file to S3/MinIO with comprehensive metadata.
        
        Args:
            file_path: Path to file or file-like object
            bucket: Target bucket
            key: Object key
            metadata: Custom metadata
            tags: Object tags
            content_type: Override content type
            content_disposition: Override disposition
            storage_class: Storage class
            server_side_encryption: SSE method
            compute_hash: Compute SHA256 hash
            
        Returns:
            Dict with upload details including version_id, etag, sha256, request_id
        """
        try:
            # Handle file path or file object
            if isinstance(file_path, (str, Path)):
                file_path = Path(file_path)
                if not file_path.exists():
                    raise StorageClientError(
                        code="FILE_NOT_FOUND",
                        message=f"File not found: {file_path}",
                        turkish_message=f"Dosya bulunamadı: {file_path}",
                        status_code=404,
                    )

                # Auto-detect content type if not provided
                if not content_type or not content_disposition:
                    auto_type, auto_disp = self.detect_content_type(str(file_path))
                    content_type = content_type or auto_type
                    content_disposition = content_disposition or auto_disp

                with open(file_path, "rb") as f:
                    file_size = file_path.stat().st_size
                    sha256 = self.compute_sha256(f) if compute_hash else None
                    return self._upload_file_object(
                        f,
                        bucket,
                        key,
                        file_size,
                        metadata,
                        tags,
                        content_type,
                        content_disposition,
                        storage_class,
                        server_side_encryption,
                        sha256,
                    )
            else:
                # File-like object
                file_path.seek(0, 2)  # Seek to end
                file_size = file_path.tell()
                file_path.seek(0)  # Reset

                sha256 = self.compute_sha256(file_path) if compute_hash else None
                return self._upload_file_object(
                    file_path,
                    bucket,
                    key,
                    file_size,
                    metadata,
                    tags,
                    content_type or "application/octet-stream",
                    content_disposition or "attachment",
                    storage_class,
                    server_side_encryption,
                    sha256,
                )

        except StorageClientError:
            raise
        except Exception as e:
            logger.error("Upload failed", bucket=bucket, key=key, error=str(e))
            raise StorageClientError(
                code="UPLOAD_ERROR",
                message=f"Upload failed: {str(e)}",
                turkish_message=f"Yükleme başarısız: {str(e)}",
            )

    def _upload_file_object(
        self,
        file_obj: BinaryIO,
        bucket: str,
        key: str,
        file_size: int,
        metadata: dict | None,
        tags: dict | None,
        content_type: str,
        content_disposition: str,
        storage_class: str,
        server_side_encryption: str,
        sha256: str | None,
    ) -> dict:
        """Internal method to upload file object."""
        # Prepare metadata
        full_metadata = metadata or {}
        if sha256:
            full_metadata["x-amz-meta-sha256"] = sha256

        # Prepare extra args
        extra_args = {
            "ContentType": content_type,
            "ContentDisposition": content_disposition,
            "StorageClass": storage_class,
            "Metadata": full_metadata,
        }

        if server_side_encryption:
            extra_args["ServerSideEncryption"] = server_side_encryption

        # Add tags if provided
        if tags:
            tag_string = "&".join([f"{k}={v}" for k, v in tags.items()])
            extra_args["Tagging"] = tag_string

        # Track request for retry logic
        attempt = 0
        last_error = None

        while attempt < self.max_retries:
            try:
                if self.use_minio:
                    # MinIO upload
                    result = self.minio_client.put_object(
                        bucket_name=bucket,
                        object_name=key,
                        data=file_obj,
                        length=file_size,
                        content_type=content_type,
                        metadata=full_metadata,
                        tags=Tags(for_object=True) if tags else None,
                    )

                    return {
                        "version_id": result.version_id,
                        "etag": result.etag,
                        "sha256": sha256,
                        "size_bytes": file_size,
                        "content_type": content_type,
                        "storage_class": storage_class,
                    }

                else:
                    # Boto3 upload with multipart support
                    response = self.s3_client.upload_fileobj(
                        Fileobj=file_obj,
                        Bucket=bucket,
                        Key=key,
                        ExtraArgs=extra_args,
                        Config=self.transfer_config,
                    )

                    # Get object metadata for version ID
                    head_response = self.s3_client.head_object(Bucket=bucket, Key=key)

                    return {
                        "version_id": head_response.get("VersionId"),
                        "etag": head_response.get("ETag", "").strip('"'),
                        "sha256": sha256,
                        "size_bytes": file_size,
                        "content_type": content_type,
                        "storage_class": storage_class,
                        "request_id": head_response.get("ResponseMetadata", {}).get(
                            "RequestId"
                        ),
                    }

            except (S3Error, ClientError) as e:
                attempt += 1
                last_error = e
                if attempt < self.max_retries:
                    wait_time = (2**attempt) + (time.time() % 1)  # Exponential backoff with jitter
                    logger.warning(
                        f"Upload attempt {attempt} failed, retrying",
                        bucket=bucket,
                        key=key,
                        error=str(e),
                        wait_time=wait_time,
                    )
                    time.sleep(wait_time)

        # All retries exhausted
        raise StorageClientError(
            code="UPLOAD_FAILED",
            message=f"Upload failed after {self.max_retries} attempts: {str(last_error)}",
            turkish_message=f"Yükleme {self.max_retries} denemeden sonra başarısız: {str(last_error)}",
        )

    def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        version_id: str | None = None,
        operation: str = "get_object",
        expires_in: int = 900,  # 15 minutes default
        response_content_type: str | None = None,
        response_content_disposition: str | None = None,
    ) -> str:
        """
        Generate presigned URL for object access.
        
        Args:
            bucket: Bucket name
            key: Object key
            version_id: Specific version ID
            operation: Operation (get_object, head_object, etc.)
            expires_in: URL expiration in seconds (max 86400 = 24 hours)
            response_content_type: Override content type in response
            response_content_disposition: Override disposition in response
            
        Returns:
            Presigned URL
        """
        try:
            # Validate expiration time
            if expires_in < 1 or expires_in > 86400:
                expires_in = min(max(expires_in, 1), 86400)

            if self.use_minio:
                # MinIO presigned URL
                if operation == "head_object":
                    method = "HEAD"
                else:
                    method = "GET"

                url = self.minio_client.presigned_get_object(
                    bucket_name=bucket,
                    object_name=key,
                    expires=timedelta(seconds=expires_in),
                    version_id=version_id,
                    response_headers={
                        "response-content-type": response_content_type,
                        "response-content-disposition": response_content_disposition,
                    }
                    if response_content_type or response_content_disposition
                    else None,
                )
            else:
                # Boto3 presigned URL
                params = {"Bucket": bucket, "Key": key}
                if version_id:
                    params["VersionId"] = version_id

                if response_content_type:
                    params["ResponseContentType"] = response_content_type
                if response_content_disposition:
                    params["ResponseContentDisposition"] = response_content_disposition

                url = self.s3_client.generate_presigned_url(
                    ClientMethod=operation, Params=params, ExpiresIn=expires_in
                )

            logger.info(
                "Presigned URL generated",
                bucket=bucket,
                key=key,
                version_id=version_id,
                expires_in=expires_in,
            )
            return url

        except Exception as e:
            logger.error("Failed to generate presigned URL", error=str(e))
            raise StorageClientError(
                code="PRESIGN_ERROR",
                message=f"Failed to generate presigned URL: {str(e)}",
                turkish_message=f"İmzalı URL oluşturulamadı: {str(e)}",
            )

    def delete_object(
        self, bucket: str, key: str, version_id: str | None = None
    ) -> bool:
        """
        Delete an object or specific version.
        
        Args:
            bucket: Bucket name
            key: Object key
            version_id: Specific version to delete
            
        Returns:
            True if successful
        """
        try:
            if self.use_minio:
                self.minio_client.remove_object(
                    bucket_name=bucket, object_name=key, version_id=version_id
                )
            else:
                params = {"Bucket": bucket, "Key": key}
                if version_id:
                    params["VersionId"] = version_id
                self.s3_client.delete_object(**params)

            logger.info(
                "Object deleted", bucket=bucket, key=key, version_id=version_id
            )
            return True

        except (S3Error, ClientError) as e:
            # Check if object doesn't exist (not an error for idempotency)
            error_code = str(e)
            if "NoSuchKey" in error_code or "404" in error_code:
                logger.info("Object already deleted", bucket=bucket, key=key)
                return True

            logger.error(
                "Failed to delete object",
                bucket=bucket,
                key=key,
                version_id=version_id,
                error=str(e),
            )
            raise StorageClientError(
                code="DELETE_ERROR",
                message=f"Failed to delete object: {str(e)}",
                turkish_message=f"Nesne silinemedi: {str(e)}",
            )

    def _process_batch_delete_errors(
        self, errors, bucket: str, batch_size: int
    ) -> int:
        """
        Process errors from batch delete operations.
        
        Args:
            errors: Iterator of deletion errors from MinIO client
            bucket: Bucket name for logging context
            batch_size: Number of objects in the batch
            
        Returns:
            Number of objects successfully deleted (0 if any errors occurred)
        """
        error_count = 0
        for error in errors:
            error_count += 1
            logger.warning(
                "Failed to delete object in batch",
                bucket=bucket,
                key=error.object_name,
                error=error.error_message,
            )
        
        # Only count as deleted if there were no errors
        return batch_size if error_count == 0 else 0

    def delete_all_versions(self, bucket: str, prefix: str) -> int:
        """
        Delete all versions of objects with given prefix using bulk operations.
        
        Args:
            bucket: Bucket name
            prefix: Object key prefix
            
        Returns:
            Number of objects deleted
        """
        deleted_count = 0

        try:
            if self.use_minio:
                # Collect all objects to delete in batches
                objects_to_delete = []
                objects = self.minio_client.list_objects(
                    bucket_name=bucket, prefix=prefix, include_version=True
                )

                for obj in objects:
                    objects_to_delete.append(
                        DeleteObject(obj.object_name, obj.version_id)
                    )
                    
                    # Process in batches of 1000 (MinIO limit)
                    if len(objects_to_delete) >= 1000:
                        errors = self.minio_client.remove_objects(
                            bucket_name=bucket,
                            delete_object_list=objects_to_delete,
                        )
                        
                        # Process batch deletion errors using helper method
                        deleted_count += self._process_batch_delete_errors(
                            errors, bucket, len(objects_to_delete)
                        )
                        
                        objects_to_delete = []
                
                # Delete remaining objects
                if objects_to_delete:
                    errors = self.minio_client.remove_objects(
                        bucket_name=bucket,
                        delete_object_list=objects_to_delete,
                    )
                    
                    # Process batch deletion errors using helper method
                    deleted_count += self._process_batch_delete_errors(
                        errors, bucket, len(objects_to_delete)
                    )

            else:
                # Use boto3 batch delete operations
                paginator = self.s3_client.get_paginator("list_object_versions")
                pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

                for page in pages:
                    delete_list = []
                    
                    # Collect versions to delete
                    for version in page.get("Versions", []):
                        delete_list.append({
                            "Key": version["Key"],
                            "VersionId": version["VersionId"]
                        })
                    
                    # Collect delete markers
                    for marker in page.get("DeleteMarkers", []):
                        delete_list.append({
                            "Key": marker["Key"],
                            "VersionId": marker["VersionId"]
                        })
                    
                    # Batch delete (S3 limit is 1000 objects per request)
                    if delete_list:
                        # Split into chunks of 1000 if necessary
                        for i in range(0, len(delete_list), 1000):
                            batch = delete_list[i:i+1000]
                            
                            try:
                                response = self.s3_client.delete_objects(
                                    Bucket=bucket,
                                    Delete={
                                        "Objects": batch,
                                        "Quiet": False
                                    }
                                )
                                
                                # Count successful deletions
                                deleted_count += len(response.get("Deleted", []))
                                
                                # Log any errors
                                for error in response.get("Errors", []):
                                    logger.warning(
                                        "Failed to delete object in batch",
                                        bucket=bucket,
                                        key=error.get("Key"),
                                        version_id=error.get("VersionId"),
                                        error=error.get("Message"),
                                    )
                                    
                            except ClientError as e:
                                logger.error(
                                    "Batch delete operation failed",
                                    bucket=bucket,
                                    batch_size=len(batch),
                                    error=str(e),
                                )

            logger.info(
                "All versions deleted",
                bucket=bucket,
                prefix=prefix,
                deleted_count=deleted_count,
            )
            return deleted_count

        except Exception as e:
            logger.error(
                "Failed to delete all versions",
                bucket=bucket,
                prefix=prefix,
                error=str(e),
            )
            raise StorageClientError(
                code="BULK_DELETE_ERROR",
                message=f"Failed to delete all versions: {str(e)}",
                turkish_message=f"Tüm sürümler silinemedi: {str(e)}",
            )

    def set_bucket_policy_private(self, bucket: str) -> bool:
        """
        Set bucket policy to block all public access.
        
        Args:
            bucket: Bucket name
            
        Returns:
            True if successful
        """
        try:
            if self.use_minio:
                # MinIO: Set a simple policy that denies all anonymous access
                # MinIO doesn't support AWS-specific IAM conditions like aws:userid
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": [
                                "s3:GetObject",
                                "s3:ListBucket",
                                "s3:GetBucketLocation",
                                "s3:GetObjectVersion",
                                "s3:PutObject",
                                "s3:DeleteObject"
                            ],
                            "Resource": [
                                f"arn:aws:s3:::{bucket}/*",
                                f"arn:aws:s3:::{bucket}"
                            ]
                        }
                    ]
                }
                
                # Validate that we have a proper policy before applying
                if policy and policy.get("Statement"):
                    self.minio_client.set_bucket_policy(bucket, json.dumps(policy))
                else:
                    logger.warning(
                        "Invalid bucket policy structure, skipping policy application",
                        bucket=bucket
                    )
                    return False

            else:
                # AWS S3 public access block
                self.s3_client.put_public_access_block(
                    Bucket=bucket,
                    PublicAccessBlockConfiguration={
                        "BlockPublicAcls": True,
                        "IgnorePublicAcls": True,
                        "BlockPublicPolicy": True,
                        "RestrictPublicBuckets": True,
                    },
                )

            logger.info("Bucket policy set to private", bucket=bucket)
            return True

        except Exception as e:
            logger.error("Failed to set bucket policy", bucket=bucket, error=str(e))
            # Not critical, continue
            return False


# Export main classes
__all__ = ["StorageClient", "StorageClientError", "CONTENT_TYPE_MAPPINGS"]