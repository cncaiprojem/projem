"""
Pydantic models for FreeCAD Model Version Control System (Task 7.22).

This module defines all data models for the Git-like version control system
specifically designed for FreeCAD models with branching, merging, diffing,
and rollback capabilities.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, ConfigDict


class ConflictResolutionStrategy(str, Enum):
    """Conflict resolution strategies for merging."""
    OURS = "ours"  # Keep our version
    THEIRS = "theirs"  # Keep their version
    AUTO = "auto"  # Try automatic resolution
    INTERACTIVE = "interactive"  # Require manual resolution
    UNION = "union"  # Union of both changes


class MergeStrategy(str, Enum):
    """Merge strategies for combining branches."""
    RECURSIVE = "recursive"  # Default recursive merge
    OCTOPUS = "octopus"  # Multi-branch merge
    OURS = "ours"  # Keep our branch
    SUBTREE = "subtree"  # Subtree merge


class ObjectType(str, Enum):
    """Types of objects in the version control system."""
    BLOB = "blob"  # File content (FreeCAD object)
    TREE = "tree"  # Directory structure
    COMMIT = "commit"  # Commit object
    TAG = "tag"  # Annotated tag


class DiffType(str, Enum):
    """Types of changes in a diff."""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"


class ChangeType(str, Enum):
    """Types of property changes."""
    VALUE_CHANGE = "value_change"
    TYPE_CHANGE = "type_change"
    ADDITION = "addition"
    DELETION = "deletion"


class Repository(BaseModel):
    """Repository metadata."""
    model_config = ConfigDict(validate_assignment=True)
    
    id: UUID = Field(default_factory=uuid4, description="Repository UUID")
    name: str = Field(description="Repository name")
    description: Optional[str] = Field(default=None, description="Repository description")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    default_branch: str = Field(default="main", description="Default branch name")
    config: Dict[str, Any] = Field(default_factory=dict, description="Repository configuration")
    tags: List[str] = Field(default_factory=list, description="Repository tags")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate repository name."""
        if not v or not v.strip():
            raise ValueError("Repository name cannot be empty")
        # Sanitize name
        return v.strip().replace(' ', '_')


class ObjectHash(BaseModel):
    """Content-addressable hash for objects."""
    model_config = ConfigDict(validate_assignment=True)
    
    sha256: str = Field(description="SHA-256 hash of object content")
    size: int = Field(description="Object size in bytes")
    object_type: ObjectType = Field(description="Type of object")
    compressed: bool = Field(default=True, description="Whether object is compressed")
    
    @field_validator('sha256')
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        """Validate SHA-256 hash format."""
        if not v or len(v) != 64:
            raise ValueError("Invalid SHA-256 hash")
        return v.lower()


class FreeCADObjectData(BaseModel):
    """Serialized FreeCAD object data."""
    model_config = ConfigDict(validate_assignment=True)
    
    type_id: str = Field(description="FreeCAD TypeId")
    name: str = Field(description="Object name")
    label: str = Field(description="Object label")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Object properties")
    placement: Optional[Dict[str, Any]] = Field(default=None, description="Object placement")
    shape_data: Optional[Dict[str, Any]] = Field(default=None, description="Shape data if applicable")
    expressions: Dict[str, str] = Field(default_factory=dict, description="Parametric expressions")
    visibility: bool = Field(default=True, description="Object visibility")
    
    def calculate_hash(self) -> str:
        """Calculate deterministic hash of object data."""
        import json
        # Sort keys for deterministic serialization
        data_str = json.dumps(self.dict(), sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()


class TreeEntry(BaseModel):
    """Entry in a tree object."""
    model_config = ConfigDict(validate_assignment=True)
    
    name: str = Field(description="Entry name")
    hash: str = Field(description="Object hash")
    mode: str = Field(default="100644", description="File mode (Unix permissions)")
    object_type: ObjectType = Field(description="Type of object")


class Tree(BaseModel):
    """Tree object representing a directory structure."""
    model_config = ConfigDict(validate_assignment=True)
    
    entries: List[TreeEntry] = Field(default_factory=list, description="Tree entries")
    
    def calculate_hash(self) -> str:
        """Calculate tree hash."""
        import json
        # Sort entries for deterministic hash
        sorted_entries = sorted(self.entries, key=lambda e: e.name)
        data = [e.dict() for e in sorted_entries]
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()


class Commit(BaseModel):
    """Commit object."""
    model_config = ConfigDict(validate_assignment=True)
    
    id: UUID = Field(default_factory=uuid4, description="Commit UUID")
    tree: str = Field(description="Tree hash")
    parents: List[str] = Field(default_factory=list, description="Parent commit hashes")
    author: str = Field(description="Author name/email")
    committer: Optional[str] = Field(default=None, description="Committer if different from author")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = Field(description="Commit message")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    hash: Optional[str] = Field(default=None, description="Commit hash")
    
    def calculate_hash(self) -> str:
        """Calculate commit hash."""
        import json
        data = {
            "tree": self.tree,
            "parents": sorted(self.parents),
            "author": self.author,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message
        }
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()


class Branch(BaseModel):
    """Branch reference."""
    model_config = ConfigDict(validate_assignment=True)
    
    name: str = Field(description="Branch name")
    head: str = Field(description="Commit hash at branch head")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    protected: bool = Field(default=False, description="Whether branch is protected")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Branch metadata")
    
    @field_validator('name')
    @classmethod
    def validate_branch_name(cls, v: str) -> str:
        """Validate branch name following Git conventions."""
        from app.utils.vcs_validation import validate_branch_name, get_invalid_branch_name_reasons
        
        if not validate_branch_name(v):
            errors = get_invalid_branch_name_reasons(v)
            if errors:
                raise ValueError(errors[0])  # Return first error
            raise ValueError("Invalid branch name")
        
        return v


class Tag(BaseModel):
    """Tag reference."""
    model_config = ConfigDict(validate_assignment=True)
    
    name: str = Field(description="Tag name")
    target: str = Field(description="Target commit hash")
    tagger: str = Field(description="Tagger name/email")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: Optional[str] = Field(default=None, description="Tag message")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Tag metadata")


class PropertyChange(BaseModel):
    """Property change in a diff."""
    model_config = ConfigDict(validate_assignment=True)
    
    property: str = Field(description="Property name")
    old_value: Any = Field(default=None, description="Old value")
    new_value: Any = Field(default=None, description="New value")
    change_type: ChangeType = Field(description="Type of change")


class ShapeDiff(BaseModel):
    """Geometric shape differences."""
    model_config = ConfigDict(validate_assignment=True)
    
    volume_change: Optional[float] = Field(default=None, description="Volume change percentage")
    area_change: Optional[float] = Field(default=None, description="Surface area change percentage")
    topology_changes: Dict[str, Any] = Field(default_factory=dict, description="Topology changes")
    vertex_count_change: Optional[int] = Field(default=None, description="Change in vertex count")
    edge_count_change: Optional[int] = Field(default=None, description="Change in edge count")
    face_count_change: Optional[int] = Field(default=None, description="Change in face count")


class ObjectDiff(BaseModel):
    """Differences between two FreeCAD objects."""
    model_config = ConfigDict(validate_assignment=True)
    
    object_id: str = Field(description="Object identifier")
    diff_type: DiffType = Field(description="Type of difference")
    property_changes: List[PropertyChange] = Field(default_factory=list, description="Property changes")
    shape_diff: Optional[ShapeDiff] = Field(default=None, description="Shape differences")
    expression_changes: Dict[str, Dict[str, str]] = Field(default_factory=dict, description="Expression changes")


class CommitDiff(BaseModel):
    """Differences between two commits."""
    model_config = ConfigDict(validate_assignment=True)
    
    from_commit: str = Field(description="Source commit hash")
    to_commit: str = Field(description="Target commit hash")
    object_diffs: List[ObjectDiff] = Field(default_factory=list, description="Object differences")
    stats: Dict[str, int] = Field(default_factory=dict, description="Diff statistics")


class MergeConflict(BaseModel):
    """Merge conflict information."""
    model_config = ConfigDict(validate_assignment=True)
    
    object_id: str = Field(description="Conflicting object ID")
    base_version: Optional[FreeCADObjectData] = Field(default=None, description="Base version")
    our_version: FreeCADObjectData = Field(description="Our version")
    their_version: FreeCADObjectData = Field(description="Their version")
    conflict_type: str = Field(description="Type of conflict")
    auto_resolvable: bool = Field(default=False, description="Whether conflict can be auto-resolved")
    suggested_resolution: Optional[str] = Field(default=None, description="Suggested resolution")


class MergeResult(BaseModel):
    """Result of a merge operation."""
    model_config = ConfigDict(validate_assignment=True)
    
    success: bool = Field(description="Whether merge was successful")
    commit_hash: Optional[str] = Field(default=None, description="Merge commit hash if successful")
    conflicts: List[MergeConflict] = Field(default_factory=list, description="Merge conflicts")
    merged_tree: Optional[str] = Field(default=None, description="Merged tree hash")
    strategy_used: MergeStrategy = Field(description="Merge strategy used")
    auto_resolved_count: int = Field(default=0, description="Number of auto-resolved conflicts")


class ResolvedObject(BaseModel):
    """Resolved object after conflict resolution."""
    model_config = ConfigDict(validate_assignment=True)
    
    object_data: Optional[FreeCADObjectData] = Field(default=None, description="Resolved object data")
    resolution_type: str = Field(description="How conflict was resolved")
    conflict_info: Optional[Dict[str, Any]] = Field(default=None, description="Conflict information")


class CommitInfo(BaseModel):
    """Commit information for history."""
    model_config = ConfigDict(validate_assignment=True)
    
    hash: str = Field(description="Commit hash")
    author: str = Field(description="Author")
    timestamp: datetime = Field(description="Commit timestamp")
    message: str = Field(description="Commit message")
    parents: List[str] = Field(default_factory=list, description="Parent hashes")
    branch: Optional[str] = Field(default=None, description="Branch name")
    tags: List[str] = Field(default_factory=list, description="Associated tags")


class CheckoutResult(BaseModel):
    """Result of a checkout operation."""
    model_config = ConfigDict(validate_assignment=True)
    
    success: bool = Field(description="Whether checkout was successful")
    commit_hash: str = Field(description="Checked out commit hash")
    branch: Optional[str] = Field(default=None, description="Branch name if applicable")
    document_path: Optional[str] = Field(default=None, description="Path to reconstructed document")
    warnings: List[str] = Field(default_factory=list, description="Any warnings during checkout")


class DeltaCompression(BaseModel):
    """Delta compression information."""
    model_config = ConfigDict(validate_assignment=True)
    
    base_hash: str = Field(description="Base object hash")
    delta_size: int = Field(description="Delta size in bytes")
    compression_ratio: float = Field(description="Compression ratio")
    algorithm: str = Field(default="xdelta3", description="Delta algorithm used")


class StorageStats(BaseModel):
    """Storage statistics for the repository."""
    model_config = ConfigDict(validate_assignment=True)
    
    total_objects: int = Field(description="Total number of objects")
    total_size_bytes: int = Field(description="Total size in bytes")
    compressed_size_bytes: int = Field(description="Compressed size in bytes")
    delta_compressed_objects: int = Field(default=0, description="Number of delta-compressed objects")
    compression_ratio: float = Field(description="Overall compression ratio")
    last_gc_timestamp: Optional[datetime] = Field(default=None, description="Last garbage collection time")
    gc_runs: int = Field(default=0, description="Number of garbage collection runs")
    objects_removed: int = Field(default=0, description="Total objects removed by garbage collection")


# Turkish translations for messages
VERSION_CONTROL_TR = {
    'init_repo': 'Depo başlatılıyor...',
    'commit_created': 'Değişiklikler kaydedildi: {hash}',
    'branch_created': 'Dal oluşturuldu: {name}',
    'branch_deleted': 'Dal silindi: {name}',
    'merge_success': 'Birleştirme başarılı',
    'merge_conflict': 'Birleştirme çakışması tespit edildi',
    'checkout': '{ref} dalına geçildi',
    'rollback': '{commit} sürümüne geri dönüldü',
    'history': 'Değişiklik geçmişi',
    'diff_calculated': 'Farklar hesaplandı',
    'object_stored': 'Nesne depolandı: {hash}',
    'object_retrieved': 'Nesne alındı: {hash}',
    'tag_created': 'Etiket oluşturuldu: {name}',
    'conflict_resolved': 'Çakışma çözüldü',
    'auto_merge_failed': 'Otomatik birleştirme başarısız',
    'storage_optimized': 'Depolama optimize edildi',
    'garbage_collected': 'Gereksiz nesneler temizlendi',
    'error_invalid_branch': 'Geçersiz dal adı',
    'error_commit_not_found': 'Commit bulunamadı',
    'error_merge_failed': 'Birleştirme başarısız',
    'error_checkout_failed': 'Dal değiştirme başarısız',
    'error_object_corrupt': 'Nesne bozuk'
}