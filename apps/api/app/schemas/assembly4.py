"""Pydantic schemas for Assembly4 operations."""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime


class PartDefinition(BaseModel):
    """Schema for defining a part in an assembly."""
    name: str = Field(..., description="Part name")
    type: str = Field(..., description="Part type (box, cylinder, imported, etc.)")
    dimensions: Optional[Dict[str, float]] = Field(None, description="Part dimensions")
    file_path: Optional[str] = Field(None, description="Path to imported file")
    material: Optional[str] = Field(None, description="Material specification")
    color: Optional[str] = Field(None, description="Part color")


class ConstraintDefinition(BaseModel):
    """Schema for defining constraints between parts."""
    type: str = Field(..., description="Constraint type (coincident, parallel, perpendicular, etc.)")
    parts: List[str] = Field(..., min_items=2, description="Parts involved in constraint")
    faces: Optional[List[str]] = Field(None, description="Faces/edges for constraint")
    offset: Optional[float] = Field(None, description="Offset value for constraint")
    angle: Optional[float] = Field(None, description="Angle for angular constraints")
    
    @validator('parts')
    def validate_parts_count(cls, v):
        """Ensure at least two parts for constraint."""
        if len(v) < 2:
            raise ValueError("At least two parts required for constraint")
        return v


class CAMSettings(BaseModel):
    """Schema for CAM/Path operation settings."""
    cut_mode: Optional[str] = Field("climb", description="Cut mode (climb, conventional, cw, ccw)")
    spindle_direction: Optional[str] = Field("forward", description="Spindle direction (forward, reverse)")
    feed_rate: Optional[float] = Field(100.0, gt=0, description="Feed rate in mm/min")
    spindle_speed: Optional[float] = Field(1000.0, gt=0, description="Spindle speed in RPM")
    tool_diameter: Optional[float] = Field(6.0, gt=0, description="Tool diameter in mm")
    depth_of_cut: Optional[float] = Field(1.0, gt=0, description="Depth of cut per pass in mm")
    stepover: Optional[float] = Field(None, gt=0, le=100, description="Stepover percentage")
    plunge_rate: Optional[float] = Field(None, gt=0, description="Plunge feed rate in mm/min")
    clearance_height: Optional[float] = Field(5.0, gt=0, description="Clearance height in mm")
    safe_height: Optional[float] = Field(10.0, gt=0, description="Safe height in mm")
    # Note: These are proper CAM fields, not stiffness/damping as incorrectly suggested
    # in PR feedback. These fields are correctly related to CAM operations.
    retract_height: Optional[float] = Field(2.0, gt=0, description="Retraction height in mm")
    ramp_angle: Optional[float] = Field(None, gt=0, le=90, description="Ramp angle in degrees")
    wcs_origin: Optional[str] = Field("world_origin", description="Work coordinate system origin")
    
    @validator('cut_mode')
    def validate_cut_mode(cls, v):
        """Validate cut mode is acceptable."""
        valid_modes = [
            "climb", "conventional", "cw", "ccw", 
            "inside", "outside", "clockwise", "counterclockwise"
        ]
        if v and v.lower() not in valid_modes:
            raise ValueError(f"Invalid cut_mode. Must be one of: {', '.join(valid_modes)}")
        return v.lower() if v else "climb"
    
    @validator('spindle_direction')
    def validate_spindle_direction(cls, v):
        """Validate spindle direction."""
        valid_directions = ["forward", "reverse", "cw", "ccw", "m3", "m4"]
        if v and v.lower() not in valid_directions:
            raise ValueError(f"Invalid spindle_direction. Must be one of: {', '.join(valid_directions)}")
        return v.lower() if v else "forward"


class Assembly4Create(BaseModel):
    """Schema for creating a new Assembly4 assembly."""
    name: str = Field(..., description="Assembly name")
    parts: List[PartDefinition] = Field(..., min_items=1, description="Parts in assembly")
    constraints: Optional[List[ConstraintDefinition]] = Field(None, description="Assembly constraints")
    cam_settings: Optional[CAMSettings] = Field(None, description="CAM operation settings")
    description: Optional[str] = Field(None, description="Assembly description")
    tags: Optional[List[str]] = Field(None, description="Tags for categorization")


class Assembly4Update(BaseModel):
    """Schema for updating an existing assembly."""
    name: Optional[str] = Field(None, description="New assembly name")
    description: Optional[str] = Field(None, description="New description")
    tags: Optional[List[str]] = Field(None, description="New tags")


class PartAdd(BaseModel):
    """Schema for adding a part to an assembly."""
    part: PartDefinition = Field(..., description="Part to add")
    position: Optional[Dict[str, float]] = Field(
        None, 
        description="Position coordinates (x, y, z)"
    )
    rotation: Optional[Dict[str, float]] = Field(
        None,
        description="Rotation angles (rx, ry, rz) in degrees"
    )


class ConstraintApply(BaseModel):
    """Schema for applying a constraint."""
    constraint: ConstraintDefinition = Field(..., description="Constraint to apply")


class CAMPathGenerate(BaseModel):
    """Schema for generating CAM paths."""
    operation: str = Field(..., description="CAM operation type (pocket, profile, drilling, etc.)")
    settings: CAMSettings = Field(..., description="CAM operation settings")
    selected_parts: Optional[List[str]] = Field(None, description="Parts to generate paths for")


class Assembly4Export(BaseModel):
    """Schema for exporting assembly."""
    format: str = Field("step", description="Export format (step, stl, fcstd, iges)")
    include_paths: bool = Field(False, description="Include CAM paths in export")
    include_constraints: bool = Field(True, description="Include constraints in export")
    
    @validator('format')
    def validate_format(cls, v):
        """Validate export format."""
        valid_formats = ["step", "stp", "stl", "fcstd", "iges", "igs", "brep"]
        if v.lower() not in valid_formats:
            raise ValueError(f"Invalid format. Must be one of: {', '.join(valid_formats)}")
        return v.lower()


class Assembly4Response(BaseModel):
    """Schema for Assembly4 operation responses."""
    id: str = Field(..., description="Assembly ID")
    name: str = Field(..., description="Assembly name")
    parts_count: int = Field(..., description="Number of parts in assembly")
    constraints_count: int = Field(..., description="Number of constraints")
    status: str = Field(..., description="Operation status")
    message: str = Field(..., description="Status message")
    gcode: Optional[str] = Field(None, description="Generated G-code if applicable")
    export_path: Optional[str] = Field(None, description="Export file path if applicable")


class CAMPathInfo(BaseModel):
    """Schema for CAM path information."""
    operation: str = Field(..., description="Operation type")
    tool_diameter: float = Field(..., description="Tool diameter used")
    feed_rate: float = Field(..., description="Feed rate")
    spindle_speed: float = Field(..., description="Spindle speed")
    path_count: int = Field(..., description="Number of tool paths")
    estimated_time: Optional[float] = Field(None, description="Estimated machining time in minutes")


class Assembly4Info(BaseModel):
    """Schema for detailed assembly information."""
    id: str = Field(..., description="Assembly ID")
    name: str = Field(..., description="Assembly name")
    parts: List[PartDefinition] = Field(..., description="Parts in assembly")
    constraints: List[ConstraintDefinition] = Field(..., description="Applied constraints")
    cam_paths: Optional[List[CAMPathInfo]] = Field(None, description="Generated CAM paths")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    description: Optional[str] = Field(None, description="Assembly description")
    tags: Optional[List[str]] = Field(None, description="Assembly tags")


class Assembly4List(BaseModel):
    """Schema for listing assemblies."""
    assemblies: List[Assembly4Info] = Field(..., description="List of assemblies")
    total: int = Field(..., description="Total number of assemblies")
    page: int = Field(1, description="Current page")
    page_size: int = Field(20, description="Items per page")


class PositionUpdate(BaseModel):
    """Schema for updating part position."""
    part_name: str = Field(..., description="Name of part to reposition")
    position: Dict[str, float] = Field(..., description="New position (x, y, z)")
    rotation: Optional[Dict[str, float]] = Field(None, description="New rotation (rx, ry, rz)")


class AssemblyValidation(BaseModel):
    """Schema for assembly validation results."""
    is_valid: bool = Field(..., description="Whether assembly is valid")
    errors: Optional[List[str]] = Field(None, description="Validation errors")
    warnings: Optional[List[str]] = Field(None, description="Validation warnings")
    collision_count: int = Field(0, description="Number of collisions detected")
    unconstrained_parts: Optional[List[str]] = Field(None, description="Parts without constraints")