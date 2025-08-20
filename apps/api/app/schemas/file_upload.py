"""
Ultra-Enterprise File Upload/Download Schemas for Task 5.3

Provides comprehensive validation schemas for:
- Upload initialization with presigned URLs
- Upload finalization with SHA256 verification
- Download with presigned URLs
- Security constraints and validation
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Final

from pydantic import BaseModel, Field, HttpUrl, validator, conint, constr

# Constants for validation
MAX_UPLOAD_SIZE: Final[int] = 200 * 1024 * 1024  # 200MB as per Task 5.3
MIN_UPLOAD_SIZE: Final[int] = 1  # At least 1 byte
PRESIGNED_PUT_TTL_SECONDS: Final[int] = 300  # 5 minutes for PUT
PRESIGNED_GET_TTL_SECONDS: Final[int] = 120  # 2 minutes for GET
SHA256_LENGTH: Final[int] = 64  # SHA256 hash is 64 hex characters
SHA256_PATTERN: Final[str] = f"^[a-f0-9]{{{SHA256_LENGTH}}}$"  # Regex pattern for SHA256 validation

# Allowed MIME types for security
ALLOWED_MIME_TYPES: Final[List[str]] = [
    # 3D Model formats
    "application/sla",  # STL
    "application/step",  # STEP
    "model/iges",  # IGES
    "model/obj",  # OBJ
    "model/gltf+json",  # GLTF
    "model/gltf-binary",  # GLB
    
    # CAM/CNC formats
    "text/plain",  # G-code, NC files
    "application/x-gcode",
    
    # Documents
    "application/pdf",
    "application/json",
    "text/csv",
    "application/xml",
    "text/xml",
    
    # Images
    "image/png",
    "image/jpeg",
    "image/svg+xml",
    
    # Archives
    "application/zip",
    "application/x-tar",
    "application/gzip",
]


class FileUploadType(str, Enum):
    """File upload types for categorization."""
    MODEL = "model"  # 3D models
    GCODE = "gcode"  # G-code files
    REPORT = "report"  # Analysis reports
    INVOICE = "invoice"  # Financial documents
    LOG = "log"  # System logs
    TEMP = "temp"  # Temporary files


class UploadInitRequest(BaseModel):
    """
    Request schema for POST /files/upload/init
    Task 5.3: Initialize file upload with presigned URL
    """
    
    type: FileUploadType = Field(
        ...,
        description="File type for categorization"
    )
    
    size: conint(ge=MIN_UPLOAD_SIZE, le=MAX_UPLOAD_SIZE) = Field(
        ...,
        description=f"File size in bytes (max {MAX_UPLOAD_SIZE // (1024*1024)}MB)"
    )
    
    sha256: constr(regex=SHA256_PATTERN, to_lower=True) = Field(
        ...,
        description="SHA256 hash of file content (lowercase hex)"
    )
    
    mime_type: str = Field(
        ...,
        description="MIME content type"
    )
    
    job_id: constr(regex="^[a-zA-Z0-9][a-zA-Z0-9_-]{0,98}[a-zA-Z0-9]$") = Field(
        ...,
        description="Associated job ID"
    )
    
    machine_id: Optional[constr(max_length=50)] = Field(
        None,
        description="Optional machine ID for tracking"
    )
    
    post_processor: Optional[constr(max_length=50)] = Field(
        None,
        description="Optional post-processor identifier"
    )
    
    filename: Optional[constr(min_length=1, max_length=255)] = Field(
        None,
        description="Original filename for reference"
    )
    
    client_ip: Optional[str] = Field(
        None,
        description="Client IP for optional binding (set by server)"
    )
    
    @validator("mime_type")
    def validate_mime_type(cls, v: str) -> str:
        """Validate MIME type against allowed list."""
        if v not in ALLOWED_MIME_TYPES:
            # Check for wildcards like image/* or text/*
            base_type = v.split('/')[0] if '/' in v else ''
            wildcard = f"{base_type}/*"
            
            if wildcard not in ALLOWED_MIME_TYPES and "*" not in ALLOWED_MIME_TYPES:
                raise ValueError(
                    f"Desteklenmeyen dosya türü: {v}. "
                    f"İzin verilen türler: {', '.join(ALLOWED_MIME_TYPES[:5])}..."
                )
        return v
    
    @validator("sha256")
    def normalize_sha256(cls, v: str) -> str:
        """Normalize SHA256 to lowercase."""
        return v.lower()
    
    @validator("filename")
    def sanitize_filename(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize filename for security."""
        if not v:
            return v
        
        # Remove path components
        v = os.path.basename(v)
        
        # Remove dangerous characters
        v = re.sub(r'[<>:"|?*\x00-\x1f]', '', v)
        
        # Ensure it has an extension
        if '.' not in v:
            v = f"{v}.bin"
        
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "type": "model",
                "size": 5242880,
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "mime_type": "application/sla",
                "job_id": "job-2024-001",
                "machine_id": "cnc-01",
                "filename": "part_v2.stl"
            }
        }


class UploadInitResponse(BaseModel):
    """
    Response schema for POST /files/upload/init
    Returns presigned PUT URL with constraints
    """
    
    key: str = Field(
        ...,
        description="Server-generated object key"
    )
    
    upload_url: HttpUrl = Field(
        ...,
        description="Presigned PUT URL for upload"
    )
    
    expires_in: int = Field(
        PRESIGNED_PUT_TTL_SECONDS,
        description="URL expiry in seconds"
    )
    
    headers: Optional[Dict[str, str]] = Field(
        None,
        description="Optional headers for upload (deprecated, use fields instead)"
    )
    
    fields: Dict[str, str] = Field(
        ...,
        description="Form fields required for multipart/form-data POST upload"
    )
    
    upload_id: str = Field(
        ...,
        description="Unique upload session ID"
    )
    
    conditions: Dict[str, any] = Field(
        default_factory=dict,
        description="Upload conditions and constraints"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "key": "artefacts/job-2024-001/550e8400-e29b-41d4-a716-446655440000.stl",
                "upload_url": "https://minio.example.com/artefacts/...",
                "expires_in": 300,
                "fields": {
                    "key": "artefacts/job-2024-001/550e8400-e29b-41d4-a716-446655440000.stl",
                    "Content-Type": "application/sla",
                    "x-amz-tagging": "job_id=job-2024-001&machine=cnc-01",
                    "x-amz-credential": "AKIAIOSFODNN7EXAMPLE/20240115/us-east-1/s3/aws4_request",
                    "x-amz-algorithm": "AWS4-HMAC-SHA256",
                    "x-amz-date": "20240115T103000Z",
                    "x-amz-signature": "abcdef123456"
                },
                "upload_id": "upload-550e8400-e29b-41d4",
                "conditions": {
                    "content-length-range": [1, 209715200],
                    "content-type": "application/sla"
                }
            }
        }


class UploadFinalizeRequest(BaseModel):
    """
    Request schema for POST /files/upload/finalize
    Task 5.3: Finalize upload and verify integrity
    """
    
    key: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Object key from upload init"
    )
    
    upload_id: Optional[str] = Field(
        None,
        description="Upload session ID for validation"
    )
    
    @validator("key")
    def validate_key(cls, v: str) -> str:
        """Validate object key format."""
        # Remove dangerous patterns
        if ".." in v or v.startswith("/") or "//" in v:
            raise ValueError("Geçersiz nesne anahtarı formatı")
        
        # Must start with valid bucket prefix
        valid_prefixes = ["artefacts/", "reports/", "logs/", "temp/"]
        if not any(v.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(f"Geçersiz nesne anahtarı öneki: {v}")
        
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "key": "artefacts/job-2024-001/550e8400-e29b-41d4-a716-446655440000.stl",
                "upload_id": "upload-550e8400-e29b-41d4"
            }
        }


class UploadFinalizeResponse(BaseModel):
    """
    Response schema for POST /files/upload/finalize
    Confirms successful upload with metadata
    """
    
    success: bool = Field(
        ...,
        description="Upload finalization status"
    )
    
    object_key: str = Field(
        ...,
        description="Final object key in storage"
    )
    
    size: int = Field(
        ...,
        description="Verified file size in bytes"
    )
    
    sha256: str = Field(
        ...,
        description="Verified SHA256 hash"
    )
    
    etag: Optional[str] = Field(
        None,
        description="S3 ETag for the object"
    )
    
    version_id: Optional[str] = Field(
        None,
        description="Version ID if versioning enabled"
    )
    
    metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="Object metadata and tags"
    )
    
    created_at: datetime = Field(
        ...,
        description="Upload completion timestamp"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "object_key": "artefacts/job-2024-001/550e8400-e29b-41d4-a716-446655440000.stl",
                "size": 5242880,
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "etag": "d41d8cd98f00b204e9800998ecf8427e",
                "version_id": "v1.0.0",
                "metadata": {
                    "job_id": "job-2024-001",
                    "machine": "cnc-01",
                    "content_type": "application/sla"
                },
                "created_at": "2024-01-15T10:30:00Z"
            }
        }



class FileDownloadResponse(BaseModel):
    """
    Response schema for GET /files/:id
    Returns presigned GET URL
    """
    
    download_url: HttpUrl = Field(
        ...,
        description="Presigned GET URL"
    )
    
    expires_in: int = Field(
        PRESIGNED_GET_TTL_SECONDS,
        description="URL expiry in seconds"
    )
    
    file_info: Dict[str, any] = Field(
        ...,
        description="File metadata"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "download_url": "https://minio.example.com/artefacts/...",
                "expires_in": 120,
                "file_info": {
                    "key": "artefacts/job-2024-001/model.stl",
                    "size": 5242880,
                    "content_type": "application/sla",
                    "last_modified": "2024-01-15T10:30:00Z"
                }
            }
        }


class UploadErrorCode(str, Enum):
    """Error codes for upload operations."""
    INVALID_INPUT = "INVALID_INPUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    UPLOAD_INCOMPLETE = "UPLOAD_INCOMPLETE"
    HASH_MISMATCH = "HASH_MISMATCH"
    MALWARE_DETECTED = "MALWARE_DETECTED"
    SCAN_UNAVAILABLE = "SCAN_UNAVAILABLE"
    STORAGE_ERROR = "STORAGE_ERROR"
    FORBIDDEN = "FORBIDDEN"


class UploadError(BaseModel):
    """Error response for upload operations."""
    
    code: UploadErrorCode = Field(
        ...,
        description="Error code"
    )
    
    message: str = Field(
        ...,
        description="Error message in English"
    )
    
    turkish_message: str = Field(
        ...,
        description="Error message in Turkish"
    )
    
    details: Optional[Dict[str, any]] = Field(
        None,
        description="Additional error details"
    )
    
    request_id: Optional[str] = Field(
        None,
        description="Request ID for tracing"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "code": "PAYLOAD_TOO_LARGE",
                "message": "File size exceeds maximum allowed size",
                "turkish_message": "Dosya boyutu maksimum limiti aşıyor",
                "details": {
                    "max_size": 209715200,
                    "provided_size": 314572800
                },
                "request_id": "req-123456"
            }
        }



__all__ = [
    "FileUploadType",
    "UploadInitRequest",
    "UploadInitResponse",
    "UploadFinalizeRequest",
    "UploadFinalizeResponse",
    "FileDownloadResponse",
    "UploadErrorCode",
    "UploadError",
    "MAX_UPLOAD_SIZE",
    "PRESIGNED_PUT_TTL_SECONDS",
    "PRESIGNED_GET_TTL_SECONDS",
    "ALLOWED_MIME_TYPES",
    "SHA256_PATTERN",
]