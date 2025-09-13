"""
Pydantic models for Task 7.24: Advanced Model Validation and Quality Assurance

This module defines all data models for the model validation system including:
- Validation results and reports
- Geometric validation models
- Manufacturing validation models
- Standards compliance models
- Quality metrics and scoring
- Certification models
- Fix suggestions
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, ConfigDict


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationStatus(str, Enum):
    """Overall validation status."""
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    ERROR = "error"
    IN_PROGRESS = "in_progress"


class ValidationProfile(str, Enum):
    """Validation profiles for different use cases."""
    QUICK = "quick"  # Basic checks only
    STANDARD = "standard"  # Standard validation
    COMPREHENSIVE = "comprehensive"  # All checks
    MANUFACTURING = "manufacturing"  # Manufacturing-focused
    CERTIFICATION = "certification"  # For certification


class ManufacturingProcess(str, Enum):
    """Manufacturing process types."""
    CNC_MILLING = "cnc_milling"
    CNC_TURNING = "cnc_turning"
    CNC_LASER = "cnc_laser"
    CNC_PLASMA = "cnc_plasma"
    FDM_3D_PRINTING = "fdm_3d_printing"
    SLA_3D_PRINTING = "sla_3d_printing"
    SLS_3D_PRINTING = "sls_3d_printing"
    INJECTION_MOLDING = "injection_molding"
    SHEET_METAL = "sheet_metal"
    CASTING = "casting"


class StandardType(str, Enum):
    """Industry standards for compliance checking."""
    ISO_10303 = "ISO_10303"  # STEP standard
    ISO_14040 = "ISO_14040"  # Environmental
    ISO_9001 = "ISO_9001"  # Quality management
    ASME_Y14_5 = "ASME_Y14_5"  # GD&T
    DIN_8580 = "DIN_8580"  # Manufacturing processes
    CE_MARKING = "CE_MARKING"  # European conformity
    ANSI_B46_1 = "ANSI_B46_1"  # Surface texture
    ISO_2768 = "ISO_2768"  # General tolerances
    ISO_286 = "ISO_286"  # ISO fit system


class FixConfidence(str, Enum):
    """Confidence levels for automated fix suggestions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class ValidationIssue(BaseModel):
    """Individual validation issue."""
    model_config = ConfigDict(validate_assignment=True)
    
    issue_id: str = Field(default_factory=lambda: uuid4().hex)
    type: str = Field(description="Issue type identifier")
    severity: ValidationSeverity = Field(description="Issue severity")
    message: str = Field(description="Human-readable message")
    turkish_message: str = Field(description="Turkish localized message")
    location: Optional[Dict[str, Any]] = Field(default=None, description="Location in model")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional details")
    fix_available: bool = Field(default=False, description="Whether automated fix exists")
    fix_suggestion: Optional[str] = Field(default=None, description="Suggested fix")


class GeometricValidation(BaseModel):
    """Geometric validation results."""
    model_config = ConfigDict(validate_assignment=True)
    
    is_valid: bool = Field(description="Overall geometric validity")
    self_intersections: List[Dict[str, Any]] = Field(default_factory=list)
    non_manifold_edges: List[Dict[str, Any]] = Field(default_factory=list)
    open_edges: List[Dict[str, Any]] = Field(default_factory=list)
    thin_walls: List[Dict[str, Any]] = Field(default_factory=list)
    small_features: List[Dict[str, Any]] = Field(default_factory=list)
    invalid_faces: List[Dict[str, Any]] = Field(default_factory=list)
    topology_errors: List[Dict[str, Any]] = Field(default_factory=list)
    surface_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    volume: Optional[float] = Field(default=None, description="Total volume in mm³")
    surface_area: Optional[float] = Field(default=None, description="Total surface area in mm²")
    bounding_box: Optional[Dict[str, float]] = Field(default=None)
    center_of_mass: Optional[Dict[str, float]] = Field(default=None)
    issues: List[ValidationIssue] = Field(default_factory=list)


class ToleranceCheck(BaseModel):
    """Tolerance validation result."""
    feature_id: str = Field(description="Feature identifier")
    feature_type: str = Field(description="Feature type")
    nominal_value: float = Field(description="Nominal dimension")
    tolerance_min: float = Field(description="Minimum tolerance")
    tolerance_max: float = Field(description="Maximum tolerance")
    actual_value: Optional[float] = Field(default=None)
    is_within_tolerance: bool = Field(default=True)
    deviation: Optional[float] = Field(default=None)


class CNCValidation(BaseModel):
    """CNC machining validation results."""
    model_config = ConfigDict(validate_assignment=True)
    
    is_machinable: bool = Field(description="Overall machinability")
    machine_type: str = Field(description="CNC machine type")
    tool_accessibility: Dict[str, bool] = Field(default_factory=dict)
    undercuts: List[Dict[str, Any]] = Field(default_factory=list)
    minimum_feature_sizes: Dict[str, float] = Field(default_factory=dict)
    tolerance_checks: List[ToleranceCheck] = Field(default_factory=list)
    setup_count: int = Field(default=1, description="Number of setups required")
    estimated_machining_time: Optional[float] = Field(default=None, description="Time in minutes")
    tool_list: List[Dict[str, Any]] = Field(default_factory=list)
    issues: List[ValidationIssue] = Field(default_factory=list)


class PrintValidation(BaseModel):
    """3D printing validation results."""
    model_config = ConfigDict(validate_assignment=True)
    
    is_printable: bool = Field(description="Overall printability")
    printer_type: str = Field(description="3D printer technology")
    printability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    overhangs: List[Dict[str, Any]] = Field(default_factory=list)
    support_required: bool = Field(default=False)
    support_volume: Optional[float] = Field(default=None, description="Support volume in mm³")
    trapped_volumes: List[Dict[str, Any]] = Field(default_factory=list)
    wall_thickness_ok: bool = Field(default=True)
    estimated_print_time: Optional[float] = Field(default=None, description="Time in hours")
    estimated_material: Optional[float] = Field(default=None, description="Material in grams")
    layer_count: Optional[int] = Field(default=None)
    issues: List[ValidationIssue] = Field(default_factory=list)


class ManufacturingValidation(BaseModel):
    """Manufacturing validation results."""
    model_config = ConfigDict(validate_assignment=True)
    
    process: ManufacturingProcess = Field(description="Manufacturing process")
    is_manufacturable: bool = Field(description="Overall manufacturability")
    cnc_validation: Optional[CNCValidation] = Field(default=None)
    print_validation: Optional[PrintValidation] = Field(default=None)
    cost_estimate: Optional[Decimal] = Field(default=None, description="Estimated cost")
    lead_time_estimate: Optional[int] = Field(default=None, description="Lead time in days")
    material_recommendations: List[str] = Field(default_factory=list)
    process_recommendations: List[str] = Field(default_factory=list)
    issues: List[ValidationIssue] = Field(default_factory=list)


class ComplianceViolation(BaseModel):
    """Standards compliance violation."""
    rule_id: str = Field(description="Rule identifier")
    rule_description: str = Field(description="Rule description")
    severity: ValidationSeverity = Field(description="Violation severity")
    location: Optional[Dict[str, Any]] = Field(default=None)
    actual_value: Optional[Any] = Field(default=None)
    expected_value: Optional[Any] = Field(default=None)
    recommendation: Optional[str] = Field(default=None)


class ComplianceResult(BaseModel):
    """Standards compliance check result."""
    model_config = ConfigDict(validate_assignment=True)
    
    standard: StandardType = Field(description="Standard checked")
    is_compliant: bool = Field(description="Overall compliance")
    compliance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    violations: List[ComplianceViolation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    certificate_eligible: bool = Field(default=False)
    checked_rules: int = Field(default=0)
    passed_rules: int = Field(default=0)


class QualityMetric(BaseModel):
    """Individual quality metric."""
    name: str = Field(description="Metric name")
    value: float = Field(description="Metric value")
    min_value: float = Field(default=0.0)
    max_value: float = Field(default=1.0)
    weight: float = Field(default=1.0, description="Weight in overall score")
    unit: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)


class QualityMetricsReport(BaseModel):
    """Quality metrics report."""
    model_config = ConfigDict(validate_assignment=True)
    
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    geometric_complexity: QualityMetric
    surface_quality: QualityMetric
    feature_consistency: QualityMetric
    parametric_robustness: QualityMetric
    assembly_compatibility: Optional[QualityMetric] = Field(default=None)
    manufacturing_readiness: QualityMetric
    documentation_completeness: QualityMetric
    metrics: Dict[str, QualityMetric] = Field(default_factory=dict)
    grade: str = Field(default="F", description="Letter grade A-F")
    
    def calculate_overall_score(self):
        """Calculate weighted overall score."""
        total_weight = 0.0
        weighted_sum = 0.0
        
        for metric in self.metrics.values():
            normalized_value = (metric.value - metric.min_value) / (metric.max_value - metric.min_value)
            weighted_sum += normalized_value * metric.weight
            total_weight += metric.weight
        
        if total_weight > 0:
            self.overall_score = weighted_sum / total_weight
            
            # Assign grade
            if self.overall_score >= 0.9:
                self.grade = "A"
            elif self.overall_score >= 0.8:
                self.grade = "B"
            elif self.overall_score >= 0.7:
                self.grade = "C"
            elif self.overall_score >= 0.6:
                self.grade = "D"
            else:
                self.grade = "F"


class FixSuggestion(BaseModel):
    """Automated fix suggestion."""
    model_config = ConfigDict(validate_assignment=True)
    
    suggestion_id: str = Field(default_factory=lambda: uuid4().hex)
    issue_id: str = Field(description="Related issue ID")
    type: str = Field(description="Fix type")
    description: str = Field(description="Fix description")
    turkish_description: str = Field(description="Turkish description")
    confidence: FixConfidence = Field(description="Confidence level")
    automated: bool = Field(default=False, description="Can be applied automatically")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    estimated_time: Optional[float] = Field(default=None, description="Time in seconds")
    side_effects: List[str] = Field(default_factory=list)
    
    async def apply(self, doc: Any) -> Dict[str, Any]:
        """Apply the fix to the document."""
        # Implementation would be in the actual service
        raise NotImplementedError("Fix application logic in service layer")


class FixReport(BaseModel):
    """Report of applied fixes."""
    model_config = ConfigDict(validate_assignment=True)
    
    total_suggestions: int = Field(default=0)
    applied_fixes: int = Field(default=0)
    successful_fixes: int = Field(default=0)
    failed_fixes: int = Field(default=0)
    skipped_fixes: int = Field(default=0)
    fixes: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)


class QualityCertificate(BaseModel):
    """Quality certificate for validated models."""
    model_config = ConfigDict(validate_assignment=True)
    
    certificate_id: UUID = Field(default_factory=uuid4)
    model_id: str = Field(description="Model identifier")
    model_hash: str = Field(description="SHA256 hash of model")
    issued_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expiry_date: datetime = Field(description="Certificate expiry")
    issuer: str = Field(description="Issuing authority")
    standards: List[StandardType] = Field(description="Standards met")
    validation_score: float = Field(ge=0.0, le=1.0)
    validation_profile: ValidationProfile = Field(default=ValidationProfile.STANDARD)
    signature: Optional[str] = Field(default=None, description="Digital signature")
    blockchain_hash: Optional[str] = Field(default=None, description="Blockchain record")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('expiry_date')
    @classmethod
    def validate_expiry(cls, v: datetime, info) -> datetime:
        """Ensure expiry is after issue date."""
        if 'issued_date' in info.data and v <= info.data['issued_date']:
            raise ValueError("Expiry date must be after issue date")
        return v


class ValidationSection(BaseModel):
    """Section of validation results."""
    name: str = Field(description="Section name")
    status: ValidationStatus = Field(description="Section status")
    duration_ms: Optional[int] = Field(default=None)
    results: Union[
        GeometricValidation,
        ManufacturingValidation,
        ComplianceResult,
        QualityMetricsReport,
        Dict[str, Any]
    ] = Field(description="Section results")
    issues_count: int = Field(default=0)
    warnings_count: int = Field(default=0)
    errors_count: int = Field(default=0)


class ValidationResult(BaseModel):
    """Complete validation result."""
    model_config = ConfigDict(validate_assignment=True)
    
    validation_id: str = Field(default_factory=lambda: uuid4().hex)
    model_id: str = Field(description="Model identifier")
    model_name: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    profile: ValidationProfile = Field(description="Validation profile used")
    status: ValidationStatus = Field(default=ValidationStatus.IN_PROGRESS)
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    sections: Dict[str, ValidationSection] = Field(default_factory=dict)
    issues: List[ValidationIssue] = Field(default_factory=list)
    fix_suggestions: List[FixSuggestion] = Field(default_factory=list)
    duration_ms: Optional[int] = Field(default=None)
    certificate: Optional[QualityCertificate] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def add_section(self, name: str, results: Any):
        """Add validation section results."""
        issues_count = 0
        warnings_count = 0
        errors_count = 0
        
        # Count issues by severity
        if hasattr(results, 'issues'):
            for issue in results.issues:
                if issue.severity == ValidationSeverity.ERROR:
                    errors_count += 1
                elif issue.severity == ValidationSeverity.WARNING:
                    warnings_count += 1
                else:
                    issues_count += 1
                self.issues.append(issue)
        
        # Determine section status
        if errors_count > 0:
            status = ValidationStatus.FAILED
        elif warnings_count > 0:
            status = ValidationStatus.PASSED_WITH_WARNINGS
        else:
            status = ValidationStatus.PASSED
        
        self.sections[name] = ValidationSection(
            name=name,
            status=status,
            results=results,
            issues_count=issues_count,
            warnings_count=warnings_count,
            errors_count=errors_count
        )
    
    def calculate_score(self):
        """Calculate overall validation score."""
        if not self.sections:
            self.overall_score = 0.0
            return
        
        total_weight = len(self.sections)
        section_scores = []
        
        for section in self.sections.values():
            if section.status == ValidationStatus.PASSED:
                section_scores.append(1.0)
            elif section.status == ValidationStatus.PASSED_WITH_WARNINGS:
                section_scores.append(0.8)
            elif section.status == ValidationStatus.FAILED:
                section_scores.append(0.0)
            else:
                section_scores.append(0.5)
        
        self.overall_score = sum(section_scores) / total_weight if total_weight > 0 else 0.0
        
        # Update overall status
        error_count = sum(s.errors_count for s in self.sections.values())
        warning_count = sum(s.warnings_count for s in self.sections.values())
        
        if error_count > 0:
            self.status = ValidationStatus.FAILED
        elif warning_count > 0:
            self.status = ValidationStatus.PASSED_WITH_WARNINGS
        else:
            self.status = ValidationStatus.PASSED


class PerformanceRequirements(BaseModel):
    """Performance requirements for validation."""
    max_recompute_time: float = Field(default=5.0, description="Max recompute time in seconds")
    max_memory_mb: float = Field(default=500.0, description="Max memory usage in MB")
    max_file_size_mb: float = Field(default=100.0, description="Max file size in MB")
    max_complexity_score: float = Field(default=1000.0, description="Max complexity score")


class PerformanceValidation(BaseModel):
    """Performance validation results."""
    model_config = ConfigDict(validate_assignment=True)
    
    is_performant: bool = Field(default=True)
    recompute_time: Optional[float] = Field(default=None, description="Seconds")
    memory_usage_mb: Optional[float] = Field(default=None)
    file_size_mb: Optional[float] = Field(default=None)
    complexity_score: Optional[float] = Field(default=None)
    issues: List[ValidationIssue] = Field(default_factory=list)


class ValidationRequest(BaseModel):
    """Request for model validation."""
    model_config = ConfigDict(validate_assignment=True)
    
    model_id: str = Field(description="Model to validate")
    profile: ValidationProfile = Field(default=ValidationProfile.STANDARD)
    processes: Optional[List[ManufacturingProcess]] = Field(default=None)
    standards: Optional[List[StandardType]] = Field(default=None)
    auto_fix: bool = Field(default=False, description="Apply automated fixes")
    performance_check: bool = Field(default=True)
    generate_certificate: bool = Field(default=False)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ValidationResponse(BaseModel):
    """Response from validation request."""
    model_config = ConfigDict(validate_assignment=True)
    
    success: bool = Field(description="Request success")
    result: Optional[ValidationResult] = Field(default=None)
    fix_report: Optional[FixReport] = Field(default=None)
    certificate: Optional[QualityCertificate] = Field(default=None)
    error: Optional[str] = Field(default=None)
    turkish_error: Optional[str] = Field(default=None)


# Turkish message mappings
VALIDATION_MESSAGES_TR = {
    'validation_started': 'Model doğrulama başlatıldı',
    'checking_geometry': 'Geometri kontrol ediliyor...',
    'checking_manufacturing': 'Üretilebilirlik kontrol ediliyor...',
    'checking_standards': 'Standart uyumluluğu kontrol ediliyor...',
    'checking_performance': 'Performans kontrol ediliyor...',
    'validation_complete': 'Doğrulama tamamlandı',
    'issues_found': '{count} sorun tespit edildi',
    'certificate_issued': 'Kalite sertifikası düzenlendi',
    'fix_suggested': 'Otomatik düzeltme önerisi',
    'fix_applied': 'Düzeltme uygulandı',
    'quality_score': 'Kalite puanı: {score}/100',
    
    # Issue types
    'self_intersection': 'Kendisiyle kesişme',
    'thin_walls': 'İnce duvarlar',
    'non_manifold': 'Manifold olmayan kenarlar',
    'overhang': 'Askıda kalan yüzey',
    'undercut': 'Alt kesim',
    'small_feature': 'Küçük özellik',
    'tolerance_violation': 'Tolerans ihlali',
    'surface_defect': 'Yüzey hatası',
    
    # Severity levels
    'info': 'Bilgi',
    'warning': 'Uyarı',
    'error': 'Hata',
    'critical': 'Kritik',
}