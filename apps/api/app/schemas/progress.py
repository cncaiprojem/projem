"""
Task 7.16: Real-time Progress Updates - Progress Message Schema v2

This module defines the progress message schema with:
- FreeCAD 1.1.0-specific event types and fields
- Backward compatibility with existing fields
- Support for Assembly4, Material Framework, OCCT operations
- Topology hash computation and export progress
- WebSocket and SSE transport compatibility
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(str, Enum):
    """Progress event types."""
    PHASE = "phase"
    ASSEMBLY4 = "assembly4"
    MATERIAL = "material"
    OCCT = "occt"
    TOPOLOGY_HASH = "topology_hash"
    DOC_GRAPH = "doc_graph"
    DOCUMENT = "document"
    EXPORT = "export"
    # Legacy types for backward compatibility
    STATUS_CHANGE = "status_change"
    PROGRESS_UPDATE = "progress_update"


class OperationGroup(str, Enum):
    """Operation group categories."""
    ASSEMBLY4 = "assembly4"
    OCCT = "occt"
    MATERIAL = "material"
    TOPOLOGY = "topology"
    DOC_GRAPH = "doc_graph"
    DOCUMENT = "document"
    EXPORT = "export"
    GENERAL = "general"


class Phase(str, Enum):
    """Operation phases."""
    START = "start"
    PROGRESS = "progress"
    END = "end"


class DocumentPhase(str, Enum):
    """Document lifecycle phases."""
    DOCUMENT_OPEN = "document_open"
    DOCUMENT_LOAD_OBJECTS = "document_load_objects"
    RECOMPUTE_START = "recompute_start"
    RECOMPUTE_END = "recompute_end"


class Assembly4Phase(str, Enum):
    """Assembly4 solving phases."""
    SOLVER_START = "solver_start"
    SOLVER_PROGRESS = "solver_progress"
    SOLVER_END = "solver_end"
    LCS_PLACEMENT_START = "lcs_placement_start"
    LCS_PLACEMENT_PROGRESS = "lcs_placement_progress"
    LCS_PLACEMENT_END = "lcs_placement_end"


class MaterialPhase(str, Enum):
    """Material Framework phases."""
    MATERIAL_RESOLVE_LIBRARY = "material_resolve_library"
    MATERIAL_APPLY_START = "material_apply_start"
    MATERIAL_APPLY_PROGRESS = "material_apply_progress"
    MATERIAL_APPLY_END = "material_apply_end"
    MATERIAL_OVERRIDE_PROPERTIES = "material_override_properties"


class OCCTOperation(str, Enum):
    """OCCT operation types."""
    BOOLEAN_FUSE = "boolean_fuse"
    BOOLEAN_CUT = "boolean_cut"
    BOOLEAN_COMMON = "boolean_common"
    FILLET = "fillet"
    CHAMFER = "chamfer"


class TopologyPhase(str, Enum):
    """Topology hash computation phases."""
    TOPO_HASH_START = "topo_hash_start"
    TOPO_HASH_PROGRESS = "topo_hash_progress"
    TOPO_HASH_END = "topo_hash_end"
    EXPORT_VALIDATION = "export_validation"


class ExportFormat(str, Enum):
    """Export formats."""
    FCSTD = "FCStd"
    STEP = "STEP"
    STL = "STL"
    GLB = "GLB"
    IGES = "IGES"
    OBJ = "OBJ"
    BREP = "BREP"


class ProgressMessageV2(BaseModel):
    """
    Progress message schema v2 with FreeCAD 1.1.0 enhancements.
    Supports both WebSocket and SSE transport.
    """
    
    # Core fields (always present)
    job_id: int = Field(..., description="Job ID being processed")
    event_id: int = Field(..., description="Monotonic event ID per job")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Schema and version info
    schema_version: str = Field(default="2.0", description="Progress schema version")
    freecad_version: Optional[str] = Field(None, description="FreeCAD version (e.g., 1.1.0)")
    occt_version: Optional[str] = Field(None, description="OCCT version (e.g., 7.8.1)")
    workbench: Optional[str] = Field(None, description="Active workbench (Part, PartDesign, Assembly4, Material)")
    platform: Optional[str] = Field(None, description="Platform info (linux, windows, darwin)")
    
    # Event classification
    event_type: EventType = Field(..., description="Type of progress event")
    operation_id: Optional[UUID] = Field(None, description="Stable UUID per operation within job")
    operation_name: Optional[str] = Field(None, description="Human-readable operation name")
    operation_group: Optional[OperationGroup] = Field(None, description="Operation category")
    
    # Phase and progress tracking
    phase: Optional[Phase] = Field(None, description="Operation phase")
    subphase: Optional[str] = Field(None, description="Detailed subphase identifier")
    step_index: Optional[int] = Field(None, ge=0, description="Current step number")
    step_total: Optional[int] = Field(None, ge=0, description="Total number of steps")
    items_done: Optional[int] = Field(None, ge=0, description="Items completed")
    items_total: Optional[int] = Field(None, ge=0, description="Total items to process")
    
    # Legacy fields for backward compatibility
    status: Optional[str] = Field(None, description="Job status (backward compat)")
    progress_pct: Optional[int] = Field(None, ge=0, le=100, description="Progress percentage (0-100)")
    current_step: Optional[str] = Field(None, description="Current step description")
    message: Optional[str] = Field(None, description="Progress message")
    
    # Time tracking
    eta_ms: Optional[int] = Field(None, ge=0, description="Estimated time to completion in milliseconds")
    elapsed_ms: Optional[int] = Field(None, ge=0, description="Elapsed time in milliseconds")
    
    # Document and object info
    document_id: Optional[str] = Field(None, description="FreeCAD document identifier")
    document_label: Optional[str] = Field(None, description="FreeCAD document label")
    object_name: Optional[str] = Field(None, description="Object being processed")
    object_type: Optional[str] = Field(None, description="Type of object (e.g., Part::Box, PartDesign::Body)")
    feature_type: Optional[str] = Field(None, description="Feature type being created")
    
    # Assembly4-specific fields
    constraints_resolved: Optional[int] = Field(None, ge=0, description="Number of constraints resolved")
    constraints_total: Optional[int] = Field(None, ge=0, description="Total constraints to resolve")
    lcs_resolved: Optional[int] = Field(None, ge=0, description="LCS placements resolved")
    lcs_total: Optional[int] = Field(None, ge=0, description="Total LCS placements")
    lcs_name: Optional[str] = Field(None, description="Current LCS being placed")
    placements_done: Optional[int] = Field(None, ge=0, description="Placements completed")
    placements_total: Optional[int] = Field(None, ge=0, description="Total placements")
    iteration: Optional[int] = Field(None, ge=0, description="Solver iteration number")
    residual: Optional[float] = Field(None, ge=0, description="Solver residual value")
    
    # Material Framework fields
    library_name: Optional[str] = Field(None, description="Material library name")
    material_key: Optional[str] = Field(None, description="Material key/identifier")
    mat_uid: Optional[str] = Field(None, description="Material unique identifier")
    objects_done: Optional[int] = Field(None, ge=0, description="Objects with material applied")
    objects_total: Optional[int] = Field(None, ge=0, description="Total objects to apply material")
    appearance_bake: Optional[bool] = Field(None, description="Whether appearance is being baked")
    properties_list_preview: Optional[List[str]] = Field(None, description="Preview of material properties")
    
    # OCCT operation fields
    occt_op: Optional[OCCTOperation] = Field(None, description="OCCT operation type")
    shapes_done: Optional[int] = Field(None, ge=0, description="Shapes processed")
    shapes_total: Optional[int] = Field(None, ge=0, description="Total shapes to process")
    solids_in: Optional[int] = Field(None, ge=0, description="Input solids count")
    solids_out: Optional[int] = Field(None, ge=0, description="Output solids count")
    edges_done: Optional[int] = Field(None, ge=0, description="Edges processed")
    edges_total: Optional[int] = Field(None, ge=0, description="Total edges to process")
    default_radius: Optional[float] = Field(None, ge=0, description="Default fillet/chamfer radius")
    variable_radius: Optional[bool] = Field(None, description="Whether using variable radius")
    
    # Topology hash fields
    faces_done: Optional[int] = Field(None, ge=0, description="Faces hashed")
    faces_total: Optional[int] = Field(None, ge=0, description="Total faces to hash")
    vertices_done: Optional[int] = Field(None, ge=0, description="Vertices hashed")
    vertices_total: Optional[int] = Field(None, ge=0, description="Total vertices to hash")
    stable_id_mode: Optional[bool] = Field(None, description="Using stable ID mode")
    seed: Optional[int] = Field(None, description="Hash seed value")
    computed_hash: Optional[str] = Field(None, description="Computed topology hash")
    expected_hash: Optional[str] = Field(None, description="Expected topology hash")
    hash_match: Optional[bool] = Field(None, description="Whether hashes match")
    
    # Document graph fields
    nodes_done: Optional[int] = Field(None, ge=0, description="Graph nodes processed")
    nodes_total: Optional[int] = Field(None, ge=0, description="Total graph nodes")
    edges_graph_done: Optional[int] = Field(None, ge=0, description="Graph edges processed")
    edges_graph_total: Optional[int] = Field(None, ge=0, description="Total graph edges")
    
    # Export fields
    export_format: Optional[ExportFormat] = Field(None, description="Export file format")
    bytes_written: Optional[int] = Field(None, ge=0, description="Bytes written to file")
    bytes_total: Optional[int] = Field(None, ge=0, description="Total bytes to write")
    
    # Metadata and flags
    operation_metadata: Optional[Dict[str, Any]] = Field(None, description="Operation-specific metadata")
    milestone: bool = Field(default=False, description="Whether this is a milestone event")
    error_code: Optional[str] = Field(None, description="Error code if applicable")
    warning: Optional[str] = Field(None, description="Warning message if applicable")
    
    @field_validator("progress_pct")
    @classmethod
    def validate_progress(cls, v: Optional[int]) -> Optional[int]:
        """Ensure progress percentage is within valid range."""
        if v is not None and not 0 <= v <= 100:
            raise ValueError(f"progress_pct must be between 0 and 100, got {v}")
        return v
    
    @model_validator(mode="after")
    def compute_legacy_fields(self) -> "ProgressMessageV2":
        """Compute legacy fields for backward compatibility."""
        # Auto-compute progress_pct if not set but we have items
        if self.progress_pct is None and self.items_done is not None and self.items_total:
            self.progress_pct = min(100, int((self.items_done / self.items_total) * 100))
        
        # Set milestone for important phase transitions
        if self.phase in [Phase.START, Phase.END]:
            self.milestone = True
        
        # Set operation_group based on event_type if not set
        if self.operation_group is None:
            group_map = {
                EventType.ASSEMBLY4: OperationGroup.ASSEMBLY4,
                EventType.MATERIAL: OperationGroup.MATERIAL,
                EventType.OCCT: OperationGroup.OCCT,
                EventType.TOPOLOGY_HASH: OperationGroup.TOPOLOGY,
                EventType.DOC_GRAPH: OperationGroup.DOC_GRAPH,
                EventType.DOCUMENT: OperationGroup.DOCUMENT,
                EventType.EXPORT: OperationGroup.EXPORT,
            }
            self.operation_group = group_map.get(self.event_type, OperationGroup.GENERAL)
        
        return self
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
            Decimal: lambda v: float(v),
        }
        use_enum_values = True
        validate_assignment = True


class ProgressSubscription(BaseModel):
    """WebSocket/SSE subscription configuration."""
    job_id: int = Field(..., description="Job ID to subscribe to")
    last_event_id: Optional[int] = Field(None, description="Last event ID for resumption")
    filter_types: Optional[List[EventType]] = Field(None, description="Event types to filter")
    include_milestones_only: bool = Field(default=False, description="Only send milestone events")


class ProgressStreamResponse(BaseModel):
    """Response wrapper for progress streams."""
    event: str = Field(default="progress", description="SSE event type")
    id: int = Field(..., description="Event ID for SSE")
    data: ProgressMessageV2 = Field(..., description="Progress message payload")
    retry: Optional[int] = Field(None, description="SSE retry interval in milliseconds")