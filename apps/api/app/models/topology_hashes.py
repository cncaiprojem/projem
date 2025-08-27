"""OCCT topology hashes for deterministic shape exports.

Task 7.15: Topology hash tracking for consistent OCCT 7.8.x exports
ensuring deterministic CAD model generation.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    String, BigInteger, ForeignKey, UniqueConstraint, Index, Text, Enum as SQLEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import ShapeKind

if TYPE_CHECKING:
    from .artefact import Artefact


class TopologyHash(Base, TimestampMixin):
    """OCCT topology hashes for deterministic exports.
    
    Task 7.15 Requirements:
    - Track topology hashes for OCCT 7.8.x shapes
    - Support hierarchy paths (Body/Pad/Face6)
    - Ensure deterministic exports across regenerations
    - Enable shape comparison and validation
    """
    
    __tablename__ = "topology_hashes"
    
    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    
    # Foreign key to artefact
    artefact_id: Mapped[int] = mapped_column(
        ForeignKey("artefacts.id", ondelete="CASCADE", name="fk_topology_hashes_artefact_id"),
        nullable=False,
        index=True
    )
    
    # Topology identification
    object_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Object path in model tree, e.g., Body/Pad/Face6"
    )
    
    shape_kind: Mapped[ShapeKind] = mapped_column(
        SQLEnum(ShapeKind),
        nullable=False,
        comment="Type of shape: Solid, Shell, Face, Edge, or Vertex"
    )
    
    # Hash information
    topo_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
        comment="Stable hash from OCCT 7.8.x"
    )
    
    occt_algo_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="7.8.x",
        index=True,
        comment="OCCT algorithm version used"
    )
    
    # Relationships
    artefact: Mapped["Artefact"] = relationship(
        "Artefact",
        back_populates="topology_hashes",
        foreign_keys=[artefact_id]
    )
    
    # Table constraints
    __table_args__ = (
        UniqueConstraint(
            'artefact_id', 'object_path', 'shape_kind',
            name='uq_topology_hashes_artefact_path_kind'
        ),
        Index('idx_topology_hashes_artefact_id', 'artefact_id'),
        Index('idx_topology_hashes_topo_hash', 'topo_hash'),
        Index('idx_topology_hashes_occt_algo_version', 'occt_algo_version'),
        {'comment': 'OCCT topology hashes for deterministic shape exports'}
    )
    
    def __repr__(self) -> str:
        return (
            f"<TopologyHash(id={self.id}, artefact_id={self.artefact_id}, "
            f"path={self.object_path}, kind={self.shape_kind.value})>"
        )
    
    def __str__(self) -> str:
        return f"TopologyHash #{self.id} - {self.object_path} ({self.shape_kind.value})"
    
    @property
    def is_leaf_node(self) -> bool:
        """Check if this is a leaf node (Vertex or Edge)."""
        return self.shape_kind in [ShapeKind.VERTEX, ShapeKind.EDGE]
    
    @property
    def is_surface(self) -> bool:
        """Check if this is a surface element (Face or Shell)."""
        return self.shape_kind in [ShapeKind.FACE, ShapeKind.SHELL]
    
    @property
    def is_volume(self) -> bool:
        """Check if this is a volume element (Solid)."""
        return self.shape_kind == ShapeKind.SOLID
    
    @property
    def hierarchy_depth(self) -> int:
        """Get the depth in the object hierarchy."""
        return self.object_path.count('/') + 1
    
    @property
    def parent_path(self) -> str:
        """Get the parent object path."""
        if '/' not in self.object_path:
            return None
        return '/'.join(self.object_path.split('/')[:-1])
    
    @property
    def object_name(self) -> str:
        """Get the object name (last part of path)."""
        return self.object_path.split('/')[-1]
    
    def matches_hash(self, other_hash: str) -> bool:
        """Check if another hash matches this one."""
        return self.topo_hash == other_hash
    
    @classmethod
    def create_from_occt(
        cls,
        artefact_id: int,
        object_path: str,
        shape_kind: ShapeKind,
        topo_hash: str,
        occt_version: str = "7.8.1"
    ) -> "TopologyHash":
        """Create a topology hash from OCCT data.
        
        Args:
            artefact_id: ID of the associated artefact
            object_path: Path in the model tree
            shape_kind: Type of shape
            topo_hash: Hash from OCCT
            occt_version: OCCT version used
            
        Returns:
            New TopologyHash instance
        """
        return cls(
            artefact_id=artefact_id,
            object_path=object_path,
            shape_kind=shape_kind,
            topo_hash=topo_hash,
            occt_algo_version=occt_version
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'artefact_id': self.artefact_id,
            'object_path': self.object_path,
            'shape_kind': self.shape_kind.value,
            'topo_hash': self.topo_hash,
            'occt_algo_version': self.occt_algo_version,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }