"""
Validation schemas and dataclasses for Task 7.24

This module provides dataclasses and schemas for validation operations.
Moved from models to schemas for better organization.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class StandardType(str, Enum):
    """Standard types for compliance checking."""
    ISO_10303 = "ISO_10303"  # STEP
    ISO_14040 = "ISO_14040"  # LCA
    ISO_9001 = "ISO_9001"  # Quality management
    ISO_2768 = "ISO_2768"  # General tolerances  
    ISO_286 = "ISO_286"  # Limits and fits
    ASME_Y14_5 = "ASME_Y14.5"  # GD&T
    DIN_8580 = "DIN_8580"  # Manufacturing processes
    CE_MARKING = "CE_MARKING"  # CE compliance


@dataclass
class ValidationIssue:
    """Represents a validation issue."""
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
    issues: List[ValidationIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)
    
    # Fields assigned by GeometricValidator
    self_intersections: List[str] = field(default_factory=list)
    non_manifold_edges: List[str] = field(default_factory=list)
    open_edges: List[str] = field(default_factory=list)
    topology_errors: List[str] = field(default_factory=list)
    bounding_box: Optional[Dict[str, float]] = None
    thin_walls: List[str] = field(default_factory=list)
    small_features: List[str] = field(default_factory=list)
    surface_quality_score: float = 100.0
    volume: Optional[float] = None
    surface_area: Optional[float] = None
    center_of_mass: Optional[Dict[str, float]] = None


@dataclass
class QualityMetricsReport:
    """Quality metrics report."""
    overall_score: float
    metrics: Dict[str, Any] = field(default_factory=dict)
    issues: List[ValidationIssue] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class QualityMetric:
    """Individual quality metric."""
    name: str
    value: float
    unit: Optional[str] = None
    threshold: Optional[float] = None
    passed: bool = True


@dataclass
class ComplianceResult:
    """Standards compliance result."""
    standard: StandardType
    is_compliant: bool
    compliance_score: float = 0.0
    violations: List['ComplianceViolation'] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    certificate_eligible: bool = False
    passed_rules: int = 0
    checked_rules: int = 0


@dataclass  
class ComplianceViolation:
    """Compliance violation detail."""
    rule_id: str
    rule_description: str
    severity: ValidationSeverity
    location: Optional[str] = None
    actual_value: Optional[float] = None
    expected_value: Optional[float] = None
    recommendation: Optional[str] = None