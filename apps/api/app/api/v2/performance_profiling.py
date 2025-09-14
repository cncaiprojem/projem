"""
FastAPI endpoints for Performance Profiling and Optimization (Task 7.25)

Provides REST API and WebSocket endpoints for:
- Real-time performance monitoring
- CPU, memory, and GPU profiling
- FreeCAD operation profiling
- Memory leak detection
- Optimization recommendations
- Performance dashboard data
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
import asyncio
import json
import uuid
import os
import tempfile
from pathlib import Path

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.core.telemetry import tracer
from app.core import metrics
from app.models.user import User
from app.schemas.performance import (
    StartProfilingRequest,
    StopProfilingRequest,
    ProfileOperationRequest,
    GenerateOptimizationPlanRequest,
    CPUProfileResponse,
    MemoryProfileResponse,
    GPUProfileResponse,
    PerformanceIssueResponse,
    OperationMetricsResponse,
    WorkflowProfileResponse,
    MemoryLeakResponse,
    FragmentationAnalysisResponse,
    GPUMetricsResponse,
    OptimizationRecommendationResponse,
    OptimizationPlanResponse,
    PerformanceReportResponse,
    MemoryReportResponse,
    GPUSummaryResponse,
    OperationStatisticsResponse,
    DocumentAnalysisResponse,
    BaselineComparisonResponse,
    ProfileListResponse,
    PerformanceMetricsMessage,
    PerformanceAlertMessage,
    BatchProfileRequest,
    BatchProfileResponse,
    ProfilingConfigRequest,
    ProfilingConfigResponse,
    ExportProfilesRequest,
    ExportProfilesResponse,
    ProfileTypeSchema,
    FreeCADOperationTypeSchema
)

# Import profiling services
from app.services.performance_profiler import performance_profiler
from app.services.freecad_operation_profiler import freecad_operation_profiler, FreeCADOperationType
from app.services.memory_profiler import memory_profiler
from app.services.gpu_monitor import gpu_monitor
from app.services.optimization_recommender import optimization_recommender

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v2/performance", tags=["performance"])


# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for real-time monitoring."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._monitoring_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

        # Start monitoring if this is the first connection
        if len(self.active_connections) == 1:
            self._monitoring_task = asyncio.create_task(self._monitor_performance())

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

        # Stop monitoring if no connections
        if len(self.active_connections) == 0 and self._monitoring_task:
            self._monitoring_task.cancel()
            self._monitoring_task = None

    async def send_metrics(self, message: PerformanceMetricsMessage):
        """Send metrics to all connected clients."""
        message_dict = message.dict()
        for connection in self.active_connections:
            try:
                await connection.send_json(message_dict)
            except Exception as e:
                logger.error(f"Error sending metrics: {e}")

    async def send_alert(self, alert: PerformanceAlertMessage):
        """Send alert to all connected clients."""
        alert_dict = alert.dict()
        for connection in self.active_connections:
            try:
                await connection.send_json(alert_dict)
            except Exception as e:
                logger.error(f"Error sending alert: {e}")

    async def _monitor_performance(self):
        """Background task to monitor performance and send updates."""
        import psutil

        while True:
            try:
                # Collect current metrics
                process = psutil.Process()
                cpu_percent = process.cpu_percent()
                memory_mb = process.memory_info().rss / (1024 * 1024)

                # Get GPU metrics if available
                gpu_percent = None
                if gpu_monitor.gpu_devices:
                    gpu_metrics = gpu_monitor.get_current_metrics(0)
                    if gpu_metrics:
                        gpu_percent = gpu_metrics.utilization_percent

                # Create metrics message
                metrics_msg = PerformanceMetricsMessage(
                    timestamp=datetime.now(timezone.utc),
                    cpu_usage_percent=cpu_percent,
                    memory_usage_mb=memory_mb,
                    gpu_usage_percent=gpu_percent,
                    active_operations=len(freecad_operation_profiler.active_operations),
                    operations_per_second=0.0,  # Would need to calculate from history
                    avg_response_time_ms=0.0,  # Would need to calculate from history
                    error_rate=0.0  # Would need to calculate from history
                )

                await self.send_metrics(metrics_msg)

                # Check for issues and send alerts
                if cpu_percent > 80:
                    alert = PerformanceAlertMessage(
                        alert_id=f"alert_{uuid.uuid4().hex[:8]}",
                        timestamp=datetime.now(timezone.utc),
                        severity="high",
                        alert_type="high_cpu_usage",
                        message=f"High CPU usage detected: {cpu_percent:.1f}%",
                        message_tr=f"Yüksek CPU kullanımı tespit edildi: {cpu_percent:.1f}%",
                        metrics={"cpu_percent": cpu_percent},
                        recommended_action="Consider scaling resources or optimizing operations",
                        recommended_action_tr="Kaynakları ölçeklendirmeyi veya işlemleri optimize etmeyi düşünün"
                    )
                    await self.send_alert(alert)

                await asyncio.sleep(5)  # Update every 5 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in performance monitoring: {e}")
                await asyncio.sleep(5)


manager = ConnectionManager()


# Profiling endpoints

@router.post("/profile/start", response_model=Dict[str, str])
async def start_profiling(
    request: StartProfilingRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Start performance profiling session.

    Başlatır:
    - CPU profiling
    - Memory profiling
    - GPU monitoring (if available)
    """
    with tracer.start_as_current_span("start_profiling") as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("profile.type", request.profile_type.value)

        profile_id = f"profile_{uuid.uuid4().hex[:8]}"

        # Start profiling based on type
        if request.profile_type == ProfileTypeSchema.CPU:
            # Start CPU profiling in background
            background_tasks.add_task(
                performance_profiler.profile_cpu,
                request.operation_name
            )
        elif request.profile_type == ProfileTypeSchema.MEMORY:
            # Start memory profiling
            background_tasks.add_task(
                performance_profiler.profile_memory,
                request.operation_name
            )
        elif request.profile_type == ProfileTypeSchema.GPU:
            # Start GPU profiling
            if not gpu_monitor.gpu_devices:
                raise HTTPException(
                    status_code=400,
                    detail="GPU monitoring not available"
                )
            background_tasks.add_task(
                performance_profiler.profile_gpu,
                request.operation_name
            )
        elif request.profile_type == ProfileTypeSchema.FULL:
            # Start full profiling
            background_tasks.add_task(
                performance_profiler.profile_full,
                request.operation_name
            )

        # Enable continuous monitoring if requested
        if request.enable_continuous:
            performance_profiler.enable_auto_profiling = True
            performance_profiler.profile_interval_seconds = request.sample_interval_seconds
            performance_profiler.start_auto_profiling()

        logger.info(f"Profiling started",
                   profile_id=profile_id,
                   profile_type=request.profile_type.value,
                   user_id=current_user.id)

        return {
            "profile_id": profile_id,
            "status": "started",
            "message": f"Profiling started for {request.operation_name}"
        }


@router.post("/profile/stop", response_model=PerformanceReportResponse)
async def stop_profiling(
    request: StopProfilingRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Stop profiling and generate report.

    Durdurur ve rapor oluşturur.
    """
    with tracer.start_as_current_span("stop_profiling") as span:
        span.set_attribute("profile.id", request.profile_id)

        # Stop auto-profiling if it was enabled
        if performance_profiler.enable_auto_profiling:
            performance_profiler.stop_auto_profiling()

        # Generate report if requested
        if request.generate_report:
            report = performance_profiler.generate_optimization_report()

            # Convert to response model
            issues = performance_profiler.detect_performance_issues()

            return PerformanceReportResponse(
                report_id=report["report_id"],
                generated_at=datetime.fromisoformat(report["generated_at"]),
                performance_score=report["performance_score"],
                issues_count=report["issues_count"],
                issues_by_type=report["issues_by_type"],
                critical_issues=[
                    PerformanceIssueResponse(
                        issue_type=issue.issue_type.value,
                        severity=issue.severity.value,
                        description=issue.description,
                        description_tr=issue.description_tr,
                        location=issue.location,
                        impact=issue.impact,
                        recommendation=issue.recommendation,
                        recommendation_tr=issue.recommendation_tr,
                        metrics=issue.metrics
                    )
                    for issue in issues if issue.severity.value == "critical"
                ],
                statistics=report["statistics"],
                recommendations=report["recommendations"],
                baseline_comparison=report["baseline_comparison"]
            )

        return PerformanceReportResponse(
            report_id=f"report_{uuid.uuid4().hex[:8]}",
            generated_at=datetime.now(timezone.utc),
            performance_score=100.0,
            issues_count=0,
            issues_by_type={},
            critical_issues=[],
            statistics={},
            recommendations=[]
        )


@router.post("/profile/operation", response_model=OperationMetricsResponse)
async def profile_operation(
    request: ProfileOperationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Profile a specific FreeCAD operation.

    FreeCAD işlemini profiller.
    """
    with tracer.start_as_current_span("profile_operation") as span:
        span.set_attribute("operation.type", request.operation_type.value)
        span.set_attribute("user.id", current_user.id)

        # Convert schema enum to service enum
        operation_type = FreeCADOperationType[request.operation_type.value.upper()]

        # Profile the operation
        with freecad_operation_profiler.profile_operation(
            operation_type,
            request.operation_name,
            request.metadata
        ) as operation:
            # Simulate some work
            await asyncio.sleep(0.1)

        # Return metrics
        return OperationMetricsResponse(
            operation_id=operation.operation_id,
            operation_type=request.operation_type,
            start_time=operation.start_time,
            end_time=operation.end_time,
            duration_seconds=operation.duration_seconds,
            cpu_time_seconds=operation.cpu_time_seconds,
            memory_used_mb=operation.memory_used_mb,
            memory_peak_mb=operation.memory_peak_mb,
            object_count=operation.object_count,
            vertex_count=operation.vertex_count,
            face_count=operation.face_count,
            success=operation.success,
            error_message=operation.error_message,
            metadata=operation.metadata
        )


# Memory profiling endpoints

@router.get("/memory/snapshot", response_model=Dict[str, Any])
async def take_memory_snapshot(
    label: Optional[str] = Query(None, description="Label for the snapshot"),
    current_user: User = Depends(get_current_user)
):
    """
    Take a memory snapshot.

    Bellek görüntüsü alır.
    """
    snapshot = memory_profiler.take_snapshot(label)

    return snapshot.to_dict()


@router.get("/memory/leaks", response_model=List[MemoryLeakResponse])
async def detect_memory_leaks(
    time_window_minutes: int = Query(10, ge=1, le=60),
    current_user: User = Depends(get_current_user)
):
    """
    Detect memory leaks.

    Bellek sızıntılarını tespit eder.
    """
    leaks = memory_profiler.detect_memory_leaks(time_window_minutes)

    return [
        MemoryLeakResponse(
            leak_id=leak.leak_id,
            detected_at=leak.detected_at,
            severity=leak.severity.value,
            growth_rate_mb_per_hour=leak.growth_rate_mb_per_hour,
            suspected_source=leak.suspected_source,
            allocation_traceback=leak.allocation_traceback,
            object_type=leak.object_type,
            instance_count=leak.instance_count,
            total_size_mb=leak.total_size_mb,
            recommendations=leak.recommendations
        )
        for leak in leaks
    ]


@router.get("/memory/fragmentation", response_model=FragmentationAnalysisResponse)
async def analyze_fragmentation(
    current_user: User = Depends(get_current_user)
):
    """
    Analyze memory fragmentation.

    Bellek parçalanmasını analiz eder.
    """
    analysis = memory_profiler.analyze_fragmentation()

    return FragmentationAnalysisResponse(
        analysis_id=analysis.analysis_id,
        timestamp=analysis.timestamp,
        fragmentation_ratio=analysis.fragmentation_ratio,
        virtual_memory_mb=analysis.virtual_memory_mb,
        resident_memory_mb=analysis.resident_memory_mb,
        shared_memory_mb=analysis.shared_memory_mb,
        heap_fragmentation=analysis.heap_fragmentation,
        recommendations=analysis.recommendations
    )


@router.get("/memory/report", response_model=MemoryReportResponse)
async def get_memory_report(
    current_user: User = Depends(get_current_user)
):
    """
    Generate comprehensive memory report.

    Kapsamlı bellek raporu oluşturur.
    """
    report = memory_profiler.generate_memory_report()

    # Get fragmentation analysis
    fragmentation = memory_profiler.analyze_fragmentation()

    # Get recent leaks
    leaks = memory_profiler.detect_memory_leaks(30)

    return MemoryReportResponse(
        report_id=report["report_id"],
        generated_at=datetime.fromisoformat(report["generated_at"]),
        current_memory_mb=report["current_memory_mb"],
        memory_trend=report["memory_trend"],
        detected_leaks=[
            MemoryLeakResponse(
                leak_id=leak.leak_id,
                detected_at=leak.detected_at,
                severity=leak.severity.value,
                growth_rate_mb_per_hour=leak.growth_rate_mb_per_hour,
                suspected_source=leak.suspected_source,
                allocation_traceback=leak.allocation_traceback,
                object_type=leak.object_type,
                instance_count=leak.instance_count,
                total_size_mb=leak.total_size_mb,
                recommendations=leak.recommendations
            )
            for leak in leaks
        ],
        fragmentation=FragmentationAnalysisResponse(
            analysis_id=fragmentation.analysis_id,
            timestamp=fragmentation.timestamp,
            fragmentation_ratio=fragmentation.fragmentation_ratio,
            virtual_memory_mb=fragmentation.virtual_memory_mb,
            resident_memory_mb=fragmentation.resident_memory_mb,
            shared_memory_mb=fragmentation.shared_memory_mb,
            heap_fragmentation=fragmentation.heap_fragmentation,
            recommendations=fragmentation.recommendations
        ),
        top_consumers=report["top_consumers"],
        gc_stats=report["gc_stats"],
        recommendations=report["recommendations"]
    )


@router.post("/memory/optimize", response_model=Dict[str, Any])
async def optimize_memory(
    current_user: User = Depends(get_current_user)
):
    """
    Perform memory optimization.

    Bellek optimizasyonu yapar.
    """
    results = memory_profiler.optimize_memory()

    logger.info(f"Memory optimization performed",
               freed_mb=results["freed_mb"],
               user_id=current_user.id)

    return results


# GPU monitoring endpoints

@router.get("/gpu/metrics", response_model=GPUSummaryResponse)
async def get_gpu_metrics(
    device_id: Optional[int] = Query(None, description="Specific GPU device ID"),
    current_user: User = Depends(get_current_user)
):
    """
    Get GPU performance metrics.

    GPU performans metriklerini alır.
    """
    summary = gpu_monitor.get_gpu_summary(device_id)
    health_issues = gpu_monitor.check_gpu_health()
    recommendations = gpu_monitor.get_optimization_recommendations()

    return GPUSummaryResponse(
        timestamp=datetime.fromisoformat(summary["timestamp"]),
        devices=summary["devices"],
        health_issues=health_issues,
        optimization_recommendations=recommendations
    )


# Optimization endpoints

@router.post("/optimize/plan", response_model=OptimizationPlanResponse)
async def generate_optimization_plan(
    request: GenerateOptimizationPlanRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Generate optimization plan based on performance data.

    Performans verilerine dayalı optimizasyon planı oluşturur.
    """
    with tracer.start_as_current_span("generate_optimization_plan") as span:
        span.set_attribute("user.id", current_user.id)

        # Generate plan
        plan = optimization_recommender.generate_optimization_plan(
            include_categories=request.include_categories,
            max_recommendations=request.max_recommendations
        )

        # Convert to response model
        return OptimizationPlanResponse(
            plan_id=plan.plan_id,
            created_at=plan.created_at,
            summary=plan.summary,
            summary_tr=plan.summary_tr,
            total_estimated_impact=plan.total_estimated_impact,
            recommendations=[
                OptimizationRecommendationResponse(**rec.to_dict())
                for rec in plan.recommendations
            ],
            quick_wins=[
                OptimizationRecommendationResponse(**rec.to_dict())
                for rec in plan.quick_wins
            ] if request.include_quick_wins else [],
            long_term_improvements=[
                OptimizationRecommendationResponse(**rec.to_dict())
                for rec in plan.long_term_improvements
            ] if request.include_long_term else [],
            monitoring_plan=plan.monitoring_plan,
            success_metrics=plan.success_metrics
        )


@router.get("/optimize/architecture", response_model=List[OptimizationRecommendationResponse])
async def get_architecture_recommendations(
    current_user: User = Depends(get_current_user)
):
    """
    Get architecture-level optimization recommendations.

    Mimari seviyesinde optimizasyon önerileri alır.
    """
    recommendations = optimization_recommender.get_architecture_recommendations()

    return [
        OptimizationRecommendationResponse(**rec.to_dict())
        for rec in recommendations
    ]


# Operation analysis endpoints

@router.get("/operations/statistics", response_model=OperationStatisticsResponse)
async def get_operation_statistics(
    operation_type: Optional[FreeCADOperationTypeSchema] = Query(None),
    current_user: User = Depends(get_current_user)
):
    """
    Get FreeCAD operation statistics.

    FreeCAD işlem istatistiklerini alır.
    """
    # Convert schema enum to service enum if provided
    op_type = FreeCADOperationType[operation_type.value.upper()] if operation_type else None

    stats = freecad_operation_profiler.get_operation_statistics(op_type)

    return OperationStatisticsResponse(
        operation_count=stats.get("operation_count", 0),
        success_rate=stats.get("success_rate", 100.0),
        duration=stats.get("duration", {}),
        memory=stats.get("memory", {}),
        operation_types=stats.get("operation_types")
    )


@router.get("/operations/document/{document_id}", response_model=DocumentAnalysisResponse)
async def analyze_document_operations(
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Analyze operations for a specific document.

    Belirli bir belge için işlemleri analiz eder.
    """
    analysis = freecad_operation_profiler.analyze_document_operations(document_id)

    return DocumentAnalysisResponse(**analysis)


# Profile management endpoints

@router.get("/profiles", response_model=ProfileListResponse)
async def list_profiles(
    profile_type: Optional[ProfileTypeSchema] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user)
):
    """
    List recent performance profiles.

    Son performans profillerini listeler.
    """
    profiles = performance_profiler.get_recent_profiles(profile_type, limit)

    return ProfileListResponse(
        profiles=profiles,
        total_count=len(profiles),
        profile_type=profile_type
    )


@router.delete("/profiles")
async def clear_profiles(
    profile_type: Optional[ProfileTypeSchema] = Query(None),
    current_user: User = Depends(get_current_user)
):
    """
    Clear stored profiles.

    Saklanan profilleri temizler.
    """
    performance_profiler.clear_profiles(profile_type)

    logger.info(f"Profiles cleared",
               profile_type=profile_type,
               user_id=current_user.id)

    return {"status": "success", "message": "Profiles cleared"}


# Configuration endpoints

@router.get("/config", response_model=ProfilingConfigResponse)
async def get_profiling_config(
    current_user: User = Depends(get_current_user)
):
    """
    Get current profiling configuration.

    Mevcut profilleme yapılandırmasını alır.
    """
    return ProfilingConfigResponse(
        enable_auto_profiling=performance_profiler.enable_auto_profiling,
        profile_interval_seconds=performance_profiler.profile_interval_seconds,
        max_profiles_stored=performance_profiler.max_profiles_stored,
        memory_snapshot_interval=memory_profiler.snapshot_interval_seconds,
        gpu_monitoring_enabled=gpu_monitor.enable_monitoring,
        leak_detection_threshold_mb=memory_profiler.leak_detection_threshold_mb,
        bottleneck_thresholds=freecad_operation_profiler.bottleneck_thresholds
    )


@router.put("/config", response_model=ProfilingConfigResponse)
async def update_profiling_config(
    request: ProfilingConfigRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Update profiling configuration.

    Profilleme yapılandırmasını günceller.
    """
    # Update configuration
    if request.enable_auto_profiling is not None:
        performance_profiler.enable_auto_profiling = request.enable_auto_profiling
        if request.enable_auto_profiling:
            performance_profiler.start_auto_profiling()
        else:
            performance_profiler.stop_auto_profiling()

    if request.profile_interval_seconds is not None:
        performance_profiler.profile_interval_seconds = request.profile_interval_seconds

    if request.max_profiles_stored is not None:
        performance_profiler.max_profiles_stored = request.max_profiles_stored

    if request.memory_snapshot_interval is not None:
        memory_profiler.snapshot_interval_seconds = request.memory_snapshot_interval

    if request.gpu_monitoring_enabled is not None:
        if request.gpu_monitoring_enabled:
            gpu_monitor.start_monitoring()
        else:
            gpu_monitor.stop_monitoring()

    if request.leak_detection_threshold_mb is not None:
        memory_profiler.leak_detection_threshold_mb = request.leak_detection_threshold_mb

    if request.bottleneck_thresholds is not None:
        freecad_operation_profiler.bottleneck_thresholds.update(request.bottleneck_thresholds)

    logger.info("Profiling configuration updated", user_id=current_user.id)

    # Return updated configuration
    return ProfilingConfigResponse(
        enable_auto_profiling=performance_profiler.enable_auto_profiling,
        profile_interval_seconds=performance_profiler.profile_interval_seconds,
        max_profiles_stored=performance_profiler.max_profiles_stored,
        memory_snapshot_interval=memory_profiler.snapshot_interval_seconds,
        gpu_monitoring_enabled=gpu_monitor.enable_monitoring,
        leak_detection_threshold_mb=memory_profiler.leak_detection_threshold_mb,
        bottleneck_thresholds=freecad_operation_profiler.bottleneck_thresholds
    )


# Export endpoints

@router.post("/export", response_model=ExportProfilesResponse)
async def export_profiles(
    request: ExportProfilesRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Export performance profiles.

    Performans profillerini dışa aktarır.
    """
    export_id = f"export_{uuid.uuid4().hex[:8]}"

    # Get profiles to export
    profiles = performance_profiler.get_recent_profiles(request.profile_type, limit=1000)

    # Filter by date if specified
    if request.start_date:
        profiles = [
            p for p in profiles
            if datetime.fromisoformat(p.get("start_time", "")) >= request.start_date
        ]

    if request.end_date:
        profiles = [
            p for p in profiles
            if datetime.fromisoformat(p.get("start_time", "")) <= request.end_date
        ]

    # Create export file
    export_dir = Path(tempfile.gettempdir()) / "performance_exports"
    export_dir.mkdir(exist_ok=True)

    if request.format == "json":
        file_path = export_dir / f"{export_id}.json"
        with open(file_path, "w") as f:
            json.dump(profiles, f, indent=2, default=str)
    elif request.format == "csv":
        # Simplified CSV export
        import csv
        file_path = export_dir / f"{export_id}.csv"

        if profiles:
            with open(file_path, "w", newline="") as f:
                # Use first profile to get headers
                fieldnames = list(profiles[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(profiles)
    else:  # HTML
        file_path = export_dir / f"{export_id}.html"
        # Generate simple HTML report
        html_content = f"""
        <html>
        <head><title>Performance Report</title></head>
        <body>
        <h1>Performance Profiles Export</h1>
        <p>Export ID: {export_id}</p>
        <p>Profile Count: {len(profiles)}</p>
        <pre>{json.dumps(profiles, indent=2, default=str)}</pre>
        </body>
        </html>
        """
        with open(file_path, "w") as f:
            f.write(html_content)

    file_size = file_path.stat().st_size

    logger.info(f"Profiles exported",
               export_id=export_id,
               format=request.format,
               profile_count=len(profiles),
               user_id=current_user.id)

    return ExportProfilesResponse(
        export_id=export_id,
        file_path=str(file_path),
        file_size_bytes=file_size,
        profile_count=len(profiles),
        export_format=request.format,
        created_at=datetime.now(timezone.utc)
    )


@router.get("/export/{export_id}/download")
async def download_export(
    export_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Download exported profiles.

    Dışa aktarılan profilleri indirir.
    """
    # Find export file
    export_dir = Path(tempfile.gettempdir()) / "performance_exports"

    for ext in [".json", ".csv", ".html"]:
        file_path = export_dir / f"{export_id}{ext}"
        if file_path.exists():
            return FileResponse(
                path=str(file_path),
                filename=f"performance_export_{export_id}{ext}",
                media_type="application/octet-stream"
            )

    raise HTTPException(status_code=404, detail="Export not found")


# WebSocket endpoint for real-time monitoring

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time performance monitoring.

    Gerçek zamanlı performans izleme için WebSocket endpoint'i.
    """
    await manager.connect(websocket)

    try:
        while True:
            # Keep connection alive and handle any incoming messages
            data = await websocket.receive_text()

            # Handle commands from client
            if data == "ping":
                await websocket.send_text("pong")
            elif data == "get_status":
                # Send current status
                status = {
                    "active_profiles": len(performance_profiler._active_profilers),
                    "memory_snapshots": len(memory_profiler.memory_snapshots),
                    "gpu_available": len(gpu_monitor.gpu_devices) > 0
                }
                await websocket.send_json(status)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected")