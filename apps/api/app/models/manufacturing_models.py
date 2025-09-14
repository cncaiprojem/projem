"""
Manufacturing validation models for Task 7.24

This module provides dataclasses and models for manufacturing validation
including CNC, 3D printing, and other manufacturing processes.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


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
class ToleranceCheck:
    """Tolerance validation check result."""
    feature_id: str
    feature_type: str
    specified_tolerance: float
    achievable_tolerance: float
    is_within_tolerance: bool
    recommendation: Optional[str] = None
    
    def dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "feature_id": self.feature_id,
            "feature_type": self.feature_type,
            "specified_tolerance": self.specified_tolerance,
            "achievable_tolerance": self.achievable_tolerance,
            "is_within_tolerance": self.is_within_tolerance,
            "recommendation": self.recommendation
        }


@dataclass
class CNCValidation:
    """CNC machining validation results."""
    machine_type: str
    is_machinable: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    tool_accessibility: Dict[str, bool] = field(default_factory=dict)
    undercuts: List[str] = field(default_factory=list)
    minimum_feature_sizes: Dict[str, float] = field(default_factory=dict)
    tolerance_checks: List[ToleranceCheck] = field(default_factory=list)
    setup_count: int = 1
    estimated_machining_time: float = 0.0  # hours
    tool_list: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PrintValidation:
    """3D printing validation results."""
    printer_type: str
    is_printable: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    overhangs: List[str] = field(default_factory=list)
    thin_walls: List[str] = field(default_factory=list)
    bridges: List[str] = field(default_factory=list)
    support_volume: float = 0.0  # cm³
    estimated_print_time: float = 0.0  # hours
    estimated_material: float = 0.0  # grams
    support_required: bool = False
    orientation_score: float = 1.0


@dataclass
class ManufacturingValidation:
    """Overall manufacturing validation result."""
    process: ManufacturingProcess
    is_manufacturable: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    cnc_validation: Optional[CNCValidation] = None
    print_validation: Optional[PrintValidation] = None
    cost_estimate: Optional[float] = None
    lead_time_estimate: Optional[int] = None  # days
    material_recommendations: List[str] = field(default_factory=list)
    process_recommendations: List[str] = field(default_factory=list)
    process_parameters: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def feasible(self) -> bool:
        """Alias for is_manufacturable for API compatibility."""
        return self.is_manufacturable


# Import centralized Turkish validation messages
from ..constants.messages import VALIDATION_MESSAGES_TR