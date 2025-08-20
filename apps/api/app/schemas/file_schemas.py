"""
File-related Pydantic schemas for MinIO/S3 operations.

Task 5.1: MinIO client configuration and credentials management
Provides validation schemas for file upload, download, and management operations.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, validator


class FileType(str, Enum):
    """Supported file types for the platform."""
    
    STL = "stl"
    STEP = "step"
    STP = "stp"
    GCODE = "gcode"
    NC = "nc"
    PDF = "pdf"
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    SVG = "svg"
    LOG = "log"
    JSON = "json"
    TXT = "txt"
    
    @classmethod
    def from_extension(cls, extension: str) -> Optional[FileType]:
        """Get FileType from file extension."""
        ext = extension.lower().lstrip(".")
        try:
            return cls(ext)
        except ValueError:
            return None
    
    def get_content_type(self) -> str:
        """Get MIME content type for the file type."""
        content_types = {
            cls.STL: "application/sla",
            cls.STEP: "application/step",
            cls.STP: "application/step",
            cls.GCODE: "text/plain",
            cls.NC: "text/plain",
            cls.PDF: "application/pdf",
            cls.PNG: "image/png",
            cls.JPG: "image/jpeg",
            cls.JPEG: "image/jpeg",
            cls.SVG: "image/svg+xml",
            cls.LOG: "text/plain",
            cls.JSON: "application/json",
            cls.TXT: "text/plain",
        }
        return content_types.get(self, "application/octet-stream")


class BucketType(str, Enum):
    """MinIO bucket types for different file categories."""
    
    ARTEFACTS = "artefacts"
    LOGS = "logs"
    REPORTS = "reports"
    INVOICES = "invoices"
    TEMP = "temp"


class FileUploadRequest(BaseModel):
    """Request schema for file upload."""
    
    filename: str = Field(..., min_length=1, max_length=255, description="Original filename")
    file_type: Optional[FileType] = Field(None, description="File type (auto-detected if not provided)")
    bucket: BucketType = Field(BucketType.ARTEFACTS, description="Target bucket")
    job_id: Optional[str] = Field(None, description="Associated job ID")
    metadata: Optional[Dict[str, str]] = Field(None, description="Additional metadata")
    
    @validator("filename")
    def validate_filename(cls, v: str) -> str:
        """Validate and sanitize filename."""
        # Remove path components and sanitize
        import os
        filename = os.path.basename(v)
        
        # Check for invalid characters
        invalid_chars = ["<", ">", ":", '"', "|", "?", "*", "\x00"]
        for char in invalid_chars:
            if char in filename:
                raise ValueError(f"İsimde geçersiz karakter: {char}")
        
        return filename
    
    class Config:
        schema_extra = {
            "example": {
                "filename": "model_v2.stl",
                "file_type": "stl",
                "bucket": "artefacts",
                "job_id": "job_123",
                "metadata": {
                    "user_id": "user_456",
                    "version": "2.0"
                }
            }
        }


class FileUploadResponse(BaseModel):
    """Response schema for successful file upload."""
    
    object_key: str = Field(..., description="Object key in MinIO")
    bucket: str = Field(..., description="Bucket name")
    size: Optional[int] = Field(None, description="File size in bytes")
    content_type: str = Field(..., description="MIME content type")
    etag: Optional[str] = Field(None, description="Entity tag for version tracking")
    upload_timestamp: datetime = Field(..., description="Upload timestamp")
    presigned_url: Optional[HttpUrl] = Field(None, description="Presigned URL for download")
    
    class Config:
        schema_extra = {
            "example": {
                "object_key": "artefacts/job_123/550e8400-e29b-41d4-a716-446655440000.stl",
                "bucket": "artefacts",
                "size": 1048576,
                "content_type": "application/sla",
                "etag": "d41d8cd98f00b204e9800998ecf8427e",
                "upload_timestamp": "2024-01-15T10:30:00Z",
                "presigned_url": "https://minio.example.com/artefacts/..."
            }
        }


class PresignedUrlRequest(BaseModel):
    """Request schema for generating presigned URLs."""
    
    bucket: str = Field(..., description="Bucket name")
    object_key: str = Field(..., description="Object key")
    operation: str = Field("download", regex="^(upload|download)$", description="Operation type")
    expires_in: int = Field(3600, ge=60, le=86400, description="URL expiration in seconds")
    response_headers: Optional[Dict[str, str]] = Field(None, description="Custom response headers")
    
    class Config:
        schema_extra = {
            "example": {
                "bucket": "artefacts",
                "object_key": "models/job_123/model.stl",
                "operation": "download",
                "expires_in": 3600,
                "response_headers": {
                    "Content-Disposition": 'attachment; filename="model.stl"'
                }
            }
        }


class PresignedUrlResponse(BaseModel):
    """Response schema for presigned URL generation."""
    
    url: HttpUrl = Field(..., description="Presigned URL")
    expires_at: datetime = Field(..., description="URL expiration time")
    operation: str = Field(..., description="Operation type (upload/download)")
    bucket: str = Field(..., description="Bucket name")
    object_key: str = Field(..., description="Object key")
    
    class Config:
        schema_extra = {
            "example": {
                "url": "https://minio.example.com/artefacts/models/job_123/model.stl?...",
                "expires_at": "2024-01-15T11:30:00Z",
                "operation": "download",
                "bucket": "artefacts",
                "object_key": "models/job_123/model.stl"
            }
        }


class FileInfo(BaseModel):
    """Schema for file information/metadata."""
    
    object_key: str = Field(..., description="Object key in MinIO")
    bucket: str = Field(..., description="Bucket name")
    filename: str = Field(..., description="Original filename")
    size: int = Field(..., description="File size in bytes")
    content_type: str = Field(..., description="MIME content type")
    last_modified: datetime = Field(..., description="Last modification time")
    etag: str = Field(..., description="Entity tag")
    metadata: Optional[Dict[str, str]] = Field(None, description="Custom metadata")
    version_id: Optional[str] = Field(None, description="Version ID if versioning enabled")
    
    class Config:
        schema_extra = {
            "example": {
                "object_key": "models/job_123/model.stl",
                "bucket": "artefacts",
                "filename": "model.stl",
                "size": 1048576,
                "content_type": "application/sla",
                "last_modified": "2024-01-15T10:30:00Z",
                "etag": "d41d8cd98f00b204e9800998ecf8427e",
                "metadata": {
                    "user_id": "user_456",
                    "job_id": "job_123"
                },
                "version_id": "v1.0.0"
            }
        }


class FileListRequest(BaseModel):
    """Request schema for listing files."""
    
    bucket: str = Field(..., description="Bucket to list")
    prefix: Optional[str] = Field(None, description="Object key prefix filter")
    max_results: int = Field(100, ge=1, le=1000, description="Maximum results to return")
    continuation_token: Optional[str] = Field(None, description="Pagination token")
    
    class Config:
        schema_extra = {
            "example": {
                "bucket": "artefacts",
                "prefix": "models/job_123/",
                "max_results": 100
            }
        }


class FileListResponse(BaseModel):
    """Response schema for file listing."""
    
    files: List[FileInfo] = Field(..., description="List of files")
    count: int = Field(..., description="Number of files returned")
    continuation_token: Optional[str] = Field(None, description="Token for next page")
    has_more: bool = Field(False, description="Whether more results available")
    
    class Config:
        schema_extra = {
            "example": {
                "files": [
                    {
                        "object_key": "models/job_123/model.stl",
                        "bucket": "artefacts",
                        "filename": "model.stl",
                        "size": 1048576,
                        "content_type": "application/sla",
                        "last_modified": "2024-01-15T10:30:00Z",
                        "etag": "d41d8cd98f00b204e9800998ecf8427e"
                    }
                ],
                "count": 1,
                "continuation_token": None,
                "has_more": False
            }
        }


class FileDeleteRequest(BaseModel):
    """Request schema for file deletion."""
    
    bucket: str = Field(..., description="Bucket name")
    object_key: str = Field(..., description="Object key to delete")
    version_id: Optional[str] = Field(None, description="Specific version to delete")
    
    class Config:
        schema_extra = {
            "example": {
                "bucket": "artefacts",
                "object_key": "models/job_123/old_model.stl"
            }
        }


class FileDeleteResponse(BaseModel):
    """Response schema for file deletion."""
    
    success: bool = Field(..., description="Whether deletion was successful")
    bucket: str = Field(..., description="Bucket name")
    object_key: str = Field(..., description="Deleted object key")
    message: str = Field(..., description="Status message")
    
    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "bucket": "artefacts",
                "object_key": "models/job_123/old_model.stl",
                "message": "Dosya başarıyla silindi"
            }
        }


class StorageError(BaseModel):
    """Schema for storage-related errors."""
    
    error_code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, any]] = Field(None, description="Additional error details")
    turkish_message: Optional[str] = Field(None, description="Turkish error message")
    
    class Config:
        schema_extra = {
            "example": {
                "error_code": "STORAGE_UNAVAILABLE",
                "message": "Storage service is currently unavailable",
                "turkish_message": "Depolama servisi şu anda kullanılamıyor",
                "details": {
                    "retry_after": 60,
                    "endpoint": "minio:9000"
                }
            }
        }


__all__ = [
    "FileType",
    "BucketType",
    "FileUploadRequest",
    "FileUploadResponse",
    "PresignedUrlRequest",
    "PresignedUrlResponse",
    "FileInfo",
    "FileListRequest",
    "FileListResponse",
    "FileDeleteRequest",
    "FileDeleteResponse",
    "StorageError",
]