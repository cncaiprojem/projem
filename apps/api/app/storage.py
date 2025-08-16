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


