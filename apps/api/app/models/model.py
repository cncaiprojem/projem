"""
3D Model storage and versioning.
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String, Integer, BigInteger, Boolean, ForeignKey,
    Index, CheckConstraint, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import ModelType, FileFormat


class Model(Base, TimestampMixin):
    """3D CAD model storage and versioning."""
    
    __tablename__ = "models"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    parent_model_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"),
        index=True
    )
    
    # Model identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    
    # Model type and format
    type: Mapped[ModelType] = mapped_column(
        SQLEnum(ModelType),
        nullable=False
    )
    file_format: Mapped[FileFormat] = mapped_column(
        SQLEnum(FileFormat),
        nullable=False
    )
    
    # Storage information
    s3_key: Mapped[str] = mapped_column(
        String(1024),
        unique=True,
        nullable=False,
        index=True
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )
    sha256_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True
    )
    
    # Versioning
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1
    )
    
    # Model generation and analysis parameters/metrics
    params: Mapped[Optional[dict]] = mapped_column(JSONB, default={})
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, default={})
    
    # Legacy metadata (kept for compatibility)
    model_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, name="metadata", default={})
    
    # Thumbnail
    thumbnail_s3_key: Mapped[Optional[str]] = mapped_column(String(1024))
    
    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="models")
    parent_model: Mapped[Optional["Model"]] = relationship(
        "Model",
        remote_side=[id],
        backref="versions"
    )
    cam_runs: Mapped[List["CamRun"]] = relationship(
        "CamRun",
        back_populates="model"
    )
    
    # Constraints and indexes  
    __table_args__ = (
        CheckConstraint('file_size > 0', name='ck_models_file_size_positive'),
        CheckConstraint('version > 0', name='ck_models_version_positive'),
        Index('idx_models_user_id', 'user_id'),
        Index('idx_models_type', 'type'),
        Index('idx_models_created_at', 'created_at'),
        Index('idx_models_params', 'params',
              postgresql_using='gin',
              postgresql_where='params IS NOT NULL'),
        Index('idx_models_metadata', 'metadata',
              postgresql_using='gin',
              postgresql_where='metadata IS NOT NULL'),
    )
    
    def __repr__(self) -> str:
        return f"<Model(id={self.id}, name={self.name}, type={self.type.value})>"
    
    @property
    def is_latest_version(self) -> bool:
        """Check if this is the latest version."""
        if not self.versions:
            return True
        return all(v.version < self.version for v in self.versions)
    
    @property
    def dimensions(self) -> Optional[dict]:
        """Extract dimensions from metadata."""
        if not self.model_metadata:
            return None
        return self.model_metadata.get('dimensions')
    
    @property
    def materials(self) -> Optional[list]:
        """Extract materials from metadata."""
        if not self.model_metadata:
            return None
        return self.model_metadata.get('materials', [])
    
    @property
    def bounding_box(self) -> Optional[dict]:
        """Extract bounding box from metadata."""
        if not self.model_metadata:
            return None
        return self.model_metadata.get('bounding_box')
    
    def create_version(self, **kwargs) -> "Model":
        """Create a new version of this model."""
        new_version = Model(
            user_id=self.user_id,
            parent_model_id=self.id,
            name=kwargs.get('name', self.name),
            description=kwargs.get('description', self.description),
            type=self.type,
            file_format=kwargs.get('file_format', self.file_format),
            s3_key=kwargs['s3_key'],  # Required
            file_size=kwargs['file_size'],  # Required
            sha256_hash=kwargs['sha256_hash'],  # Required
            version=self.version + 1,
            model_metadata=kwargs.get('metadata', self.model_metadata),
            thumbnail_s3_key=kwargs.get('thumbnail_s3_key')
        )
        return new_version
    
    def update_metadata(self, key: str, value: any):
        """Update specific metadata field."""
        if not self.model_metadata:
            self.model_metadata = {}
        self.model_metadata[key] = value