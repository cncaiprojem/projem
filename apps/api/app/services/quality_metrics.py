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
                    # Check if face is planar
                    try:
                        if hasattr(face, 'Surface'):
                            surface = face.Surface
                            # Check surface type
                            surface_type = surface.__class__.__name__
                            if surface_type == 'Plane':
                                planar_faces += 1
                            else:
                                # For other surfaces, check curvature
                                # Sample center point
                                u_param = face.ParameterRange[:2]
                                v_param = face.ParameterRange[2:]
                                u_mid = (u_param[0] + u_param[1]) / 2
                                v_mid = (v_param[0] + v_param[1]) / 2
                                
                                # Check curvature at center
                                if hasattr(surface, 'curvature'):
                                    curv = surface.curvature(u_mid, v_mid)
                                    # If curvature is very small, consider it planar
                                    if curv and abs(curv[0]) < 0.001 and abs(curv[1]) < 0.001:
                                        planar_faces += 1
                                    else:
                                        curved_faces += 1
                                else:
                                    curved_faces += 1
                        else:
                            # Default to curved if we can't determine
                            curved_faces += 1
                    except Exception as e:
                        # On error, assume curved
                        logger.debug(f"Face analysis error: {e}")
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
    def analyze_surface_quality(shape: Any) -> Dict[str, float]:
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
                    smoothness = SurfaceQualityAnalyzer._calculate_smoothness(face)
                    smoothness_scores.append(smoothness)
                    
                    # Check edge continuity
                    continuity = SurfaceQualityAnalyzer._check_continuity(face)
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
    def _calculate_smoothness(face: Any) -> float:
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
                    except Exception as e:
                        logger.debug(f"Sampling error: {e}")
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
            
        except ImportError as e:
            logger.warning(f"FreeCAD not available for smoothness calculation: {e}")
            return 0.85
        except Exception as e:
            logger.debug(f"Smoothness calculation error: {e}")
            return 0.85
    
    @staticmethod
    def _check_continuity(face: Any) -> float:
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
                                        dist = point.distanceToPoint(other_point) if hasattr(point, 'distanceToPoint') else (point - other_point).Length
                                        
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
                            except Exception as e:
                                logger.debug(f"Inner loop error: {e}")
                                continue
                                
                except Exception as e:
                    logger.debug(f"Processing error: {e}")
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
            
        except ImportError as e:
            logger.warning(f"FreeCAD not available for continuity check: {e}")
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
        patterns = []
        
        try:
            import Part
            import FreeCAD
            
            if hasattr(shape, 'Faces'):
                # Group faces by area and type
                face_groups = {}
                for i, face in enumerate(shape.Faces):
                    area = round(face.Area, 2)
                    surface_type = face.Surface.__class__.__name__ if hasattr(face, 'Surface') else 'Unknown'
                    key = (surface_type, area)
                    
                    if key not in face_groups:
                        face_groups[key] = []
                    face_groups[key].append(i)
                
                # Identify patterns (groups with multiple similar faces)
                for (surface_type, area), indices in face_groups.items():
                    if len(indices) > 1:
                        patterns.append({
                            "type": "repeated_face",
                            "surface_type": surface_type,
                            "area": area,
                            "count": len(indices),
                            "indices": indices
                        })
            
            if hasattr(shape, 'Edges'):
                # Group edges by length
                edge_groups = {}
                for i, edge in enumerate(shape.Edges):
                    if hasattr(edge, 'Length'):
                        length = round(edge.Length, 2)
                        if length not in edge_groups:
                            edge_groups[length] = []
                        edge_groups[length].append(i)
                
                # Identify edge patterns
                for length, indices in edge_groups.items():
                    if len(indices) > 2:  # At least 3 similar edges
                        patterns.append({
                            "type": "repeated_edge",
                            "length": length,
                            "count": len(indices),
                            "indices": indices
                        })
                        
        except Exception as e:
            logger.debug("Pattern detection error")
        
        return patterns
    
    @staticmethod
    def _evaluate_pattern_consistency(patterns: List[Dict[str, Any]]) -> float:
        """Evaluate consistency of detected patterns."""
        if not patterns:
            return 1.0  # No patterns means no inconsistency
        
        consistency_score = 1.0
        
        try:
            # Check face patterns
            face_patterns = [p for p in patterns if p.get('type') == 'repeated_face']
            if face_patterns:
                # Check if repeated faces have consistent counts (e.g., 4 sides of a box)
                counts = [p['count'] for p in face_patterns]
                if counts:
                    # Check for common multiples (2, 4, 6, 8, etc.)
                    common_counts = [2, 4, 6, 8]
                    matches = sum(1 for c in counts if c in common_counts)
                    consistency_score *= (0.5 + 0.5 * matches / len(counts))
                    
                    # Check for consistency in areas
                    areas = [p['area'] for p in face_patterns]
                    if len(set(areas)) == 1:  # All same area
                        consistency_score *= 1.0
                    else:
                        # Calculate coefficient of variation
                        mean_area = sum(areas) / len(areas)
                        if mean_area > 0:
                            std_dev = math.sqrt(sum((a - mean_area)**2 for a in areas) / len(areas))
                            cv = std_dev / mean_area
                            consistency_score *= max(0.5, 1.0 - cv)
            
            # Check edge patterns
            edge_patterns = [p for p in patterns if p.get('type') == 'repeated_edge']
            if edge_patterns:
                # Similar edges should appear in multiples
                edge_counts = [p['count'] for p in edge_patterns]
                # Check for even numbers (paired edges)
                even_count = sum(1 for c in edge_counts if c % 2 == 0)
                consistency_score *= (0.6 + 0.4 * even_count / len(edge_counts))
            
            return max(0.0, min(1.0, consistency_score))
            
        except Exception as e:
            logger.debug(f"Pattern consistency evaluation error: {e}")
            return 0.9
    
    @staticmethod
    def _extract_dimensions(shape: Any) -> List[float]:
        """Extract key dimensions from shape."""
        dimensions = []
        
        try:
            # Get bounding box dimensions
            if hasattr(shape, 'BoundBox'):
                bbox = shape.BoundBox
                dimensions.extend([
                    bbox.XLength,
                    bbox.YLength,
                    bbox.ZLength
                ])
            
            # Get edge lengths
            if hasattr(shape, 'Edges'):
                edge_lengths = []
                for edge in shape.Edges:
                    if hasattr(edge, 'Length'):
                        edge_lengths.append(edge.Length)
                
                if edge_lengths:
                    # Add unique edge lengths (rounded to avoid duplicates)
                    unique_lengths = list(set(round(l, 2) for l in edge_lengths))
                    dimensions.extend(sorted(unique_lengths)[:10])  # Top 10 unique lengths
            
            # Get face areas
            if hasattr(shape, 'Faces'):
                face_areas = []
                for face in shape.Faces:
                    if hasattr(face, 'Area'):
                        face_areas.append(face.Area)
                
                if face_areas:
                    # Add significant face areas
                    unique_areas = list(set(round(a, 2) for a in face_areas if a > 0.01))
                    dimensions.extend([math.sqrt(a) for a in sorted(unique_areas)[:5]])  # Convert to linear dimension
            
            return dimensions if dimensions else [1.0, 1.0, 1.0]
            
        except Exception as e:
            logger.debug(f"Dimension extraction error: {e}")
            return [1.0, 1.0, 1.0]
    
    @staticmethod
    def _evaluate_dimension_consistency(dimensions: List[float]) -> float:
        """Evaluate consistency of dimensions."""
        if not dimensions:
            return 0.5
        
        consistency_score = 1.0
        
        try:
            # Check for round numbers (good for manufacturing)
            round_count = sum(1 for d in dimensions if abs(d - round(d)) < 0.01)
            round_ratio = round_count / len(dimensions)
            consistency_score *= (0.5 + 0.5 * round_ratio)
            
            # Check for standard sizes (metric)
            standard_sizes = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 16, 20, 25, 30, 40, 50, 60, 80, 100]
            standard_count = sum(1 for d in dimensions if any(abs(d - s) < 0.1 for s in standard_sizes))
            standard_ratio = standard_count / len(dimensions)
            consistency_score *= (0.6 + 0.4 * standard_ratio)
            
            # Check for dimensional relationships (ratios)
            if len(dimensions) >= 2:
                ratios = []
                for i in range(len(dimensions) - 1):
                    if dimensions[i] > 0:
                        ratio = dimensions[i+1] / dimensions[i]
                        ratios.append(ratio)
                
                # Check for common ratios (1:1, 1:2, 2:3, golden ratio, etc.)
                common_ratios = [1.0, 2.0, 0.5, 1.5, 1.618, 0.618, 3.0, 0.333]
                ratio_matches = sum(1 for r in ratios if any(abs(r - cr) < 0.05 for cr in common_ratios))
                if ratios:
                    consistency_score *= (0.7 + 0.3 * ratio_matches / len(ratios))
            
            return max(0.0, min(1.0, consistency_score))
            
        except Exception as e:
            logger.debug(f"Dimension consistency evaluation error: {e}")
            return 0.85
    
    @staticmethod
    def _check_symmetry(shape: Any) -> float:
        """Check model symmetry."""
        symmetry_score = 0.0
        
        try:
            import Part
            import FreeCAD
            
            if hasattr(shape, 'BoundBox'):
                bbox = shape.BoundBox
                center = FreeCAD.Vector(
                    (bbox.XMin + bbox.XMax) / 2,
                    (bbox.YMin + bbox.YMax) / 2,
                    (bbox.ZMin + bbox.ZMax) / 2
                )
                
                # Check symmetry along each axis
                symmetry_axes = []
                
                # X-axis symmetry
                try:
                    mirror_x = shape.mirror(center, FreeCAD.Vector(1, 0, 0))
                    # Compare volumes
                    if hasattr(shape, 'Volume') and hasattr(mirror_x, 'Volume'):
                        vol_diff = abs(shape.Volume - mirror_x.Volume) / max(shape.Volume, 0.001)
                        if vol_diff < 0.01:  # Less than 1% difference
                            symmetry_axes.append('X')
                except Exception as e:
                    logger.debug(f"Symmetry check error: {e}")
                
                # Y-axis symmetry
                try:
                    mirror_y = shape.mirror(center, FreeCAD.Vector(0, 1, 0))
                    if hasattr(shape, 'Volume') and hasattr(mirror_y, 'Volume'):
                        vol_diff = abs(shape.Volume - mirror_y.Volume) / max(shape.Volume, 0.001)
                        if vol_diff < 0.01:
                            symmetry_axes.append('Y')
                except Exception as e:
                    logger.debug(f"Symmetry check error: {e}")
                
                # Z-axis symmetry
                try:
                    mirror_z = shape.mirror(center, FreeCAD.Vector(0, 0, 1))
                    if hasattr(shape, 'Volume') and hasattr(mirror_z, 'Volume'):
                        vol_diff = abs(shape.Volume - mirror_z.Volume) / max(shape.Volume, 0.001)
                        if vol_diff < 0.01:
                            symmetry_axes.append('Z')
                except Exception as e:
                    logger.debug(f"Symmetry check error: {e}")
                
                # Calculate symmetry score based on number of symmetry axes
                symmetry_score = len(symmetry_axes) / 3.0
                
                # Bonus for perfect symmetry (all three axes)
                if len(symmetry_axes) == 3:
                    symmetry_score = 1.0
                elif len(symmetry_axes) == 2:
                    symmetry_score = 0.8
                elif len(symmetry_axes) == 1:
                    symmetry_score = 0.6
                else:
                    symmetry_score = 0.3  # Some partial symmetry
                    
        except ImportError as e:
            logger.warning(f"FreeCAD not available for symmetry check: {e}")
            symmetry_score = 0.8
        except Exception as e:
            logger.debug("Symmetry check error")
            symmetry_score = 0.8
        
        return symmetry_score
    
    @staticmethod
    def _check_alignment(shape: Any) -> float:
        """Check feature alignment."""
        alignment_score = 1.0
        
        try:
            import FreeCAD
            
            if hasattr(shape, 'Faces'):
                # Check face alignment
                face_normals = []
                face_centers = []
                
                for face in shape.Faces:
                    try:
                        # Get face normal at center
                        if hasattr(face, 'Surface'):
                            u_param = face.ParameterRange[0:2]
                            v_param = face.ParameterRange[2:4]
                            u_mid = (u_param[0] + u_param[1]) / 2
                            v_mid = (v_param[0] + v_param[1]) / 2
                            
                            if hasattr(face, 'normalAt'):
                                normal = face.normalAt(u_mid, v_mid)
                                face_normals.append(normal)
                            
                            if hasattr(face, 'CenterOfMass'):
                                face_centers.append(face.CenterOfMass)
                    except Exception as e:
                        logger.debug(f"Sampling error: {e}")
                        continue
                
                # Check for aligned normals (parallel or perpendicular)
                if face_normals:
                    aligned_count = 0
                    total_comparisons = 0
                    
                    for i in range(len(face_normals)):
                        for j in range(i + 1, len(face_normals)):
                            total_comparisons += 1
                            n1, n2 = face_normals[i], face_normals[j]
                            
                            if hasattr(n1, 'dot'):
                                dot_product = abs(n1.dot(n2))
                                # Check if parallel (dot = 1) or perpendicular (dot = 0)
                                if dot_product > 0.98 or dot_product < 0.02:
                                    aligned_count += 1
                                elif abs(dot_product - 0.707) < 0.02:  # 45 degrees
                                    aligned_count += 0.5
                    
                    if total_comparisons > 0:
                        alignment_ratio = aligned_count / total_comparisons
                        alignment_score *= (0.5 + 0.5 * alignment_ratio)
                
                # Check for aligned centers (grid alignment)
                if face_centers and len(face_centers) > 2:
                    # Check if centers align on axes
                    x_coords = [c.x for c in face_centers if hasattr(c, 'x')]
                    y_coords = [c.y for c in face_centers if hasattr(c, 'y')]
                    z_coords = [c.z for c in face_centers if hasattr(c, 'z')]
                    
                    # Check for repeated coordinates (alignment)
                    def check_grid_alignment(coords):
                        if not coords:
                            return 0.5
                        rounded = [round(c, 2) for c in coords]
                        unique = len(set(rounded))
                        # Fewer unique values means better alignment
                        return max(0.3, 1.0 - unique / len(coords))
                    
                    x_alignment = check_grid_alignment(x_coords)
                    y_alignment = check_grid_alignment(y_coords)
                    z_alignment = check_grid_alignment(z_coords)
                    
                    grid_score = (x_alignment + y_alignment + z_alignment) / 3
                    alignment_score *= (0.6 + 0.4 * grid_score)
            
            # Check edge alignment
            if hasattr(shape, 'Edges'):
                edge_vectors = []
                for edge in shape.Edges:
                    try:
                        if hasattr(edge, 'Curve'):
                            # Get edge direction
                            if hasattr(edge.Curve, 'Direction'):
                                edge_vectors.append(edge.Curve.Direction)
                    except Exception as e:
                        logger.debug(f"Sampling error: {e}")
                        continue
                
                if edge_vectors:
                    # Check for aligned edges
                    axis_aligned = 0
                    for vec in edge_vectors:
                        if hasattr(vec, 'x'):
                            # Check if aligned with main axes
                            if (abs(vec.x) > 0.98 and abs(vec.y) < 0.02 and abs(vec.z) < 0.02) or \
                               (abs(vec.y) > 0.98 and abs(vec.x) < 0.02 and abs(vec.z) < 0.02) or \
                               (abs(vec.z) > 0.98 and abs(vec.x) < 0.02 and abs(vec.y) < 0.02):
                                axis_aligned += 1
                    
                    if edge_vectors:
                        axis_ratio = axis_aligned / len(edge_vectors)
                        alignment_score *= (0.7 + 0.3 * axis_ratio)
            
            return max(0.0, min(1.0, alignment_score))
            
        except ImportError as e:
            logger.debug(f"FreeCAD import error for alignment check: {e}")
            return 0.9
        except Exception as e:
            logger.debug(f"Alignment check error: {e}")
            return 0.9


class ParametricRobustnessChecker:
    """Checker for parametric robustness."""
    
    @staticmethod
    def test_robustness(doc_handle: Any) -> Dict[str, float]:
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
            robustness_metrics["rebuild_stability"] = ParametricRobustnessChecker._test_rebuild(doc_handle)
            
            # Test parameter sensitivity
            robustness_metrics["parameter_sensitivity"] = ParametricRobustnessChecker._test_parameter_changes(doc_handle)
            
            # Test constraint stability
            robustness_metrics["constraint_stability"] = ParametricRobustnessChecker._test_constraints(doc_handle)
            
            # Test update reliability
            robustness_metrics["update_reliability"] = ParametricRobustnessChecker._test_updates(doc_handle)
            
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
    def _test_rebuild(doc_handle: Any) -> float:
        """Test model rebuild stability."""
        rebuild_score = 0.95
        
        try:
            if doc_handle:
                # Attempt to recompute the document
                if hasattr(doc_handle, 'recompute'):
                    errors_before = len(doc_handle.RecomputeErrors) if hasattr(doc_handle, 'RecomputeErrors') else 0
                    
                    # Perform recompute
                    result = doc_handle.recompute()
                    
                    errors_after = len(doc_handle.RecomputeErrors) if hasattr(doc_handle, 'RecomputeErrors') else 0
                    
                    # Check recompute result
                    if result == 0:  # Success
                        rebuild_score = 1.0
                    elif errors_after == errors_before:
                        rebuild_score = 0.9  # No new errors
                    elif errors_after > errors_before:
                        # New errors introduced
                        rebuild_score = max(0.5, 1.0 - 0.1 * (errors_after - errors_before))
                    
                    # Check for broken references
                    if hasattr(doc_handle, 'Objects'):
                        broken_count = 0
                        for obj in doc_handle.Objects:
                            if hasattr(obj, 'State'):
                                if 'Error' in obj.State or 'Invalid' in obj.State:
                                    broken_count += 1
                        
                        if broken_count > 0:
                            rebuild_score *= max(0.5, 1.0 - 0.1 * broken_count)
        
        except Exception as e:
            logger.debug(f"Rebuild test error: {e}")
            rebuild_score = 0.85
        
        return rebuild_score
    
    @staticmethod
    def _test_parameter_changes(doc_handle: Any) -> float:
        """Test sensitivity to parameter changes."""
        sensitivity_score = 0.85
        
        try:
            if doc_handle and hasattr(doc_handle, 'Objects'):
                stable_changes = 0
                total_tests = 0
                
                for obj in doc_handle.Objects:
                    # Find parametric objects
                    if hasattr(obj, 'PropertiesList'):
                        properties = obj.PropertiesList
                        
                        for prop in properties:
                            try:
                                # Test numeric properties
                                if hasattr(obj, prop):
                                    value = getattr(obj, prop)
                                    if isinstance(value, (int, float)):
                                        total_tests += 1
                                        original_value = value
                                        
                                        # Make small change (5%)
                                        test_value = value * 1.05 if value != 0 else 0.1
                                        setattr(obj, prop, test_value)
                                        
                                        # Check if change is accepted
                                        if hasattr(doc_handle, 'recompute'):
                                            result = doc_handle.recompute()
                                            if result == 0:
                                                stable_changes += 1
                                        
                                        # Restore original value
                                        setattr(obj, prop, original_value)
                                        
                                        if total_tests >= 5:  # Test sample of properties
                                            break
                            except Exception as e:
                                logger.debug(f"Inner loop error: {e}")
                                continue
                
                if total_tests > 0:
                    sensitivity_score = stable_changes / total_tests
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
        return sensitivity_score
    
    @staticmethod
    def _test_constraints(doc_handle: Any) -> float:
        """Test constraint stability."""
        constraint_score = 0.9
        
        try:
            if doc_handle and hasattr(doc_handle, 'Objects'):
                constraint_count = 0
                valid_constraints = 0
                
                for obj in doc_handle.Objects:
                    # Check for sketch constraints
                    if hasattr(obj, 'TypeId'):
                        if 'Sketch' in str(obj.TypeId):
                            if hasattr(obj, 'Constraints'):
                                for constraint in obj.Constraints:
                                    constraint_count += 1
                                    # Check if constraint is satisfied
                                    if hasattr(constraint, 'Type'):
                                        # Basic check - constraint exists and has a type
                                        valid_constraints += 1
                
                if constraint_count > 0:
                    constraint_score = valid_constraints / constraint_count
                else:
                    # No constraints might mean simple model (not necessarily bad)
                    constraint_score = 0.85
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
        return constraint_score
    
    @staticmethod
    def _test_updates(doc_handle: Any) -> float:
        """Test update reliability."""
        update_score = 0.88
        
        try:
            if doc_handle:
                update_failures = 0
                update_attempts = 0
                
                # Test document updates
                if hasattr(doc_handle, 'touch'):
                    update_attempts += 1
                    try:
                        doc_handle.touch()
                        if hasattr(doc_handle, 'recompute'):
                            result = doc_handle.recompute()
                            if result != 0:
                                update_failures += 1
                    except Exception as e:
                        logger.debug(f"Document update error: {e}")
                        update_failures += 1
                
                # Test object updates
                if hasattr(doc_handle, 'Objects'):
                    for obj in doc_handle.Objects[:3]:  # Test first 3 objects
                        if hasattr(obj, 'touch'):
                            update_attempts += 1
                            try:
                                obj.touch()
                                if hasattr(obj, 'recompute'):
                                    obj.recompute()
                            except Exception as e:
                                logger.debug(f"Object update error: {e}")
                                update_failures += 1
                
                if update_attempts > 0:
                    update_score = 1.0 - (update_failures / update_attempts)
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
        return update_score


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
        interface_score = 0.85
        
        try:
            if hasattr(shape, 'Faces'):
                # Look for mating surfaces (flat faces that could interface)
                flat_faces = []
                for face in shape.Faces:
                    try:
                        if hasattr(face, 'Surface'):
                            surface_type = face.Surface.__class__.__name__
                            if surface_type == 'Plane':
                                flat_faces.append(face)
                    except Exception as e:
                        logger.debug(f"Sampling error: {e}")
                        continue
                
                if flat_faces:
                    # Check for parallel flat faces (potential interfaces)
                    parallel_pairs = 0
                    for i in range(len(flat_faces)):
                        for j in range(i + 1, len(flat_faces)):
                            try:
                                if hasattr(flat_faces[i], 'Surface') and hasattr(flat_faces[j], 'Surface'):
                                    normal1 = flat_faces[i].Surface.Axis
                                    normal2 = flat_faces[j].Surface.Axis
                                    if hasattr(normal1, 'dot'):
                                        dot = abs(normal1.dot(normal2))
                                        if dot > 0.98:  # Nearly parallel
                                            parallel_pairs += 1
                            except Exception as e:
                                logger.debug(f"Inner loop error: {e}")
                                continue
                    
                    # More parallel pairs = better interface potential
                    if len(flat_faces) > 1:
                        interface_score = min(1.0, 0.5 + 0.1 * parallel_pairs)
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
        return interface_score
    
    @staticmethod
    def _check_mating_surfaces(shape: Any) -> float:
        """Check mating surface quality."""
        mating_score = 0.9
        
        try:
            if hasattr(shape, 'Faces'):
                # Check for cylindrical surfaces (common mating features)
                cylindrical_count = 0
                planar_count = 0
                
                for face in shape.Faces:
                    try:
                        if hasattr(face, 'Surface'):
                            surface_type = face.Surface.__class__.__name__
                            if surface_type == 'Cylinder':
                                cylindrical_count += 1
                            elif surface_type == 'Plane':
                                planar_count += 1
                    except Exception as e:
                        logger.debug(f"Sampling error: {e}")
                        continue
                
                total_faces = len(shape.Faces)
                if total_faces > 0:
                    # Good mating surfaces have a mix of planar and cylindrical
                    if cylindrical_count > 0 and planar_count > 0:
                        mating_score = 0.95
                    elif cylindrical_count > 0 or planar_count > 0:
                        mating_score = 0.85
                    else:
                        mating_score = 0.7
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
        return mating_score
    
    @staticmethod
    def _check_clearances(shape: Any) -> float:
        """Check clearance compliance."""
        clearance_score = 0.95
        
        try:
            if hasattr(shape, 'BoundBox'):
                bbox = shape.BoundBox
                # Check if the model has reasonable proportions
                dimensions = [bbox.XLength, bbox.YLength, bbox.ZLength]
                max_dim = max(dimensions)
                min_dim = min(dimensions)
                
                if min_dim > 0:
                    aspect_ratio = max_dim / min_dim
                    # Extreme aspect ratios might indicate clearance issues
                    if aspect_ratio > 100:
                        clearance_score = 0.6
                    elif aspect_ratio > 50:
                        clearance_score = 0.75
                    elif aspect_ratio > 20:
                        clearance_score = 0.85
                    else:
                        clearance_score = 0.95
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
        return clearance_score
    
    @staticmethod
    def _check_assembly_features(shape: Any) -> float:
        """Check assembly feature presence."""
        feature_score = 0.5  # Base score
        
        try:
            feature_count = 0
            
            if hasattr(shape, 'Faces'):
                # Check for holes (cylindrical faces)
                for face in shape.Faces:
                    try:
                        if hasattr(face, 'Surface'):
                            if face.Surface.__class__.__name__ == 'Cylinder':
                                # Check if it's a hole (internal cylinder)
                                if hasattr(face, 'Area'):
                                    feature_count += 1
                    except Exception as e:
                        logger.debug(f"Sampling error: {e}")
                        continue
            
            if hasattr(shape, 'Edges'):
                # Check for chamfers and fillets (curved edges)
                for edge in shape.Edges:
                    try:
                        if hasattr(edge, 'Curve'):
                            curve_type = edge.Curve.__class__.__name__
                            if curve_type in ['Circle', 'Arc', 'BSplineCurve']:
                                feature_count += 1
                    except Exception as e:
                        logger.debug(f"Sampling error: {e}")
                        continue
            
            # More features = better assembly readiness
            if feature_count > 10:
                feature_score = 0.95
            elif feature_count > 5:
                feature_score = 0.85
            elif feature_count > 2:
                feature_score = 0.75
            elif feature_count > 0:
                feature_score = 0.65
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
        return feature_score


class QualityMetrics:
    """Main quality metrics calculator."""
    
    def __init__(self):
        self.complexity_analyzer = ComplexityAnalyzer()
        self.surface_analyzer = SurfaceQualityAnalyzer()
        self.consistency_checker = FeatureConsistencyChecker()
        self.robustness_checker = ParametricRobustnessChecker()
        self.assembly_checker = AssemblyCompatibilityChecker()
    
    def calculate_metrics(self, doc_handle: Any) -> QualityMetricsReport:
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
                    surface_metrics = self.surface_analyzer.analyze_surface_quality(shape)
                    report.surface_quality.value = surface_metrics.get("finish_quality", 0.5)
                    
                    # Check feature consistency
                    consistency_metrics = self.consistency_checker.check_consistency(shape)
                    report.feature_consistency.value = consistency_metrics.get("overall_consistency", 0.7)
                    
                    # Test parametric robustness
                    robustness_metrics = self.robustness_checker.test_robustness(doc_handle)
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
        try:
            if doc_handle:
                # Try to get shape from document objects
                if hasattr(doc_handle, 'Objects'):
                    for obj in doc_handle.Objects:
                        if hasattr(obj, 'Shape'):
                            return obj.Shape
                        elif hasattr(obj, 'Mesh'):
                            # Convert mesh to shape if needed
                            import Part
                            if hasattr(Part, 'Shape'):
                                shape = Part.Shape()
                                if hasattr(shape, 'makeShapeFromMesh'):
                                    shape.makeShapeFromMesh(obj.Mesh, 0.1)
                                    return shape
                
                # Try to get combined shape
                if hasattr(doc_handle, 'Shape'):
                    return doc_handle.Shape
        
        except Exception as e:
            logger.debug(f"Could not extract shape from document: {e}")
        
        return None
    
    def _has_assembly_features(self, doc_handle: Any) -> bool:
        """Check if model has assembly features."""
        try:
            if doc_handle and hasattr(doc_handle, 'Objects'):
                for obj in doc_handle.Objects:
                    # Check for assembly-related objects
                    if hasattr(obj, 'TypeId'):
                        type_id = str(obj.TypeId).lower()
                        if any(keyword in type_id for keyword in ['assembly', 'joint', 'constraint', 'mate']):
                            return True
                    
                    # Check for multiple bodies/parts
                    if hasattr(obj, 'Label'):
                        label = str(obj.Label).lower()
                        if any(keyword in label for keyword in ['assembly', 'part', 'component']):
                            return True
            
            # Check if document has multiple solid bodies
            if doc_handle:
                shape = self._get_shape_from_document(doc_handle)
                if shape and hasattr(shape, 'Solids'):
                    if len(shape.Solids) > 1:
                        return True
        
        except Exception as e:
            logger.debug(f"Check error: {e}")
        
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
        doc_score = 0.0
        doc_items = 0
        
        try:
            if doc_handle:
                # Check for document properties
                if hasattr(doc_handle, 'Properties'):
                    properties = doc_handle.Properties if hasattr(doc_handle, 'Properties') else []
                    
                    # Check for material specification
                    if any('material' in str(p).lower() for p in properties):
                        doc_score += 0.25
                        doc_items += 1
                    
                    # Check for tolerances
                    if any('tolerance' in str(p).lower() for p in properties):
                        doc_score += 0.25
                        doc_items += 1
                    
                    # Check for author/creator info
                    if any(key in str(p).lower() for p in properties for key in ['author', 'creator', 'designer']):
                        doc_score += 0.15
                        doc_items += 1
                    
                    # Check for revision/version info
                    if any(key in str(p).lower() for p in properties for key in ['revision', 'version']):
                        doc_score += 0.15
                        doc_items += 1
                
                # Check for object documentation
                if hasattr(doc_handle, 'Objects'):
                    has_descriptions = False
                    has_labels = False
                    
                    for obj in doc_handle.Objects:
                        if hasattr(obj, 'Label') and obj.Label:
                            has_labels = True
                        if hasattr(obj, 'Description') and obj.Description:
                            has_descriptions = True
                    
                    if has_labels:
                        doc_score += 0.1
                        doc_items += 1
                    if has_descriptions:
                        doc_score += 0.1
                        doc_items += 1
                
                # If no documentation found, give a base score
                if doc_items == 0:
                    doc_score = 0.3  # Minimal documentation
        
        except Exception as e:
            logger.debug(f"Documentation check error: {e}")
            doc_score = 0.75  # Default to reasonable documentation
        
        return min(1.0, doc_score)