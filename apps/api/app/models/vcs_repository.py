"""
Database models for Version Control System repositories.

This module defines SQLAlchemy models for persisting VCS repository metadata
and managing repository instances in a production-ready manner.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin
from .user import User


class VCSRepository(Base, TimestampMixin):
    """
    Database model for version control repositories.
    
    This model stores repository metadata and configuration,
    providing a persistent registry for VCS instances.
    """
    
    __tablename__ = "vcs_repositories"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Unique repository identifier (used in API paths)
    repository_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: uuid4().hex,
        comment="Unique repository identifier"
    )
    
    # Repository metadata
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Repository name"
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Repository description"
    )
    
    # Owner relationship
    owner_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Repository owner"
    )
    
    owner: Mapped["User"] = relationship(
        "User",
        back_populates="vcs_repositories",
        lazy="joined"
    )
    
    # Repository configuration
    storage_path: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Physical storage path for repository data"
    )
    
    use_real_freecad: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether to use real FreeCAD API"
    )
    
    # Repository state
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether repository is active"
    )
    
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether repository is locked for maintenance"
    )
    
    # Current branch tracking
    current_branch: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default="main",
        comment="Current active branch"
    )
    
    # Repository statistics (updated periodically)
    commit_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Total number of commits"
    )
    
    branch_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="Total number of branches"
    )
    
    tag_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Total number of tags"
    )
    
    storage_size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Repository storage size in bytes"
    )
    
    # Last activity tracking
    last_commit_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last commit"
    )
    
    last_gc_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last garbage collection"
    )
    
    # Additional metadata as JSON
    metadata: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="Additional repository metadata"
    )
    
    # Indexes for performance
    __table_args__ = (
        Index("ix_vcs_repositories_owner_id_is_active", "owner_id", "is_active"),
        Index("ix_vcs_repositories_repository_id_is_active", "repository_id", "is_active"),
        UniqueConstraint("owner_id", "name", name="uq_vcs_repositories_owner_name"),
    )
    
    def __repr__(self) -> str:
        return f"<VCSRepository(id={self.id}, name={self.name}, owner={self.owner_id})>"
    
    def to_dict(self, exclude: set[str] | None = None) -> dict:
        """Convert to dictionary for API responses."""
        data = super().to_dict(exclude)
        
        # Add computed fields
        data["is_empty"] = self.commit_count == 0
        data["requires_gc"] = self._requires_gc()
        
        return data
    
    def _requires_gc(self) -> bool:
        """Check if repository requires garbage collection."""
        from datetime import timedelta
        
        if not self.last_gc_at:
            return True
        
        # GC recommended every 30 days or after 100 commits since last GC
        days_since_gc = (datetime.now(timezone.utc) - self.last_gc_at).days
        return days_since_gc > 30