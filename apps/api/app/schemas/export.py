"""
Export Schemas for Task 7.9

Pydantic schemas for unified deterministic export pipeline with
comprehensive validation and configuration options.

Features:
- Export format configuration
- Version pinning specifications
- Tessellation parameters
- Metadata tracking
- Validation settings
- Turkish localization support
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from pydantic import PositiveFloat, NonNegativeFloat, PositiveInt


class ExportFormat(str, Enum):
    """Supported export formats with deterministic output."""
    FCSTD = "FCStd"
    STEP = "STEP"
    STL = "STL"
    GLB = "GLB"
    IGES = "IGES"  # Future support
    BREP = "BREP"  # Future support
    OBJ = "OBJ"    # Future support


class StepSchema(str, Enum):
    """STEP schema versions."""
    AP203 = "AP203"  # Configuration controlled design
    AP214 = "AP214"  # Automotive design (default)
    AP242 = "AP242"  # Managed model based 3D engineering


class StlFormat(str, Enum):
    """STL file format options."""
    BINARY = "binary"
    ASCII = "ascii"


class MeshQuality(str, Enum):
    """Predefined mesh quality levels."""
    DRAFT = "draft"      # Fast, low quality
    STANDARD = "standard" # Balanced
    HIGH = "high"        # High quality
    ULTRA = "ultra"      # Maximum quality
    CUSTOM = "custom"    # User-defined parameters


class ExportTessellationParams(BaseModel):
    """
    Tessellation parameters for mesh generation.
    
    These parameters control the quality and size of exported meshes.
    """
    model_config = ConfigDict(validate_assignment=True, use_enum_values=True)
    
    quality: MeshQuality = Field(
        default=MeshQuality.STANDARD,
        description="Predefined quality level or custom"
    )
    
    linear_deflection: Optional[PositiveFloat] = Field(
        default=None,
        description="Maximum linear deviation from true surface (mm)",
        le=10.0  # Maximum 10mm deviation
    )
    
    angular_deflection: Optional[PositiveFloat] = Field(
        default=None,
        description="Maximum angular deviation between adjacent facets (radians)",
        le=1.0  # Maximum ~57 degrees
    )
    
    relative: bool = Field(
        default=False,
        description="Use relative values based on model size"
    )
    
    @model_validator(mode='after')
    def set_quality_parameters(self) -> 'ExportTessellationParams':
        """Set deflection parameters based on quality level."""
        if self.quality != MeshQuality.CUSTOM:
            quality_settings = {
                MeshQuality.DRAFT: (1.0, 0.8),
                MeshQuality.STANDARD: (0.1, 0.5),
                MeshQuality.HIGH: (0.01, 0.2),
                MeshQuality.ULTRA: (0.001, 0.1),
            }
            
            if self.quality in quality_settings:
                linear, angular = quality_settings[self.quality]
                if self.linear_deflection is None:
                    self.linear_deflection = linear
                if self.angular_deflection is None:
                    self.angular_deflection = angular
        
        # Ensure custom quality has parameters
        elif self.quality == MeshQuality.CUSTOM:
            if self.linear_deflection is None:
                self.linear_deflection = 0.1  # Default
            if self.angular_deflection is None:
                self.angular_deflection = 0.5  # Default
        
        return self


class ExportStepOptions(BaseModel):
    """STEP export specific options."""
    model_config = ConfigDict(validate_assignment=True)
    
    schema: StepSchema = Field(
        default=StepSchema.AP214,
        description="STEP schema version to use"
    )
    
    tolerance: PositiveFloat = Field(
        default=0.001,
        description="Export tolerance (mm)",
        le=1.0
    )
    
    write_surfaces: bool = Field(
        default=True,
        description="Include surface information"
    )
    
    write_solids: bool = Field(
        default=True,
        description="Include solid information"
    )
    
    compress: bool = Field(
        default=False,
        description="Compress output (may affect determinism)"
    )


class ExportStlOptions(BaseModel):
    """STL export specific options."""
    model_config = ConfigDict(validate_assignment=True)
    
    format: StlFormat = Field(
        default=StlFormat.BINARY,
        description="STL file format"
    )
    
    tessellation: ExportTessellationParams = Field(
        default_factory=ExportTessellationParams,
        description="Mesh tessellation parameters"
    )
    
    export_colors: bool = Field(
        default=False,
        description="Export colors (binary STL only, non-standard)"
    )


class ExportGlbOptions(BaseModel):
    """GLB export specific options."""
    model_config = ConfigDict(validate_assignment=True)
    
    tessellation: ExportTessellationParams = Field(
        default_factory=ExportTessellationParams,
        description="Mesh tessellation parameters"
    )
    
    include_normals: bool = Field(
        default=True,
        description="Include vertex normals"
    )
    
    include_uvs: bool = Field(
        default=False,
        description="Include texture coordinates"
    )
    
    include_materials: bool = Field(
        default=True,
        description="Include material information"
    )
    
    quantization: bool = Field(
        default=False,
        description="Enable mesh quantization (affects determinism)"
    )
    
    draco_compression: bool = Field(
        default=False,
        description="Enable Draco compression (affects determinism)"
    )


class VersionRequirement(BaseModel):
    """Version requirement specification."""
    model_config = ConfigDict(validate_assignment=True)
    
    name: str = Field(
        description="Library or component name"
    )
    
    min_version: Optional[str] = Field(
        default=None,
        description="Minimum version (inclusive)"
    )
    
    max_version: Optional[str] = Field(
        default=None,
        description="Maximum version (exclusive)"
    )
    
    exact_version: Optional[str] = Field(
        default=None,
        description="Exact version required"
    )
    
    @model_validator(mode='after')
    def validate_version_spec(self) -> 'VersionRequirement':
        """Ensure version specification is valid."""
        if self.exact_version:
            if self.min_version or self.max_version:
                raise ValueError(
                    "Cannot specify exact_version with min/max_version"
                )
        return self


class ExportConfiguration(BaseModel):
    """
    Complete export configuration for unified pipeline.
    
    This schema defines all parameters needed for deterministic export.
    """
    model_config = ConfigDict(validate_assignment=True, use_enum_values=True)
    
    # Format selection
    formats: List[ExportFormat] = Field(
        default=[ExportFormat.STEP, ExportFormat.STL],
        description="Export formats to generate",
        min_length=1
    )
    
    # Output configuration
    output_directory: str = Field(
        description="Output directory path"
    )
    
    base_name: Optional[str] = Field(
        default=None,
        description="Base name for output files (without extension)"
    )
    
    # Determinism settings
    source_date_epoch: Optional[int] = Field(
        default=None,
        description="Unix timestamp for reproducible dates",
        ge=0
    )
    
    deterministic_mode: bool = Field(
        default=True,
        description="Enable full deterministic mode"
    )
    
    random_seed: int = Field(
        default=42,
        description="Random seed for deterministic operations"
    )
    
    # Format-specific options
    step_options: Optional[ExportStepOptions] = Field(
        default=None,
        description="STEP export options"
    )
    
    stl_options: Optional[ExportStlOptions] = Field(
        default=None,
        description="STL export options"
    )
    
    glb_options: Optional[ExportGlbOptions] = Field(
        default=None,
        description="GLB export options"
    )
    
    # Version pinning
    version_requirements: Optional[List[VersionRequirement]] = Field(
        default=None,
        description="Version requirements for dependencies"
    )
    
    # Validation settings
    validate_output: bool = Field(
        default=True,
        description="Validate exported files"
    )
    
    verify_determinism: bool = Field(
        default=False,
        description="Verify determinism with multiple exports"
    )
    
    determinism_iterations: PositiveInt = Field(
        default=3,
        description="Number of iterations for determinism verification",
        le=10
    )
    
    # Metadata tracking
    generate_metadata: bool = Field(
        default=True,
        description="Generate export metadata file"
    )
    
    include_hash: bool = Field(
        default=True,
        description="Include file hashes in results"
    )
    
    # Performance settings
    parallel_export: bool = Field(
        default=False,
        description="Enable parallel export (may affect determinism)"
    )
    
    cache_shapes: bool = Field(
        default=True,
        description="Cache shapes for performance"
    )
    
    @field_validator('output_directory')
    @classmethod
    def validate_output_directory(cls, v: str) -> str:
        """Ensure output directory is valid."""
        path = Path(v)
        if not path.is_absolute():
            # Convert to absolute path
            path = path.absolute()
        return str(path)
    
    @model_validator(mode='after')
    def set_format_options(self) -> 'ExportConfiguration':
        """Initialize format-specific options if needed."""
        if ExportFormat.STEP in self.formats and not self.step_options:
            self.step_options = ExportStepOptions()
        
        if ExportFormat.STL in self.formats and not self.stl_options:
            self.stl_options = ExportStlOptions()
        
        if ExportFormat.GLB in self.formats and not self.glb_options:
            self.glb_options = ExportGlbOptions()
        
        return self


class ExportResult(BaseModel):
    """Result of a single format export."""
    model_config = ConfigDict(validate_assignment=True)
    
    format: ExportFormat = Field(
        description="Export format"
    )
    
    path: str = Field(
        description="Path to exported file"
    )
    
    size: PositiveInt = Field(
        description="File size in bytes"
    )
    
    hash: Optional[str] = Field(
        default=None,
        description="SHA256 hash of file"
    )
    
    deterministic: bool = Field(
        default=False,
        description="Whether export was deterministic"
    )
    
    # Format-specific metadata
    schema_version: Optional[str] = Field(
        default=None,
        description="Schema version (STEP)"
    )
    
    facet_count: Optional[PositiveInt] = Field(
        default=None,
        description="Number of facets (STL/GLB)"
    )
    
    vertex_count: Optional[PositiveInt] = Field(
        default=None,
        description="Number of vertices (STL/GLB)"
    )
    
    export_time_ms: Optional[float] = Field(
        default=None,
        description="Export time in milliseconds",
        ge=0
    )
    
    error: Optional[str] = Field(
        default=None,
        description="Error message if export failed"
    )


class ExportMetadataInfo(BaseModel):
    """Export metadata information."""
    model_config = ConfigDict(validate_assignment=True)
    
    freecad_version: str = Field(
        description="FreeCAD version used"
    )
    
    python_version: str = Field(
        description="Python version used"
    )
    
    export_timestamp: datetime = Field(
        description="Export timestamp (ISO format)"
    )
    
    export_parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Export parameters by format"
    )
    
    library_versions: Dict[str, str] = Field(
        default_factory=dict,
        description="Library versions used"
    )
    
    tolerances: Dict[str, float] = Field(
        default_factory=dict,
        description="Tolerance values used"
    )
    
    hash_values: Dict[str, str] = Field(
        default_factory=dict,
        description="File hashes by format"
    )


class UnifiedExportResponse(BaseModel):
    """
    Response from unified export operation.
    
    Contains results for all requested formats and metadata.
    """
    model_config = ConfigDict(validate_assignment=True)
    
    job_id: Optional[str] = Field(
        default=None,
        description="Job ID for tracking"
    )
    
    status: str = Field(
        default="success",
        description="Overall export status"
    )
    
    results: Dict[str, ExportResult] = Field(
        default_factory=dict,
        description="Export results by format"
    )
    
    metadata: Optional[ExportMetadataInfo] = Field(
        default=None,
        description="Export metadata"
    )
    
    determinism_verified: Optional[bool] = Field(
        default=None,
        description="Whether determinism was verified"
    )
    
    total_time_ms: float = Field(
        description="Total export time in milliseconds",
        ge=0
    )
    
    errors: List[str] = Field(
        default_factory=list,
        description="List of errors encountered"
    )
    
    warnings: List[str] = Field(
        default_factory=list,
        description="List of warnings"
    )
    
    @property
    def success_count(self) -> int:
        """Count of successful exports."""
        return sum(
            1 for r in self.results.values()
            if r.error is None
        )
    
    @property
    def failure_count(self) -> int:
        """Count of failed exports."""
        return sum(
            1 for r in self.results.values()
            if r.error is not None
        )
    
    def get_result(self, format: Union[str, ExportFormat]) -> Optional[ExportResult]:
        """Get result for specific format."""
        if isinstance(format, str):
            format = format.upper()
        return self.results.get(format)


class ExportValidationResult(BaseModel):
    """Result of export validation."""
    model_config = ConfigDict(validate_assignment=True)
    
    format: ExportFormat = Field(
        description="Format that was validated"
    )
    
    valid: bool = Field(
        description="Whether export is valid"
    )
    
    file_exists: bool = Field(
        default=True,
        description="Whether file exists"
    )
    
    size_valid: bool = Field(
        default=True,
        description="Whether file size is valid"
    )
    
    hash_match: bool = Field(
        default=True,
        description="Whether hash matches expected"
    )
    
    structure_valid: bool = Field(
        default=True,
        description="Whether file structure is valid"
    )
    
    errors: List[str] = Field(
        default_factory=list,
        description="Validation errors"
    )
    
    warnings: List[str] = Field(
        default_factory=list,
        description="Validation warnings"
    )


# Turkish translations for error messages
TURKISH_MESSAGES = {
    "export_failed": "Dışa aktarma başarısız oldu",
    "invalid_format": "Geçersiz format",
    "file_not_found": "Dosya bulunamadı",
    "validation_failed": "Doğrulama başarısız",
    "determinism_failed": "Determinizm doğrulaması başarısız",
    "version_mismatch": "Sürüm uyuşmazlığı",
    "insufficient_permissions": "Yetersiz izinler",
    "output_dir_not_found": "Çıktı dizini bulunamadı",
    "shape_not_found": "Şekil bulunamadı",
    "mesh_generation_failed": "Mesh oluşturma başarısız",
}