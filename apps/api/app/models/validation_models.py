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


# Import dataclasses from schemas - only import what's actually used
from ..schemas.validation_schemas import (
    StandardType,
    ComplianceResult
)


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