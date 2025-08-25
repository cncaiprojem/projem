from __future__ import annotations

import hashlib
import mimetypes
from datetime import timedelta
from pathlib import Path
from typing import Optional

import boto3
import structlog

from .config import settings
from .services.s3 import get_s3_service

logger = structlog.get_logger(__name__)


def get_s3_client():
    """Legacy boto3 S3 client for backward compatibility."""
    session = boto3.session.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_s3_region,
    )
    return session.client("s3", endpoint_url=settings.aws_s3_endpoint)


def upload_file(path: Path, key: str, bucket: str = None) -> str:
    """
    Upload file using the new S3 service with fallback to legacy method.
    
    Args:
        path: Local file path to upload
        key: S3 object key
        bucket: Target bucket (defaults to artefacts bucket)
        
    Returns:
        str: Object key of uploaded file
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    try:
        # Use new S3 service
        s3_service = get_s3_service()
        ctype, _ = mimetypes.guess_type(str(path))
        
        return s3_service.upload_file(
            local_path=path,
            bucket=bucket,
            object_key=key,
            content_type=ctype or "application/octet-stream"
        )
    except Exception as e:
        logger.warning("New S3 service failed, falling back to legacy method", 
                      error=str(e), path=str(path), key=key)
        
        # Fallback to legacy boto3 method
        s3 = get_s3_client()
        ctype, _ = mimetypes.guess_type(str(path))
        extra = {"ContentType": ctype or "application/octet-stream"}
        s3.upload_file(str(path), bucket, key, ExtraArgs=extra)
        return key


def presigned_url(key: str, expires: int = 3600, bucket: str = None) -> Optional[str]:
    """
    Generate presigned download URL using new S3 service with fallback.
    
    Args:
        key: S3 object key
        expires: URL expiration in seconds
        bucket: Source bucket (defaults to artefacts bucket)
        
    Returns:
        Optional[str]: Presigned URL or None if failed
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    try:
        # Use new S3 service
        s3_service = get_s3_service()
        url = s3_service.generate_presigned_download_url(
            bucket=bucket,
            object_key=key,
            expiry=timedelta(seconds=expires)
        )
        return url
    except Exception as e:
        logger.warning("New S3 service failed for presigned URL, falling back to legacy method", 
                      error=str(e), key=key, bucket=bucket)
        
        try:
            # Fallback to legacy boto3 method
            s3 = get_s3_client()
            url = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires,
            )
            return url
        except Exception:
            return None


def upload_and_sign(path: Path, artefact_type: str, bucket: str = None) -> dict:
    """
    Upload file and generate signed URL for download.
    
    Args:
        path: Local file path to upload
        artefact_type: Type of artefact (e.g., 'stl', 'gcode', 'step')
        bucket: Target bucket (defaults to artefacts bucket)
        
    Returns:
        dict: Upload metadata with signed URL
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
        
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    size = path.stat().st_size
    key = f"artefacts/{path.name}"
    
    # Upload file
    upload_file(path, key, bucket)
    
    # Generate presigned URL
    url = presigned_url(key, bucket=bucket)
    
    return {
        "type": artefact_type,
        "path": str(path),
        "s3_key": key,
        "bucket": bucket,
        "size": size,
        "sha256": sha,
        "signed_url": url,
    }


def presigned_upload_url(key: str, expires: int = 3600, bucket: str = None, content_type: str = None) -> Optional[str]:
    """
    Generate presigned upload URL using new S3 service.
    
    Args:
        key: S3 object key for upload
        expires: URL expiration in seconds
        bucket: Target bucket (defaults to artefacts bucket)
        content_type: MIME type for the upload
        
    Returns:
        Optional[str]: Presigned upload URL or None if failed
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    try:
        s3_service = get_s3_service()
        url = s3_service.generate_presigned_upload_url(
            bucket=bucket,
            object_key=key,
            expiry=timedelta(seconds=expires),
            content_type=content_type
        )
        return url
    except Exception as e:
        logger.error("Failed to generate presigned upload URL", 
                    error=str(e), key=key, bucket=bucket)
        return None


def download_file(key: str, local_path: Path, bucket: str = None) -> bool:
    """
    Download file from S3 to local path using new S3 service.
    
    Args:
        key: S3 object key to download
        local_path: Local destination path
        bucket: Source bucket (defaults to artefacts bucket)
        
    Returns:
        bool: True if download successful
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    try:
        s3_service = get_s3_service()
        s3_service.download_file(bucket, key, local_path)
        return True
    except Exception as e:
        logger.error("Failed to download file", 
                    error=str(e), key=key, bucket=bucket, local_path=str(local_path))
        return False


def delete_file(key: str, bucket: str = None) -> bool:
    """
    Delete file from S3 using new S3 service.
    
    Args:
        key: S3 object key to delete
        bucket: Source bucket (defaults to artefacts bucket)
        
    Returns:
        bool: True if deletion successful
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    try:
        s3_service = get_s3_service()
        s3_service.delete_object(bucket, key)
        return True
    except Exception as e:
        logger.error("Failed to delete file", 
                    error=str(e), key=key, bucket=bucket)
        return False


def list_files(prefix: str = None, bucket: str = None) -> list:
    """
    List files in S3 bucket using new S3 service.
    
    Args:
        prefix: Object key prefix to filter by
        bucket: Source bucket (defaults to artefacts bucket)
        
    Returns:
        list: List of object information dicts
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    try:
        s3_service = get_s3_service()
        return s3_service.list_objects(bucket, prefix=prefix)
    except Exception as e:
        logger.error("Failed to list files", 
                    error=str(e), prefix=prefix, bucket=bucket)
        return []


# Create a shared thread pool executor for S3 operations
# This improves throughput for concurrent S3 checks
_s3_executor = None

def get_s3_executor():
    """Get or create the shared S3 thread pool executor."""
    global _s3_executor
    if _s3_executor is None:
        from concurrent.futures import ThreadPoolExecutor
        # Use multiple workers to allow concurrent S3 operations
        _s3_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="s3_async")
    return _s3_executor


def shutdown_s3_executor():
    """Shutdown the shared S3 thread pool executor during application shutdown."""
    global _s3_executor
    if _s3_executor:
        logger.info("Shutting down S3 thread pool executor.")
        _s3_executor.shutdown(wait=True)
        _s3_executor = None

async def object_exists_async(key: str, bucket: str = None) -> bool:
    """
    Check if object exists in S3 bucket (async version).
    
    This is an async wrapper that performs the S3 check in a thread pool
    to avoid blocking the event loop.
    
    Args:
        key: S3 object key to check
        bucket: Source bucket (defaults to artefacts bucket)
        
    Returns:
        bool: True if object exists, False otherwise
    """
    import asyncio
    
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    def _check_exists():
        try:
            s3_service = get_s3_service()
            # Try to get object metadata (head_object)
            info = s3_service.get_object_info(bucket, key)
            return info is not None
        except Exception:
            # Object doesn't exist or error occurred
            return False
    
    # Use shared thread pool for better throughput with concurrent checks
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(get_s3_executor(), _check_exists)


def object_exists(key: str, bucket: str = None) -> bool:
    """
    Check if object exists in S3 bucket (synchronous version).
    
    Note: Consider using object_exists_async for better performance in async contexts.
    
    Args:
        key: S3 object key to check
        bucket: Source bucket (defaults to artefacts bucket)
        
    Returns:
        bool: True if object exists, False otherwise
    """
    if bucket is None:
        bucket = settings.s3_bucket_name
    
    try:
        s3_service = get_s3_service()
        # Try to get object metadata (head_object)
        info = s3_service.get_object_info(bucket, key)
        return info is not None
    except Exception:
        # Object doesn't exist or error occurred
        return False


# Export singleton instance for backward compatibility
# This allows `from ..storage import s3_service` to work
class S3ServiceProxy:
    """Proxy class that delegates all calls to the actual S3Service instance."""
    
    def __getattr__(self, name):
        """Delegate all attribute access to the actual S3Service."""
        service = get_s3_service()
        return getattr(service, name)
    
    # Add async object_exists method for convenience
    async def object_exists_async(self, key: str, bucket: str = None) -> bool:
        """Async version of object_exists."""
        return await object_exists_async(key, bucket)
    
    def object_exists(self, key: str, bucket: str = None) -> bool:
        """Sync version of object_exists."""
        return object_exists(key, bucket)


# Create singleton instance
s3_service = S3ServiceProxy()


