"""
Ultra-Enterprise Assembly4 JSON Schema Definitions for Task 7.8

This module provides comprehensive Pydantic schemas for Assembly4 JSON parsing
with full constraint handling, OndselSolver integration, and CAM generation.

Features:
- Assembly4 JSON schema validation
- LCS (Local Coordinate System) definitions
- Constraint types (Attachment, AxisCoincident, PlaneCoincident, etc.)
- Part references and hierarchy
- Collision detection results
- DOF (Degrees of Freedom) analysis
- CAM generation parameters
- Export options
- Turkish localization for error messages
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from pydantic import PositiveInt, NonNegativeInt, PositiveFloat, NonNegativeFloat

logger = logging.getLogger(__name__)


# Constraint Types Enumeration
class ConstraintType(str, Enum):
    """Assembly4 constraint types."""
    ATTACHMENT = "Attachment"
    AXIS_COINCIDENT = "AxisCoincident"
    PLANE_COINCIDENT = "PlaneCoincident"
    POINT_ON_LINE = "PointOnLine"
    ANGLE = "Angle"
    OFFSET = "Offset"
    POINT_COINCIDENT = "PointCoincident"
    PARALLEL = "Parallel"
    PERPENDICULAR = "Perpendicular"
    TANGENT = "Tangent"
    DISTANCE = "Distance"
    SYMMETRY = "Symmetry"


# Solver Types
class SolverType(str, Enum):
    """Available solver types."""
    ONDSEL = "ondsel"
    FALLBACK = "fallback"
    SEQUENTIAL = "sequential"


# Export Format Types
class ExportFormat(str, Enum):
    """Supported export formats."""
    FCSTD = "FCStd"
    STEP = "STEP"
    IGES = "IGES"
    STL = "STL"
    OBJ = "OBJ"
    BREP = "BREP"
    BOM_JSON = "BOM_JSON"
    BOM_CSV = "BOM_CSV"


# CAM Operation Types
class CAMOperationType(str, Enum):
    """Supported CAM operations."""
    FACING = "Facing"
    PROFILE = "Profile"
    POCKET = "Pocket"
    DRILLING = "Drilling"
    ADAPTIVE = "Adaptive"
    HELIX = "Helix"
    ENGRAVE = "Engrave"
    DEBURR = "Deburr"
    THREAD_MILLING = "ThreadMilling"


# CAM Strategy Types
class CAMStrategy(str, Enum):
    """CAM cutting strategies."""
    ZIGZAG = "ZigZag"
    OFFSET = "Offset"
    SPIRAL = "Spiral"
    ZIGZAG_OFFSET = "ZigZagOffset"
    LINE = "Line"
    GRID = "Grid"


# CAM Post Processor Types
class CAMPostProcessor(str, Enum):
    """Supported post processors."""
    LINUXCNC = "LinuxCNC"
    GRBL = "GRBL"
    MACH3 = "Mach3"
    MACH4 = "Mach4"
    HAAS = "Haas"
    FANUC = "Fanuc"
    SIEMENS = "Siemens"
    CENTROID = "Centroid"
    SMOOTHIE = "Smoothie"


# Base Classes
class Vector3D(BaseModel):
    """3D vector representation."""
    x: float = Field(default=0.0, description="X coordinate in mm")
    y: float = Field(default=0.0, description="Y coordinate in mm")
    z: float = Field(default=0.0, description="Z coordinate in mm")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {"x": 10.0, "y": 20.0, "z": 30.0}
    })


class Rotation3D(BaseModel):
    """3D rotation representation (Euler angles in radians)."""
    roll: float = Field(default=0.0, ge=-3.14159, le=3.14159, description="Roll angle in radians")
    pitch: float = Field(default=0.0, ge=-3.14159, le=3.14159, description="Pitch angle in radians")
    yaw: float = Field(default=0.0, ge=-3.14159, le=3.14159, description="Yaw angle in radians")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {"roll": 0.0, "pitch": 1.5708, "yaw": 0.0}
    })


class Placement(BaseModel):
    """FreeCAD placement (position and rotation)."""
    position: Vector3D = Field(default_factory=Vector3D, description="Position vector")
    rotation: Rotation3D = Field(default_factory=Rotation3D, description="Rotation angles")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "position": {"x": 0, "y": 0, "z": 0},
            "rotation": {"roll": 0, "pitch": 0, "yaw": 0}
        }
    })


class LCSDefinition(BaseModel):
    """Local Coordinate System definition."""
    name: str = Field(..., min_length=1, max_length=100, description="LCS unique name")
    placement: Placement = Field(default_factory=Placement, description="LCS placement")
    is_root: bool = Field(default=False, description="Is this the root LCS?")
    visible: bool = Field(default=True, description="LCS visibility in assembly")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "LCS_Base",
            "placement": {
                "position": {"x": 0, "y": 0, "z": 0},
                "rotation": {"roll": 0, "pitch": 0, "yaw": 0}
            },
            "is_root": True,
            "visible": True
        }
    })
    
    @field_validator("name")
    @classmethod
    def validate_lcs_name(cls, v: str) -> str:
        """Validate LCS name format."""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("LCS adı sadece alfanumerik karakterler, alt çizgi ve tire içerebilir")
        return v


class PartReference(BaseModel):
    """Reference to a part in the assembly."""
    id: str = Field(..., min_length=1, max_length=100, description="Unique part identifier")
    model_ref: str = Field(..., description="Path to model file (STEP/FCStd)")
    initial_placement: Optional[Placement] = Field(None, description="Initial placement")
    lcs_list: List[str] = Field(default_factory=list, description="List of LCS names in this part")
    quantity: PositiveInt = Field(default=1, description="Number of instances")
    visible: bool = Field(default=True, description="Part visibility")
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Part color (hex)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": "gear_1",
            "model_ref": "/models/gear.FCStd",
            "initial_placement": {
                "position": {"x": 0, "y": 0, "z": 0},
                "rotation": {"roll": 0, "pitch": 0, "yaw": 0}
            },
            "lcs_list": ["LCS_Input", "LCS_Output"],
            "quantity": 1,
            "visible": True,
            "color": "#FF5733"
        }
    })
    
    @field_validator("model_ref")
    @classmethod
    def validate_model_ref(cls, v: str) -> str:
        """Validate model reference format."""
        valid_extensions = (".fcstd", ".step", ".stp", ".iges", ".igs", ".brep")
        if not v.lower().endswith(valid_extensions):
            raise ValueError(f"Desteklenmeyen dosya formatı. Geçerli formatlar: {valid_extensions}")
        return v


class ConstraintReference(BaseModel):
    """Reference to a part/LCS for constraints."""
    part_id: str = Field(..., description="Part identifier")
    lcs_name: Optional[str] = Field(None, description="LCS name (if referencing LCS)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {"part_id": "gear_1", "lcs_name": "LCS_Output"}
    })


class AssemblyConstraint(BaseModel):
    """Assembly constraint definition."""
    id: Optional[str] = Field(None, description="Constraint identifier")
    type: ConstraintType = Field(..., description="Constraint type")
    reference1: ConstraintReference = Field(..., description="First reference")
    reference2: ConstraintReference = Field(..., description="Second reference")
    value: Optional[float] = Field(None, description="Constraint value (angle/distance)")
    tolerance: float = Field(default=0.01, gt=0, description="Constraint tolerance in mm")
    enabled: bool = Field(default=True, description="Is constraint active?")
    # Joint physics parameters (from old assembly)
    stiffness: Optional[float] = Field(None, ge=0, description="Joint stiffness coefficient")
    damping: Optional[float] = Field(None, ge=0, description="Joint damping coefficient")
    min_limit: Optional[float] = Field(None, description="Minimum joint limit (angle/distance)")
    max_limit: Optional[float] = Field(None, description="Maximum joint limit (angle/distance)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": "constraint_1",
            "type": "Attachment",
            "reference1": {"part_id": "gear_1", "lcs_name": "LCS_Output"},
            "reference2": {"part_id": "shaft_1", "lcs_name": "LCS_Input"},
            "value": None,
            "tolerance": 0.01,
            "enabled": True
        }
    })
    
    @model_validator(mode='after')
    def validate_constraint_requirements(self) -> 'AssemblyConstraint':
        """Validate constraint-specific requirements."""
        if self.type in [ConstraintType.ANGLE, ConstraintType.OFFSET, ConstraintType.DISTANCE]:
            if self.value is None:
                raise ValueError(f"{self.type} kısıtı için değer gereklidir")
        
        # Validate arity for different constraint types
        constraint_arity = {
            ConstraintType.ATTACHMENT: (True, True),  # Both need LCS
            ConstraintType.AXIS_COINCIDENT: (True, True),
            ConstraintType.PLANE_COINCIDENT: (True, True),
            ConstraintType.POINT_ON_LINE: (True, True),
            ConstraintType.POINT_COINCIDENT: (True, True),
        }
        
        if self.type in constraint_arity:
            needs_lcs1, needs_lcs2 = constraint_arity[self.type]
            if needs_lcs1 and not self.reference1.lcs_name:
                raise ValueError(f"{self.type} kısıtı için reference1'de LCS gereklidir")
            if needs_lcs2 and not self.reference2.lcs_name:
                raise ValueError(f"{self.type} kısıtı için reference2'de LCS gereklidir")
        
        # Validate joint physics parameters
        if self.stiffness is not None:
            if self.stiffness <= 0:
                raise ValueError(f"Joint stiffness must be greater than 0, got {self.stiffness}")
        
        if self.damping is not None:
            if self.damping < 0:
                raise ValueError(f"Joint damping must be greater than or equal to 0, got {self.damping}")
        
        # Optional: Check combined range for realistic values
        if self.stiffness is not None and self.damping is not None:
            # Damping ratio = damping / (2 * sqrt(stiffness * mass))
            # For stability, damping ratio should typically be < 1.0
            # Since we don't have mass, we can't calculate exact damping ratio
            # But we can ensure reasonable relative values
            if self.damping > 10 * self.stiffness:  # Overly damped system warning
                logger.warning(f"High damping ratio detected: damping={self.damping}, stiffness={self.stiffness}")
        
        # Validate joint limits
        if self.min_limit is not None and self.max_limit is not None:
            if self.min_limit >= self.max_limit:
                raise ValueError(f"Joint min_limit ({self.min_limit}) must be less than max_limit ({self.max_limit})")
        
        return self


class AssemblyHierarchy(BaseModel):
    """Assembly hierarchy definition."""
    root_part_id: Optional[str] = Field(None, description="Root part identifier")
    root_lcs_name: str = Field(default="LCS_Origin", description="Root LCS name")
    parent_child_map: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Parent-child relationship map"
    )
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "root_part_id": "base_plate",
            "root_lcs_name": "LCS_Origin",
            "parent_child_map": {
                "base_plate": ["gear_1", "gear_2"],
                "gear_1": ["shaft_1"]
            }
        }
    })


# Main Assembly4 Input Schema
class Assembly4Input(BaseModel):
    """Complete Assembly4 JSON input schema."""
    name: str = Field(..., min_length=1, max_length=200, description="Assembly name")
    description: Optional[str] = Field(None, description="Assembly description")
    parts: List[PartReference] = Field(..., min_length=1, description="List of parts")
    constraints: List[AssemblyConstraint] = Field(default_factory=list, description="Constraints")
    lcs_definitions: List[LCSDefinition] = Field(default_factory=list, description="LCS definitions")
    hierarchy: Optional[AssemblyHierarchy] = Field(None, description="Assembly hierarchy")
    solver_type: SolverType = Field(default=SolverType.ONDSEL, description="Solver to use")
    tolerance: float = Field(default=0.01, gt=0, le=1.0, description="Global tolerance in mm")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "Planetary Gearbox Assembly",
            "description": "3-stage planetary gearbox",
            "parts": [
                {
                    "id": "sun_gear",
                    "model_ref": "/models/sun_gear.FCStd",
                    "lcs_list": ["LCS_Center", "LCS_Teeth"]
                }
            ],
            "constraints": [
                {
                    "type": "Attachment",
                    "reference1": {"part_id": "sun_gear", "lcs_name": "LCS_Center"},
                    "reference2": {"part_id": "carrier", "lcs_name": "LCS_Sun"}
                }
            ],
            "solver_type": "ondsel"
        }
    })
    
    @model_validator(mode='after')
    def validate_assembly_consistency(self) -> 'Assembly4Input':
        """Validate assembly consistency."""
        # Check unique part IDs
        part_ids = [p.id for p in self.parts]
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("Part ID'leri benzersiz olmalıdır")
        
        # Check LCS references exist
        part_lcs_map = {p.id: set(p.lcs_list) for p in self.parts}
        
        for constraint in self.constraints:
            # Check part references (allow "world" or "ground" as special references for ground frame)
            special_parts = {"world", "ground"}
            if constraint.reference1.part_id not in part_ids and constraint.reference1.part_id not in special_parts:
                raise ValueError(f"Kısıt referansı bulunamadı: {constraint.reference1.part_id}")
            if constraint.reference2.part_id not in part_ids and constraint.reference2.part_id not in special_parts:
                raise ValueError(f"Kısıt referansı bulunamadı: {constraint.reference2.part_id}")
            
            # Check LCS references if specified
            if constraint.reference1.lcs_name:
                if constraint.reference1.lcs_name not in part_lcs_map.get(constraint.reference1.part_id, set()):
                    # Check global LCS definitions
                    global_lcs = {lcs.name for lcs in self.lcs_definitions}
                    if constraint.reference1.lcs_name not in global_lcs:
                        raise ValueError(
                            f"LCS bulunamadı: {constraint.reference1.lcs_name} "
                            f"(part: {constraint.reference1.part_id})"
                        )
            
            if constraint.reference2.lcs_name:
                if constraint.reference2.lcs_name not in part_lcs_map.get(constraint.reference2.part_id, set()):
                    global_lcs = {lcs.name for lcs in self.lcs_definitions}
                    if constraint.reference2.lcs_name not in global_lcs:
                        raise ValueError(
                            f"LCS bulunamadı: {constraint.reference2.lcs_name} "
                            f"(part: {constraint.reference2.part_id})"
                        )
        
        # Validate at least one grounded reference
        has_root = any(lcs.is_root for lcs in self.lcs_definitions)
        # Check specifically for attachment to world/ground (not just any attachment)
        has_fixed_part = any(
            c.type == ConstraintType.ATTACHMENT and 
            (c.reference1.part_id in {"world", "ground"} or 
             c.reference2.part_id in {"world", "ground"})
            for c in self.constraints
        )
        if not (has_root or has_fixed_part or (self.hierarchy and self.hierarchy.root_part_id)):
            raise ValueError("En az bir sabit referans (root LCS veya fixed base) gereklidir")
        
        return self


# Collision Detection Results
class CollisionPair(BaseModel):
    """Collision pair result."""
    part1_id: str = Field(..., description="First part ID")
    part2_id: str = Field(..., description="Second part ID")
    type: Literal["interference", "overlap", "contact"] = Field(..., description="Collision type")
    volume: Optional[float] = Field(None, ge=0, description="Interference volume in mm³")
    min_distance: Optional[float] = Field(None, description="Minimum distance between parts")
    contact_points: List[Vector3D] = Field(default_factory=list, description="Contact points")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "part1_id": "gear_1",
            "part2_id": "gear_2",
            "type": "interference",
            "volume": 125.5,
            "min_distance": -2.5
        }
    })


class CollisionReport(BaseModel):
    """Complete collision detection report."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tolerance: float = Field(..., description="Detection tolerance used")
    total_pairs_checked: int = Field(..., ge=0, description="Total pairs checked")
    collisions: List[CollisionPair] = Field(default_factory=list, description="Detected collisions")
    computation_time_ms: float = Field(..., ge=0, description="Computation time in milliseconds")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "tolerance": 0.01,
            "total_pairs_checked": 45,
            "collisions": [],
            "computation_time_ms": 234.5
        }
    })


# DOF Analysis Results
class DOFAnalysis(BaseModel):
    """Degrees of Freedom analysis result."""
    total_parts: int = Field(..., ge=1, description="Total number of parts")
    total_dof: int = Field(..., ge=0, description="Total degrees of freedom")
    constrained_dof: int = Field(..., ge=0, description="Constrained degrees of freedom")
    remaining_dof: int = Field(..., ge=0, description="Remaining degrees of freedom")
    is_fully_constrained: bool = Field(..., description="Is assembly fully constrained?")
    is_over_constrained: bool = Field(..., description="Is assembly over-constrained?")
    mobility: int = Field(..., description="Assembly mobility")
    constraint_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="DOF reduction per constraint type"
    )
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total_parts": 5,
            "total_dof": 30,
            "constrained_dof": 28,
            "remaining_dof": 2,
            "is_fully_constrained": False,
            "is_over_constrained": False,
            "mobility": 2,
            "constraint_breakdown": {
                "Attachment": 12,
                "AxisCoincident": 8,
                "PlaneCoincident": 6,
                "Angle": 2
            }
        }
    })


# CAM Generation Parameters
class ToolDefinition(BaseModel):
    """Cutting tool definition."""
    name: str = Field(..., description="Tool name")
    type: Literal["endmill", "ballmill", "drill", "chamfer", "engraver"] = Field(..., description="Tool type")
    diameter: PositiveFloat = Field(..., description="Tool diameter in mm")
    flutes: PositiveInt = Field(default=2, description="Number of flutes")
    length: PositiveFloat = Field(..., description="Tool length in mm")
    material: str = Field(default="HSS", description="Tool material (HSS, Carbide, Cobalt, etc.)")
    coating: Optional[str] = Field(default=None, description="Tool coating (TiN, TiAlN, DLC, etc.)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "6mm Endmill",
            "type": "endmill",
            "diameter": 6.0,
            "flutes": 4,
            "length": 50.0,
            "material": "Carbide",
            "coating": "TiAlN"
        }
    })


class FeedsAndSpeeds(BaseModel):
    """Feeds and speeds parameters."""
    spindle_speed: PositiveInt = Field(..., description="Spindle speed in RPM")
    feed_rate: PositiveFloat = Field(..., description="Feed rate in mm/min")
    plunge_rate: PositiveFloat = Field(..., description="Plunge rate in mm/min")
    step_down: PositiveFloat = Field(..., description="Step down in mm")
    step_over: PositiveFloat = Field(..., description="Step over percentage (0-100)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "spindle_speed": 12000,
            "feed_rate": 600,
            "plunge_rate": 200,
            "step_down": 2.0,
            "step_over": 40.0
        }
    })


class CAMOperation(BaseModel):
    """CAM operation definition."""
    name: str = Field(..., description="Operation name")
    type: CAMOperationType = Field(..., description="Operation type")
    tool: ToolDefinition = Field(..., description="Tool to use")
    feeds_speeds: FeedsAndSpeeds = Field(..., description="Feeds and speeds")
    strategy: CAMStrategy = Field(default=CAMStrategy.ZIGZAG, description="Cutting strategy")
    cut_mode: Literal["climb", "conventional"] = Field(default="climb", description="Cut mode")
    coolant: bool = Field(default=True, description="Use coolant")
    finish_pass: bool = Field(default=False, description="Add finish pass")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "Pocket Operation",
            "type": "Pocket",
            "tool": {
                "name": "6mm Endmill",
                "type": "endmill",
                "diameter": 6.0,
                "flutes": 4,
                "length": 50.0
            },
            "feeds_speeds": {
                "spindle_speed": 12000,
                "feed_rate": 600,
                "plunge_rate": 200,
                "step_down": 2.0,
                "step_over": 40.0
            },
            "strategy": "ZigZag",
            "cut_mode": "climb",
            "coolant": True
        }
    })


class StockDefinition(BaseModel):
    """Stock material definition."""
    type: Literal["box", "cylinder", "from_shape"] = Field(..., description="Stock type")
    material: str = Field(default="Aluminum", description="Stock material")
    margins: Vector3D = Field(default_factory=lambda: Vector3D(x=5, y=5, z=5), description="Stock margins")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "type": "box",
            "material": "Aluminum 6061",
            "margins": {"x": 5, "y": 5, "z": 2}
        }
    })


class CAMJobParameters(BaseModel):
    """CAM job parameters."""
    wcs_origin: Optional[str] = Field(None, description="WCS origin LCS name")
    wcs_offset: Vector3D = Field(default_factory=Vector3D, description="WCS offset")
    stock: StockDefinition = Field(..., description="Stock definition")
    operations: List[CAMOperation] = Field(..., min_length=1, description="CAM operations")
    post_processor: CAMPostProcessor = Field(default=CAMPostProcessor.LINUXCNC, description="Post processor")
    safety_height: float = Field(default=10.0, gt=0, description="Safety height in mm")
    clearance_height: float = Field(default=5.0, gt=0, description="Clearance height in mm")
    rapid_feed_rate: PositiveFloat = Field(default=5000, description="Rapid feed rate mm/min")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "wcs_origin": "LCS_Origin",
            "stock": {"type": "box", "material": "Aluminum"},
            "operations": [],
            "post_processor": "LinuxCNC",
            "safety_height": 10.0
        }
    })


# Export Options
class ExportOptions(BaseModel):
    """Export options for assembly."""
    formats: List[ExportFormat] = Field(..., min_length=1, description="Export formats")
    include_hidden: bool = Field(default=False, description="Include hidden parts")
    generate_exploded: bool = Field(default=False, description="Generate exploded view")
    exploded_factor: float = Field(default=1.5, gt=1.0, le=5.0, description="Explosion factor")
    merge_step: bool = Field(default=True, description="Merge into single STEP file")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "formats": ["FCStd", "STEP", "BOM_JSON"],
            "include_hidden": False,
            "generate_exploded": True,
            "exploded_factor": 2.0
        }
    })


# BOM (Bill of Materials) Output
class BOMEntry(BaseModel):
    """Bill of Materials entry."""
    part_id: str = Field(..., description="Part identifier")
    name: str = Field(..., description="Part name")
    source: str = Field(..., description="Source file")
    quantity: PositiveInt = Field(..., description="Quantity")
    material: Optional[str] = Field(None, description="Material")
    weight: Optional[float] = Field(None, ge=0, description="Weight in grams")
    cost: Optional[Decimal] = Field(None, ge=0, description="Cost per unit")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "part_id": "gear_1",
            "name": "Sun Gear",
            "source": "/models/sun_gear.FCStd",
            "quantity": 1,
            "material": "Steel",
            "weight": 250.5,
            "cost": Decimal("15.50")
        }
    })


class BillOfMaterials(BaseModel):
    """Complete Bill of Materials."""
    assembly_name: str = Field(..., description="Assembly name")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    entries: List[BOMEntry] = Field(..., description="BOM entries")
    total_parts: int = Field(..., ge=0, description="Total unique parts")
    total_quantity: int = Field(..., ge=0, description="Total quantity")
    total_weight: Optional[float] = Field(None, ge=0, description="Total weight in grams")
    total_cost: Optional[Decimal] = Field(None, ge=0, description="Total cost")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "assembly_name": "Planetary Gearbox",
            "entries": [],
            "total_parts": 15,
            "total_quantity": 42
        }
    })


# Assembly Result
class AssemblyResult(BaseModel):
    """Complete assembly generation result."""
    job_id: str = Field(..., description="Job identifier")
    status: Literal["success", "partial", "failed"] = Field(..., description="Assembly status")
    assembly_file: Optional[str] = Field(None, description="Path to assembly FCStd file")
    exploded_file: Optional[str] = Field(None, description="Path to exploded view FCStd")
    step_file: Optional[str] = Field(None, description="Path to STEP export")
    bom: Optional[BillOfMaterials] = Field(None, description="Bill of Materials")
    collision_report: Optional[CollisionReport] = Field(None, description="Collision report")
    dof_analysis: Optional[DOFAnalysis] = Field(None, description="DOF analysis")
    cam_files: Optional[List[str]] = Field(None, description="Generated CAM files")
    errors: List[str] = Field(default_factory=list, description="Error messages")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
    computation_time_ms: float = Field(..., ge=0, description="Total computation time")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "job_id": "job_12345",
            "status": "success",
            "assembly_file": "/outputs/assembly.FCStd",
            "computation_time_ms": 1234.5
        }
    })


# CAM Result
class CAMResult(BaseModel):
    """CAM generation result."""
    job_file: str = Field(..., description="Path to job FCStd with paths")
    gcode_files: Dict[str, str] = Field(..., description="Post processor to G-code file mapping")
    cam_report: Dict[str, Any] = Field(..., description="CAM report with details")
    estimated_time_min: float = Field(..., ge=0, description="Estimated machining time in minutes")
    tool_changes: int = Field(..., ge=0, description="Number of tool changes")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "job_file": "/outputs/job.FCStd",
            "gcode_files": {"LinuxCNC": "/outputs/job.ngc"},
            "cam_report": {},
            "estimated_time_min": 45.5,
            "tool_changes": 3
        }
    })


# Request/Response Models for API
class Assembly4Request(BaseModel):
    """API request for Assembly4 processing."""
    input: Assembly4Input = Field(..., description="Assembly4 input data")
    generate_cam: bool = Field(default=False, description="Generate CAM paths")
    cam_parameters: Optional[CAMJobParameters] = Field(None, description="CAM parameters")
    export_options: ExportOptions = Field(
        default_factory=lambda: ExportOptions(formats=["FCStd"]), 
        description="Export options"
    )
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "input": {},
            "generate_cam": False,
            "export_options": {
                "formats": ["FCStd", "STEP"]
            }
        }
    })


class Assembly4Response(BaseModel):
    """API response for Assembly4 processing."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Processing status")
    assembly_result: Optional[AssemblyResult] = Field(None, description="Assembly result")
    cam_result: Optional[CAMResult] = Field(None, description="CAM result")
    signed_urls: Optional[Dict[str, str]] = Field(None, description="Signed URLs for downloads")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "job_id": "job_12345",
            "status": "completed",
            "signed_urls": {
                "assembly": "https://...",
                "step": "https://...",
                "bom": "https://..."
            }
        }
    })