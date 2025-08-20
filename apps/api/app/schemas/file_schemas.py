"""
File-related Pydantic schemas for MinIO/S3 operations.

Task 5.1: MinIO client configuration and credentials management
Provides validation schemas for file upload, download, and management operations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Final, Union

import structlog
from pydantic import BaseModel, Field, HttpUrl, validator, root_validator, constr

logger = structlog.get_logger(__name__)


# File size limits
MAX_UPLOAD_SIZE: Final[int] = 5 * 1024 * 1024 * 1024  # 5GB
MAX_FILENAME_LENGTH: Final[int] = 255
MAX_METADATA_SIZE: Final[int] = 2048  # 2KB for metadata

class FileType(str, Enum):
    """Supported file types for the platform with categorization."""
    
    # 3D Model formats
    STL = "stl"
    STEP = "step"
    STP = "stp"
    IGES = "iges"
    IGS = "igs"
    OBJ = "obj"
    
    # CNC/CAM formats
    GCODE = "gcode"
    NC = "nc"
    TAP = "tap"
    
    # Document formats
    PDF = "pdf"
    DOC = "doc"
    DOCX = "docx"
    
    # Image formats
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    SVG = "svg"
    BMP = "bmp"
    
    # Data formats
    LOG = "log"
    JSON = "json"
    XML = "xml"
    CSV = "csv"
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
            # 3D Model formats
            self.STL: "application/sla",
            self.STEP: "application/step",
            self.STP: "application/step",
            self.IGES: "model/iges",
            self.IGS: "model/iges",
            self.OBJ: "model/obj",
            
            # CNC/CAM formats
            self.GCODE: "text/plain",
            self.NC: "text/plain",
            self.TAP: "text/plain",
            
            # Document formats
            self.PDF: "application/pdf",
            self.DOC: "application/msword",
            self.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            
            # Image formats
            self.PNG: "image/png",
            self.JPG: "image/jpeg",
            self.JPEG: "image/jpeg",
            self.SVG: "image/svg+xml",
            self.BMP: "image/bmp",
            
            # Data formats
            self.LOG: "text/plain",
            self.JSON: "application/json",
            self.XML: "application/xml",
            self.CSV: "text/csv",
            self.TXT: "text/plain",
        }
        return content_types.get(self, "application/octet-stream")
    
    @classmethod
    def is_3d_model(cls, file_type: 'FileType') -> bool:
        """Check if file type is a 3D model format."""
        return file_type in [cls.STL, cls.STEP, cls.STP, cls.IGES, cls.IGS, cls.OBJ]
    
    @classmethod
    def is_cnc_format(cls, file_type: 'FileType') -> bool:
        """Check if file type is a CNC/CAM format."""
        return file_type in [cls.GCODE, cls.NC, cls.TAP]
    
    @classmethod
    def is_image(cls, file_type: 'FileType') -> bool:
        """Check if file type is an image format."""
        return file_type in [cls.PNG, cls.JPG, cls.JPEG, cls.SVG, cls.BMP]


class BucketType(str, Enum):
    """MinIO bucket types for different file categories."""
    
    ARTEFACTS = "artefacts"
    LOGS = "logs"
    REPORTS = "reports"
    INVOICES = "invoices"
    TEMP = "temp"


class FileUploadRequest(BaseModel):
    """Request schema for file upload with enhanced validation."""
    
    filename: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FILENAME_LENGTH,
        description="Original filename",
        example="model_v2.stl"
    )
    file_type: Optional[FileType] = Field(
        None,
        description="File type (auto-detected if not provided)"
    )
    bucket: BucketType = Field(
        BucketType.ARTEFACTS,
        description="Target bucket for storage"
    )
    job_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        regex="^[a-zA-Z0-9_-]+$",
        description="Associated job ID"
    )
    metadata: Optional[Dict[str, str]] = Field(
        None,
        description="Additional metadata (max 2KB total)"
    )
    file_size: Optional[int] = Field(
        None,
        gt=0,
        le=MAX_UPLOAD_SIZE,
        description="File size in bytes for validation"
    )
    
    @validator("filename")
    def validate_filename(cls, v: str) -> str:
        """Validate and sanitize filename with security checks."""
        import os
        import re
        import unicodedata
        
        # Remove path components and sanitize
        filename = os.path.basename(v).strip()
        
        # Check for empty filename
        if not filename:
            raise ValueError("Dosya adı boş olamaz")
        
        # Normalize Unicode characters (NFC normalization)
        filename = unicodedata.normalize('NFC', filename)
        
        # Check for invalid characters
        invalid_chars = ["<", ">", ":", '"', "|", "?", "*", "\x00", "/", "\\"]
        for char in invalid_chars:
            if char in filename:
                raise ValueError(f"İsimde geçersiz karakter: {char}")
        
        # Check for control characters
        for char in filename:
            if ord(char) < 32:
                raise ValueError(f"Dosya adında kontrol karakteri: {repr(char)}")
        
        # Check for reserved names (Windows)
        reserved_names = [
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
        ]
        name_without_ext = filename.split('.')[0].upper()
        if name_without_ext in reserved_names:
            raise ValueError(f"Rezerve edilmiş dosya adı: {filename}")
        
        # Ensure filename has an extension
        if '.' not in filename:
            raise ValueError("Dosya uzantısı gerekli")
        
        # Check for double extensions that might bypass security
        parts = filename.split('.')
        if len(parts) > 2:
            # Check for suspicious double extensions like .php.jpg
            suspicious_extensions = ['php', 'asp', 'aspx', 'jsp', 'cgi', 'exe', 'bat', 'cmd', 'sh']
            for ext in parts[:-1]:
                if ext.lower() in suspicious_extensions:
                    raise ValueError(f"Güvenlik riski: şüpheli çift uzantı {filename}")
        
        return filename
    
    @validator("metadata")
    def validate_metadata(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Validate metadata size and content."""
        if v is None:
            return v
            
        # Check total size
        import json
        metadata_str = json.dumps(v)
        if len(metadata_str) > MAX_METADATA_SIZE:
            raise ValueError(
                f"Metadata çok büyük: {len(metadata_str)} bytes (max: {MAX_METADATA_SIZE})"
            )
        
        # Sanitize values
        sanitized = {}
        for key, value in v.items():
            # Limit key length
            if len(key) > 50:
                raise ValueError(f"Metadata anahtarı çok uzun: {key}")
            
            # Limit value length
            if len(value) > 500:
                value = value[:500]
            
            # Remove control characters
            value = ''.join(char for char in value if ord(char) >= 32 or char == '\n')
            sanitized[key] = value
        
        return sanitized
    
    @root_validator
    def validate_file_type_consistency(cls, values):
        """Ensure file type matches filename extension."""
        filename = values.get('filename')
        file_type = values.get('file_type')
        
        if filename and file_type:
            extension = filename.split('.')[-1].lower()
            try:
                detected_type = FileType(extension)
                if detected_type != file_type:
                    logger.warning(
                        "File type mismatch",
                        filename=filename,
                        provided_type=file_type,
                        detected_type=detected_type
                    )
            except ValueError:
                # Extension not in FileType enum
                pass
        
        return values
    
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
    """Response schema for successful file upload with enhanced metadata."""
    
    object_key: str = Field(..., description="Object key in MinIO")
    bucket: str = Field(..., description="Bucket name")
    size: Optional[int] = Field(None, ge=0, description="File size in bytes")
    content_type: str = Field(..., description="MIME content type")
    etag: Optional[str] = Field(None, description="Entity tag for version tracking")
    checksum: Optional[str] = Field(None, description="MD5 checksum of file content")
    upload_timestamp: datetime = Field(..., description="Upload timestamp")
    presigned_url: Optional[HttpUrl] = Field(None, description="Presigned URL for download")
    version_id: Optional[str] = Field(None, description="Version ID if versioning enabled")
    metadata: Optional[Dict[str, str]] = Field(None, description="File metadata")
    
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
    """Request schema for generating presigned URLs with validation."""
    
    bucket: str = Field(
        ...,
        min_length=3,
        max_length=63,
        regex="^[a-z0-9][a-z0-9.-]*[a-z0-9]$",
        description="Bucket name (S3 naming rules)"
    )
    object_key: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Object key"
    )
    operation: str = Field(
        "download",
        regex="^(upload|download)$",
        description="Operation type"
    )
    expires_in: int = Field(
        3600,
        ge=60,
        le=604800,  # Max 7 days
        description="URL expiration in seconds (60s to 7 days)"
    )
    response_headers: Optional[Dict[str, str]] = Field(
        None,
        description="Custom response headers for download"
    )
    
    @validator("response_headers")
    def validate_response_headers(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Validate response headers for security."""
        if v is None:
            return v
            
        # List of allowed response headers
        allowed_headers = [
            "Content-Type",
            "Content-Language",
            "Expires",
            "Cache-Control",
            "Content-Disposition",
            "Content-Encoding",
            "X-Content-Type-Options",
            "X-Frame-Options"
        ]
        
        # Filter and validate headers
        validated = {}
        for key, value in v.items():
            # Case-insensitive header matching
            normalized_key = key.replace('_', '-')
            if any(normalized_key.lower() == allowed.lower() for allowed in allowed_headers):
                # Sanitize header value - remove newlines and control characters
                value = ''.join(char for char in value if ord(char) >= 32 or char in '\t')
                validated[key] = value[:500]  # Increased limit for Content-Disposition
            else:
                logger.warning(
                    "Disallowed response header",
                    header=key
                )
        
        return validated if validated else None
    
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
    """Schema for file information/metadata with enhanced fields."""
    
    object_key: str = Field(..., description="Object key in MinIO")
    bucket: str = Field(..., description="Bucket name")
    filename: str = Field(..., description="Original filename")
    size: int = Field(..., ge=0, description="File size in bytes")
    content_type: str = Field(..., description="MIME content type")
    last_modified: datetime = Field(..., description="Last modification time")
    etag: str = Field(..., description="Entity tag")
    metadata: Optional[Dict[str, str]] = Field(default_factory=dict, description="Custom metadata")
    version_id: Optional[str] = Field(None, description="Version ID if versioning enabled")
    checksum: Optional[str] = Field(None, description="MD5 checksum")
    storage_class: Optional[str] = Field(None, description="Storage class (STANDARD, GLACIER, etc.)")
    is_delete_marker: bool = Field(False, description="Whether this is a delete marker")
    
    @property
    def file_type(self) -> Optional[FileType]:
        """Get file type from filename."""
        if self.filename:
            extension = self.filename.split('.')[-1].lower()
            return FileType.from_extension(extension)
        return None
    
    @property
    def is_expired(self) -> bool:
        """Check if file has expired (for temp files)."""
        if self.bucket == BucketType.TEMP.value:
            # Temp files expire after 24 hours
            expiry = self.last_modified + timedelta(hours=24)
            return datetime.utcnow() > expiry
        return False
    
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
    """Request schema for listing files with enhanced filtering."""
    
    bucket: str = Field(..., description="Bucket to list")
    prefix: Optional[str] = Field(
        None,
        max_length=1024,
        description="Object key prefix filter"
    )
    delimiter: Optional[str] = Field(
        None,
        max_length=1,
        description="Delimiter for grouping keys (usually '/')"
    )
    max_results: int = Field(
        100,
        ge=1,
        le=1000,
        description="Maximum results to return"
    )
    start_after: Optional[str] = Field(
        None,
        max_length=1024,
        description="Start listing after this key (for pagination)"
    )
    continuation_token: Optional[str] = Field(
        None,
        description="Pagination token from previous response"
    )
    include_versions: bool = Field(
        False,
        description="Include all object versions"
    )
    
    @validator("prefix", "start_after")
    def sanitize_keys(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize object key prefixes."""
        if v:
            # Remove dangerous patterns
            v = v.replace("..", "").replace("//", "/")
            # Remove leading and trailing slashes
            v = v.strip("/")
            # Remove control characters
            v = ''.join(char for char in v if ord(char) >= 32 or char in '\t\n')
            # Limit length to prevent abuse
            v = v[:1024]
        return v if v else None
    
    class Config:
        schema_extra = {
            "example": {
                "bucket": "artefacts",
                "prefix": "models/job_123/",
                "max_results": 100
            }
        }


class FileListResponse(BaseModel):
    """Response schema for file listing with pagination support."""
    
    files: List[FileInfo] = Field(default_factory=list, description="List of files")
    directories: List[str] = Field(default_factory=list, description="List of directory prefixes")
    count: int = Field(..., ge=0, description="Number of files returned")
    total_size: Optional[int] = Field(None, ge=0, description="Total size of all files in bytes")
    continuation_token: Optional[str] = Field(None, description="Token for next page")
    next_start_after: Optional[str] = Field(None, description="Key to use for next page")
    has_more: bool = Field(False, description="Whether more results available")
    is_truncated: bool = Field(False, description="Whether results were truncated")
    
    @validator("count", always=True)
    def set_count(cls, v: int, values: dict) -> int:
        """Auto-set count from files list."""
        files = values.get('files', [])
        return len(files) if files else 0
    
    @validator("total_size", always=True)
    def calculate_total_size(cls, v: Optional[int], values: dict) -> Optional[int]:
        """Calculate total size from files."""
        if v is not None:
            return v
        files = values.get('files', [])
        if files:
            return sum(f.size for f in files if f.size)
        return None
    
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
    """Request schema for file deletion with validation."""
    
    bucket: str = Field(
        ...,
        min_length=3,
        max_length=63,
        description="Bucket name"
    )
    object_key: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Object key to delete"
    )
    version_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Specific version to delete"
    )
    bypass_governance: bool = Field(
        False,
        description="Bypass governance retention (requires special permissions)"
    )
    
    @validator("object_key")
    def validate_object_key(cls, v: str) -> str:
        """Validate object key for safety."""
        # Import validation function from core module
        from app.core.minio_config import validate_object_key
        
        # Validate with core function
        v = validate_object_key(v)
        
        # Additional check: Prevent deletion of critical system files
        protected_prefixes = [".system/", ".config/", ".backup/", ".minio.sys/"]
        for prefix in protected_prefixes:
            if v.startswith(prefix):
                raise ValueError(
                    f"Korumalı dosya silinemez: {v}"
                )
        
        # Prevent deletion of versioning markers
        if v.endswith(".delete-marker") or "/.versions/" in v:
            raise ValueError(
                f"Sürüm dosyası doğrudan silinemez: {v}"
            )
        
        return v
    
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
    """Schema for storage-related errors with enhanced details."""
    
    error_code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional error details"
    )
    turkish_message: Optional[str] = Field(None, description="Turkish error message")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Error timestamp"
    )
    request_id: Optional[str] = Field(None, description="Request ID for tracing")
    retry_after: Optional[int] = Field(
        None,
        ge=0,
        description="Seconds to wait before retry (for rate limiting)"
    )
    
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


# Batch operation schemas
class BatchFileOperation(BaseModel):
    """Schema for batch file operations."""
    
    operation: str = Field(
        ...,
        regex="^(copy|move|delete)$",
        description="Operation type"
    )
    source_bucket: str = Field(..., description="Source bucket")
    source_key: str = Field(..., description="Source object key")
    dest_bucket: Optional[str] = Field(None, description="Destination bucket (for copy/move)")
    dest_key: Optional[str] = Field(None, description="Destination key (for copy/move)")
    
    @root_validator
    def validate_operation_requirements(cls, values):
        """Ensure required fields for each operation."""
        operation = values.get('operation')
        dest_bucket = values.get('dest_bucket')
        dest_key = values.get('dest_key')
        
        if operation in ['copy', 'move']:
            if not dest_bucket or not dest_key:
                raise ValueError(
                    f"{operation} işlemi için hedef bucket ve key gerekli"
                )
        
        return values

class BatchFileOperationResponse(BaseModel):
    """Response for batch file operations."""
    
    successful: List[str] = Field(
        default_factory=list,
        description="Successfully processed keys"
    )
    failed: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Failed operations with reasons"
    )
    total_processed: int = Field(..., ge=0, description="Total files processed")
    duration_seconds: Optional[float] = Field(None, ge=0, description="Operation duration")
    
    @validator("total_processed", always=True)
    def calculate_total(cls, v: int, values: dict) -> int:
        """Calculate total from successful and failed."""
        successful = values.get('successful', [])
        failed = values.get('failed', [])
        calculated = len(successful) + len(failed)
        if v != calculated and calculated > 0:
            logger.warning(
                "Total processed mismatch",
                provided=v,
                calculated=calculated
            )
        return calculated if calculated > 0 else v

# Type aliases for better type hints
FileMetadata = Dict[str, str]
FileList = List[FileInfo]

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
    "BatchFileOperation",
    "BatchFileOperationResponse",
    "FileMetadata",
    "FileList",
]