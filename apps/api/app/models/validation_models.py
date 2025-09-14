"""
Database models for Task 7.24 Model Validation

This module provides SQLAlchemy models for storing validation results,
certificates, and fix suggestions in the database.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field
import json

from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Float, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

# Create Base if not available from database
try:
    from ..core.database import Base
except ImportError:
    Base = declarative_base()


# Validation-related dataclasses and enums
class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class StandardType(str, Enum):
    """Standard types for compliance checking."""
    ISO_10303 = "ISO_10303"  # STEP
    ASME_Y14_5 = "ASME_Y14.5"  # GD&T
    ISO_1101 = "ISO_1101"  # Geometrical tolerancing
    DIN_919 = "DIN_919"  # German standards
    ISO_9001 = "ISO_9001"  # Quality management


@dataclass
class ValidationIssue:
    """Represents a validation issue."""
    issue_type: str
    severity: ValidationSeverity
    message: str
    turkish_message: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None
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
    compliance_score: float
    violations: List['ComplianceViolation'] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    certificate_eligible: bool = False


@dataclass
class ComplianceViolation:
    """Compliance violation detail."""
    rule_id: str
    rule_description: str
    severity: ValidationSeverity
    location: Optional[str] = None
    measured_value: Optional[float] = None
    expected_value: Optional[float] = None
    turkish_description: Optional[str] = None


# Import centralized Turkish validation messages
from ..constants.messages import VALIDATION_MESSAGES_TR


class ValidationResult(Base):
    """Model for storing validation results."""
    __tablename__ = "validation_results"
    
    id = Column(Integer, primary_key=True, index=True)
    validation_id = Column(String(255), unique=True, index=True, nullable=False)
    job_id = Column(String(255), index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Validation details
    profile = Column(String(50), nullable=False)  # basic, comprehensive, manufacturing
    is_valid = Column(Boolean, default=False)
    validation_score = Column(Float, nullable=True)
    
    # Timing
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Results
    sections = Column(JSON, nullable=True)  # Dict of validation sections
    issues = Column(JSON, nullable=True)  # List of validation issues
    metrics = Column(JSON, nullable=True)  # Performance metrics
    
    # Model hash for integrity
    model_hash = Column(String(64), nullable=True)  # SHA256 hash
    
    # Status tracking
    status = Column(String(20), default="pending")  # pending, completed, failed
    error_message = Column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="validation_results")
    certificates = relationship("ValidationCertificate", back_populates="validation_result")
    fix_suggestions = relationship("FixSuggestion", back_populates="validation_result")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_validation_user_created', 'user_id', 'created_at'),
        Index('idx_validation_status', 'status'),
    )


class ValidationCertificate(Base):
    """Model for storing validation certificates."""
    __tablename__ = "validation_certificates"
    
    id = Column(Integer, primary_key=True, index=True)
    certificate_id = Column(String(255), unique=True, index=True, nullable=False)
    validation_result_id = Column(Integer, ForeignKey("validation_results.id"), nullable=False)
    
    # Certificate details
    issued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Standards compliance
    standards = Column(JSON, nullable=True)  # List of standards (ISO, ASME, etc.)
    compliance_level = Column(String(50), nullable=True)  # full, partial, none
    
    # Digital signature
    signature = Column(Text, nullable=False)  # Digital signature of certificate
    model_hash = Column(String(64), nullable=False)  # SHA256 hash of validated model
    
    # Certificate metadata
    cert_metadata = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy reserved word
    
    # Relationships
    validation_result = relationship("ValidationResult", back_populates="certificates")
    
    # Indexes
    __table_args__ = (
        Index('idx_certificate_issued', 'issued_at'),
        Index('idx_certificate_expires', 'expires_at'),
    )


class FixSuggestion(Base):
    """Model for storing fix suggestions."""
    __tablename__ = "fix_suggestions"
    
    id = Column(Integer, primary_key=True, index=True)
    suggestion_id = Column(String(255), unique=True, index=True, nullable=False)
    validation_result_id = Column(Integer, ForeignKey("validation_results.id"), nullable=False)
    
    # Suggestion details
    type = Column(String(100), nullable=False)  # e.g., remove_self_intersection, thicken_walls
    severity = Column(String(20), nullable=False)  # critical, error, warning
    
    # Fix information
    description = Column(Text, nullable=False)
    turkish_description = Column(Text, nullable=True)
    
    # Automation
    automated = Column(Boolean, default=False)
    confidence = Column(String(20), nullable=True)  # high, medium, low
    
    # Parameters for fix
    parameters = Column(JSON, nullable=True)
    
    # Application status
    applied = Column(Boolean, default=False)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    application_result = Column(JSON, nullable=True)
    
    # Relationships
    validation_result = relationship("ValidationResult", back_populates="fix_suggestions")
    
    # Indexes
    __table_args__ = (
        Index('idx_suggestion_type', 'type'),
        Index('idx_suggestion_applied', 'applied'),
    )


class ValidationHistory(Base):
    """Model for tracking validation history."""
    __tablename__ = "validation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(255), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Version tracking
    version = Column(Integer, nullable=False, default=1)
    
    # Validation reference
    validation_result_id = Column(Integer, ForeignKey("validation_results.id"), nullable=True)
    
    # Change tracking
    action = Column(String(50), nullable=False)  # validated, fixed, certified
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # Change details
    changes = Column(JSON, nullable=True)
    comment = Column(Text, nullable=True)
    
    # Relationships
    user = relationship("User")
    validation_result = relationship("ValidationResult")
    
    # Indexes
    __table_args__ = (
        Index('idx_history_job_version', 'job_id', 'version'),
        Index('idx_history_user_timestamp', 'user_id', 'timestamp'),
    )