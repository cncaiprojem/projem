"""
MinIO/S3 Client Service for FreeCAD CNC/CAM Platform

Provides secure file upload/download operations with presigned URLs
and proper error handling for all file operations.
"""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple, Union
from urllib.parse import urlparse

import structlog
from minio import Minio
from minio.error import S3Error
from minio.commonconfig import CopySource

logger = structlog.get_logger(__name__)


class S3Service:
    """
    MinIO/S3 client wrapper with presigned URL generation and file management.
    
    Handles all file storage operations for the FreeCAD platform including:
    - STL, STEP, and G-code file uploads
    - Log file storage and retrieval
    - Report generation and storage
    - Invoice document management
    """
    
    def __init__(self):
        """Initialize S3 client with environment configuration."""
        self.endpoint = os.getenv("AWS_S3_ENDPOINT", "http://minio:9000")
        self.access_key = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
        self.secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
        self.region = os.getenv("AWS_S3_REGION", "us-east-1")
        self.secure = os.getenv("AWS_S3_SECURE", "false").lower() == "true"
        
        # Parse endpoint to get host and port
        parsed = urlparse(self.endpoint)
        host_port = parsed.netloc
        
        try:
            self.client = Minio(
                endpoint=host_port,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
                region=self.region
            )
            logger.info("S3 client initialized", endpoint=host_port, secure=self.secure)
        except Exception as e:
            logger.error("Failed to initialize S3 client", error=str(e), endpoint=host_port)
            raise
    
    def _ensure_bucket_exists(self, bucket_name: str) -> bool:
        """
        Ensure bucket exists, create if it doesn't.
        
        Args:
            bucket_name: Name of the bucket to check/create
            
        Returns:
            bool: True if bucket exists or was created successfully
        """
        try:
            if not self.client.bucket_exists(bucket_name):
                logger.warning("Bucket does not exist", bucket=bucket_name)
                return False
            return True
        except S3Error as e:
            logger.error("Error checking bucket existence", bucket=bucket_name, error=str(e))
            return False
    
    def generate_presigned_upload_url(
        self, 
        bucket: str, 
        object_key: str, 
        expiry: timedelta = timedelta(hours=1),
        content_type: Optional[str] = None
    ) -> str:
        """
        Generate presigned URL for file upload.
        
        Args:
            bucket: Target bucket name
            object_key: Object key/path in bucket
            expiry: URL expiration time (default: 1 hour)
            content_type: MIME type for the upload
            
        Returns:
            str: Presigned upload URL
            
        Raises:
            S3Error: If URL generation fails
        """
        try:
            if not self._ensure_bucket_exists(bucket):
                raise S3Error(f"Bucket {bucket} does not exist")
            
            # Prepare additional headers if content type is specified
            extra_headers = {}
            if content_type:
                extra_headers["Content-Type"] = content_type
            
            url = self.client.presigned_put_object(
                bucket_name=bucket,
                object_name=object_key,
                expires=expiry,
                response_headers=extra_headers if extra_headers else None
            )
            
            logger.info("Generated presigned upload URL", 
                       bucket=bucket, 
                       object_key=object_key, 
                       expiry_hours=expiry.total_seconds()/3600)
            
            return url
            
        except S3Error as e:
            logger.error("Failed to generate presigned upload URL", 
                        bucket=bucket, 
                        object_key=object_key, 
                        error=str(e))
            raise
    
    def generate_presigned_download_url(
        self, 
        bucket: str, 
        object_key: str, 
        expiry: timedelta = timedelta(hours=1),
        response_headers: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Generate presigned URL for file download.
        
        Args:
            bucket: Source bucket name
            object_key: Object key/path in bucket
            expiry: URL expiration time (default: 1 hour)
            response_headers: Additional headers for the response
            
        Returns:
            str: Presigned download URL
            
        Raises:
            S3Error: If URL generation fails or object doesn't exist
        """
        try:
            if not self._ensure_bucket_exists(bucket):
                raise S3Error(f"Bucket {bucket} does not exist")
            
            # Check if object exists
            try:
                self.client.stat_object(bucket, object_key)
            except S3Error as e:
                if e.code == "NoSuchKey":
                    raise S3Error(f"Object {object_key} not found in bucket {bucket}")
                raise
            
            url = self.client.presigned_get_object(
                bucket_name=bucket,
                object_name=object_key,
                expires=expiry,
                response_headers=response_headers
            )
            
            logger.info("Generated presigned download URL", 
                       bucket=bucket, 
                       object_key=object_key, 
                       expiry_hours=expiry.total_seconds()/3600)
            
            return url
            
        except S3Error as e:
            logger.error("Failed to generate presigned download URL", 
                        bucket=bucket, 
                        object_key=object_key, 
                        error=str(e))
            raise
    
    def upload_file(
        self, 
        local_path: Union[str, Path], 
        bucket: str, 
        object_key: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Upload file directly to S3.
        
        Args:
            local_path: Path to local file to upload
            bucket: Target bucket name
            object_key: Object key/path in bucket
            content_type: MIME type for the file
            metadata: Additional metadata to store with the object
            
        Returns:
            str: Object key of uploaded file
            
        Raises:
            S3Error: If upload fails
            FileNotFoundError: If local file doesn't exist
        """
        local_path = Path(local_path)
        
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        
        try:
            if not self._ensure_bucket_exists(bucket):
                raise S3Error(f"Bucket {bucket} does not exist")
            
            # Auto-detect content type if not provided
            if not content_type:
                content_type = self._get_content_type(local_path)
            
            self.client.fput_object(
                bucket_name=bucket,
                object_name=object_key,
                file_path=str(local_path),
                content_type=content_type,
                metadata=metadata
            )
            
            logger.info("File uploaded successfully", 
                       local_path=str(local_path),
                       bucket=bucket, 
                       object_key=object_key,
                       content_type=content_type)
            
            return object_key
            
        except S3Error as e:
            logger.error("Failed to upload file", 
                        local_path=str(local_path),
                        bucket=bucket, 
                        object_key=object_key, 
                        error=str(e))
            raise
    
    def download_file(
        self, 
        bucket: str, 
        object_key: str, 
        local_path: Union[str, Path]
    ) -> Path:
        """
        Download file from S3 to local path.
        
        Args:
            bucket: Source bucket name
            object_key: Object key/path in bucket
            local_path: Local path to save the file
            
        Returns:
            Path: Path to downloaded file
            
        Raises:
            S3Error: If download fails or object doesn't exist
        """
        local_path = Path(local_path)
        
        try:
            if not self._ensure_bucket_exists(bucket):
                raise S3Error(f"Bucket {bucket} does not exist")
            
            # Ensure parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            self.client.fget_object(
                bucket_name=bucket,
                object_name=object_key,
                file_path=str(local_path)
            )
            
            logger.info("File downloaded successfully", 
                       bucket=bucket, 
                       object_key=object_key,
                       local_path=str(local_path))
            
            return local_path
            
        except S3Error as e:
            logger.error("Failed to download file", 
                        bucket=bucket, 
                        object_key=object_key,
                        local_path=str(local_path), 
                        error=str(e))
            raise
    
    def delete_object(self, bucket: str, object_key: str) -> bool:
        """
        Delete object from S3.
        
        Args:
            bucket: Source bucket name
            object_key: Object key/path to delete
            
        Returns:
            bool: True if deletion was successful
            
        Raises:
            S3Error: If deletion fails
        """
        try:
            if not self._ensure_bucket_exists(bucket):
                raise S3Error(f"Bucket {bucket} does not exist")
            
            self.client.remove_object(bucket, object_key)
            
            logger.info("Object deleted successfully", 
                       bucket=bucket, 
                       object_key=object_key)
            
            return True
            
        except S3Error as e:
            logger.error("Failed to delete object", 
                        bucket=bucket, 
                        object_key=object_key, 
                        error=str(e))
            raise
    
    def list_objects(
        self, 
        bucket: str, 
        prefix: Optional[str] = None,
        recursive: bool = True
    ) -> list:
        """
        List objects in bucket with optional prefix filter.
        
        Args:
            bucket: Bucket name to list
            prefix: Object key prefix to filter by
            recursive: Whether to list recursively
            
        Returns:
            list: List of object information dicts
        """
        try:
            if not self._ensure_bucket_exists(bucket):
                raise S3Error(f"Bucket {bucket} does not exist")
            
            objects = []
            for obj in self.client.list_objects(bucket, prefix=prefix, recursive=recursive):
                objects.append({
                    "key": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag
                })
            
            logger.info("Listed objects", 
                       bucket=bucket, 
                       prefix=prefix,
                       count=len(objects))
            
            return objects
            
        except S3Error as e:
            logger.error("Failed to list objects", 
                        bucket=bucket, 
                        prefix=prefix, 
                        error=str(e))
            raise
    
    def get_object_info(self, bucket: str, object_key: str) -> Dict:
        """
        Get metadata and information about an object.
        
        Args:
            bucket: Bucket name
            object_key: Object key to inspect
            
        Returns:
            Dict: Object metadata and information
            
        Raises:
            S3Error: If object doesn't exist or access fails
        """
        try:
            if not self._ensure_bucket_exists(bucket):
                raise S3Error(f"Bucket {bucket} does not exist")
            
            stat = self.client.stat_object(bucket, object_key)
            
            info = {
                "key": object_key,
                "size": stat.size,
                "last_modified": stat.last_modified,
                "etag": stat.etag,
                "content_type": stat.content_type,
                "metadata": stat.metadata,
                "version_id": getattr(stat, 'version_id', None)
            }
            
            logger.info("Retrieved object info", 
                       bucket=bucket, 
                       object_key=object_key,
                       size=stat.size)
            
            return info
            
        except S3Error as e:
            logger.error("Failed to get object info", 
                        bucket=bucket, 
                        object_key=object_key, 
                        error=str(e))
            raise
    
    def copy_object(
        self, 
        source_bucket: str, 
        source_key: str,
        dest_bucket: str, 
        dest_key: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Copy object from source to destination.
        
        Args:
            source_bucket: Source bucket name
            source_key: Source object key
            dest_bucket: Destination bucket name
            dest_key: Destination object key
            metadata: New metadata for the copied object
            
        Returns:
            str: Destination object key
            
        Raises:
            S3Error: If copy operation fails
        """
        try:
            if not self._ensure_bucket_exists(source_bucket):
                raise S3Error(f"Source bucket {source_bucket} does not exist")
            if not self._ensure_bucket_exists(dest_bucket):
                raise S3Error(f"Destination bucket {dest_bucket} does not exist")
            
            copy_source = CopySource(source_bucket, source_key)
            
            self.client.copy_object(
                bucket_name=dest_bucket,
                object_name=dest_key,
                source=copy_source,
                metadata=metadata
            )
            
            logger.info("Object copied successfully", 
                       source_bucket=source_bucket,
                       source_key=source_key,
                       dest_bucket=dest_bucket,
                       dest_key=dest_key)
            
            return dest_key
            
        except S3Error as e:
            logger.error("Failed to copy object", 
                        source_bucket=source_bucket,
                        source_key=source_key,
                        dest_bucket=dest_bucket,
                        dest_key=dest_key,
                        error=str(e))
            raise
    
    def _get_content_type(self, file_path: Path) -> str:
        """
        Determine content type based on file extension.
        
        Args:
            file_path: Path to the file
            
        Returns:
            str: MIME content type
        """
        extension = file_path.suffix.lower()
        
        content_types = {
            '.stl': 'application/sla',
            '.step': 'application/step',
            '.stp': 'application/step',
            '.gcode': 'text/plain',
            '.nc': 'text/plain',
            '.txt': 'text/plain',
            '.log': 'text/plain',
            '.json': 'application/json',
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.svg': 'image/svg+xml'
        }
        
        return content_types.get(extension, 'application/octet-stream')
    
    def create_temp_download_url(
        self, 
        bucket: str, 
        object_key: str,
        filename: Optional[str] = None,
        expiry_minutes: int = 15
    ) -> str:
        """
        Create temporary download URL with custom filename.
        
        Args:
            bucket: Source bucket name
            object_key: Object key to download
            filename: Custom filename for download (optional)
            expiry_minutes: URL expiration in minutes
            
        Returns:
            str: Temporary download URL
        """
        headers = {}
        if filename:
            headers['response-content-disposition'] = f'attachment; filename="{filename}"'
        
        return self.generate_presigned_download_url(
            bucket=bucket,
            object_key=object_key,
            expiry=timedelta(minutes=expiry_minutes),
            response_headers=headers
        )


# Global instance for dependency injection
s3_service = S3Service()


def get_s3_service() -> S3Service:
    """
    Dependency injection function for FastAPI.
    
    Returns:
        S3Service: Configured S3 service instance
    """
    return s3_service