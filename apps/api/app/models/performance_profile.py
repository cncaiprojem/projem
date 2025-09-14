"""
Database models for Performance Profiling (Task 7.25)

Stores performance profiles, optimization recommendations, and metrics history.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from ..core.database import Base


class ProfileType(str, enum.Enum):
    """Profile type enumeration."""
    CPU = "cpu"
    MEMORY = "memory"
    GPU = "gpu"
    FULL = "full"
    LIGHTWEIGHT = "lightweight"


class OptimizationPriority(str, enum.Enum):
    """Optimization priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PerformanceProfile(Base):
    """
    Stores performance profiling sessions.

    Performans profilleme oturumlarını saklar.
    """
    __tablename__ = "performance_profiles"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(String(50), unique=True, nullable=False, index=True)
    profile_type = Column(SQLEnum(ProfileType), nullable=False)
    operation_name = Column(String(255), nullable=False)

    # Timing
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # CPU metrics
    cpu_time_seconds = Column(Float, nullable=True)
    function_calls = Column(JSON, nullable=True)  # Stores function call statistics
    hot_spots = Column(JSON, nullable=True)  # Top time-consuming functions

    # Memory metrics
    peak_memory_mb = Column(Float, nullable=True)
    memory_growth_mb = Column(Float, nullable=True)
    allocations = Column(JSON, nullable=True)  # Top memory allocations
    potential_leaks = Column(JSON, nullable=True)  # Detected memory leaks
    fragmentation_ratio = Column(Float, nullable=True)

    # GPU metrics
    gpu_available = Column(Boolean, default=False)
    gpu_name = Column(String(255), nullable=True)
    gpu_utilization_percent = Column(Float, nullable=True)
    gpu_memory_used_mb = Column(Float, nullable=True)

    # Metadata
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(String(50), nullable=True, index=True)
    document_id = Column(String(100), nullable=True, index=True)
    correlation_id = Column(String(50), nullable=True)
    metadata = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="performance_profiles")
    issues = relationship("PerformanceIssue", back_populates="profile", cascade="all, delete-orphan")
    recommendations = relationship("OptimizationRecommendation", back_populates="profile", cascade="all, delete-orphan")

    # Indexes for common queries
    __table_args__ = (
        Index("idx_performance_profile_user_time", "user_id", "start_time"),
        Index("idx_performance_profile_type_time", "profile_type", "start_time"),
        Index("idx_performance_profile_job", "job_id"),
    )


class PerformanceIssue(Base):
    """
    Stores detected performance issues.

    Tespit edilen performans sorunlarını saklar.
    """
    __tablename__ = "performance_issues"

    id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(String(50), unique=True, nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("performance_profiles.id"), nullable=False)

    # Issue details
    issue_type = Column(String(50), nullable=False)
    severity = Column(SQLEnum(OptimizationPriority), nullable=False)
    description = Column(Text, nullable=False)
    description_tr = Column(Text, nullable=False)  # Turkish description
    location = Column(String(500), nullable=True)  # Function/module/line
    impact = Column(Float, nullable=False)  # Performance impact (0.0 to 1.0)

    # Recommendations
    recommendation = Column(Text, nullable=False)
    recommendation_tr = Column(Text, nullable=False)  # Turkish recommendation

    # Metrics
    metrics = Column(JSON, nullable=True)  # Related metrics

    # Status
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # Timestamps
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    profile = relationship("PerformanceProfile", back_populates="issues")

    # Indexes
    __table_args__ = (
        Index("idx_performance_issue_type_severity", "issue_type", "severity"),
        Index("idx_performance_issue_resolved", "resolved"),
    )


class OptimizationRecommendation(Base):
    """
    Stores optimization recommendations.

    Optimizasyon önerilerini saklar.
    """
    __tablename__ = "optimization_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    recommendation_id = Column(String(50), unique=True, nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("performance_profiles.id"), nullable=True)
    plan_id = Column(Integer, ForeignKey("optimization_plans.id"), nullable=True)

    # Recommendation details
    title = Column(String(255), nullable=False)
    title_tr = Column(String(255), nullable=False)  # Turkish title
    description = Column(Text, nullable=False)
    description_tr = Column(Text, nullable=False)  # Turkish description

    # Classification
    category = Column(String(50), nullable=False)  # performance, scalability, etc.
    optimization_type = Column(String(50), nullable=False)  # algorithm, caching, etc.
    priority = Column(SQLEnum(OptimizationPriority), nullable=False)

    # Impact and effort
    estimated_impact = Column(String(100), nullable=False)  # e.g., "20-30% improvement"
    effort_level = Column(String(20), nullable=False)  # low, medium, high

    # Implementation
    implementation_steps = Column(JSON, nullable=False)  # List of steps
    implementation_steps_tr = Column(JSON, nullable=False)  # Turkish steps
    code_examples = Column(JSON, nullable=True)  # Code snippets

    # Related issues
    related_issues = Column(JSON, nullable=True)  # List of related issue IDs

    # Metrics
    metrics_before = Column(JSON, nullable=True)  # Current metrics
    metrics_expected = Column(JSON, nullable=True)  # Expected metrics after implementation

    # Implementation status
    implemented = Column(Boolean, default=False)
    implemented_at = Column(DateTime(timezone=True), nullable=True)
    implementation_notes = Column(Text, nullable=True)
    actual_impact = Column(String(100), nullable=True)  # Actual impact after implementation

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    profile = relationship("PerformanceProfile", back_populates="recommendations")
    plan = relationship("OptimizationPlan", back_populates="recommendations")

    # Indexes
    __table_args__ = (
        Index("idx_optimization_rec_priority", "priority"),
        Index("idx_optimization_rec_category", "category"),
        Index("idx_optimization_rec_implemented", "implemented"),
    )


class OptimizationPlan(Base):
    """
    Stores optimization plans with multiple recommendations.

    Birden fazla öneri içeren optimizasyon planlarını saklar.
    """
    __tablename__ = "optimization_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Plan details
    summary = Column(Text, nullable=False)
    summary_tr = Column(Text, nullable=False)  # Turkish summary
    total_estimated_impact = Column(String(100), nullable=False)

    # Monitoring and success metrics
    monitoring_plan = Column(JSON, nullable=True)
    success_metrics = Column(JSON, nullable=True)

    # Status
    status = Column(String(50), default="draft")  # draft, approved, in_progress, completed
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="optimization_plans")
    approver = relationship("User", foreign_keys=[approved_by])
    recommendations = relationship("OptimizationRecommendation", back_populates="plan", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("idx_optimization_plan_user", "user_id"),
        Index("idx_optimization_plan_status", "status"),
    )


class MemorySnapshot(Base):
    """
    Stores memory snapshots for tracking memory usage over time.

    Zaman içinde bellek kullanımını izlemek için bellek görüntülerini saklar.
    """
    __tablename__ = "memory_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Memory metrics
    process_memory_mb = Column(Float, nullable=False)
    python_memory_mb = Column(Float, nullable=False)
    gc_stats = Column(JSON, nullable=True)  # Garbage collection statistics
    top_allocations = Column(JSON, nullable=True)  # Top memory allocations
    object_counts = Column(JSON, nullable=True)  # Object counts by type

    # Context
    label = Column(String(255), nullable=True)
    job_id = Column(String(50), nullable=True, index=True)
    document_id = Column(String(100), nullable=True)

    # Timestamps
    timestamp = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User")

    # Indexes
    __table_args__ = (
        Index("idx_memory_snapshot_user_time", "user_id", "timestamp"),
        Index("idx_memory_snapshot_job", "job_id"),
    )


class OperationMetrics(Base):
    """
    Stores FreeCAD operation performance metrics.

    FreeCAD işlem performans metriklerini saklar.
    """
    __tablename__ = "operation_metrics"

    id = Column(Integer, primary_key=True, index=True)
    operation_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Operation details
    operation_type = Column(String(50), nullable=False)
    operation_name = Column(String(255), nullable=True)
    job_id = Column(String(50), nullable=True, index=True)
    document_id = Column(String(100), nullable=True, index=True)
    workflow_id = Column(String(50), nullable=True, index=True)

    # Performance metrics
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    cpu_time_seconds = Column(Float, nullable=True)
    memory_used_mb = Column(Float, nullable=True)
    memory_peak_mb = Column(Float, nullable=True)

    # Geometry metrics
    object_count = Column(Integer, default=0)
    vertex_count = Column(Integer, default=0)
    face_count = Column(Integer, default=0)

    # Status
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    # Metadata
    metadata = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")

    # Indexes
    __table_args__ = (
        Index("idx_operation_metrics_type_time", "operation_type", "start_time"),
        Index("idx_operation_metrics_user_time", "user_id", "start_time"),
        Index("idx_operation_metrics_job", "job_id"),
        Index("idx_operation_metrics_document", "document_id"),
        Index("idx_operation_metrics_workflow", "workflow_id"),
    )


class PerformanceBaseline(Base):
    """
    Stores performance baselines for comparison.

    Karşılaştırma için performans temel değerlerini saklar.
    """
    __tablename__ = "performance_baselines"

    id = Column(Integer, primary_key=True, index=True)
    baseline_name = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Baseline type
    baseline_type = Column(String(50), nullable=False)  # operation, workflow, system
    operation_type = Column(String(50), nullable=True)  # For operation-specific baselines

    # Metrics
    avg_duration_seconds = Column(Float, nullable=True)
    max_duration_seconds = Column(Float, nullable=True)
    avg_memory_mb = Column(Float, nullable=True)
    max_memory_mb = Column(Float, nullable=True)
    avg_cpu_percent = Column(Float, nullable=True)
    sample_count = Column(Integer, nullable=False)

    # Additional statistics
    statistics = Column(JSON, nullable=True)

    # Status
    active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")

    # Indexes and constraints
    __table_args__ = (
        UniqueConstraint("baseline_name", "user_id", "baseline_type", name="uq_baseline_name_user_type"),
        Index("idx_performance_baseline_active", "active"),
        Index("idx_performance_baseline_type", "baseline_type", "operation_type"),
    )