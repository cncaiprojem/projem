"""
Pydantic v2 Schemas for Design API v1 - Task 7.1
Enterprise-grade model generation endpoint schemas with discriminated unions.

Features:
- Discriminated unions for design inputs
- Strict field validation with Turkish error messages
- UUID and enum type constraints
- Cross-field validators for material/process compatibility
- Units normalization and dimension validation
"""

from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union, ClassVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    PositiveFloat,
    PositiveInt,
    constr,
    conint,
)
from pydantic_settings import BaseSettings


# Enums for strict typing

class DesignUnit(str, Enum):
    """Supported measurement units."""
    MILLIMETER = "mm"
    CENTIMETER = "cm"
    METER = "m"
    INCH = "in"
    FOOT = "ft"


class MaterialType(str, Enum):
    """Supported material types."""
    STEEL = "steel"
    ALUMINUM = "aluminum"
    PLASTIC_ABS = "plastic_abs"
    PLASTIC_PLA = "plastic_pla"
    PLASTIC_PETG = "plastic_petg"
    WOOD_OAK = "wood_oak"
    WOOD_PINE = "wood_pine"
    BRASS = "brass"
    COPPER = "copper"
    TITANIUM = "titanium"


class ProcessType(str, Enum):
    """Manufacturing process types."""
    CNC_MILLING = "cnc_milling"
    CNC_TURNING = "cnc_turning"
    THREE_D_PRINTING = "3d_printing"
    LASER_CUTTING = "laser_cutting"
    WATER_JET = "water_jet"
    WIRE_EDM = "wire_edm"


class AssemblyConstraintType(str, Enum):
    """Assembly4 constraint types."""
    COINCIDENT = "coincident"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    ANGLE = "angle"
    DISTANCE = "distance"
    TANGENT = "tangent"
    CONCENTRIC = "concentric"


# Design constraints configuration
class DesignSettings(BaseSettings):
    """
    Configurable settings for design constraints.
    
    These settings can be overridden via environment variables or config files,
    allowing different manufacturing constraints for different enterprise deployments.
    """
    model_config = ConfigDict(
        env_prefix="DESIGN_",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Dimension limits (in millimeters)
    max_dimension_mm: float = Field(
        default=100_000,  # 100 meters in mm
        description="Maximum allowed dimension in millimeters",
        gt=0
    )
    min_dimension_mm: float = Field(
        default=0.001,  # 1 micrometer in mm
        description="Minimum allowed dimension in millimeters",
        gt=0
    )
    
    # Additional configurable constraints
    max_assembly_parts: int = Field(
        default=1000,
        description="Maximum number of parts in an assembly",
        gt=0
    )
    max_file_size_mb: int = Field(
        default=500,
        description="Maximum file upload size in megabytes",
        gt=0
    )
    max_prompt_length: int = Field(
        default=2000,
        description="Maximum length of AI prompt",
        gt=0
    )
    
    # Tolerance settings
    default_tolerance_percent: float = Field(
        default=0.1,
        description="Default tolerance as percentage of dimension",
        ge=0,
        le=10
    )
    
    # Process-specific constraints
    cnc_min_feature_size_mm: float = Field(
        default=0.5,
        description="Minimum feature size for CNC milling",
        gt=0
    )
    printing_3d_layer_height_mm: float = Field(
        default=0.1,
        description="Default layer height for 3D printing",
        gt=0
    )


# Factory function for settings - allows context-specific configuration
def get_design_settings(**overrides) -> DesignSettings:
    """
    Returns a DesignSettings instance.
    Pass overrides as keyword arguments for testing or context-specific configuration.
    
    This pattern allows for:
    - Different settings in test environments
    - Per-tenant configuration in multi-tenant deployments
    - Easy mocking and dependency injection
    
    Examples:
        # Default settings
        settings = get_design_settings()
        
        # Test with specific limits
        test_settings = get_design_settings(max_dimension_mm=1000)
        
        # Production override
        prod_settings = get_design_settings(max_assembly_parts=5000)
    """
    return DesignSettings(**overrides)


# Thread-local storage for design settings to avoid concurrency issues
_design_settings_local = threading.local()

# Context manager for temporary settings override (useful for testing)
class design_settings_context:
    """
    Context manager for temporarily overriding design settings using thread-local storage.
    This ensures thread safety in concurrent environments.
    
    Usage:
        with design_settings_context(max_dimension_mm=1000):
            # Code here uses the overridden settings
            validate_dimension(value)
    """
    def __init__(self, **overrides):
        self.overrides = overrides
        self.original_settings = None
        
    def __enter__(self):
        self.original_settings = getattr(_design_settings_local, "settings", None)
        _design_settings_local.settings = get_design_settings(**self.overrides)
        return _design_settings_local.settings
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.original_settings is not None:
            _design_settings_local.settings = self.original_settings
        else:
            if hasattr(_design_settings_local, "settings"):
                del _design_settings_local.settings


def current_design_settings() -> DesignSettings:
    """
    Returns the current thread-local design settings, or the default singleton if not set.
    This ensures thread safety when using the context manager.
    """
    return getattr(_design_settings_local, "settings", _default_design_settings)


# Default singleton for backward compatibility
# Prefer using get_design_settings() or dependency injection in new code
_default_design_settings = get_design_settings()
design_settings = _default_design_settings  # Backward compatibility alias

# NOTE: To override settings in tests, you can use:
# 1. Context manager for temporary override:
#    with design_settings_context(max_dimension_mm=1000):
#        # test code here
# 2. Monkeypatch to replace design_settings:
#    monkeypatch.setattr('app.schemas.design_v2.design_settings', get_design_settings(max_dimension_mm=1000))
# 3. Replace individual attributes:
#    monkeypatch.setattr(design_settings, 'max_dimension_mm', 1000)
# 4. Dependency injection in routers/services:
#    def create_design(settings: DesignSettings = Depends(get_design_settings))


# Base models with strict validation

class DimensionSpec(BaseModel):
    """Dimension specification with units."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    value: PositiveFloat = Field(..., description="Dimension value", gt=0)
    unit: DesignUnit = Field(DesignUnit.MILLIMETER, description="Measurement unit")
    tolerance: Optional[PositiveFloat] = Field(None, description="Tolerance value", gt=0)
    
    @field_validator("value")
    @classmethod
    def validate_reasonable_dimension(cls, v: float) -> float:
        """Ensure dimensions are within configurable bounds."""
        # Use thread-safe current_design_settings() instead of global design_settings
        # This prevents race conditions in multi-threaded environments
        settings = current_design_settings()
        if v > settings.max_dimension_mm:
            raise ValueError(f"Boyut çok büyük (maksimum {settings.max_dimension_mm}mm)")
        if v < settings.min_dimension_mm:
            raise ValueError(f"Boyut çok küçük (minimum {settings.min_dimension_mm}mm)")
        return v
    
    def to_mm(self) -> float:
        """Convert dimension to millimeters."""
        conversions = {
            DesignUnit.MILLIMETER: 1.0,
            DesignUnit.CENTIMETER: 10.0,
            DesignUnit.METER: 1000.0,
            DesignUnit.INCH: 25.4,
            DesignUnit.FOOT: 304.8,
        }
        return self.value * conversions[self.unit]


class MaterialSpec(BaseModel):
    """Material specification with process compatibility."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    type: MaterialType = Field(..., description="Material type")
    grade: Optional[str] = Field(None, description="Material grade/specification")
    surface_finish: Optional[str] = Field(None, description="Surface finish requirement")
    
    def is_compatible_with_process(self, process: ProcessType) -> bool:
        """Check if material is compatible with manufacturing process."""
        compatibility = {
            ProcessType.CNC_MILLING: [MaterialType.STEEL, MaterialType.ALUMINUM, MaterialType.BRASS, MaterialType.COPPER],
            ProcessType.CNC_TURNING: [MaterialType.STEEL, MaterialType.ALUMINUM, MaterialType.BRASS, MaterialType.COPPER],
            ProcessType.THREE_D_PRINTING: [MaterialType.PLASTIC_ABS, MaterialType.PLASTIC_PLA, MaterialType.PLASTIC_PETG],
            ProcessType.LASER_CUTTING: [MaterialType.STEEL, MaterialType.ALUMINUM, MaterialType.WOOD_OAK, MaterialType.WOOD_PINE],
            ProcessType.WATER_JET: [MaterialType.STEEL, MaterialType.ALUMINUM, MaterialType.TITANIUM],
            ProcessType.WIRE_EDM: [MaterialType.STEEL, MaterialType.TITANIUM, MaterialType.BRASS],
        }
        return self.type in compatibility.get(process, [])


# Discriminated union for design inputs

class DesignPromptInput(BaseModel):
    """AI-powered design generation from natural language prompt."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    type: Literal["prompt"] = Field("prompt", description="Input type discriminator")
    prompt: constr(min_length=10, max_length=2000) = Field(
        ..., 
        description="Natural language design description",
        examples=["10mm çapında 50mm uzunluğunda mil tasarla"]
    )
    context: Optional[str] = Field(None, description="Additional context", max_length=1000)
    max_iterations: conint(ge=1, le=10) = Field(3, description="Max AI refinement iterations")
    temperature: float = Field(0.7, ge=0.0, le=1.0, description="AI creativity level")
    
    @field_validator("prompt")
    @classmethod
    def validate_prompt_content(cls, v: str) -> str:
        """Validate prompt contains meaningful content."""
        if len(v.split()) < 3:
            raise ValueError("Prompt en az 3 kelime içermelidir")
        # Use thread-safe current_design_settings()
        settings = current_design_settings()
        if len(v) > settings.max_prompt_length:
            raise ValueError(f"Prompt çok uzun (maksimum {settings.max_prompt_length} karakter)")
        return v


class DesignParametricInput(BaseModel):
    """Parametric design generation with explicit dimensions."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    type: Literal["params"] = Field("params", description="Input type discriminator")
    template_id: str = Field(..., description="Parametric template identifier")
    dimensions: Dict[str, DimensionSpec] = Field(
        ..., 
        description="Named dimensions",
        min_length=1,
        max_length=50
    )
    material: MaterialSpec = Field(..., description="Material specification")
    process: ProcessType = Field(..., description="Manufacturing process")
    quantity: PositiveInt = Field(1, description="Production quantity")
    
    @model_validator(mode="after")
    def validate_material_process_compatibility(self) -> "DesignParametricInput":
        """Ensure material is compatible with selected process."""
        if not self.material.is_compatible_with_process(self.process):
            raise ValueError(
                f"{self.material.type.value} malzemesi {self.process.value} "
                f"işlemi ile uyumlu değil"
            )
        return self


class DesignUploadInput(BaseModel):
    """Design upload with file reference."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    type: Literal["upload"] = Field("upload", description="Input type discriminator")
    s3_key: constr(min_length=1, max_length=500) = Field(
        ..., 
        description="S3 object key for uploaded file"
    )
    file_format: constr(pattern=r"^\.(step|stp|iges|igs|stl|fcstd|brep)$") = Field(
        ..., 
        description="File format extension"
    )
    file_size: conint(gt=0, le=104857600) = Field(  # 100MB limit
        ..., 
        description="File size in bytes"
    )
    sha256: constr(pattern=r"^[a-f0-9]{64}$") = Field(
        ..., 
        description="SHA256 checksum of file"
    )
    conversion_target: Optional[str] = Field(
        None, 
        description="Target format for conversion"
    )


class Assembly4Constraint(BaseModel):
    """Assembly4 constraint definition."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    type: AssemblyConstraintType = Field(..., description="Constraint type")
    part1: str = Field(..., description="First part reference")
    part2: str = Field(..., description="Second part reference")
    feature1: Optional[str] = Field(None, description="Feature on part1")
    feature2: Optional[str] = Field(None, description="Feature on part2")
    value: Optional[float] = Field(None, description="Constraint value (for angle/distance)")
    
    @model_validator(mode="after")
    def validate_constraint_requirements(self) -> "Assembly4Constraint":
        """Validate constraint-specific requirements."""
        if self.type in [AssemblyConstraintType.ANGLE, AssemblyConstraintType.DISTANCE]:
            if self.value is None:
                raise ValueError(f"{self.type.value} kısıtı için değer gerekli")
        return self


# Part type specific models with dimension validation
class CylinderPart(BaseModel):
    """Cylinder part with specific dimension requirements."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    name: str = Field(..., description="Part name/identifier", min_length=1, max_length=100)
    part_type: Literal["cylinder"] = Field("cylinder", description="Part type discriminator")
    radius: PositiveFloat = Field(..., description="Cylinder radius", gt=0)
    height: PositiveFloat = Field(..., description="Cylinder height", gt=0)
    material: Optional[str] = Field(None, description="Part material")
    quantity: int = Field(1, description="Number of instances", ge=1, le=100)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional part metadata")
    
    @field_validator("radius", "height")
    @classmethod
    def validate_dimensions(cls, v: float) -> float:
        """Validate dimension bounds using configurable settings."""
        # Use thread-safe current_design_settings()
        settings = current_design_settings()
        if v > settings.max_dimension_mm:
            raise ValueError(f"Boyut çok büyük (maksimum {settings.max_dimension_mm}mm)")
        if v < settings.min_dimension_mm:
            raise ValueError(f"Boyut çok küçük (minimum {settings.min_dimension_mm}mm)")
        return v


class BoxPart(BaseModel):
    """Box part with specific dimension requirements."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    name: str = Field(..., description="Part name/identifier", min_length=1, max_length=100)
    part_type: Literal["box"] = Field("box", description="Part type discriminator")
    width: PositiveFloat = Field(..., description="Box width", gt=0)
    height: PositiveFloat = Field(..., description="Box height", gt=0)
    depth: PositiveFloat = Field(..., description="Box depth", gt=0)
    material: Optional[str] = Field(None, description="Part material")
    quantity: int = Field(1, description="Number of instances", ge=1, le=100)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional part metadata")
    
    @field_validator("width", "height", "depth")
    @classmethod
    def validate_dimensions(cls, v: float) -> float:
        """Validate dimension bounds using configurable settings."""
        # Use thread-safe current_design_settings()
        settings = current_design_settings()
        if v > settings.max_dimension_mm:
            raise ValueError(f"Boyut çok büyük (maksimum {settings.max_dimension_mm}mm)")
        if v < settings.min_dimension_mm:
            raise ValueError(f"Boyut çok küçük (minimum {settings.min_dimension_mm}mm)")
        return v


class SpherePart(BaseModel):
    """Sphere part with specific dimension requirements."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    name: str = Field(..., description="Part name/identifier", min_length=1, max_length=100)
    part_type: Literal["sphere"] = Field("sphere", description="Part type discriminator")
    radius: PositiveFloat = Field(..., description="Sphere radius", gt=0)
    material: Optional[str] = Field(None, description="Part material")
    quantity: int = Field(1, description="Number of instances", ge=1, le=100)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional part metadata")
    
    @field_validator("radius")
    @classmethod
    def validate_dimensions(cls, v: float) -> float:
        """Validate dimension bounds using configurable settings."""
        # Use thread-safe current_design_settings()
        settings = current_design_settings()
        if v > settings.max_dimension_mm:
            raise ValueError(f"Boyut çok büyük (maksimum {settings.max_dimension_mm}mm)")
        if v < settings.min_dimension_mm:
            raise ValueError(f"Boyut çok küçük (minimum {settings.min_dimension_mm}mm)")
        return v


class ExistingPart(BaseModel):
    """Reference to an existing part file."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    name: str = Field(..., description="Part name/identifier", min_length=1, max_length=100)
    part_type: Literal["existing"] = Field("existing", description="Part type discriminator")
    path: str = Field(..., description="Path to existing part file", min_length=1)
    material: Optional[str] = Field(None, description="Part material")
    quantity: int = Field(1, description="Number of instances", ge=1, le=100)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional part metadata")


# Discriminated union for assembly parts
AssemblyPart = Annotated[
    Union[
        CylinderPart,
        BoxPart,
        SpherePart,
        ExistingPart,
    ],
    Field(discriminator="part_type")
]


class Assembly4Input(BaseModel):
    """Assembly4 assembly generation input."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    type: Literal["a4"] = Field("a4", description="Input type discriminator")
    parts: List[AssemblyPart] = Field(
        ..., 
        description="Part definitions or references (discriminated union of CylinderPart, BoxPart, SpherePart, ExistingPart)",
        min_length=2,
        max_length=100
    )
    constraints: List[Assembly4Constraint] = Field(
        ..., 
        description="Assembly constraints",
        min_length=1,
        max_length=500
    )
    validate_assembly: bool = Field(True, description="Validate assembly after creation")
    generate_bom: bool = Field(True, description="Generate bill of materials")
    
    @model_validator(mode="after")
    def validate_constraint_part_references(self) -> "Assembly4Input":
        """Ensure all constraint part references exist in the parts list.
        
        This validation prevents runtime errors by ensuring referential integrity
        at the schema level, as recommended by Gemini Code Assist.
        Works with the discriminated union part types.
        """
        # Extract names from all part types (they all have 'name' field)
        part_names = {part.name for part in self.parts}
        
        for i, constraint in enumerate(self.constraints):
            if constraint.part1 not in part_names:
                raise ValueError(
                    f"Kısıt {i+1}: part1 '{constraint.part1}' tanımlı parçalarda bulunamadı. "
                    f"Mevcut parçalar: {', '.join(sorted(part_names))}"
                )
            if constraint.part2 not in part_names:
                raise ValueError(
                    f"Kısıt {i+1}: part2 '{constraint.part2}' tanımlı parçalarda bulunamadı. "
                    f"Mevcut parçalar: {', '.join(sorted(part_names))}"
                )
        
        return self


# Discriminated union type
DesignInput = Annotated[
    Union[
        DesignPromptInput,
        DesignParametricInput,
        DesignUploadInput,
        Assembly4Input,
    ],
    Field(discriminator="type")
]


# Request/Response models

class DesignCreateRequest(BaseModel):
    """Create design job request with idempotency support."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    design: DesignInput = Field(..., description="Design input specification")
    priority: conint(ge=0, le=10) = Field(5, description="Job priority")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    chain_cam: bool = Field(False, description="Chain CAM generation after design")
    chain_sim: bool = Field(False, description="Chain simulation after CAM")
    
    @model_validator(mode="after")
    def validate_chaining(self) -> "DesignCreateRequest":
        """Validate job chaining logic."""
        if self.chain_sim and not self.chain_cam:
            raise ValueError("Simülasyon için önce CAM gerekli")
        return self


class DesignJobResponse(BaseModel):
    """Design job creation response."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "request_id": "req_1234567890",
                "status": "accepted",
                "queue": "model",
                "estimated_duration": 120,
                "created_at": "2024-08-24T12:00:00Z"
            }
        }
    )
    
    job_id: UUID = Field(..., description="Unique job identifier")
    request_id: str = Field(..., description="Request tracking ID")
    status: Literal["accepted", "duplicate"] = Field(..., description="Job acceptance status")
    queue: str = Field(..., description="Queue name for job processing")
    estimated_duration: Optional[int] = Field(None, description="Estimated processing time in seconds")
    created_at: datetime = Field(..., description="Job creation timestamp")


class JobStatusResponse(BaseModel):
    """Job status polling response."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    job_id: UUID = Field(..., description="Job identifier")
    status: str = Field(..., description="Current job status")
    progress: int = Field(..., ge=0, le=100, description="Progress percentage")
    message: Optional[str] = Field(None, description="Status message")
    started_at: Optional[datetime] = Field(None, description="Processing start time")
    finished_at: Optional[datetime] = Field(None, description="Processing end time")
    error: Optional[Dict[str, Any]] = Field(None, description="Error details if failed")
    result: Optional[Dict[str, Any]] = Field(None, description="Result data if completed")


class ArtefactResponse(BaseModel):
    """Generated artefact information."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    id: UUID = Field(..., description="Artefact identifier")
    type: str = Field(..., description="Artefact type (model, drawing, gcode, etc)")
    s3_key: str = Field(..., description="S3 object key")
    presigned_url: str = Field(..., description="Temporary download URL")
    size_bytes: int = Field(..., description="File size")
    sha256: str = Field(..., description="File checksum")
    format: str = Field(..., description="File format")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    created_at: datetime = Field(..., description="Creation timestamp")


class JobArtefactsResponse(BaseModel):
    """Job artefacts list response."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    job_id: UUID = Field(..., description="Job identifier")
    artefacts: List[ArtefactResponse] = Field(..., description="Generated artefacts")
    total_count: int = Field(..., description="Total artefact count")
    total_size: int = Field(..., description="Total size in bytes")


# Error response models

class RateLimitError(BaseModel):
    """Rate limit error response."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    error: Literal["rate_limit_exceeded"] = "rate_limit_exceeded"
    message: str = Field(..., description="Error message in Turkish")
    retry_after: int = Field(..., description="Seconds until rate limit resets")
    limit: int = Field(..., description="Rate limit maximum")
    remaining: int = Field(..., description="Remaining requests in window")
    reset_at: datetime = Field(..., description="Rate limit reset timestamp")


class ValidationError(BaseModel):
    """Validation error response."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    error: Literal["validation_error"] = "validation_error"
    message: str = Field(..., description="Error message in Turkish")
    details: List[Dict[str, Any]] = Field(..., description="Field-level error details")


class AuthorizationError(BaseModel):
    """Authorization error response."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    error: Literal["authorization_error"] = "authorization_error"
    message: str = Field(..., description="Error message in Turkish")
    required_scope: Optional[str] = Field(None, description="Required permission scope")
    required_license: Optional[str] = Field(None, description="Required license type")


class IdempotencyError(BaseModel):
    """Idempotency conflict error response."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    error: Literal["idempotency_conflict"] = "idempotency_conflict"
    message: str = Field(..., description="Error message in Turkish")
    existing_job_id: UUID = Field(..., description="Existing job with same idempotency key")
    request_mismatch: bool = Field(..., description="Whether request body differs")