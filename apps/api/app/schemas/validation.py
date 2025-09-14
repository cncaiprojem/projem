"""
Validation schemas for Task 7.24 Model Validation

This module provides Pydantic schemas for validation requests, responses,
and all related data structures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, ConfigDict

# Import Turkish validation messages from models


class ValidationProfile(str, Enum):
    """Validation profile enumeration."""
    QUICK = "quick"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"
    MANUFACTURING = "manufacturing"
    CERTIFICATION = "certification"


class ValidationStatus(str, Enum):
    """Validation status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    ERROR = "error"


class ValidationSeverity(str, Enum):
    """Issue severity levels."""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ManufacturingProcess(str, Enum):
    """Manufacturing process types."""
    CNC_MILLING = "cnc_milling"
    CNC_TURNING = "cnc_turning"
    CNC_LASER = "cnc_laser"
    FDM_3D_PRINTING = "fdm_3d_printing"
    SLA_3D_PRINTING = "sla_3d_printing"
    SLS_3D_PRINTING = "sls_3d_printing"
    INJECTION_MOLDING = "injection_molding"
    CASTING = "casting"
    SHEET_METAL = "sheet_metal"


class StandardType(str, Enum):
    """Standard types for compliance checking."""
    ISO_10303 = "ISO_10303"  # STEP
    ISO_14040 = "ISO_14040"  # LCA
    ISO_9001 = "ISO_9001"  # Quality management
    ISO_2768 = "ISO_2768"  # General tolerances
    ISO_286 = "ISO_286"  # Limits and fits
    ISO_1101 = "ISO_1101"  # Geometrical tolerancing
    ASME_Y14_5 = "ASME_Y14.5"  # GD&T
    DIN_919 = "DIN_919"  # German standards
    DIN_8580 = "DIN_8580"  # Manufacturing processes
    CE_MARKING = "CE_MARKING"  # CE compliance


class ValidationRequest(BaseModel):
    """Request for model validation."""
    model_config = ConfigDict(use_enum_values=True)
    
    model_id: str = Field(..., description="Model identifier")
    job_id: Optional[str] = Field(None, description="Job identifier")
    user_id: int = Field(..., description="User identifier")
    
    profile: ValidationProfile = Field(
        ValidationProfile.STANDARD,
        description="Validation profile to use"
    )
    
    # Options
    auto_fix: bool = Field(False, description="Apply automatic fixes")
    generate_report: bool = Field(True, description="Generate validation report")
    check_manufacturing: bool = Field(True, description="Check manufacturing constraints")
    
    # Manufacturing options
    manufacturing_process: Optional[ManufacturingProcess] = None
    material: Optional[str] = None
    machine_spec: Optional[Dict[str, Any]] = None
    
    # Standards to check
    standards: List[StandardType] = Field(default_factory=list)
    
    # Custom tolerances
    tolerances: Optional[Dict[str, float]] = None


class ValidationIssue(BaseModel):
    """Single validation issue."""
    model_config = ConfigDict(use_enum_values=True)
    
    issue_id: str = Field(default_factory=lambda: str(uuid4()), description="Issue identifier")
    type: str = Field(..., description="Issue type")
    severity: ValidationSeverity = Field(..., description="Issue severity")
    message: str = Field(..., description="Issue message")
    turkish_message: Optional[str] = Field(None, description="Turkish message")
    
    location: Optional[Dict[str, Any]] = Field(None, description="Issue location")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")
    
    fix_available: bool = Field(False, description="Fix available")
    fix_suggestion: Optional[str] = Field(None, description="Fix suggestion")


class FixSuggestion(BaseModel):
    """Fix suggestion for validation issues."""
    model_config = ConfigDict(use_enum_values=True)
    
    suggestion_id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = Field(..., description="Fix type")
    description: str = Field(..., description="Fix description")
    turkish_description: Optional[str] = Field(None, description="Turkish description")
    
    severity: ValidationSeverity = Field(..., description="Issue severity")
    automated: bool = Field(False, description="Can be automated")
    confidence: str = Field("medium", description="Confidence level")
    
    parameters: Dict[str, Any] = Field(default_factory=dict)
    estimated_time: Optional[float] = Field(None, description="Estimated time in seconds")


class FixReport(BaseModel):
    """Report of applied fixes."""
    model_config = ConfigDict(use_enum_values=True)
    
    total_suggestions: int = 0
    applied_fixes: int = 0
    successful_fixes: int = 0
    failed_fixes: int = 0
    skipped_fixes: int = 0
    
    fixes: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    
    duration_seconds: Optional[float] = None


class ValidationSection(BaseModel):
    """Validation section result."""
    model_config = ConfigDict(use_enum_values=True)
    
    name: str = Field(..., description="Section name")
    status: ValidationStatus = Field(..., description="Section status")
    score: float = Field(0.0, description="Section score (0-1)")
    
    issues: List[ValidationIssue] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    
    duration_seconds: Optional[float] = None


class ValidationResult(BaseModel):
    """Complete validation result."""
    model_config = ConfigDict(use_enum_values=True)
    
    validation_id: str = Field(default_factory=lambda: str(uuid4()))
    model_id: str = Field(..., description="Model identifier")
    job_id: Optional[str] = Field(None, description="Job identifier")
    
    profile: ValidationProfile = Field(..., description="Profile used")
    status: ValidationStatus = Field(..., description="Overall status")
    overall_score: float = Field(0.0, description="Overall score (0-1)")
    
    sections: Dict[str, ValidationSection] = Field(default_factory=dict)
    issues: List[ValidationIssue] = Field(default_factory=list)
    
    fix_suggestions: List[FixSuggestion] = Field(default_factory=list)
    fix_report: Optional[FixReport] = None
    
    certificate: Optional[QualityCertificate] = None
    
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: Optional[float] = None
    
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QualityCertificate(BaseModel):
    """Quality certificate for validated model."""
    model_config = ConfigDict(use_enum_values=True)
    
    certificate_id: str = Field(default_factory=lambda: str(uuid4()))
    model_id: str = Field(..., description="Model identifier")
    model_hash: str = Field(..., description="SHA256 hash of model")
    
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    
    validation_score: float = Field(..., description="Validation score")
    standards_compliant: List[StandardType] = Field(default_factory=list)
    
    issuer: str = Field("FreeCAD Validation System")
    signature: str = Field(..., description="Digital signature")
    
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ValidationResponse(BaseModel):
    """Response for validation request."""
    model_config = ConfigDict(use_enum_values=True)
    
    success: bool = Field(..., description="Operation success")
    result: Optional[ValidationResult] = None
    error: Optional[str] = None
    turkish_error: Optional[str] = None
    
    validation_id: Optional[str] = None
    report_url: Optional[str] = None


# Additional schemas for Task 7.24

class ManufacturingValidationRequest(BaseModel):
    """Request for manufacturing validation."""
    model_config = ConfigDict(use_enum_values=True)
    
    document_path: str = Field(..., description="Path to CAD document")
    process: ManufacturingProcess = Field(..., description="Manufacturing process")
    machine_spec: Dict[str, Any] = Field(default_factory=dict, description="Machine specifications")
    material: Optional[str] = Field(None, description="Material type")
    quantity: int = Field(1, description="Production quantity")


class ManufacturingValidationResponse(BaseModel):
    """Response for manufacturing validation."""
    model_config = ConfigDict(use_enum_values=True)
    
    process: ManufacturingProcess
    is_feasible: bool
    feasibility_score: float = Field(..., ge=0, le=1)
    issues: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    cost_estimate: Optional[float] = None
    lead_time_days: Optional[int] = None
    recommendations: List[str] = Field(default_factory=list)
    machine_compatibility: Dict[str, Any] = Field(default_factory=dict)  # Changed to Any to support nested structures
    process_parameters: Dict[str, Any] = Field(default_factory=dict)


class StandardsComplianceRequest(BaseModel):
    """Request for standards compliance check."""
    model_config = ConfigDict(use_enum_values=True)
    
    document_path: str = Field(..., description="Path to CAD document")
    standards: List[StandardType] = Field(..., description="Standards to check")
    strict_mode: bool = Field(False, description="Enable strict compliance")


class ComplianceViolation(BaseModel):
    """Details of a compliance violation."""
    model_config = ConfigDict(use_enum_values=True)
    
    rule_id: str
    rule_description: str
    severity: ValidationSeverity
    location: Optional[str] = None
    measured_value: Optional[float] = None
    expected_value: Optional[float] = None
    turkish_description: Optional[str] = None


class ComplianceResult(BaseModel):
    """Result of standards compliance check."""
    model_config = ConfigDict(use_enum_values=True)
    
    standard: StandardType
    is_compliant: bool
    compliance_score: float = Field(..., ge=0, le=1)
    violations: List[ComplianceViolation] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    certificate_eligible: bool = False


class QualityMetricsResponse(BaseModel):
    """Response containing quality metrics."""
    model_config = ConfigDict(use_enum_values=True)
    
    document_id: str
    timestamp: datetime
    metrics: Dict[str, Any] = Field(default_factory=dict)  # Changed to Any to support nested objects
    quality_score: float = Field(..., ge=0, le=100)
    grade: str = Field(..., description="Quality grade (A-F)")
    complexity: Optional[float] = Field(None, description="Complexity score")
    manufacturing_readiness: Optional[float] = Field(None, description="Manufacturing readiness score")
    issues_by_category: Dict[str, List[str]] = Field(default_factory=dict)  # Changed to List[str]
    improvement_areas: List[str] = Field(default_factory=list)


class CertificateRequest(BaseModel):
    """Request for certificate generation."""
    model_config = ConfigDict(use_enum_values=True)
    
    validation_id: str = Field(..., description="Validation result ID")
    standards: List[StandardType] = Field(..., description="Standards for certification")
    validity_days: int = Field(365, description="Certificate validity period")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CertificateVerificationRequest(BaseModel):
    """Request for certificate verification."""
    model_config = ConfigDict(use_enum_values=True)
    
    certificate_id: str = Field(..., description="Certificate ID to verify")
    include_details: bool = Field(False, description="Include full certificate details")


class AutoFixRequest(BaseModel):
    """Request for automated fixes."""
    model_config = ConfigDict(use_enum_values=True)

    document_path: str = Field(..., description="Path to CAD document")
    fix_ids: List[str] = Field(..., description="Fix IDs to apply")
    revalidate: bool = Field(True, description="Re-validate after fixes")
    auto_approve: bool = Field(False, description="Auto-approve safe fixes")
    save_result: bool = Field(True, description="Save fixed document")
    output_path: Optional[str] = Field(None, description="Custom output path for fixed document")


# Dataclasses for internal validation operations
# These are used internally by validation services and not exposed via API

@dataclass
class ValidationIssueDataclass:
    """Represents a validation issue (dataclass version for internal use)."""
    type: str
    severity: ValidationSeverity
    message: str
    turkish_message: str
    details: Optional[Dict[str, Any]] = None
    location: Optional[str] = None
    fix_available: bool = False
    fix_suggestion: Optional[str] = None


@dataclass
class GeometricValidation:
    """Geometric validation result."""
    is_valid: bool
    issues: List[ValidationIssueDataclass] = dataclass_field(default_factory=list)
    metrics: Dict[str, Any] = dataclass_field(default_factory=dict)
    warnings: List[str] = dataclass_field(default_factory=list)
    info: List[str] = dataclass_field(default_factory=list)

    # Fields assigned by GeometricValidator
    self_intersections: List[str] = dataclass_field(default_factory=list)
    non_manifold_edges: List[str] = dataclass_field(default_factory=list)
    open_edges: List[str] = dataclass_field(default_factory=list)
    topology_errors: List[str] = dataclass_field(default_factory=list)
    bounding_box: Optional[Dict[str, float]] = None
    thin_walls: List[str] = dataclass_field(default_factory=list)
    small_features: List[str] = dataclass_field(default_factory=list)
    surface_quality_score: float = 100.0
    volume: Optional[float] = None
    surface_area: Optional[float] = None
    center_of_mass: Optional[Dict[str, float]] = None


@dataclass
class QualityMetricsReport:
    """Quality metrics report."""
    overall_score: float
    metrics: Dict[str, Any] = dataclass_field(default_factory=dict)
    issues: List[ValidationIssueDataclass] = dataclass_field(default_factory=list)
    recommendations: List[str] = dataclass_field(default_factory=list)


@dataclass
class QualityMetric:
    """Individual quality metric."""
    name: str
    value: float
    unit: Optional[str] = None
    threshold: Optional[float] = None
    passed: bool = True


@dataclass
class ComplianceResultDataclass:
    """Standards compliance result (dataclass version for internal use)."""
    standard: StandardType
    is_compliant: bool
    compliance_score: float = 0.0
    violations: List['ComplianceViolationDataclass'] = dataclass_field(default_factory=list)
    recommendations: List[str] = dataclass_field(default_factory=list)
    warnings: List[str] = dataclass_field(default_factory=list)
    certificate_eligible: bool = False
    passed_rules: int = 0
    checked_rules: int = 0


@dataclass
class ComplianceViolationDataclass:
    """Compliance violation detail (dataclass version for internal use)."""
    rule_id: str
    rule_description: str
    severity: ValidationSeverity
    location: Optional[str] = None
    actual_value: Optional[float] = None
    expected_value: Optional[float] = None
    recommendation: Optional[str] = None