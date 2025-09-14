"""
Pydantic schemas for Performance Profiling (Task 7.25)

Provides data validation and serialization for performance profiling API endpoints.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


# Enums

class ProfileTypeSchema(str, Enum):
    """Profile type enumeration."""
    CPU = "cpu"
    MEMORY = "memory"
    GPU = "gpu"
    FULL = "full"
    LIGHTWEIGHT = "lightweight"


class PerformanceIssueTypeSchema(str, Enum):
    """Performance issue types."""
    HIGH_CPU_USAGE = "high_cpu_usage"
    MEMORY_LEAK = "memory_leak"
    MEMORY_FRAGMENTATION = "memory_fragmentation"
    SLOW_FUNCTION = "slow_function"
    EXCESSIVE_ALLOCATIONS = "excessive_allocations"
    GPU_UNDERUTILIZATION = "gpu_underutilization"
    IO_BOTTLENECK = "io_bottleneck"
    LOCK_CONTENTION = "lock_contention"
    CACHE_MISS = "cache_miss"


class OptimizationPrioritySchema(str, Enum):
    """Optimization priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FreeCADOperationTypeSchema(str, Enum):
    """FreeCAD operation types."""
    DOCUMENT_CREATE = "document_create"
    DOCUMENT_OPEN = "document_open"
    DOCUMENT_SAVE = "document_save"
    DOCUMENT_CLOSE = "document_close"
    GEOMETRY_CREATE = "geometry_create"
    GEOMETRY_MODIFY = "geometry_modify"
    GEOMETRY_BOOLEAN = "geometry_boolean"
    MESH_GENERATION = "mesh_generation"
    CAM_PATH_GENERATION = "cam_path_generation"
    ASSEMBLY_OPERATION = "assembly_operation"
    RENDERING = "rendering"
    IMPORT_OPERATION = "import_operation"
    EXPORT_OPERATION = "export_operation"
    ANALYSIS_OPERATION = "analysis_operation"
    CONSTRAINT_SOLVING = "constraint_solving"


class OptimizationTypeSchema(str, Enum):
    """Optimization types."""
    ALGORITHM = "algorithm"
    CACHING = "caching"
    PARALLELIZATION = "parallelization"
    BATCHING = "batching"
    MEMORY = "memory"
    IO = "io"
    DATABASE = "database"
    ARCHITECTURE = "architecture"


class RecommendationCategorySchema(str, Enum):
    """Recommendation categories."""
    PERFORMANCE = "performance"
    SCALABILITY = "scalability"
    RELIABILITY = "reliability"
    MAINTAINABILITY = "maintainability"
    COST = "cost"


class EffortLevelSchema(str, Enum):
    """Effort level for optimization recommendations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExportFormatSchema(str, Enum):
    """Export format options."""
    JSON = "json"
    CSV = "csv"
    HTML = "html"


# Request schemas

class StartProfilingRequest(BaseModel):
    """Request to start performance profiling."""
    model_config = ConfigDict(validate_assignment=True)

    profile_type: ProfileTypeSchema = Field(
        default=ProfileTypeSchema.FULL,
        description="Type of profiling to perform"
    )
    operation_name: str = Field(
        default="unknown",
        description="Name of the operation being profiled"
    )
    enable_continuous: bool = Field(
        default=False,
        description="Enable continuous monitoring"
    )
    sample_interval_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Sampling interval for continuous monitoring"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata for the profiling session"
    )


class StopProfilingRequest(BaseModel):
    """Request to stop performance profiling."""
    profile_id: str = Field(description="Profile session ID to stop")
    generate_report: bool = Field(
        default=True,
        description="Generate report after stopping"
    )


class ProfileOperationRequest(BaseModel):
    """Request to profile a specific FreeCAD operation."""
    model_config = ConfigDict(validate_assignment=True)

    operation_type: FreeCADOperationTypeSchema = Field(
        description="Type of FreeCAD operation"
    )
    operation_name: Optional[str] = Field(
        default=None,
        description="Custom name for the operation"
    )
    document_id: Optional[str] = Field(
        default=None,
        description="Document ID if operation is document-related"
    )
    job_id: Optional[str] = Field(
        default=None,
        description="Job ID associated with the operation"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional operation metadata"
    )


class GenerateOptimizationPlanRequest(BaseModel):
    """Request to generate optimization plan."""
    include_categories: Optional[List[RecommendationCategorySchema]] = Field(
        default=None,
        description="Categories to include in recommendations"
    )
    max_recommendations: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of recommendations"
    )
    include_quick_wins: bool = Field(
        default=True,
        description="Include low-effort, high-impact recommendations"
    )
    include_long_term: bool = Field(
        default=True,
        description="Include high-effort, high-impact recommendations"
    )


# Response schemas

class CPUProfileResponse(BaseModel):
    """CPU profiling results."""
    profile_id: str
    start_time: datetime
    end_time: datetime
    total_time: float
    function_calls: Dict[str, Dict[str, Any]]
    hot_spots: List[Dict[str, Any]]
    correlation_id: Optional[str] = None


class MemoryProfileResponse(BaseModel):
    """Memory profiling results."""
    profile_id: str
    start_time: datetime
    end_time: datetime
    peak_memory_mb: float
    current_memory_mb: float
    memory_growth_mb: float
    allocations: List[Dict[str, Any]]
    potential_leaks: List[Dict[str, Any]]
    fragmentation_ratio: float
    gc_stats: Dict[str, Any]
    correlation_id: Optional[str] = None


class GPUProfileResponse(BaseModel):
    """GPU profiling results."""
    profile_id: str
    start_time: datetime
    end_time: datetime
    gpu_available: bool
    gpu_name: Optional[str] = None
    gpu_memory_total_mb: Optional[float] = None
    gpu_memory_used_mb: Optional[float] = None
    gpu_utilization_percent: Optional[float] = None
    cuda_operations: List[Dict[str, Any]] = Field(default_factory=list)
    opencl_operations: List[Dict[str, Any]] = Field(default_factory=list)
    correlation_id: Optional[str] = None


class PerformanceIssueResponse(BaseModel):
    """Detected performance issue."""
    issue_type: PerformanceIssueTypeSchema
    severity: OptimizationPrioritySchema
    description: str
    description_tr: str
    location: Optional[str] = None
    impact: float = Field(ge=0.0, le=1.0)
    recommendation: str
    recommendation_tr: str
    metrics: Dict[str, Any] = Field(default_factory=dict)


class OperationMetricsResponse(BaseModel):
    """FreeCAD operation metrics."""
    operation_id: str
    operation_type: FreeCADOperationTypeSchema
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: float
    cpu_time_seconds: float
    memory_used_mb: float
    memory_peak_mb: float
    object_count: int = 0
    vertex_count: int = 0
    face_count: int = 0
    success: bool
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowProfileResponse(BaseModel):
    """FreeCAD workflow profiling results."""
    workflow_id: str
    workflow_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_duration_seconds: float
    operations: List[OperationMetricsResponse]
    bottlenecks: List[Dict[str, Any]]
    optimization_suggestions: List[Dict[str, Any]]
    resource_usage: Dict[str, Any]


class MemoryLeakResponse(BaseModel):
    """Detected memory leak information."""
    leak_id: str
    detected_at: datetime
    severity: str
    growth_rate_mb_per_hour: float
    suspected_source: Optional[str] = None
    allocation_traceback: Optional[List[str]] = None
    object_type: Optional[str] = None
    instance_count: int
    total_size_mb: float
    recommendations: List[str]


class FragmentationAnalysisResponse(BaseModel):
    """Memory fragmentation analysis."""
    analysis_id: str
    timestamp: datetime
    fragmentation_ratio: float = Field(ge=0.0, le=1.0)
    virtual_memory_mb: float
    resident_memory_mb: float
    shared_memory_mb: float
    heap_fragmentation: float = Field(ge=0.0, le=1.0)
    recommendations: List[str]


class GPUMetricsResponse(BaseModel):
    """GPU performance metrics."""
    timestamp: datetime
    device_id: int
    device_name: str
    utilization_percent: float = Field(ge=0.0, le=100.0)
    memory_used_mb: float
    memory_free_mb: float
    memory_utilization_percent: float = Field(ge=0.0, le=100.0)
    temperature_c: Optional[float] = None
    power_draw_w: Optional[float] = None
    fan_speed_percent: Optional[float] = None
    processes: List[Dict[str, Any]] = Field(default_factory=list)


class OptimizationRecommendationResponse(BaseModel):
    """Single optimization recommendation."""
    recommendation_id: str
    title: str
    title_tr: str
    description: str
    description_tr: str
    category: RecommendationCategorySchema
    optimization_type: OptimizationTypeSchema
    priority: OptimizationPrioritySchema
    estimated_impact: str
    effort_level: EffortLevelSchema
    implementation_steps: List[str]
    implementation_steps_tr: List[str]
    code_examples: Optional[List[str]] = None
    related_issues: List[str] = Field(default_factory=list)
    metrics_before: Dict[str, Any] = Field(default_factory=dict)
    metrics_expected: Dict[str, Any] = Field(default_factory=dict)


class OptimizationPlanResponse(BaseModel):
    """Complete optimization plan."""
    plan_id: str
    created_at: datetime
    summary: str
    summary_tr: str
    total_estimated_impact: str
    recommendations: List[OptimizationRecommendationResponse]
    quick_wins: List[OptimizationRecommendationResponse]
    long_term_improvements: List[OptimizationRecommendationResponse]
    monitoring_plan: Dict[str, Any]
    success_metrics: Dict[str, Any]


class PerformanceReportResponse(BaseModel):
    """Comprehensive performance report."""
    report_id: str
    generated_at: datetime
    performance_score: float = Field(ge=0.0, le=100.0)
    issues_count: int
    issues_by_type: Dict[str, List[Dict[str, Any]]]
    critical_issues: List[PerformanceIssueResponse]
    statistics: Dict[str, Any]
    recommendations: List[Dict[str, Any]]
    baseline_comparison: Optional[Dict[str, Any]] = None


class MemoryReportResponse(BaseModel):
    """Memory analysis report."""
    report_id: str
    generated_at: datetime
    current_memory_mb: float
    memory_trend: Dict[str, Any]
    detected_leaks: List[MemoryLeakResponse]
    fragmentation: FragmentationAnalysisResponse
    top_consumers: List[Dict[str, Any]]
    gc_stats: Dict[str, Any]
    recommendations: List[str]


class GPUSummaryResponse(BaseModel):
    """GPU performance summary."""
    timestamp: datetime
    devices: List[Dict[str, Any]]
    health_issues: List[Dict[str, Any]]
    optimization_recommendations: List[Dict[str, Any]]


class OperationStatisticsResponse(BaseModel):
    """FreeCAD operation statistics."""
    operation_count: int
    success_rate: float = Field(ge=0.0, le=100.0)
    duration: Dict[str, float]
    memory: Dict[str, float]
    operation_types: Optional[Dict[str, int]] = None


class DocumentAnalysisResponse(BaseModel):
    """Document operation analysis."""
    document_id: str
    total_operations: int
    total_time_seconds: float
    total_memory_mb: float
    operations_by_type: Dict[str, Dict[str, Any]]
    slowest_operations: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]


class BaselineComparisonResponse(BaseModel):
    """Performance baseline comparison."""
    operation_id: str
    operation_type: FreeCADOperationTypeSchema
    duration: Dict[str, Any]
    memory: Dict[str, Any]
    recommendations: List[Dict[str, Any]]


class ProfileListResponse(BaseModel):
    """List of performance profiles."""
    profiles: List[Dict[str, Any]]
    total_count: int
    profile_type: Optional[ProfileTypeSchema] = None


# WebSocket messages

class PerformanceMetricsMessage(BaseModel):
    """Real-time performance metrics for WebSocket."""
    timestamp: datetime
    cpu_usage_percent: float
    memory_usage_mb: float
    gpu_usage_percent: Optional[float] = None
    active_operations: int
    operations_per_second: float
    avg_response_time_ms: float
    error_rate: float = Field(ge=0.0, le=1.0)


class PerformanceAlertMessage(BaseModel):
    """Performance alert message."""
    alert_id: str
    timestamp: datetime
    severity: OptimizationPrioritySchema
    alert_type: PerformanceIssueTypeSchema
    message: str
    message_tr: str
    metrics: Dict[str, Any]
    recommended_action: str
    recommended_action_tr: str


# Batch operation schemas

class BatchProfileRequest(BaseModel):
    """Request to profile multiple operations."""
    operations: List[ProfileOperationRequest]
    aggregate_results: bool = Field(
        default=True,
        description="Aggregate results into single report"
    )


class BatchProfileResponse(BaseModel):
    """Batch profiling results."""
    batch_id: str
    total_operations: int
    successful_operations: int
    failed_operations: int
    total_duration_seconds: float
    individual_results: List[OperationMetricsResponse]
    aggregate_metrics: Optional[Dict[str, Any]] = None
    recommendations: List[OptimizationRecommendationResponse]


# Configuration schemas

class ProfilingConfigRequest(BaseModel):
    """Profiling configuration update request."""
    model_config = ConfigDict(validate_assignment=True)

    enable_auto_profiling: Optional[bool] = None
    profile_interval_seconds: Optional[int] = Field(None, ge=1, le=3600)
    max_profiles_stored: Optional[int] = Field(None, ge=10, le=1000)
    memory_snapshot_interval: Optional[int] = Field(None, ge=10, le=600)
    gpu_monitoring_enabled: Optional[bool] = None
    leak_detection_threshold_mb: Optional[float] = Field(None, ge=1.0, le=100.0)
    bottleneck_thresholds: Optional[Dict[str, float]] = None


class ProfilingConfigResponse(BaseModel):
    """Current profiling configuration."""
    enable_auto_profiling: bool
    profile_interval_seconds: int
    max_profiles_stored: int
    memory_snapshot_interval: int
    gpu_monitoring_enabled: bool
    leak_detection_threshold_mb: float
    bottleneck_thresholds: Dict[str, float]


# Export schemas

class ExportProfilesRequest(BaseModel):
    """Request to export performance profiles."""
    profile_type: Optional[ProfileTypeSchema] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    format: ExportFormatSchema = Field(default=ExportFormatSchema.JSON)
    include_raw_data: bool = Field(default=False)


class ExportProfilesResponse(BaseModel):
    """Export result."""
    export_id: str
    file_path: str
    file_size_bytes: int
    profile_count: int
    export_format: ExportFormatSchema
    created_at: datetime