"""
3D Model storage and versioning with FreeCAD 1.1.0 alignment.

Task 7.15: Enhanced model tracking with versioning, OCCT determinism,
and Assembly4 workbench support.
"""

import re
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    String, Integer, BigInteger, Boolean, ForeignKey, SmallInteger,
    Index, CheckConstraint, Enum as SQLEnum, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import ModelStatus

# Compile regex patterns at module level for performance
FREECAD_VERSION_PATTERN = re.compile(r'^1\.1\.\d+$')
OCCT_VERSION_PATTERN = re.compile(r'^7\.8\.\d+$')

if TYPE_CHECKING:
    from .job import Job


class Model(Base, TimestampMixin):
    """3D CAD model generation records with FreeCAD 1.1.0 versioning.
    
    Task 7.15 Requirements:
    - Tracks FreeCAD and OCCT versions for compatibility
    - Supports model revisioning and parent-child relationships
    - Stores canonical parameters for regeneration
    - Integrates with FreeCADDocumentManager (Task 7.19)
    """
    
    __tablename__ = "models"
    
    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger, 
        primary_key=True, 
        autoincrement=True
    )
    
    # Foreign keys
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE", name="fk_models_job_id"),
        nullable=False,
        index=True,
        comment="Associated job that generated this model"
    )
    parent_model_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL", name="fk_models_parent_model_id"),
        index=True,
        comment="Reference to parent model for versioning"
    )
    
    # Core model fields
    canonical_params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Canonical parameters used for model generation"
    )
    script_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash of the generation script"
    )
    status: Mapped[ModelStatus] = mapped_column(
        SQLEnum(ModelStatus),
        nullable=False,
        default=ModelStatus.PENDING,
        index=True
    )
    
    # FreeCAD 1.1.0 versioning fields
    freecad_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="FreeCAD version (must match 1.1.x pattern)"
    )
    occt_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="OpenCASCADE version (must match 7.8.x pattern)"
    )
    model_rev: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        index=True,
        comment="Model revision number"
    )
    freecad_doc_uuid: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="FreeCAD document UUID"
    )
    doc_schema_version: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=110,
        comment="FreeCAD document schema version"
    )
    
    # Relationships
    job: Mapped["Job"] = relationship(
        "Job", 
        back_populates="models",
        foreign_keys=[job_id]
    )
    parent_model: Mapped[Optional["Model"]] = relationship(
        "Model",
        remote_side=[id],
        backref="child_models"
    )
    
    # Constraints and indexes  
    __table_args__ = (
        # Check constraints for version validation
        CheckConstraint(
            "freecad_version ~ '^1\\.1\\.\\d+$'",
            name='ck_models_freecad_version'
        ),
        CheckConstraint(
            "occt_version ~ '^7\\.8\\.\\d+$'",
            name='ck_models_occt_version'
        ),
        CheckConstraint(
            'model_rev > 0',
            name='ck_models_model_rev_positive'
        ),
        
        # Unique constraint for document UUID and revision
        UniqueConstraint(
            'freecad_doc_uuid', 'model_rev',
            name='uq_models_doc_uuid_rev',
            postgresql_where='freecad_doc_uuid IS NOT NULL'
        ),
        
        # Indexes for performance
        Index('idx_models_job_id', 'job_id'),
        Index('idx_models_status', 'status'),
        Index('idx_models_script_hash', 'script_hash'),
        Index('idx_models_freecad_doc_uuid', 'freecad_doc_uuid'),
        Index('idx_models_model_rev', 'model_rev'),
        Index('idx_models_created_at', 'created_at'),
        Index('idx_models_versions', 'freecad_version', 'occt_version'),
        Index('idx_models_canonical_params', 'canonical_params',
              postgresql_using='gin',
              postgresql_where='canonical_params IS NOT NULL'),
    )
    
    def __repr__(self) -> str:
        return f"<Model(id={self.id}, job_id={self.job_id}, status={self.status.value}, rev={self.model_rev})>"
    
    def __str__(self) -> str:
        return f"Model #{self.id} - Job {self.job_id} (Rev {self.model_rev})"
    
    @property
    def is_latest_revision(self) -> bool:
        """Check if this is the latest revision.
        
        Note: Children have HIGHER model_rev, not lower.
        A model is the latest revision if it has no children.
        
        WARNING: This property may cause N+1 queries when called on multiple models.
        Consider using eager loading with joinedload() or selectinload() when
        querying multiple models if you need to access this property.
        
        Example:
            from sqlalchemy.orm import selectinload
            models = session.query(Model).options(selectinload(Model.child_models)).all()
        """
        # If no child models exist, this is the latest revision
        return not bool(self.child_models)
    
    @property
    def is_assembly(self) -> bool:
        """Check if this model is an assembly based on parameters."""
        return self.canonical_params.get('type') == 'assembly'
    
    @property
    def has_valid_versions(self) -> bool:
        """Validate FreeCAD and OCCT versions."""
        return (
            FREECAD_VERSION_PATTERN.match(self.freecad_version) is not None and
            OCCT_VERSION_PATTERN.match(self.occt_version) is not None
        )
    
    def create_revision(self, **kwargs) -> "Model":
        """Create a new revision of this model."""
        # model_rev will be auto-incremented by the trigger
        new_revision = Model(
            job_id=kwargs.get('job_id', self.job_id),
            parent_model_id=self.id,
            canonical_params=kwargs.get('canonical_params', self.canonical_params),
            script_hash=kwargs['script_hash'],  # Required
            status=ModelStatus.PENDING,
            freecad_version=kwargs.get('freecad_version', self.freecad_version),
            occt_version=kwargs.get('occt_version', self.occt_version),
            freecad_doc_uuid=kwargs.get('freecad_doc_uuid', self.freecad_doc_uuid),
            doc_schema_version=kwargs.get('doc_schema_version', self.doc_schema_version)
        )
        return new_revision
    
    def update_status(self, status: ModelStatus) -> None:
        """Update model status."""
        self.status = status
    
    def set_document_uuid(self, doc_uuid: UUID) -> None:
        """Set FreeCAD document UUID."""
        self.freecad_doc_uuid = doc_uuid