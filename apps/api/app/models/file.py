"""
Ultra-Enterprise File Metadata Model for Task 5.3

SQLAlchemy model for tracking file uploads and metadata:
- File metadata storage
- Upload session tracking
- SHA256 verification records
- Audit trail for compliance
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import uuid4

from sqlalchemy import (
    String, BigInteger, DateTime,
    Text, JSON, Enum as SQLEnum, Index, CheckConstraint,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base
from app.core.database import get_db_time


class FileStatus(enum.Enum):
    """File upload status tracking."""
    PENDING = "pending"  # Upload initialized
    UPLOADING = "uploading"  # Upload in progress
    VERIFYING = "verifying"  # SHA256 verification in progress
    SCANNING = "scanning"  # Malware scan in progress (Task 5.6)
    COMPLETED = "completed"  # Successfully uploaded and verified
    FAILED = "failed"  # Upload or verification failed
    DELETED = "deleted"  # Soft deleted


class FileType(enum.Enum):
    """File type categorization."""
    MODEL = "model"  # 3D models
    GCODE = "gcode"  # G-code files
    REPORT = "report"  # Analysis reports
    INVOICE = "invoice"  # Financial documents
    LOG = "log"  # System logs
    TEMP = "temp"  # Temporary files


class FileMetadata(Base):
    """
    File metadata model for tracking uploads.
    Task 5.3: Store file information and verification data
    """
    __tablename__ = "file_metadata"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False
    )
    
    # File identification
    object_key: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        unique=True,
        index=True,
        comment="S3/MinIO object key"
    )
    
    bucket: Mapped[str] = mapped_column(
        String(63),
        nullable=False,
        index=True,
        comment="S3/MinIO bucket name"
    )
    
    # File properties
    filename: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Original filename"
    )
    
    file_type: Mapped[FileType] = mapped_column(
        SQLEnum(FileType),
        nullable=False,
        index=True,
        comment="File type category"
    )
    
    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="MIME content type"
    )
    
    size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="File size in bytes"
    )
    
    # Verification
    sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash (lowercase hex)"
    )
    
    etag: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="S3 ETag"
    )
    
    version_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="S3 version ID"
    )
    
    # Status tracking
    status: Mapped[FileStatus] = mapped_column(
        SQLEnum(FileStatus),
        nullable=False,
        default=FileStatus.PENDING,
        index=True,
        comment="Upload status"
    )
    
    # Relationships
    job_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Associated job ID"
    )
    
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Uploader user ID"
    )
    
    # Optional tracking
    machine_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Machine identifier"
    )
    
    post_processor: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Post-processor identifier"
    )
    
    # Metadata
    tags: Mapped[Optional[Dict[str, str]]] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="Object tags (job_id, machine, post)"
    )
    
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="Additional metadata"
    )
    
    # Security
    client_ip: Mapped[Optional[str]] = mapped_column(
        String(45),  # Support IPv6
        nullable=True,
        comment="Client IP for audit"
    )
    
    malware_scan_result: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Malware scan result (Task 5.6)"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=get_db_time,
        comment="Upload timestamp"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=get_db_time,
        onupdate=get_db_time,
        comment="Last update timestamp"
    )
    
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Verification completion timestamp"
    )
    
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft deletion timestamp"
    )
    
    # Relationships
    user = relationship("User", back_populates="uploaded_files", lazy="select")
    
    # Indexes and constraints
    __table_args__ = (
        # Composite indexes for common queries
        Index("ix_file_metadata_job_status", "job_id", "status"),
        Index("ix_file_metadata_type_created", "file_type", "created_at"),
        Index("ix_file_metadata_user_created", "user_id", "created_at"),
        
        # Unique constraint for job_id + filename (prevent duplicates)
        UniqueConstraint("job_id", "filename", name="uq_job_filename"),
        
        # Check constraints
        CheckConstraint("size > 0", name="ck_positive_size"),
        CheckConstraint("length(sha256) = 64", name="ck_sha256_length"),
        CheckConstraint("length(object_key) > 0", name="ck_object_key_not_empty"),
        
        {"comment": "File metadata for upload tracking and verification"}
    )
    
    def __repr__(self) -> str:
        return (
            f"<FileMetadata(id={self.id}, key={self.object_key}, "
            f"type={self.file_type.value}, status={self.status.value})>"
        )
    
    @property
    def is_completed(self) -> bool:
        """Check if upload is completed."""
        return self.status == FileStatus.COMPLETED
    
    @property
    def is_deleted(self) -> bool:
        """Check if file is soft deleted."""
        return self.status == FileStatus.DELETED or self.deleted_at is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "object_key": self.object_key,
            "bucket": self.bucket,
            "filename": self.filename,
            "file_type": self.file_type.value,
            "mime_type": self.mime_type,
            "size": self.size,
            "sha256": self.sha256,
            "status": self.status.value,
            "job_id": self.job_id,
            "user_id": str(self.user_id) if self.user_id else None,
            "machine_id": self.machine_id,
            "tags": self.tags or {},
            "metadata": self.metadata or {},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }


class UploadSession(Base):
    """
    Upload session tracking for Task 5.3.
    Stores expected metadata for validation during finalization.
    """
    __tablename__ = "upload_sessions"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False
    )
    
    # Session identification
    upload_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique upload session ID"
    )
    
    # Expected file properties
    object_key: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="Expected object key"
    )
    
    expected_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Expected file size"
    )
    
    expected_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Expected SHA256 hash"
    )
    
    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Expected MIME type"
    )
    
    # Tracking
    job_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Associated job ID"
    )
    
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Session owner"
    )
    
    client_ip: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="Client IP for binding"
    )
    
    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="Session status"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=get_db_time,
        comment="Session creation time"
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Session expiry time"
    )
    
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Completion timestamp"
    )
    
    # Metadata
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="Session metadata"
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_upload_sessions_expires", "expires_at"),
        Index("ix_upload_sessions_user_created", "user_id", "created_at"),
        CheckConstraint("expected_size > 0", name="ck_session_positive_size"),
        {"comment": "Upload session tracking for validation"}
    )
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        # Use timezone-aware comparison
        now_utc = datetime.now(timezone.utc)
        expires_utc = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return now_utc > expires_utc
    
    @property
    def is_completed(self) -> bool:
        """Check if session is completed."""
        return self.status == "completed" and self.completed_at is not None


__all__ = [
    "FileMetadata",
    "UploadSession",
    "FileStatus",
    "FileType",
]