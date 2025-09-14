"""
Advanced Memory Profiler for Task 7.25

This module provides comprehensive memory profiling capabilities with:
- Memory leak detection using tracemalloc and gc
- Memory fragmentation analysis
- Object reference tracking
- Memory usage patterns and trends
- Automatic leak detection algorithms
- Integration with FreeCAD operations
"""

from __future__ import annotations

import gc
import sys
import tracemalloc
import weakref
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Type
import uuid

import psutil

from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from .profiling_state_manager import state_manager

logger = get_logger(__name__)


class LeakSeverity(str, Enum):
    """Bellek sızıntısı ciddiyet seviyeleri - Memory leak severity levels."""
    CRITICAL = "critical"  # > 100MB/hour growth
    HIGH = "high"  # 50-100MB/hour growth
    MEDIUM = "medium"  # 10-50MB/hour growth
    LOW = "low"  # < 10MB/hour growth
    NONE = "none"  # No leak detected


@dataclass
class MemorySnapshot:
    """Memory snapshot at a point in time."""
    snapshot_id: str
    timestamp: datetime
    process_memory_mb: float
    python_memory_mb: float
    gc_stats: Dict[str, Any]
    top_allocations: List[Dict[str, Any]]
    object_counts: Dict[str, int]
    traceback_stats: Optional[List[Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "process_memory_mb": self.process_memory_mb,
            "python_memory_mb": self.python_memory_mb,
            "gc_stats": self.gc_stats,
            "top_allocations": self.top_allocations,
            "object_counts": self.object_counts
        }


@dataclass
class MemoryLeak:
    """Detected memory leak information."""
    leak_id: str
    detected_at: datetime
    severity: LeakSeverity
    growth_rate_mb_per_hour: float
    suspected_source: Optional[str]
    allocation_traceback: Optional[List[str]]
    object_type: Optional[str]
    instance_count: int
    total_size_mb: float
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "leak_id": self.leak_id,
            "detected_at": self.detected_at.isoformat(),
            "severity": self.severity.value,
            "growth_rate_mb_per_hour": self.growth_rate_mb_per_hour,
            "suspected_source": self.suspected_source,
            "allocation_traceback": self.allocation_traceback,
            "object_type": self.object_type,
            "instance_count": self.instance_count,
            "total_size_mb": self.total_size_mb,
            "recommendations": self.recommendations
        }


@dataclass
class FragmentationAnalysis:
    """Memory fragmentation analysis results."""
    analysis_id: str
    timestamp: datetime
    fragmentation_ratio: float  # 0.0 to 1.0
    virtual_memory_mb: float
    resident_memory_mb: float
    shared_memory_mb: float
    heap_fragmentation: float
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "analysis_id": self.analysis_id,
            "timestamp": self.timestamp.isoformat(),
            "fragmentation_ratio": self.fragmentation_ratio,
            "virtual_memory_mb": self.virtual_memory_mb,
            "resident_memory_mb": self.resident_memory_mb,
            "shared_memory_mb": self.shared_memory_mb,
            "heap_fragmentation": self.heap_fragmentation,
            "recommendations": self.recommendations
        }


class AdvancedMemoryProfiler:
    """
    Advanced memory profiler with leak detection and fragmentation analysis.

    Provides comprehensive memory profiling including:
    - Real-time memory tracking
    - Leak detection algorithms
    - Fragmentation analysis
    - Object lifecycle monitoring
    """

    def __init__(self,
                 enable_continuous_monitoring: bool = False,
                 snapshot_interval_seconds: int = 60,
                 max_snapshots: int = 100,
                 leak_detection_threshold_mb: float = 50.0):
        """
        Initialize memory profiler.

        Args:
            enable_continuous_monitoring: Enable continuous memory monitoring
            snapshot_interval_seconds: Interval between memory snapshots
            max_snapshots: Maximum number of snapshots to store
            leak_detection_threshold_mb: Minimum growth to consider as leak
        """
        self.enable_continuous_monitoring = enable_continuous_monitoring
        self.snapshot_interval_seconds = snapshot_interval_seconds
        self.max_snapshots = max_snapshots
        self.leak_detection_threshold_mb = leak_detection_threshold_mb

        # Storage - now using Redis through state_manager
        # Remove local storage - all state is in Redis
        # self.memory_snapshots: deque = deque(maxlen=max_snapshots)
        # self.detected_leaks: List[MemoryLeak] = []
        # self.fragmentation_analyses: deque = deque(maxlen=50)

        # Object tracking
        self.tracked_objects: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
        self.object_creation_stats: Dict[str, int] = defaultdict(int)
        self.object_deletion_stats: Dict[str, int] = defaultdict(int)

        # Monitoring state
        self._monitoring_thread = None
        self._stop_monitoring = False

        # Initialize tracemalloc if not already started
        if not tracemalloc.is_tracing():
            tracemalloc.start(10)  # Store up to 10 frames

        # Start continuous monitoring if enabled
        if self.enable_continuous_monitoring:
            self.start_continuous_monitoring()

        logger.info("AdvancedMemoryProfiler initialized",
                   continuous_monitoring=enable_continuous_monitoring,
                   snapshot_interval=snapshot_interval_seconds)

    def take_snapshot(self, label: Optional[str] = None) -> MemorySnapshot:
        """
        Take a memory snapshot.

        Args:
            label: Optional label for the snapshot

        Returns:
            Memory snapshot
        """
        correlation_id = get_correlation_id()
        snapshot_id = f"snapshot_{label or 'manual'}_{uuid.uuid4().hex[:8]}"

        with create_span("memory_snapshot", correlation_id=correlation_id) as span:
            span.set_attribute("snapshot.id", snapshot_id)

            # Get process memory info
            process = psutil.Process()
            memory_info = process.memory_info()
            process_memory_mb = memory_info.rss / (1024 * 1024)

            # Get Python memory info
            python_memory_mb = sys.getsizeof(gc.get_objects()) / (1024 * 1024)

            # Get GC statistics
            gc_stats = {
                "collections": {f"gen{i}": gc.get_count()[i] for i in range(len(gc.get_count()))},
                "collected": len(gc.garbage),
                "uncollectable": len([o for o in gc.garbage if not gc.is_tracked(o)]),
                "thresholds": gc.get_threshold()
            }

            # Get top memory allocations
            top_allocations = []
            if tracemalloc.is_tracing():
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics('lineno')[:20]  # Top 20

                for stat in top_stats:
                    top_allocations.append({
                        "file": stat.traceback.format()[0] if stat.traceback else "unknown",
                        "size_mb": stat.size / (1024 * 1024),
                        "count": stat.count
                    })

            # Get object counts by type
            object_counts = defaultdict(int)
            for obj in gc.get_objects():
                object_counts[type(obj).__name__] += 1

            # Sort object counts
            sorted_counts = dict(sorted(object_counts.items(),
                                      key=lambda x: x[1],
                                      reverse=True)[:20])  # Top 20 types

            # Create snapshot
            snapshot = MemorySnapshot(
                snapshot_id=snapshot_id,
                timestamp=datetime.now(timezone.utc),
                process_memory_mb=process_memory_mb,
                python_memory_mb=python_memory_mb,
                gc_stats=gc_stats,
                top_allocations=top_allocations,
                object_counts=sorted_counts
            )

            # Store snapshot in Redis
            state_manager.add_memory_snapshot(snapshot.to_dict())

            logger.debug("Memory snapshot taken",
                        snapshot_id=snapshot_id,
                        process_memory_mb=process_memory_mb,
                        object_count=sum(object_counts.values()))

            # Update metrics
            metrics.memory_snapshot_size_mb.labels(
                snapshot_type="manual" if label else "auto"
            ).set(process_memory_mb)

            return snapshot

    def detect_memory_leaks(self,
                          time_window_minutes: int = 10) -> List[MemoryLeak]:
        """
        Detect memory leaks based on recent snapshots.

        Args:
            time_window_minutes: Time window to analyze

        Returns:
            List of detected memory leaks
        """
        # Get snapshots from Redis
        snapshots_data = state_manager.get_memory_snapshots(limit=100)

        if len(snapshots_data) < 2:
            return []

        leaks = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)

        # Get recent snapshots
        recent_snapshots = []
        for s_data in snapshots_data:
            timestamp_str = s_data.get('timestamp')
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    if timestamp > cutoff_time:
                        # Convert dict back to MemorySnapshot
                        snapshot = MemorySnapshot(
                            snapshot_id=s_data.get('snapshot_id', ''),
                            timestamp=timestamp,
                            process_memory_mb=s_data.get('process_memory_mb', 0),
                            python_memory_mb=s_data.get('python_memory_mb', 0),
                            gc_stats=s_data.get('gc_stats', {}),
                            top_allocations=s_data.get('top_allocations', []),
                            object_counts=s_data.get('object_counts', {})
                        )
                        recent_snapshots.append(snapshot)
                except (ValueError, TypeError):
                    continue

        if len(recent_snapshots) < 2:
            return []

        # Analyze memory growth
        first_snapshot = recent_snapshots[0]
        last_snapshot = recent_snapshots[-1]
        time_diff_hours = (last_snapshot.timestamp - first_snapshot.timestamp).total_seconds() / 3600

        if time_diff_hours == 0:
            return []

        memory_growth_mb = last_snapshot.process_memory_mb - first_snapshot.process_memory_mb
        growth_rate_mb_per_hour = memory_growth_mb / time_diff_hours

        # Check if positive growth exceeds threshold (only detect leaks, not memory reductions)
        if growth_rate_mb_per_hour > self.leak_detection_threshold_mb:
            # Determine severity based on growth rate
            if growth_rate_mb_per_hour > 100:
                severity = LeakSeverity.CRITICAL
            elif growth_rate_mb_per_hour > 50:
                severity = LeakSeverity.HIGH
            elif growth_rate_mb_per_hour > 10:
                severity = LeakSeverity.MEDIUM
            else:
                severity = LeakSeverity.LOW

            # Analyze object growth
            suspected_types = self._analyze_object_growth(first_snapshot, last_snapshot)

            # Get allocation traceback if available
            allocation_traceback = None
            if last_snapshot.top_allocations:
                # Find fastest growing allocation
                allocation_traceback = [last_snapshot.top_allocations[0]["file"]]

            # Generate recommendations
            recommendations = self._generate_leak_recommendations(severity, suspected_types)

            leak = MemoryLeak(
                leak_id=f"leak_{uuid.uuid4().hex[:8]}",
                detected_at=datetime.now(timezone.utc),
                severity=severity,
                growth_rate_mb_per_hour=growth_rate_mb_per_hour,
                suspected_source=suspected_types[0] if suspected_types else None,
                allocation_traceback=allocation_traceback,
                object_type=suspected_types[0] if suspected_types else None,
                instance_count=0,  # Would need more detailed tracking
                total_size_mb=memory_growth_mb,
                recommendations=recommendations
            )

            leaks.append(leak)
            # Store leak in Redis
            state_manager.add_detected_leak(leak.to_dict())

            logger.warning("Memory leak detected",
                         leak_id=leak.leak_id,
                         severity=severity.value,
                         growth_rate_mb_per_hour=growth_rate_mb_per_hour)

        return leaks

    def analyze_fragmentation(self) -> FragmentationAnalysis:
        """
        Analyze memory fragmentation.

        Returns:
            Fragmentation analysis results
        """
        analysis_id = f"frag_{uuid.uuid4().hex[:8]}"

        # Get memory info
        process = psutil.Process()
        memory_info = process.memory_info_ex() if hasattr(process, 'memory_info_ex') else process.memory_info()

        # Calculate fragmentation metrics
        virtual_memory_mb = memory_info.vms / (1024 * 1024) if hasattr(memory_info, 'vms') else 0
        resident_memory_mb = memory_info.rss / (1024 * 1024)
        shared_memory_mb = memory_info.shared / (1024 * 1024) if hasattr(memory_info, 'shared') else 0

        # Simplified fragmentation ratio
        fragmentation_ratio = 0.0
        if virtual_memory_mb > 0:
            fragmentation_ratio = 1.0 - (resident_memory_mb / virtual_memory_mb)

        # Heap fragmentation (simplified - would need platform-specific code for accurate measurement)
        heap_fragmentation = self._estimate_heap_fragmentation()

        # Generate recommendations
        recommendations = []
        if fragmentation_ratio > 0.3:
            recommendations.append("High memory fragmentation detected. Consider restarting the application.")
            recommendations.append("Yüksek bellek parçalanması tespit edildi. Uygulamayı yeniden başlatmayı düşünün.")

        if heap_fragmentation > 0.4:
            recommendations.append("High heap fragmentation. Consider using memory pools.")
            recommendations.append("Yüksek heap parçalanması. Bellek havuzları kullanmayı düşünün.")

        analysis = FragmentationAnalysis(
            analysis_id=analysis_id,
            timestamp=datetime.now(timezone.utc),
            fragmentation_ratio=fragmentation_ratio,
            virtual_memory_mb=virtual_memory_mb,
            resident_memory_mb=resident_memory_mb,
            shared_memory_mb=shared_memory_mb,
            heap_fragmentation=heap_fragmentation,
            recommendations=recommendations
        )

        # Store analysis in Redis
        state_manager.add_fragmentation_analysis(analysis.to_dict())

        logger.info("Fragmentation analysis completed",
                   analysis_id=analysis_id,
                   fragmentation_ratio=fragmentation_ratio)

        return analysis

    @contextmanager
    def track_allocations(self, operation_name: str = "unknown"):
        """
        Context manager to track memory allocations during an operation.

        Usage:
            with profiler.track_allocations("my_operation"):
                # Your code here
                pass
        """
        if not tracemalloc.is_tracing():
            tracemalloc.start(10)

        snapshot_before = tracemalloc.take_snapshot()
        initial_objects = set(id(obj) for obj in gc.get_objects())

        try:
            yield
        finally:
            snapshot_after = tracemalloc.take_snapshot()
            final_objects = set(id(obj) for obj in gc.get_objects())

            # Find new objects
            new_objects = final_objects - initial_objects

            # Analyze allocation differences
            top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')

            # Log significant allocations
            significant_allocations = [
                stat for stat in top_stats
                if stat.size_diff > 1024 * 1024  # > 1MB
            ]

            if significant_allocations:
                logger.info(f"Significant allocations in {operation_name}",
                          allocation_count=len(significant_allocations),
                          new_objects=len(new_objects))

                for stat in significant_allocations[:5]:  # Top 5
                    logger.debug(f"Allocation: {stat.traceback.format()[0] if stat.traceback else 'unknown'} "
                               f"- {stat.size_diff / (1024 * 1024):.2f}MB")

    def track_object(self, obj: Any, name: str):
        """
        Track a specific object for memory monitoring.

        Args:
            obj: Object to track
            name: Name for identification
        """
        try:
            self.tracked_objects[name] = obj
            self.object_creation_stats[type(obj).__name__] += 1
            logger.debug(f"Tracking object: {name} ({type(obj).__name__})")
        except TypeError:
            # Object doesn't support weak references
            logger.debug(f"Cannot track object (no weak ref support): {name}")

    def get_tracked_objects_report(self) -> Dict[str, Any]:
        """
        Get report on tracked objects.

        Returns:
            Report on tracked objects
        """
        alive_objects = {}
        for name, obj_ref in list(self.tracked_objects.items()):
            if obj_ref is not None:
                alive_objects[name] = {
                    "type": type(obj_ref).__name__,
                    "size_bytes": sys.getsizeof(obj_ref),
                    "id": id(obj_ref)
                }

        return {
            "tracked_count": len(self.tracked_objects),
            "alive_count": len(alive_objects),
            "alive_objects": alive_objects,
            "creation_stats": dict(self.object_creation_stats),
            "deletion_stats": dict(self.object_deletion_stats)
        }

    def find_circular_references(self) -> List[Dict[str, Any]]:
        """
        Find circular references that may cause memory leaks.

        Returns:
            List of circular reference information
        """
        gc.collect()
        circular_refs = []

        for obj in gc.garbage:
            referrers = gc.get_referrers(obj)
            if len(referrers) > 1:
                circular_refs.append({
                    "object_type": type(obj).__name__,
                    "object_id": id(obj),
                    "referrer_count": len(referrers),
                    "referrer_types": [type(r).__name__ for r in referrers[:5]]  # First 5
                })

        if circular_refs:
            logger.warning(f"Found {len(circular_refs)} circular references")

        return circular_refs

    def optimize_memory(self) -> Dict[str, Any]:
        """
        Perform memory optimization operations.

        Returns:
            Optimization results
        """
        initial_memory = psutil.Process().memory_info().rss / (1024 * 1024)

        # Force garbage collection
        gc.collect(2)  # Full collection

        # Clear caches if possible
        # This would be application-specific

        # Compact memory if possible (platform-specific)
        # On some platforms, we could use ctypes to call malloc_trim

        final_memory = psutil.Process().memory_info().rss / (1024 * 1024)
        freed_mb = initial_memory - final_memory

        results = {
            "initial_memory_mb": initial_memory,
            "final_memory_mb": final_memory,
            "freed_mb": freed_mb,
            "gc_collected": len(gc.garbage),
            "optimization_successful": freed_mb > 0
        }

        logger.info("Memory optimization completed",
                   freed_mb=freed_mb,
                   final_memory_mb=final_memory)

        return results

    def generate_memory_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive memory report.

        Returns:
            Memory analysis report
        """
        # Current memory state
        process = psutil.Process()
        current_memory = process.memory_info().rss / (1024 * 1024)

        # Memory trend
        memory_trend = self._calculate_memory_trend()

        # Recent leaks
        recent_leaks = self.detect_memory_leaks(time_window_minutes=30)

        # Fragmentation
        fragmentation = self.analyze_fragmentation()

        # Top memory consumers
        top_consumers = self._get_top_memory_consumers()

        report = {
            "report_id": f"mem_report_{uuid.uuid4().hex[:8]}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_memory_mb": current_memory,
            "memory_trend": memory_trend,
            "detected_leaks": [leak.to_dict() for leak in recent_leaks],
            "fragmentation": fragmentation.to_dict(),
            "top_consumers": top_consumers,
            "gc_stats": {
                "collections": dict(zip(["gen0", "gen1", "gen2"], gc.get_count())),
                "thresholds": gc.get_threshold(),
                "garbage_count": len(gc.garbage)
            },
            "recommendations": self._generate_memory_recommendations(
                current_memory, memory_trend, recent_leaks, fragmentation
            )
        }

        logger.info("Memory report generated",
                   report_id=report["report_id"],
                   current_memory_mb=current_memory,
                   leak_count=len(recent_leaks))

        return report

    # Private helper methods

    def _analyze_object_growth(self,
                              first_snapshot: MemorySnapshot,
                              last_snapshot: MemorySnapshot) -> List[str]:
        """Analyze which object types are growing."""
        growing_types = []

        for obj_type in last_snapshot.object_counts:
            if obj_type in first_snapshot.object_counts:
                growth = last_snapshot.object_counts[obj_type] - first_snapshot.object_counts[obj_type]
                if growth > 100:  # Significant growth
                    growing_types.append(obj_type)

        # Sort by growth
        growing_types.sort(key=lambda t: (
            last_snapshot.object_counts.get(t, 0) - first_snapshot.object_counts.get(t, 0)
        ), reverse=True)

        return growing_types[:5]  # Top 5

    def _generate_leak_recommendations(self,
                                      severity: LeakSeverity,
                                      suspected_types: List[str]) -> List[str]:
        """Generate recommendations for memory leak."""
        recommendations = []

        if severity in [LeakSeverity.CRITICAL, LeakSeverity.HIGH]:
            recommendations.append("Immediate action required to prevent out-of-memory errors")
            recommendations.append("Bellek dışı hatalarını önlemek için acil eylem gerekli")

        if suspected_types:
            recommendations.append(f"Check for unreleased {suspected_types[0]} objects")
            recommendations.append(f"Serbest bırakılmamış {suspected_types[0]} nesnelerini kontrol edin")

        recommendations.append("Review recent code changes for resource leaks")
        recommendations.append("Kaynak sızıntıları için son kod değişikliklerini gözden geçirin")

        return recommendations

    def _estimate_heap_fragmentation(self) -> float:
        """Estimate heap fragmentation."""
        import psutil
        import sys

        # Get process memory info
        process = psutil.Process()
        memory_info = process.memory_info()

        # Calculate fragmentation based on RSS vs heap size
        # This is a more accurate estimation
        gc.collect()

        # Get Python heap size (approximate)
        python_objects_size = sum(sys.getsizeof(obj) for obj in gc.get_objects()[:1000])  # Sample

        # Get resident set size
        rss = memory_info.rss

        # Calculate fragmentation ratio
        if rss > 0 and python_objects_size > 0:
            # Higher ratio means more fragmentation
            fragmentation = 1.0 - (python_objects_size / rss)
            fragmentation = max(0.0, min(1.0, fragmentation))  # Clamp to [0, 1]
        else:
            # Fallback to GC-based estimation
            garbage_ratio = len(gc.garbage) / max(sum(gc.get_count()), 1)
            fragmentation = min(garbage_ratio, 1.0)

        return fragmentation

    def _calculate_memory_trend(self) -> Dict[str, Any]:
        """Calculate memory usage trend."""
        # Get snapshots from Redis
        snapshots_data = state_manager.get_memory_snapshots(limit=10)

        if len(snapshots_data) < 2:
            return {"status": "insufficient_data"}

        recent_snapshots = []
        for s_data in snapshots_data:
            timestamp_str = s_data.get('timestamp')
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    # Create minimal snapshot for trend calculation
                    snapshot = MemorySnapshot(
                        snapshot_id=s_data.get('snapshot_id', ''),
                        timestamp=timestamp,
                        process_memory_mb=s_data.get('process_memory_mb', 0),
                        python_memory_mb=s_data.get('python_memory_mb', 0),
                        gc_stats=s_data.get('gc_stats', {}),
                        top_allocations=s_data.get('top_allocations', []),
                        object_counts=s_data.get('object_counts', {})
                    )
                    recent_snapshots.append(snapshot)
                except (ValueError, TypeError):
                    continue

        if len(recent_snapshots) < 2:
            return {"status": "insufficient_data"}

        # Calculate trend
        memory_values = [s.process_memory_mb for s in recent_snapshots]

        # Simple linear regression
        n = len(memory_values)
        x_mean = n / 2
        y_mean = sum(memory_values) / n

        numerator = sum((i - x_mean) * (memory_values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0

        return {
            "status": "calculated",
            "slope_mb_per_snapshot": slope,
            "trend": "increasing" if slope > 0.5 else "decreasing" if slope < -0.5 else "stable",
            "sample_count": n
        }

    def _get_top_memory_consumers(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """Get top memory consuming objects/types."""
        # Get latest snapshot from Redis
        snapshots_data = state_manager.get_memory_snapshots(limit=1)

        if not snapshots_data:
            return []

        latest_snapshot_data = snapshots_data[0]
        object_counts = latest_snapshot_data.get('object_counts', {})

        consumers = []
        for obj_type, count in list(object_counts.items())[:top_n]:
            consumers.append({
                "type": obj_type,
                "count": count,
                "estimated_mb": count * 0.001  # Very rough estimate
            })

        return consumers

    def _generate_memory_recommendations(self,
                                        current_memory: float,
                                        trend: Dict[str, Any],
                                        leaks: List[MemoryLeak],
                                        fragmentation: FragmentationAnalysis) -> List[str]:
        """Generate memory optimization recommendations."""
        recommendations = []

        # High memory usage
        if current_memory > 1024:  # > 1GB
            recommendations.append("Memory usage is high. Consider optimizing data structures.")
            recommendations.append("Bellek kullanımı yüksek. Veri yapılarını optimize etmeyi düşünün.")

        # Memory trend
        if trend.get("trend") == "increasing":
            recommendations.append("Memory usage is increasing. Monitor for potential leaks.")
            recommendations.append("Bellek kullanımı artıyor. Potansiyel sızıntılar için izleyin.")

        # Leaks
        if leaks:
            recommendations.append(f"Found {len(leaks)} potential memory leak(s). Investigate immediately.")
            recommendations.append(f"{len(leaks)} potansiyel bellek sızıntısı bulundu. Hemen araştırın.")

        # Fragmentation
        if fragmentation.fragmentation_ratio > 0.3:
            recommendations.append("High fragmentation detected. Consider memory compaction.")
            recommendations.append("Yüksek parçalanma tespit edildi. Bellek sıkıştırmayı düşünün.")

        return recommendations


# Global memory profiler instance
memory_profiler = AdvancedMemoryProfiler(
    enable_continuous_monitoring=False,  # Disabled by default for performance
    snapshot_interval_seconds=60,
    max_snapshots=100,
    leak_detection_threshold_mb=50.0  # Consistent with constructor default
)