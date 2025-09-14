"""
Optimization Recommender for Task 7.25

This module analyzes performance profiles and generates actionable optimization recommendations for:
- FreeCAD operations optimization
- Memory usage optimization
- CPU performance improvements
- GPU utilization improvements
- Workflow optimization
- Architecture recommendations
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..middleware.correlation_middleware import get_correlation_id

# Import profilers
from .performance_profiler import PerformanceProfiler, performance_profiler, PerformanceIssue, OptimizationPriority
from .freecad_operation_profiler import FreeCADOperationProfiler, freecad_operation_profiler
from .memory_profiler import AdvancedMemoryProfiler, memory_profiler
from .gpu_monitor import GPUMonitor, gpu_monitor

logger = get_logger(__name__)


class OptimizationType(str, Enum):
    """Optimization types."""
    ALGORITHM = "algorithm"  # Algorithm optimization
    CACHING = "caching"  # Add caching
    PARALLELIZATION = "parallelization"  # Parallelize operations
    BATCHING = "batching"  # Batch operations
    MEMORY = "memory"  # Memory optimization
    IO = "io"  # I/O optimization
    DATABASE = "database"  # Database optimization
    ARCHITECTURE = "architecture"  # Architecture changes


class RecommendationCategory(str, Enum):
    """Recommendation categories."""
    PERFORMANCE = "performance"
    SCALABILITY = "scalability"
    RELIABILITY = "reliability"
    MAINTAINABILITY = "maintainability"
    COST = "cost"


@dataclass
class OptimizationRecommendation:
    """Single optimization recommendation."""
    recommendation_id: str
    title: str
    title_tr: str  # Turkish title
    description: str
    description_tr: str  # Turkish description
    category: RecommendationCategory
    optimization_type: OptimizationType
    priority: OptimizationPriority
    estimated_impact: str  # e.g., "20-30% improvement"
    effort_level: str  # low, medium, high
    implementation_steps: List[str]
    implementation_steps_tr: List[str]  # Turkish steps
    code_examples: Optional[List[str]] = None
    related_issues: List[str] = field(default_factory=list)
    metrics_before: Dict[str, Any] = field(default_factory=dict)
    metrics_expected: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "title_tr": self.title_tr,
            "description": self.description,
            "description_tr": self.description_tr,
            "category": self.category.value,
            "optimization_type": self.optimization_type.value,
            "priority": self.priority.value,
            "estimated_impact": self.estimated_impact,
            "effort_level": self.effort_level,
            "implementation_steps": self.implementation_steps,
            "implementation_steps_tr": self.implementation_steps_tr,
            "code_examples": self.code_examples,
            "related_issues": self.related_issues,
            "metrics_before": self.metrics_before,
            "metrics_expected": self.metrics_expected
        }


@dataclass
class OptimizationPlan:
    """Complete optimization plan with multiple recommendations."""
    plan_id: str
    created_at: datetime
    summary: str
    summary_tr: str
    total_estimated_impact: str
    recommendations: List[OptimizationRecommendation]
    quick_wins: List[OptimizationRecommendation]  # Low effort, high impact
    long_term_improvements: List[OptimizationRecommendation]  # High effort, high impact
    monitoring_plan: Dict[str, Any]
    success_metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at.isoformat(),
            "summary": self.summary,
            "summary_tr": self.summary_tr,
            "total_estimated_impact": self.total_estimated_impact,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "quick_wins": [r.to_dict() for r in self.quick_wins],
            "long_term_improvements": [r.to_dict() for r in self.long_term_improvements],
            "monitoring_plan": self.monitoring_plan,
            "success_metrics": self.success_metrics
        }


class OptimizationRecommender:
    """
    Intelligent optimization recommender that analyzes performance data
    and generates actionable recommendations.
    """

    def __init__(self,
                 base_profiler: Optional[PerformanceProfiler] = None,
                 freecad_profiler: Optional[FreeCADOperationProfiler] = None,
                 memory_prof: Optional[AdvancedMemoryProfiler] = None,
                 gpu_mon: Optional[GPUMonitor] = None):
        """
        Initialize optimization recommender.

        Args:
            base_profiler: Base performance profiler
            freecad_profiler: FreeCAD operation profiler
            memory_prof: Memory profiler
            gpu_mon: GPU monitor
        """
        self.base_profiler = base_profiler or performance_profiler
        self.freecad_profiler = freecad_profiler or freecad_operation_profiler
        self.memory_profiler = memory_prof or memory_profiler
        self.gpu_monitor = gpu_mon or gpu_monitor

        # Recommendation templates
        self.recommendation_templates = self._load_recommendation_templates()

        # Historical recommendations for tracking
        self.generated_plans: List[OptimizationPlan] = []

        logger.info("OptimizationRecommender initialized")

    def generate_optimization_plan(self,
                                  include_categories: Optional[List[RecommendationCategory]] = None,
                                  max_recommendations: int = 10) -> OptimizationPlan:
        """
        Generate comprehensive optimization plan based on current performance data.

        Args:
            include_categories: Categories to include (None for all)
            max_recommendations: Maximum number of recommendations

        Returns:
            Optimization plan with recommendations
        """
        correlation_id = get_correlation_id()

        with create_span("generate_optimization_plan", correlation_id=correlation_id) as span:
            span.set_attribute("max_recommendations", max_recommendations)

            # Collect all performance issues
            all_issues = self._collect_all_issues()

            # Generate recommendations based on issues
            recommendations = self._generate_recommendations_from_issues(all_issues)

            # Add proactive recommendations
            recommendations.extend(self._generate_proactive_recommendations())

            # Filter by categories if specified
            if include_categories:
                recommendations = [
                    r for r in recommendations
                    if r.category in include_categories
                ]

            # Sort by priority and impact
            recommendations.sort(
                key=lambda r: (
                    self._priority_score(r.priority),
                    self._impact_score(r.estimated_impact)
                ),
                reverse=True
            )

            # Limit recommendations
            recommendations = recommendations[:max_recommendations]

            # Categorize recommendations
            quick_wins = [
                r for r in recommendations
                if r.effort_level == "low" and self._impact_score(r.estimated_impact) >= 20
            ]

            long_term = [
                r for r in recommendations
                if r.effort_level == "high" and self._impact_score(r.estimated_impact) >= 30
            ]

            # Create monitoring plan
            monitoring_plan = self._create_monitoring_plan(recommendations)

            # Define success metrics
            success_metrics = self._define_success_metrics(recommendations)

            # Calculate total estimated impact
            total_impact = self._calculate_total_impact(recommendations)

            # Create optimization plan
            plan = OptimizationPlan(
                plan_id=f"opt_plan_{uuid.uuid4().hex[:8]}",
                created_at=datetime.now(timezone.utc),
                summary=f"Generated {len(recommendations)} optimization recommendations based on performance analysis",
                summary_tr=f"Performans analizine dayalı {len(recommendations)} optimizasyon önerisi oluşturuldu",
                total_estimated_impact=total_impact,
                recommendations=recommendations,
                quick_wins=quick_wins,
                long_term_improvements=long_term,
                monitoring_plan=monitoring_plan,
                success_metrics=success_metrics
            )

            # Store plan
            self.generated_plans.append(plan)

            logger.info("Optimization plan generated",
                       plan_id=plan.plan_id,
                       recommendation_count=len(recommendations),
                       quick_wins=len(quick_wins),
                       correlation_id=correlation_id)

            return plan

    def analyze_specific_operation(self,
                                  operation_id: str) -> List[OptimizationRecommendation]:
        """
        Analyze a specific operation and generate recommendations.

        Args:
            operation_id: Operation ID to analyze

        Returns:
            List of recommendations for the operation
        """
        recommendations = []

        # Find operation in FreeCAD profiler
        operation = None
        for op in self.freecad_profiler.completed_operations:
            if op.operation_id == operation_id:
                operation = op
                break

        if not operation:
            logger.warning(f"Operation {operation_id} not found")
            return recommendations

        # Analyze operation performance
        baseline_comparison = self.freecad_profiler.compare_with_baseline(operation)

        # Generate recommendations based on comparison
        if baseline_comparison.get("duration", {}).get("status") == "slower":
            deviation = baseline_comparison["duration"]["deviation_percent"]
            if deviation > 50:
                recommendations.append(self._create_performance_recommendation(
                    title="Optimize Slow Operation",
                    title_tr="Yavaş İşlemi Optimize Et",
                    description=f"Operation {operation_id} is {deviation:.1f}% slower than baseline",
                    description_tr=f"{operation_id} işlemi temel değerden %{deviation:.1f} daha yavaş",
                    optimization_type=OptimizationType.ALGORITHM,
                    priority=OptimizationPriority.HIGH,
                    estimated_impact="30-50%",
                    implementation_steps=[
                        "Profile the operation to identify bottlenecks",
                        "Review algorithm complexity",
                        "Consider caching intermediate results",
                        "Optimize data structures"
                    ],
                    implementation_steps_tr=[
                        "Darboğazları belirlemek için işlemi profille",
                        "Algoritma karmaşıklığını gözden geçir",
                        "Ara sonuçları önbelleklemeyi düşün",
                        "Veri yapılarını optimize et"
                    ]
                ))

        if baseline_comparison.get("memory", {}).get("status") == "higher":
            deviation = baseline_comparison["memory"]["deviation_percent"]
            if deviation > 100:
                recommendations.append(self._create_memory_recommendation(
                    title="Reduce Memory Usage",
                    title_tr="Bellek Kullanımını Azalt",
                    description=f"Operation {operation_id} uses {deviation:.1f}% more memory than baseline",
                    description_tr=f"{operation_id} işlemi temel değerden %{deviation:.1f} daha fazla bellek kullanıyor",
                    priority=OptimizationPriority.MEDIUM,
                    estimated_impact="20-30%",
                    implementation_steps=[
                        "Identify large data structures",
                        "Use generators instead of lists where possible",
                        "Release resources early",
                        "Consider streaming processing"
                    ],
                    implementation_steps_tr=[
                        "Büyük veri yapılarını belirle",
                        "Mümkün olduğunda listeler yerine jeneratörler kullan",
                        "Kaynakları erken serbest bırak",
                        "Akış işlemeyi düşün"
                    ]
                ))

        return recommendations

    def get_architecture_recommendations(self) -> List[OptimizationRecommendation]:
        """
        Generate architecture-level optimization recommendations.

        Returns:
            Architecture recommendations
        """
        recommendations = []

        # Check for repeated operations that could benefit from caching
        operation_counts = defaultdict(int)
        for op in self.freecad_profiler.completed_operations:
            operation_counts[op.operation_type.value] += 1

        for op_type, count in operation_counts.items():
            if count > 100:
                recommendations.append(self._create_caching_recommendation(
                    operation_type=op_type,
                    operation_count=count
                ))

        # Check for sequential operations that could be parallelized
        workflows = self.freecad_profiler.completed_workflows
        for workflow in workflows[-5:]:  # Last 5 workflows
            if len(workflow.operations) > 5:
                sequential_time = sum(op.duration_seconds for op in workflow.operations)
                if sequential_time > 10:  # More than 10 seconds
                    recommendations.append(self._create_parallelization_recommendation(
                        workflow_name=workflow.workflow_name,
                        operation_count=len(workflow.operations),
                        total_time=sequential_time
                    ))

        # Check for memory issues that might benefit from architectural changes
        memory_issues = [
            issue for issue in self.base_profiler.detect_performance_issues()
            if issue.issue_type.value in ["memory_leak", "memory_fragmentation"]
        ]

        if memory_issues:
            recommendations.append(OptimizationRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                title="Implement Memory Pool Architecture",
                title_tr="Bellek Havuzu Mimarisi Uygula",
                description="Multiple memory issues detected. Consider implementing memory pools",
                description_tr="Birden fazla bellek sorunu tespit edildi. Bellek havuzları uygulamayı düşünün",
                category=RecommendationCategory.SCALABILITY,
                optimization_type=OptimizationType.ARCHITECTURE,
                priority=OptimizationPriority.HIGH,
                estimated_impact="40-60%",
                effort_level="high",
                implementation_steps=[
                    "Design memory pool architecture",
                    "Implement object pooling for frequently created objects",
                    "Add memory pool monitoring",
                    "Gradually migrate to pool-based allocation"
                ],
                implementation_steps_tr=[
                    "Bellek havuzu mimarisini tasarla",
                    "Sık oluşturulan nesneler için nesne havuzlaması uygula",
                    "Bellek havuzu izleme ekle",
                    "Kademeli olarak havuz tabanlı tahsise geç"
                ],
                related_issues=[issue.issue_type.value for issue in memory_issues]
            ))

        return recommendations

    def compare_optimization_plans(self,
                                  plan_id1: str,
                                  plan_id2: str) -> Dict[str, Any]:
        """
        Compare two optimization plans.

        Args:
            plan_id1: First plan ID
            plan_id2: Second plan ID

        Returns:
            Comparison results
        """
        plan1 = next((p for p in self.generated_plans if p.plan_id == plan_id1), None)
        plan2 = next((p for p in self.generated_plans if p.plan_id == plan_id2), None)

        if not plan1 or not plan2:
            return {"error": "One or both plans not found"}

        comparison = {
            "plan1": {
                "id": plan1.plan_id,
                "created_at": plan1.created_at.isoformat(),
                "recommendation_count": len(plan1.recommendations),
                "estimated_impact": plan1.total_estimated_impact
            },
            "plan2": {
                "id": plan2.plan_id,
                "created_at": plan2.created_at.isoformat(),
                "recommendation_count": len(plan2.recommendations),
                "estimated_impact": plan2.total_estimated_impact
            },
            "common_recommendations": [],
            "unique_to_plan1": [],
            "unique_to_plan2": []
        }

        # Find common and unique recommendations
        plan1_types = set(r.optimization_type for r in plan1.recommendations)
        plan2_types = set(r.optimization_type for r in plan2.recommendations)

        common_types = plan1_types & plan2_types
        unique1_types = plan1_types - plan2_types
        unique2_types = plan2_types - plan1_types

        comparison["common_recommendations"] = list(common_types)
        comparison["unique_to_plan1"] = list(unique1_types)
        comparison["unique_to_plan2"] = list(unique2_types)

        return comparison

    # Private helper methods

    def _collect_all_issues(self) -> List[PerformanceIssue]:
        """Collect all performance issues from profilers."""
        all_issues = []

        # Get issues from base profiler
        all_issues.extend(self.base_profiler.detect_performance_issues())

        # Get memory leaks
        memory_leaks = self.memory_profiler.detect_memory_leaks()
        for leak in memory_leaks:
            all_issues.append(PerformanceIssue(
                issue_type="memory_leak",
                severity=OptimizationPriority.CRITICAL if leak.severity.value == "critical" else OptimizationPriority.HIGH,
                description=f"Memory leak: {leak.growth_rate_mb_per_hour:.1f}MB/hour growth",
                description_tr=f"Bellek sızıntısı: {leak.growth_rate_mb_per_hour:.1f}MB/saat büyüme",
                location=leak.suspected_source,
                impact=min(leak.growth_rate_mb_per_hour / 100, 1.0),
                recommendation=leak.recommendations[0] if leak.recommendations else "",
                recommendation_tr=leak.recommendations[1] if len(leak.recommendations) > 1 else "",
                metrics={"growth_rate": leak.growth_rate_mb_per_hour}
            ))

        # Get GPU issues if available
        if self.gpu_monitor.gpu_devices:
            gpu_issues = self.gpu_monitor.check_gpu_health()
            for issue in gpu_issues:
                if issue.get("severity") in ["critical", "warning"]:
                    all_issues.append(PerformanceIssue(
                        issue_type="gpu_issue",
                        severity=OptimizationPriority.HIGH if issue["severity"] == "critical" else OptimizationPriority.MEDIUM,
                        description=issue["issue"],
                        description_tr=issue.get("issue_tr", issue["issue"]),
                        location=f"GPU {issue['device_id']}",
                        impact=0.5,
                        recommendation="Check GPU cooling and workload",
                        recommendation_tr="GPU soğutmasını ve iş yükünü kontrol edin",
                        metrics={"device_id": issue["device_id"]}
                    ))

        return all_issues

    def _generate_recommendations_from_issues(self,
                                             issues: List[PerformanceIssue]) -> List[OptimizationRecommendation]:
        """Generate recommendations from performance issues."""
        recommendations = []

        # Group issues by type
        issues_by_type = defaultdict(list)
        for issue in issues:
            issues_by_type[issue.issue_type].append(issue)

        # Generate recommendations for each issue type
        for issue_type, type_issues in issues_by_type.items():
            if issue_type == "slow_function":
                for issue in type_issues[:3]:  # Top 3 slow functions
                    recommendations.append(self._create_performance_recommendation(
                        title=f"Optimize {issue.location}",
                        title_tr=f"{issue.location} Optimize Et",
                        description=issue.description,
                        description_tr=issue.description_tr,
                        optimization_type=OptimizationType.ALGORITHM,
                        priority=issue.severity,
                        estimated_impact=f"{int(issue.impact * 100)}% improvement",
                        implementation_steps=[
                            "Profile the function in detail",
                            "Identify algorithmic bottlenecks",
                            "Consider caching results",
                            "Optimize inner loops"
                        ],
                        implementation_steps_tr=[
                            "Fonksiyonu detaylı profille",
                            "Algoritmik darboğazları belirle",
                            "Sonuçları önbelleklemeyi düşün",
                            "İç döngüleri optimize et"
                        ],
                        metrics_before=issue.metrics
                    ))

            elif issue_type == "memory_leak":
                # Combine all memory leaks into one recommendation
                total_growth = sum(issue.metrics.get("growth_rate", 0) for issue in type_issues)
                recommendations.append(self._create_memory_recommendation(
                    title="Fix Memory Leaks",
                    title_tr="Bellek Sızıntılarını Düzelt",
                    description=f"Total memory growth: {total_growth:.1f}MB/hour",
                    description_tr=f"Toplam bellek büyümesi: {total_growth:.1f}MB/saat",
                    priority=OptimizationPriority.CRITICAL,
                    estimated_impact="50-70%",
                    implementation_steps=[
                        "Use memory profiler to identify leak sources",
                        "Review resource management in identified modules",
                        "Ensure proper cleanup in destructors",
                        "Add automated memory leak tests"
                    ],
                    implementation_steps_tr=[
                        "Sızıntı kaynaklarını belirlemek için bellek profilleyici kullan",
                        "Belirlenen modüllerde kaynak yönetimini gözden geçir",
                        "Yıkıcılarda uygun temizleme sağla",
                        "Otomatik bellek sızıntısı testleri ekle"
                    ],
                    metrics_before={"total_growth_rate": total_growth}
                ))

        return recommendations

    def _generate_proactive_recommendations(self) -> List[OptimizationRecommendation]:
        """Generate proactive optimization recommendations."""
        recommendations = []

        # Check if caching would help
        if len(self.freecad_profiler.completed_operations) > 100:
            recommendations.append(OptimizationRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                title="Implement Result Caching",
                title_tr="Sonuç Önbellekleme Uygula",
                description="High operation count detected. Caching could improve performance",
                description_tr="Yüksek işlem sayısı tespit edildi. Önbellekleme performansı artırabilir",
                category=RecommendationCategory.PERFORMANCE,
                optimization_type=OptimizationType.CACHING,
                priority=OptimizationPriority.MEDIUM,
                estimated_impact="20-40%",
                effort_level="medium",
                implementation_steps=[
                    "Identify cacheable operations",
                    "Implement LRU cache with appropriate size",
                    "Add cache hit/miss metrics",
                    "Monitor cache effectiveness"
                ],
                implementation_steps_tr=[
                    "Önbelleğe alınabilir işlemleri belirle",
                    "Uygun boyutta LRU önbellek uygula",
                    "Önbellek isabet/ıskalama metriklerini ekle",
                    "Önbellek etkinliğini izle"
                ],
                code_examples=[
                    "from functools import lru_cache",
                    "@lru_cache(maxsize=128)",
                    "def expensive_operation(params):",
                    "    # Your code here",
                    "    pass"
                ]
            ))

        # Check if async would help
        io_operations = [
            op for op in self.freecad_profiler.completed_operations
            if "save" in op.operation_type.value.lower() or "load" in op.operation_type.value.lower()
        ]

        if len(io_operations) > 20:
            recommendations.append(OptimizationRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                title="Implement Async I/O",
                title_tr="Asenkron I/O Uygula",
                description="Multiple I/O operations detected. Async processing could improve throughput",
                description_tr="Birden fazla I/O işlemi tespit edildi. Asenkron işleme verimi artırabilir",
                category=RecommendationCategory.PERFORMANCE,
                optimization_type=OptimizationType.IO,
                priority=OptimizationPriority.MEDIUM,
                estimated_impact="30-50%",
                effort_level="medium",
                implementation_steps=[
                    "Convert I/O operations to async",
                    "Use asyncio.gather for parallel I/O",
                    "Implement proper error handling",
                    "Add async performance metrics"
                ],
                implementation_steps_tr=[
                    "I/O işlemlerini asenkrona dönüştür",
                    "Paralel I/O için asyncio.gather kullan",
                    "Uygun hata işleme uygula",
                    "Asenkron performans metrikleri ekle"
                ]
            ))

        return recommendations

    def _create_performance_recommendation(self, **kwargs) -> OptimizationRecommendation:
        """Create a performance optimization recommendation."""
        return OptimizationRecommendation(
            recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
            category=RecommendationCategory.PERFORMANCE,
            effort_level=kwargs.get("effort_level", "medium"),
            code_examples=kwargs.get("code_examples"),
            related_issues=kwargs.get("related_issues", []),
            metrics_before=kwargs.get("metrics_before", {}),
            metrics_expected=kwargs.get("metrics_expected", {}),
            **{k: v for k, v in kwargs.items() if k not in ["effort_level", "code_examples", "related_issues", "metrics_before", "metrics_expected"]}
        )

    def _create_memory_recommendation(self, **kwargs) -> OptimizationRecommendation:
        """Create a memory optimization recommendation."""
        return OptimizationRecommendation(
            recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
            category=RecommendationCategory.SCALABILITY,
            optimization_type=OptimizationType.MEMORY,
            effort_level=kwargs.get("effort_level", "medium"),
            **{k: v for k, v in kwargs.items() if k != "effort_level"}
        )

    def _create_caching_recommendation(self,
                                      operation_type: str,
                                      operation_count: int) -> OptimizationRecommendation:
        """Create a caching recommendation."""
        return OptimizationRecommendation(
            recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
            title=f"Cache {operation_type} Results",
            title_tr=f"{operation_type} Sonuçlarını Önbelleğe Al",
            description=f"Operation {operation_type} executed {operation_count} times. Caching could reduce redundant computations",
            description_tr=f"{operation_type} işlemi {operation_count} kez yürütüldü. Önbellekleme gereksiz hesaplamaları azaltabilir",
            category=RecommendationCategory.PERFORMANCE,
            optimization_type=OptimizationType.CACHING,
            priority=OptimizationPriority.HIGH if operation_count > 500 else OptimizationPriority.MEDIUM,
            estimated_impact=f"{min(operation_count / 10, 60)}% reduction",
            effort_level="low",
            implementation_steps=[
                f"Add caching decorator to {operation_type} operations",
                "Configure cache size based on memory constraints",
                "Implement cache invalidation strategy",
                "Monitor cache hit rates"
            ],
            implementation_steps_tr=[
                f"{operation_type} işlemlerine önbellekleme dekoratörü ekle",
                "Bellek kısıtlamalarına göre önbellek boyutunu yapılandır",
                "Önbellek geçersizleştirme stratejisi uygula",
                "Önbellek isabet oranlarını izle"
            ],
            metrics_before={"operation_count": operation_count}
        )

    def _create_parallelization_recommendation(self,
                                              workflow_name: str,
                                              operation_count: int,
                                              total_time: float) -> OptimizationRecommendation:
        """Create a parallelization recommendation."""
        return OptimizationRecommendation(
            recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
            title=f"Parallelize {workflow_name} Workflow",
            title_tr=f"{workflow_name} İş Akışını Paralel Hale Getir",
            description=f"Workflow has {operation_count} operations taking {total_time:.1f}s sequentially",
            description_tr=f"İş akışında sıralı olarak {total_time:.1f}s süren {operation_count} işlem var",
            category=RecommendationCategory.PERFORMANCE,
            optimization_type=OptimizationType.PARALLELIZATION,
            priority=OptimizationPriority.HIGH,
            estimated_impact=f"{min(operation_count * 10, 70)}% speedup",
            effort_level="high",
            implementation_steps=[
                "Identify independent operations",
                "Implement parallel execution using multiprocessing or asyncio",
                "Handle synchronization and data sharing",
                "Test for race conditions"
            ],
            implementation_steps_tr=[
                "Bağımsız işlemleri belirle",
                "Multiprocessing veya asyncio kullanarak paralel yürütme uygula",
                "Senkronizasyon ve veri paylaşımını yönet",
                "Yarış koşullarını test et"
            ],
            metrics_before={"sequential_time": total_time, "operation_count": operation_count}
        )

    def _load_recommendation_templates(self) -> Dict[str, Any]:
        """Load recommendation templates."""
        # In a real implementation, these could be loaded from a configuration file
        return {
            "caching": {
                "steps": ["Identify cacheable data", "Choose cache strategy", "Implement cache", "Monitor effectiveness"],
                "steps_tr": ["Önbelleğe alınabilir veriyi belirle", "Önbellek stratejisi seç", "Önbellek uygula", "Etkinliği izle"]
            },
            "parallelization": {
                "steps": ["Identify parallelizable tasks", "Choose parallelization method", "Implement parallel execution", "Handle synchronization"],
                "steps_tr": ["Paralel hale getirilebilir görevleri belirle", "Paralelleştirme yöntemi seç", "Paralel yürütme uygula", "Senkronizasyonu yönet"]
            }
        }

    def _priority_score(self, priority: OptimizationPriority) -> int:
        """Convert priority to numeric score."""
        scores = {
            OptimizationPriority.CRITICAL: 4,
            OptimizationPriority.HIGH: 3,
            OptimizationPriority.MEDIUM: 2,
            OptimizationPriority.LOW: 1
        }
        return scores.get(priority, 0)

    def _impact_score(self, impact_str: str) -> int:
        """Extract numeric impact score from string."""
        # Try to extract percentage from string like "20-30%"
        import re
        match = re.search(r'(\d+)', impact_str)
        if match:
            return int(match.group(1))
        return 0

    def _calculate_total_impact(self, recommendations: List[OptimizationRecommendation]) -> str:
        """Calculate total estimated impact of recommendations."""
        total_impact = 0
        for rec in recommendations:
            impact = self._impact_score(rec.estimated_impact)
            # Diminishing returns - each additional optimization has less impact
            total_impact += impact * (0.8 ** recommendations.index(rec))

        return f"{min(int(total_impact), 90)}% potential improvement"

    def _create_monitoring_plan(self, recommendations: List[OptimizationRecommendation]) -> Dict[str, Any]:
        """Create monitoring plan for optimization implementation."""
        return {
            "metrics_to_track": [
                "CPU utilization",
                "Memory usage",
                "Operation duration",
                "Error rates",
                "Throughput"
            ],
            "monitoring_frequency": "Every 5 minutes during implementation",
            "alert_thresholds": {
                "cpu_percent": 80,
                "memory_mb": 2048,
                "error_rate": 0.05
            },
            "review_schedule": "Weekly optimization review meetings"
        }

    def _define_success_metrics(self, recommendations: List[OptimizationRecommendation]) -> Dict[str, Any]:
        """Define success metrics for optimization plan."""
        return {
            "performance_targets": {
                "response_time_reduction": "30%",
                "memory_usage_reduction": "20%",
                "throughput_increase": "40%"
            },
            "quality_targets": {
                "error_rate": "< 1%",
                "availability": "> 99.9%"
            },
            "timeline": "3 months for full implementation",
            "evaluation_criteria": "A/B testing with baseline metrics"
        }


# Global optimization recommender instance
optimization_recommender = OptimizationRecommender()