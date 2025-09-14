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
import time
import re

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
from app.services.profiling_state_manager import state_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v2/performance", tags=["performance"])


# WebSocket connection manager with Redis Pub/Sub for multi-worker support
class ConnectionManager:
    """
    Manages WebSocket connections for real-time monitoring with Redis Pub/Sub.

    Architecture:
    - Each worker maintains local WebSocket connections
    - Metrics/alerts are published to Redis channels
    - All workers subscribe to channels and forward to their local clients
    - Ensures all clients receive updates regardless of which worker generated them
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._monitoring_task: Optional[asyncio.Task] = None
        self._subscriber_task: Optional[asyncio.Task] = None
        self._last_metrics_time = time.time()

        # Redis Pub/Sub channels
        self.METRICS_CHANNEL = "performance:metrics"
        self.ALERTS_CHANNEL = "performance:alerts"

        # Redis connection pools
        self._publisher_pool = None  # Lazy-initialized async pool for publishing
        self._subscriber_client = None  # Separate connection for subscribing (required by Redis Pub/Sub)
        self._pubsub = None

    async def connect(self, websocket: WebSocket):
        """Accept WebSocket connection and start monitoring/subscribing if first client."""
        await websocket.accept()
        self.active_connections.append(websocket)

        # Log connection with worker info
        logger.info(f"WebSocket client connected",
                   worker_id=os.getpid(),
                   total_connections=len(self.active_connections))

        # Start monitoring and subscribing if this is the first connection
        if len(self.active_connections) == 1:
            # Start local monitoring task (generates metrics)
            self._monitoring_task = asyncio.create_task(self._monitor_performance())

            # Start Redis subscriber task (receives metrics from all workers)
            self._subscriber_task = asyncio.create_task(self._subscribe_to_redis())

    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection and cleanup if last client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        logger.info(f"WebSocket client disconnected",
                   worker_id=os.getpid(),
                   remaining_connections=len(self.active_connections))

        # Stop monitoring and subscribing if no connections
        if len(self.active_connections) == 0:
            if self._monitoring_task:
                self._monitoring_task.cancel()
                self._monitoring_task = None

            if self._subscriber_task:
                self._subscriber_task.cancel()
                self._subscriber_task = None

            # Cleanup Redis subscriber
            if self._pubsub:
                try:
                    self._pubsub.close()
                except Exception as e:
                    logger.error(f"Error closing pubsub: {e}")
                self._pubsub = None

            if self._subscriber_client:
                try:
                    self._subscriber_client.close()
                except Exception as e:
                    logger.error(f"Error closing subscriber client: {e}")
                self._subscriber_client = None

            # Cleanup publisher pool
            if self._publisher_pool:
                try:
                    # Properly disconnect async pool
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if not loop.is_closed():
                        asyncio.create_task(self._publisher_pool.disconnect())
                except Exception as e:
                    logger.error(f"Error closing publisher pool: {e}")
                self._publisher_pool = None

    async def _subscribe_to_redis(self):
        """
        Subscribe to Redis channels and forward messages to local WebSocket clients.
        Runs as long as there are active connections.
        """
        import redis.asyncio as redis_async

        try:
            # Create dedicated connection for subscribing
            self._subscriber_client = redis_async.Redis.from_url(
                state_manager.redis_url,
                decode_responses=False
            )

            self._pubsub = self._subscriber_client.pubsub()

            # Subscribe to channels
            await self._pubsub.subscribe(self.METRICS_CHANNEL, self.ALERTS_CHANNEL)

            logger.info(f"Redis Pub/Sub subscriber started",
                       worker_id=os.getpid(),
                       channels=[self.METRICS_CHANNEL, self.ALERTS_CHANNEL])

            # Listen for messages
            async for message in self._pubsub.listen():
                if message['type'] == 'message':
                    try:
                        # Deserialize message
                        data = json.loads(message['data'].decode('utf-8'))
                        channel = message['channel'].decode('utf-8')

                        # Forward to local WebSocket clients
                        await self._broadcast_to_local_clients(data, channel)

                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode message: {e}")
                    except Exception as e:
                        logger.error(f"Error processing pub/sub message: {e}")

        except asyncio.CancelledError:
            logger.info("Redis subscriber task cancelled", worker_id=os.getpid())
            raise
        except Exception as e:
            logger.error(f"Redis subscriber error: {e}", worker_id=os.getpid())
            # Reconnect after error
            await asyncio.sleep(5)
            if self.active_connections:
                self._subscriber_task = asyncio.create_task(self._subscribe_to_redis())

    async def _broadcast_to_local_clients(self, data: dict, channel: str):
        """Broadcast message to all local WebSocket clients."""
        if not self.active_connections:
            return

        # Create a copy to avoid modification during iteration
        connections = list(self.active_connections)
        disconnected = []

        for connection in connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"Error sending to WebSocket client: {e}")
                disconnected.append(connection)

        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def publish_metrics(self, message: PerformanceMetricsMessage):
        """
        Publish metrics to Redis channel for all workers to receive.
        This replaces the old send_metrics method.
        """
        try:
            message_dict = message.dict()
            message_dict['worker_id'] = os.getpid()  # Include source worker ID

            # Publish to Redis channel
            await self._execute_redis_publish(
                self.METRICS_CHANNEL,
                json.dumps(message_dict, default=str)
            )

        except Exception as e:
            logger.error(f"Failed to publish metrics: {e}")

    async def publish_alert(self, alert: PerformanceAlertMessage):
        """
        Publish alert to Redis channel for all workers to receive.
        This replaces the old send_alert method.
        """
        try:
            alert_dict = alert.dict()
            alert_dict['worker_id'] = os.getpid()  # Include source worker ID

            # Publish to Redis channel
            await self._execute_redis_publish(
                self.ALERTS_CHANNEL,
                json.dumps(alert_dict, default=str)
            )

        except Exception as e:
            logger.error(f"Failed to publish alert: {e}")

    async def _execute_redis_publish(self, channel: str, message: str):
        """Execute Redis publish with error handling."""
        try:
            import redis.asyncio as redis_async

            # Initialize publisher pool if needed (lazy initialization)
            if self._publisher_pool is None:
                self._publisher_pool = redis_async.ConnectionPool.from_url(
                    state_manager.redis_url,
                    max_connections=10,
                    decode_responses=False
                )

            # Use pooled connection for publishing
            async_client = redis_async.Redis(connection_pool=self._publisher_pool)

            # Publish message
            await async_client.publish(channel, message.encode('utf-8'))

        except Exception as e:
            logger.error(f"Redis publish failed: {e}", channel=channel)
            raise

    # Compatibility methods for backward compatibility
    async def send_metrics(self, message: PerformanceMetricsMessage):
        """
        Send metrics to all connected clients (backward compatibility).
        Now publishes to Redis instead of direct sending.
        """
        await self.publish_metrics(message)

    async def send_alert(self, alert: PerformanceAlertMessage):
        """
        Send alert to all connected clients (backward compatibility).
        Now publishes to Redis instead of direct sending.
        """
        await self.publish_alert(alert)

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
                # Calculate real metrics from history
                ops_per_second = self._calculate_operations_per_second()
                avg_response_ms = self._calculate_avg_response_time()
                error_rate_val = self._calculate_error_rate()

                # Get active operations count from Redis
                active_ops_count = len(state_manager.get_active_freecad_operations())

                metrics_msg = PerformanceMetricsMessage(
                    timestamp=datetime.now(timezone.utc),
                    cpu_usage_percent=cpu_percent,
                    memory_usage_mb=memory_mb,
                    gpu_usage_percent=gpu_percent,
                    active_operations=active_ops_count,
                    operations_per_second=ops_per_second,
                    avg_response_time_ms=avg_response_ms,
                    error_rate=error_rate_val
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

    def _calculate_operations_per_second(self) -> float:
        """Calculate operations per second from recent history in Redis."""
        # Get recent operations from Redis state manager
        recent_ops = state_manager.get_recent_operations(seconds=60)

        if not recent_ops:
            return 0.0

        current_time = time.time()
        # Filter operations within last minute
        recent_ops = [op for op in recent_ops
                     if current_time - op.get('timestamp', 0) <= 60]

        if not recent_ops:
            return 0.0

        time_span = current_time - recent_ops[0]['timestamp']
        return len(recent_ops) / max(time_span, 1.0)

    def _calculate_avg_response_time(self) -> float:
        """Calculate average response time in milliseconds from Redis."""
        # Get recent operations from Redis state manager
        recent_ops = state_manager.get_recent_operations(seconds=300)  # Last 5 minutes

        if not recent_ops:
            return 0.0

        # Get last 20 operations
        recent_ops = recent_ops[-20:] if len(recent_ops) > 20 else recent_ops

        durations = [op.get('duration_ms', 0) for op in recent_ops if 'duration_ms' in op]
        if not durations:
            return 0.0

        return sum(durations) / len(durations)

    def _calculate_error_rate(self) -> float:
        """Calculate error rate from recent operations in Redis."""
        # Get recent operations from Redis state manager
        recent_ops = state_manager.get_recent_operations(seconds=600)  # Last 10 minutes

        if not recent_ops:
            return 0.0

        # Get last 50 operations
        recent_ops = recent_ops[-50:] if len(recent_ops) > 50 else recent_ops

        errors = sum(1 for op in recent_ops if not op.get('success', True))
        return (errors / len(recent_ops)) * 100.0


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

        # Store profile data in Redis for multi-worker access
        profile_data = {
            "type": request.profile_type.value,
            "operation": request.operation_name,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id
        }

        # Start profiling based on type
        if request.profile_type == ProfileTypeSchema.GPU:
            # Check GPU availability
            if not gpu_monitor.gpu_devices:
                raise HTTPException(
                    status_code=400,
                    detail="GPU monitoring not available"
                )

        # Store only in Redis-based state manager for multi-worker consistency
        state_manager.add_active_profiler(profile_id, profile_data)

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

        # Remove from active profilers in Redis
        state_manager.remove_active_profiler(request.profile_id)

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
                generated_at=datetime.fromisoformat(report["generated_at"]) if report.get("generated_at") else datetime.now(timezone.utc),
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
            # Real operation profiling - geometry stats will be collected automatically
            pass

        # Store operation in Redis for metrics calculation
        operation_data = {
            'operation_id': operation.operation_id,
            'operation_type': request.operation_type.value,
            'duration_ms': operation.duration_seconds * 1000,
            'success': operation.success,
            'timestamp': time.time(),
            'user_id': current_user.id
        }
        state_manager.add_operation_history(operation_data)

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

    # Filter by date if specified with error handling
    if request.start_date:
        filtered_profiles = []
        for p in profiles:
            if p.get("start_time"):
                try:
                    start_time = datetime.fromisoformat(p.get("start_time")) if isinstance(p.get("start_time"), str) else p.get("start_time")
                    if start_time >= request.start_date:
                        filtered_profiles.append(p)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid start_time format in profile: {e}")
                    continue
        profiles = filtered_profiles

    if request.end_date:
        filtered_profiles = []
        for p in profiles:
            if p.get("start_time"):
                try:
                    start_time = datetime.fromisoformat(p.get("start_time")) if isinstance(p.get("start_time"), str) else p.get("start_time")
                    if start_time <= request.end_date:
                        filtered_profiles.append(p)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid start_time format in profile: {e}")
                    continue
        profiles = filtered_profiles

    # Create export file
    export_dir = Path(tempfile.gettempdir()) / "performance_exports"
    export_dir.mkdir(exist_ok=True)

    if request.format == "json":
        file_path = export_dir / f"{export_id}.json"
        with open(file_path, "w") as f:
            json.dump(profiles, f, indent=2, default=str)
    elif request.format == "csv":
        # CSV export with handling for different profile types
        import csv
        file_path = export_dir / f"{export_id}.csv"

        if profiles:
            with open(file_path, "w", newline="", encoding='utf-8') as f:
                # Collect all unique keys from all profiles
                all_keys = set()
                for profile in profiles:
                    all_keys.update(profile.keys())

                # Sort keys for consistent ordering
                fieldnames = sorted(list(all_keys))

                writer = csv.DictWriter(f, fieldnames=fieldnames, restval='')
                writer.writeheader()

                # Write each profile, handling nested structures
                for profile in profiles:
                    # Flatten nested structures to strings
                    flat_profile = {}
                    for key, value in profile.items():
                        if isinstance(value, (dict, list)):
                            flat_profile[key] = json.dumps(value, default=str)
                        else:
                            flat_profile[key] = value
                    writer.writerow(flat_profile)
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
    # Validate export_id to prevent path traversal
    if not re.fullmatch(r'^export_[a-f0-9]{8}$', export_id):
        raise HTTPException(status_code=400, detail="Invalid export ID format")

    # Find export file
    export_dir = Path(tempfile.gettempdir()) / "performance_exports"

    # Ensure export_dir is secure
    export_dir = export_dir.resolve()

    for ext in [".json", ".csv", ".html"]:
        file_path = (export_dir / f"{export_id}{ext}").resolve()

        # Ensure file_path is within export_dir (prevent path traversal)
        if not str(file_path).startswith(str(export_dir)):
            raise HTTPException(status_code=403, detail="Access denied")

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
                # Send current status from Redis state
                active_profilers = state_manager.get_active_profilers()
                memory_snapshots = state_manager.get_memory_snapshots(10)

                status = {
                    "active_profiles": len(active_profilers),
                    "memory_snapshots": len(memory_snapshots),
                    "gpu_available": len(gpu_monitor.gpu_devices) > 0,
                    "worker_id": os.getpid()  # Include worker ID for debugging
                }
                await websocket.send_json(status)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected")