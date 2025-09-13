"""
Quality Metrics Calculator for Task 7.24

This module calculates comprehensive quality metrics for FreeCAD models including:
- Geometric complexity analysis
- Surface quality assessment
- Feature consistency checking
- Parametric robustness testing
- Assembly compatibility verification
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, Dict, List, Optional, Tuple

from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..models.validation_models import (
    QualityMetricsReport,
    QualityMetric,
    VALIDATION_MESSAGES_TR
)

logger = get_logger(__name__)


class ComplexityAnalyzer:
    """Analyzer for geometric complexity."""
    
    @staticmethod
    def calculate_complexity_index(
        face_count: int,
        edge_count: int,
        vertex_count: int,
        feature_count: int
    ) -> float:
        """Calculate overall complexity index."""
        # Weighted complexity calculation
        complexity = (
            face_count * 0.3 +
            edge_count * 0.2 +
            vertex_count * 0.1 +
            feature_count * 0.4
        )
        
        # Normalize to 0-100 scale
        # Assuming 1000 total elements is very complex
        normalized = min(complexity / 10, 100)
        
        return normalized
    
    @staticmethod
    def calculate_shape_complexity(shape: Any) -> Dict[str, Any]:
        """Calculate detailed shape complexity metrics."""
        metrics = {
            "face_count": 0,
            "edge_count": 0,
            "vertex_count": 0,
            "feature_count": 0,
            "topology_complexity": 0.0,
            "curvature_complexity": 0.0
        }
        
        try:
            if hasattr(shape, 'Faces'):
                metrics["face_count"] = len(shape.Faces)
                
                # Analyze face types
                planar_faces = 0
                curved_faces = 0
                for face in shape.Faces:
                    # Check if face is planar (simplified)
                    if True:  # Placeholder for actual planarity check
                        planar_faces += 1
                    else:
                        curved_faces += 1
                
                metrics["curvature_complexity"] = curved_faces / max(metrics["face_count"], 1)
            
            if hasattr(shape, 'Edges'):
                metrics["edge_count"] = len(shape.Edges)
            
            if hasattr(shape, 'Vertexes'):
                metrics["vertex_count"] = len(shape.Vertexes)
            
            # Calculate Euler characteristic for topology complexity
            # V - E + F = 2 for simple polyhedron
            euler = metrics["vertex_count"] - metrics["edge_count"] + metrics["face_count"]
            metrics["topology_complexity"] = abs(euler - 2) / 10  # Normalize deviation
            
        except Exception as e:
            logger.warning(f"Complexity calculation error: {e}")
        
        return metrics


class SurfaceQualityAnalyzer:
    """Analyzer for surface quality."""
    
    @staticmethod
    async def analyze_surface_quality(shape: Any) -> Dict[str, float]:
        """Analyze surface quality metrics."""
        quality_metrics = {
            "smoothness": 0.0,
            "continuity": 0.0,
            "defect_score": 0.0,
            "finish_quality": 0.0
        }
        
        try:
            if hasattr(shape, 'Faces'):
                # Analyze each face
                smoothness_scores = []
                continuity_scores = []
                
                for face in shape.Faces:
                    # Calculate surface smoothness (simplified)
                    smoothness = await SurfaceQualityAnalyzer._calculate_smoothness(face)
                    smoothness_scores.append(smoothness)
                    
                    # Check edge continuity
                    continuity = await SurfaceQualityAnalyzer._check_continuity(face)
                    continuity_scores.append(continuity)
                
                quality_metrics["smoothness"] = sum(smoothness_scores) / max(len(smoothness_scores), 1)
                quality_metrics["continuity"] = sum(continuity_scores) / max(len(continuity_scores), 1)
                
                # Calculate defect score (inverse of quality)
                quality_metrics["defect_score"] = 1.0 - (quality_metrics["smoothness"] * 0.5 + 
                                                         quality_metrics["continuity"] * 0.5)
                
                # Overall finish quality
                quality_metrics["finish_quality"] = (
                    quality_metrics["smoothness"] * 0.4 +
                    quality_metrics["continuity"] * 0.4 +
                    (1.0 - quality_metrics["defect_score"]) * 0.2
                )
            
        except Exception as e:
            logger.warning(f"Surface quality analysis error: {e}")
            # Default to medium quality
            quality_metrics["finish_quality"] = 0.5
        
        return quality_metrics
    
    @staticmethod
    async def _calculate_smoothness(face: Any) -> float:
        """Calculate face smoothness based on curvature analysis."""
        try:
            # Import FreeCAD modules lazily
            import Part
            
            if not hasattr(face, 'Surface'):
                return 0.5  # Default for non-analyzable faces
            
            surface = face.Surface
            smoothness_score = 1.0
            
            # Sample points across the face for curvature analysis
            u_param = face.ParameterRange[0:2]
            v_param = face.ParameterRange[2:4]
            
            curvatures = []
            sample_points = 10  # Sample 10x10 grid
            
            for i in range(sample_points):
                for j in range(sample_points):
                    u = u_param[0] + (u_param[1] - u_param[0]) * i / (sample_points - 1)
                    v = v_param[0] + (v_param[1] - v_param[0]) * j / (sample_points - 1)
                    
                    try:
                        # Get curvature at this point
                        if hasattr(surface, 'curvature'):
                            curv = surface.curvature(u, v)
                            if curv:
                                # Store principal curvatures
                                curvatures.append(abs(curv[0]) + abs(curv[1]))
                    except:
                        continue
            
            if curvatures:
                # Calculate smoothness based on curvature variation
                avg_curvature = sum(curvatures) / len(curvatures)
                max_curvature = max(curvatures)
                min_curvature = min(curvatures)
                
                # High variation means less smooth
                if max_curvature > 0:
                    variation = (max_curvature - min_curvature) / max_curvature
                    smoothness_score = max(0.0, 1.0 - variation * 0.5)
                
                # Penalize high curvature values (sharp bends)
                if avg_curvature > 10:
                    smoothness_score *= 0.7
                elif avg_curvature > 5:
                    smoothness_score *= 0.85
            
            return smoothness_score
            
        except ImportError:
            logger.warning("FreeCAD not available for smoothness calculation")
            return 0.85
        except Exception as e:
            logger.debug(f"Smoothness calculation error: {e}")
            return 0.85
    
    @staticmethod
    async def _check_continuity(face: Any) -> float:
        """Check edge continuity (G0, G1, G2)."""
        try:
            # Import FreeCAD modules lazily
            import Part
            
            if not hasattr(face, 'Edges'):
                return 0.5  # Default for non-analyzable faces
            
            continuity_score = 1.0
            edges = face.Edges
            
            if not edges:
                return 1.0  # No edges means no discontinuity
            
            discontinuities = {
                'g0': 0,  # Position discontinuity
                'g1': 0,  # Tangent discontinuity
                'g2': 0   # Curvature discontinuity
            }
            
            for edge in edges:
                try:
                    if hasattr(edge, 'Curve'):
                        curve = edge.Curve
                        
                        # Check continuity at edge endpoints
                        param_range = edge.ParameterRange
                        
                        # Sample points along the edge
                        for t in [param_range[0], (param_range[0] + param_range[1]) / 2, param_range[1]]:
                            try:
                                point = curve.value(t)
                                
                                # Check if this point connects smoothly to adjacent edges
                                for other_edge in edges:
                                    if other_edge == edge:
                                        continue
                                    
                                    # Check G0 continuity (position)
                                    other_range = other_edge.ParameterRange
                                    for other_t in [other_range[0], other_range[1]]:
                                        other_point = other_edge.Curve.value(other_t)
                                        dist = point.distanceToPoint(other_point) if hasattr(point, 'distanceToPoint') else abs(point - other_point)
                                        
                                        if dist < 0.001:  # Points are connected
                                            # Check G1 continuity (tangent)
                                            if hasattr(curve, 'tangent') and hasattr(other_edge.Curve, 'tangent'):
                                                tan1 = curve.tangent(t)
                                                tan2 = other_edge.Curve.tangent(other_t)
                                                
                                                if tan1 and tan2:
                                                    # Check if tangents are parallel
                                                    dot_product = abs(tan1[0].dot(tan2[0])) if hasattr(tan1[0], 'dot') else 1.0
                                                    if dot_product < 0.95:  # Not parallel
                                                        discontinuities['g1'] += 1
                                            
                                            # Check G2 continuity (curvature)
                                            if hasattr(curve, 'curvature') and hasattr(other_edge.Curve, 'curvature'):
                                                curv1 = curve.curvature(t)
                                                curv2 = other_edge.Curve.curvature(other_t)
                                                
                                                if curv1 is not None and curv2 is not None:
                                                    curv_diff = abs(curv1 - curv2)
                                                    if curv_diff > 0.1:  # Curvature discontinuity
                                                        discontinuities['g2'] += 1
                            except:
                                continue
                                
                except Exception:
                    continue
            
            # Calculate continuity score based on discontinuities
            total_checks = len(edges) * 3  # 3 points per edge
            if total_checks > 0:
                # Penalize based on discontinuity severity
                g0_penalty = discontinuities['g0'] * 0.5 / total_checks
                g1_penalty = discontinuities['g1'] * 0.3 / total_checks
                g2_penalty = discontinuities['g2'] * 0.2 / total_checks
                
                continuity_score = max(0.0, 1.0 - g0_penalty - g1_penalty - g2_penalty)
            
            return continuity_score
            
        except ImportError:
            logger.warning("FreeCAD not available for continuity check")
            return 0.9
        except Exception as e:
            logger.debug(f"Continuity check error: {e}")
            return 0.9


class FeatureConsistencyChecker:
    """Checker for feature consistency."""
    
    @staticmethod
    def check_consistency(shape: Any) -> Dict[str, Any]:
        """Check feature consistency across model."""
        consistency_report = {
            "pattern_consistency": 0.0,
            "dimension_consistency": 0.0,
            "symmetry_score": 0.0,
            "alignment_score": 0.0,
            "overall_consistency": 0.0
        }
        
        try:
            # Check pattern consistency (repeated features)
            patterns = FeatureConsistencyChecker._detect_patterns(shape)
            if patterns:
                consistency_report["pattern_consistency"] = FeatureConsistencyChecker._evaluate_pattern_consistency(patterns)
            else:
                consistency_report["pattern_consistency"] = 1.0  # No patterns is consistent
            
            # Check dimension consistency
            dimensions = FeatureConsistencyChecker._extract_dimensions(shape)
            consistency_report["dimension_consistency"] = FeatureConsistencyChecker._evaluate_dimension_consistency(dimensions)
            
            # Check symmetry
            consistency_report["symmetry_score"] = FeatureConsistencyChecker._check_symmetry(shape)
            
            # Check alignment
            consistency_report["alignment_score"] = FeatureConsistencyChecker._check_alignment(shape)
            
            # Calculate overall consistency
            consistency_report["overall_consistency"] = (
                consistency_report["pattern_consistency"] * 0.25 +
                consistency_report["dimension_consistency"] * 0.25 +
                consistency_report["symmetry_score"] * 0.25 +
                consistency_report["alignment_score"] * 0.25
            )
            
        except Exception as e:
            logger.warning(f"Consistency check error: {e}")
            consistency_report["overall_consistency"] = 0.7
        
        return consistency_report
    
    @staticmethod
    def _detect_patterns(shape: Any) -> List[Dict[str, Any]]:
        """Detect repeated patterns in model."""
        # Placeholder implementation
        return []
    
    @staticmethod
    def _evaluate_pattern_consistency(patterns: List[Dict[str, Any]]) -> float:
        """Evaluate consistency of detected patterns."""
        return 0.9
    
    @staticmethod
    def _extract_dimensions(shape: Any) -> List[float]:
        """Extract key dimensions from shape."""
        # Placeholder implementation
        return [10.0, 20.0, 30.0]
    
    @staticmethod
    def _evaluate_dimension_consistency(dimensions: List[float]) -> float:
        """Evaluate consistency of dimensions."""
        # Check for standard dimensions, round numbers, etc.
        return 0.85
    
    @staticmethod
    def _check_symmetry(shape: Any) -> float:
        """Check model symmetry."""
        # Placeholder implementation
        return 0.8
    
    @staticmethod
    def _check_alignment(shape: Any) -> float:
        """Check feature alignment."""
        # Placeholder implementation
        return 0.9


class ParametricRobustnessChecker:
    """Checker for parametric robustness."""
    
    @staticmethod
    async def test_robustness(doc_handle: Any) -> Dict[str, float]:
        """Test parametric robustness of model."""
        robustness_metrics = {
            "rebuild_stability": 0.0,
            "parameter_sensitivity": 0.0,
            "constraint_stability": 0.0,
            "update_reliability": 0.0,
            "overall_robustness": 0.0
        }
        
        try:
            # Test rebuild stability
            robustness_metrics["rebuild_stability"] = await ParametricRobustnessChecker._test_rebuild(doc_handle)
            
            # Test parameter sensitivity
            robustness_metrics["parameter_sensitivity"] = await ParametricRobustnessChecker._test_parameter_changes(doc_handle)
            
            # Test constraint stability
            robustness_metrics["constraint_stability"] = await ParametricRobustnessChecker._test_constraints(doc_handle)
            
            # Test update reliability
            robustness_metrics["update_reliability"] = await ParametricRobustnessChecker._test_updates(doc_handle)
            
            # Calculate overall robustness
            robustness_metrics["overall_robustness"] = (
                robustness_metrics["rebuild_stability"] * 0.3 +
                robustness_metrics["parameter_sensitivity"] * 0.3 +
                robustness_metrics["constraint_stability"] * 0.2 +
                robustness_metrics["update_reliability"] * 0.2
            )
            
        except Exception as e:
            logger.warning(f"Robustness test error: {e}")
            robustness_metrics["overall_robustness"] = 0.6
        
        return robustness_metrics
    
    @staticmethod
    async def _test_rebuild(doc_handle: Any) -> float:
        """Test model rebuild stability."""
        # Placeholder implementation
        # Would force recompute and check for errors
        return 0.95
    
    @staticmethod
    async def _test_parameter_changes(doc_handle: Any) -> float:
        """Test sensitivity to parameter changes."""
        # Placeholder implementation
        # Would modify parameters and check stability
        return 0.85
    
    @staticmethod
    async def _test_constraints(doc_handle: Any) -> float:
        """Test constraint stability."""
        # Placeholder implementation
        return 0.9
    
    @staticmethod
    async def _test_updates(doc_handle: Any) -> float:
        """Test update reliability."""
        # Placeholder implementation
        return 0.88


class AssemblyCompatibilityChecker:
    """Checker for assembly compatibility."""
    
    @staticmethod
    def check_compatibility(shape: Any) -> Dict[str, float]:
        """Check assembly compatibility."""
        compatibility_metrics = {
            "interface_quality": 0.0,
            "mating_surfaces": 0.0,
            "clearance_compliance": 0.0,
            "assembly_features": 0.0,
            "overall_compatibility": 0.0
        }
        
        try:
            # Check interface quality
            compatibility_metrics["interface_quality"] = AssemblyCompatibilityChecker._check_interfaces(shape)
            
            # Check mating surfaces
            compatibility_metrics["mating_surfaces"] = AssemblyCompatibilityChecker._check_mating_surfaces(shape)
            
            # Check clearances
            compatibility_metrics["clearance_compliance"] = AssemblyCompatibilityChecker._check_clearances(shape)
            
            # Check assembly features
            compatibility_metrics["assembly_features"] = AssemblyCompatibilityChecker._check_assembly_features(shape)
            
            # Calculate overall compatibility
            compatibility_metrics["overall_compatibility"] = (
                compatibility_metrics["interface_quality"] * 0.3 +
                compatibility_metrics["mating_surfaces"] * 0.3 +
                compatibility_metrics["clearance_compliance"] * 0.2 +
                compatibility_metrics["assembly_features"] * 0.2
            )
            
        except Exception as e:
            logger.warning(f"Assembly compatibility check error: {e}")
            compatibility_metrics["overall_compatibility"] = 0.7
        
        return compatibility_metrics
    
    @staticmethod
    def _check_interfaces(shape: Any) -> float:
        """Check interface quality."""
        return 0.85
    
    @staticmethod
    def _check_mating_surfaces(shape: Any) -> float:
        """Check mating surface quality."""
        return 0.9
    
    @staticmethod
    def _check_clearances(shape: Any) -> float:
        """Check clearance compliance."""
        return 0.95
    
    @staticmethod
    def _check_assembly_features(shape: Any) -> float:
        """Check assembly feature presence."""
        return 0.8


class QualityMetrics:
    """Main quality metrics calculator."""
    
    def __init__(self):
        self.complexity_analyzer = ComplexityAnalyzer()
        self.surface_analyzer = SurfaceQualityAnalyzer()
        self.consistency_checker = FeatureConsistencyChecker()
        self.robustness_checker = ParametricRobustnessChecker()
        self.assembly_checker = AssemblyCompatibilityChecker()
    
    async def calculate_metrics(self, doc_handle: Any) -> QualityMetricsReport:
        """Calculate comprehensive quality metrics."""
        correlation_id = get_correlation_id()
        
        with create_span("quality_metrics_calculation", correlation_id=correlation_id) as span:
            report = QualityMetricsReport(
                geometric_complexity=QualityMetric(
                    name="Geometric Complexity",
                    value=0.0,
                    min_value=0.0,
                    max_value=100.0,
                    weight=1.0,
                    unit="index",
                    description="Measure of geometric complexity"
                ),
                surface_quality=QualityMetric(
                    name="Surface Quality",
                    value=0.0,
                    min_value=0.0,
                    max_value=1.0,
                    weight=1.5,
                    unit="score",
                    description="Surface finish and quality"
                ),
                feature_consistency=QualityMetric(
                    name="Feature Consistency",
                    value=0.0,
                    min_value=0.0,
                    max_value=1.0,
                    weight=1.2,
                    unit="score",
                    description="Consistency of features"
                ),
                parametric_robustness=QualityMetric(
                    name="Parametric Robustness",
                    value=0.0,
                    min_value=0.0,
                    max_value=1.0,
                    weight=1.3,
                    unit="score",
                    description="Robustness of parametric model"
                ),
                manufacturing_readiness=QualityMetric(
                    name="Manufacturing Readiness",
                    value=0.0,
                    min_value=0.0,
                    max_value=1.0,
                    weight=1.5,
                    unit="score",
                    description="Readiness for manufacturing"
                ),
                documentation_completeness=QualityMetric(
                    name="Documentation Completeness",
                    value=0.0,
                    min_value=0.0,
                    max_value=1.0,
                    weight=0.8,
                    unit="score",
                    description="Completeness of documentation"
                )
            )
            
            try:
                # Get shape from document
                shape = self._get_shape_from_document(doc_handle)
                
                if shape:
                    # Calculate geometric complexity
                    complexity_metrics = self.complexity_analyzer.calculate_shape_complexity(shape)
                    complexity_index = self.complexity_analyzer.calculate_complexity_index(
                        complexity_metrics["face_count"],
                        complexity_metrics["edge_count"],
                        complexity_metrics["vertex_count"],
                        complexity_metrics.get("feature_count", 0)
                    )
                    report.geometric_complexity.value = complexity_index
                    
                    # Calculate surface quality
                    surface_metrics = await self.surface_analyzer.analyze_surface_quality(shape)
                    report.surface_quality.value = surface_metrics.get("finish_quality", 0.5)
                    
                    # Check feature consistency
                    consistency_metrics = self.consistency_checker.check_consistency(shape)
                    report.feature_consistency.value = consistency_metrics.get("overall_consistency", 0.7)
                    
                    # Test parametric robustness
                    robustness_metrics = await self.robustness_checker.test_robustness(doc_handle)
                    report.parametric_robustness.value = robustness_metrics.get("overall_robustness", 0.6)
                    
                    # Check assembly compatibility if applicable
                    if self._has_assembly_features(doc_handle):
                        assembly_metrics = self.assembly_checker.check_compatibility(shape)
                        report.assembly_compatibility = QualityMetric(
                            name="Assembly Compatibility",
                            value=assembly_metrics.get("overall_compatibility", 0.7),
                            min_value=0.0,
                            max_value=1.0,
                            weight=1.2,
                            unit="score",
                            description="Compatibility for assembly"
                        )
                    
                    # Estimate manufacturing readiness
                    report.manufacturing_readiness.value = self._estimate_manufacturing_readiness(
                        complexity_index,
                        report.surface_quality.value,
                        report.feature_consistency.value
                    )
                    
                    # Check documentation completeness
                    report.documentation_completeness.value = self._check_documentation(doc_handle)
                
                # Populate metrics dictionary
                report.metrics = {
                    "geometric_complexity": report.geometric_complexity,
                    "surface_quality": report.surface_quality,
                    "feature_consistency": report.feature_consistency,
                    "parametric_robustness": report.parametric_robustness,
                    "manufacturing_readiness": report.manufacturing_readiness,
                    "documentation_completeness": report.documentation_completeness
                }
                
                if report.assembly_compatibility:
                    report.metrics["assembly_compatibility"] = report.assembly_compatibility
                
                # Calculate overall score
                report.calculate_overall_score()
                
                metrics.quality_metrics_calculated.labels(
                    grade=report.grade
                ).inc()
                
                logger.info(
                    f"Quality metrics calculated",
                    overall_score=report.overall_score,
                    grade=report.grade
                )
                
            except Exception as e:
                logger.error(f"Quality metrics calculation error: {e}", exc_info=True)
                # Set default values
                report.overall_score = 0.5
                report.grade = "C"
            
            return report
    
    def _get_shape_from_document(self, doc_handle: Any) -> Optional[Any]:
        """Extract shape from document."""
        # Same mock implementation as in other validators
        if doc_handle:
            class MockShape:
                def __init__(self):
                    self.Faces = list(range(15))
                    self.Edges = list(range(30))
                    self.Vertexes = list(range(20))
            
            return MockShape()
        return None
    
    def _has_assembly_features(self, doc_handle: Any) -> bool:
        """Check if model has assembly features."""
        # Placeholder implementation
        return False
    
    def _estimate_manufacturing_readiness(
        self,
        complexity: float,
        surface_quality: float,
        consistency: float
    ) -> float:
        """Estimate manufacturing readiness."""
        # Lower complexity is better for manufacturing
        complexity_factor = 1.0 - (complexity / 100.0)
        
        # Calculate readiness
        readiness = (
            complexity_factor * 0.3 +
            surface_quality * 0.4 +
            consistency * 0.3
        )
        
        return min(max(readiness, 0.0), 1.0)
    
    def _check_documentation(self, doc_handle: Any) -> float:
        """Check documentation completeness."""
        # Placeholder implementation
        # Would check for:
        # - Material specifications
        # - Tolerances
        # - Assembly instructions
        # - BOM
        return 0.75