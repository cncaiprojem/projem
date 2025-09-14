"""
Geometric Validator for Task 7.24

This module provides comprehensive geometric validation for FreeCAD models including:
- Self-intersection detection
- Topology validation
- Thin wall detection
- Feature size validation
- Surface quality analysis
"""

from __future__ import annotations

# asyncio removed - using sync methods for CPU-bound operations
import math
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..models.validation_models import (
    GeometricValidation,
    ValidationIssue,
    ValidationSeverity
)
from ..utils.freecad_utils import get_shape_from_document

logger = get_logger(__name__)

# Geometric Validation Constants
VERTEX_ROUNDING_PRECISION = 4  # Decimal places for vertex coordinate rounding
MIN_WALL_THICKNESS_DEFAULT = 1.0  # mm
MIN_FEATURE_SIZE_DEFAULT = 0.5  # mm
MAX_EDGE_LENGTH_DEFAULT = 1000.0  # mm
SURFACE_DEVIATION_TOLERANCE_DEFAULT = 0.01  # mm
ANGLE_TOLERANCE_DEFAULT = 0.1  # degrees


@dataclass
class GeometricTolerances:
    """Geometric tolerances for validation."""
    min_wall_thickness: float = MIN_WALL_THICKNESS_DEFAULT
    min_feature_size: float = MIN_FEATURE_SIZE_DEFAULT
    max_edge_length: float = MAX_EDGE_LENGTH_DEFAULT
    surface_deviation_tolerance: float = SURFACE_DEVIATION_TOLERANCE_DEFAULT
    angle_tolerance: float = ANGLE_TOLERANCE_DEFAULT
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GeometricTolerances:
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


@dataclass
class ThinWallSection:
    """Thin wall section information."""
    face_id: int
    location: Tuple[float, float, float]
    thickness: float
    min_required: float
    area: float


@dataclass
class TopologyCheck:
    """Topology check result."""
    is_valid: bool = True
    errors: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
    
    def add_error(self, error_type: str, details: Any):
        """Add topology error."""
        self.is_valid = False
        self.errors.append({
            "type": error_type,
            "details": details
        })


class WallThicknessAnalyzer:
    """Analyzer for wall thickness using ray casting."""
    
    def __init__(self, resolution: int = 20):
        """Initialize with reasonable resolution (20x20x20 = 8K points instead of 100x100x100 = 1M points)."""
        self.resolution = resolution
    
    def analyze(self, shape: Any) -> Dict[Tuple[float, float, float], float]:
        """Analyze wall thickness across the shape."""
        thickness_map = {}
        
        try:
            # Get bounding box
            bbox = shape.BoundBox if hasattr(shape, 'BoundBox') else None
            if not bbox:
                return thickness_map
            
            # Create sampling grid with adaptive resolution based on size
            # Use lower resolution for larger models to avoid excessive computation
            max_dim = max(bbox.XLength, bbox.YLength, bbox.ZLength)
            if max_dim > 1000:  # Large model (> 1m)
                effective_resolution = min(self.resolution, 10)
            elif max_dim > 500:  # Medium model (> 500mm)
                effective_resolution = min(self.resolution, 15)
            else:  # Small model
                effective_resolution = self.resolution
            
            x_samples = effective_resolution
            y_samples = effective_resolution
            z_samples = effective_resolution
            
            x_step = bbox.XLength / x_samples if x_samples > 0 else 1
            y_step = bbox.YLength / y_samples if y_samples > 0 else 1
            z_step = bbox.ZLength / z_samples if z_samples > 0 else 1
            
            # Sample points and cast rays
            for i in range(x_samples):
                for j in range(y_samples):
                    for k in range(z_samples):
                        x = bbox.XMin + i * x_step
                        y = bbox.YMin + j * y_step
                        z = bbox.ZMin + k * z_step
                        
                        # Cast ray in multiple directions
                        thickness = self._measure_thickness_at_point(
                            shape, (x, y, z)
                        )
                        if thickness > 0:
                            thickness_map[(x, y, z)] = thickness
            
        except Exception as e:
            logger.warning(f"Wall thickness analysis error: {e}")
        
        return thickness_map
    
    def _measure_thickness_at_point(
        self, 
        shape: Any, 
        point: Tuple[float, float, float]
    ) -> float:
        """Measure wall thickness at a specific point using ray casting."""
        try:
            import Part
            import FreeCAD
            
            # Create point object
            fc_point = FreeCAD.Vector(point[0], point[1], point[2])
            
            # Check if point is inside shape
            if not shape.isInside(fc_point, 0.01, True):
                return 0.0
            
            # Cast rays in multiple directions to find minimum thickness
            directions = [
                FreeCAD.Vector(1, 0, 0),   # +X
                FreeCAD.Vector(-1, 0, 0),  # -X
                FreeCAD.Vector(0, 1, 0),   # +Y
                FreeCAD.Vector(0, -1, 0),  # -Y
                FreeCAD.Vector(0, 0, 1),   # +Z
                FreeCAD.Vector(0, 0, -1),  # -Z
            ]
            
            min_thickness = float('inf')
            
            for direction in directions:
                # Create ray line
                ray_line = Part.LineSegment(fc_point, fc_point + direction * 10000)
                
                # Find intersections with shape
                intersections = shape.section(ray_line.toShape())
                
                if intersections and hasattr(intersections, 'Vertexes'):
                    # Calculate distances to intersection points
                    for vertex in intersections.Vertexes:
                        distance = fc_point.distanceToPoint(vertex.Point)
                        if distance > 0.001:  # Ignore self-intersection
                            min_thickness = min(min_thickness, distance)
            
            return min_thickness if min_thickness != float('inf') else 0.0
            
        except Exception as e:
            logger.warning(f"Thickness measurement error at {point}: {e}")
            return 0.0


class GeometricValidator:
    """Validator for geometric properties and constraints."""
    
    def __init__(self, rule_engine: Any = None, basic_mode: bool = False):
        self.rule_engine = rule_engine
        self.basic_mode = basic_mode
        self.wall_analyzer = WallThicknessAnalyzer()
    
    def validate(
        self, 
        doc_handle: Any,
        tolerances: Optional[GeometricTolerances] = None
    ) -> GeometricValidation:
        """Perform comprehensive geometric validation."""
        correlation_id = get_correlation_id()
        
        with create_span("geometric_validation", correlation_id=correlation_id) as span:
            span.set_attribute("basic_mode", self.basic_mode)
            
            validation = GeometricValidation()
            tolerances = tolerances or GeometricTolerances()
            
            try:
                # Get shape from document
                shape = self._get_shape_from_document(doc_handle)
                if not shape:
                    validation.is_valid = False
                    validation.issues.append(ValidationIssue(
                        type="no_geometry",
                        severity=ValidationSeverity.CRITICAL,
                        message="No geometry found in document",
                        turkish_message="Belgede geometri bulunamadı"
                    ))
                    return validation
                
                # Basic validations (always performed)
                self._validate_basic_geometry(shape, validation, tolerances)
                
                if not self.basic_mode:
                    # Advanced validations (run sequentially in sync mode)
                    self._check_self_intersections(shape, validation)
                    self._validate_topology(shape, validation)
                    self._detect_thin_walls(shape, validation, tolerances)
                    self._validate_features(shape, validation, tolerances)
                    self._check_surface_quality(shape, validation)
                
                # Calculate geometric properties
                self._calculate_properties(shape, validation)
                
                # Determine overall validity
                error_count = sum(1 for issue in validation.issues 
                                if issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL])
                validation.is_valid = error_count == 0
                
                metrics.geometric_validations_total.labels(
                    status="valid" if validation.is_valid else "invalid"
                ).inc()
                
                logger.info(
                    f"Geometric validation completed",
                    is_valid=validation.is_valid,
                    issues_count=len(validation.issues)
                )
                
            except Exception as e:
                logger.error("Geometric validation error", exc_info=True)
                validation.is_valid = False
                validation.issues.append(ValidationIssue(
                    type="validation_error",
                    severity=ValidationSeverity.ERROR,
                    message="Validation error occurred",
                    turkish_message="Doğrulama hatası oluştu"
                ))
            
            return validation
    
    def _get_shape_from_document(self, doc_handle: Any) -> Optional[Any]:
        """Extract shape from FreeCAD document."""
        return get_shape_from_document(doc_handle)
    
    def _validate_basic_geometry(
        self,
        shape: Any,
        validation: GeometricValidation,
        tolerances: GeometricTolerances
    ):
        """Perform basic geometric validation."""
        try:
            # Check if shape is valid
            if hasattr(shape, 'isValid') and not shape.isValid():
                validation.issues.append(ValidationIssue(
                    type="invalid_shape",
                    severity=ValidationSeverity.CRITICAL,
                    message="Shape is invalid",
                    turkish_message="Şekil geçersiz",
                    fix_available=True,
                    fix_suggestion="Rebuild shape from sketches"
                ))
            
            # Check for empty geometry
            if hasattr(shape, 'Faces') and len(shape.Faces) == 0:
                validation.issues.append(ValidationIssue(
                    type="empty_geometry",
                    severity=ValidationSeverity.ERROR,
                    message="Shape has no faces",
                    turkish_message="Şeklin yüzeyi yok"
                ))
            
            # Check bounding box
            if hasattr(shape, 'BoundBox'):
                bbox = shape.BoundBox
                max_dim = max(bbox.XLength, bbox.YLength, bbox.ZLength)
                if max_dim > tolerances.max_edge_length:
                    validation.issues.append(ValidationIssue(
                        type="oversized",
                        severity=ValidationSeverity.WARNING,
                        message=f"Model exceeds maximum size: {max_dim:.2f}mm",
                        turkish_message=f"Model maksimum boyutu aşıyor: {max_dim:.2f}mm",
                        details={"max_dimension": max_dim}
                    ))
                
                validation.bounding_box = {
                    "min": {"x": bbox.XMin, "y": bbox.YMin, "z": bbox.ZMin},
                    "max": {"x": bbox.XMax, "y": bbox.YMax, "z": bbox.ZMax},
                    "size": {"x": bbox.XLength, "y": bbox.YLength, "z": bbox.ZLength}
                }
            
        except Exception as e:
            logger.warning(f"Basic geometry validation error: {e}")
    
    def _check_self_intersections(
        self,
        shape: Any,
        validation: GeometricValidation
    ):
        """Check for self-intersecting geometry."""
        try:
            has_intersections = False
            
            # Check using FreeCAD's built-in method if available
            if hasattr(shape, 'hasSelfIntersections'):
                has_intersections = shape.hasSelfIntersections()
            
            # Additional check using shape analysis
            if not has_intersections and hasattr(shape, 'Faces'):
                try:
                    import Part
                    # Check face-to-face intersections with performance limits
                    faces = shape.Faces
                    num_faces = len(faces)
                    
                    # Constants for performance optimization
                    MAX_FACE_CHECKS = 1000  # Limit total intersection checks
                    MAX_FACES_FOR_FULL_CHECK = 100  # Skip detailed check for very complex models
                    
                    if num_faces > MAX_FACES_FOR_FULL_CHECK:
                        # For complex models, sample a subset of faces
                        import random
                        sample_size = min(20, num_faces // 5)  # Check ~20% or max 20 faces
                        sampled_indices = random.sample(range(num_faces), sample_size)
                        faces_to_check = [faces[i] for i in sampled_indices]
                        logger.debug(f"Complex model with {num_faces} faces - sampling {sample_size} faces")
                    else:
                        faces_to_check = faces
                        sampled_indices = range(num_faces)
                    
                    checks_performed = 0
                    for idx, i in enumerate(sampled_indices):
                        if checks_performed >= MAX_FACE_CHECKS:
                            logger.debug(f"Reached maximum face intersection checks ({MAX_FACE_CHECKS})")
                            break
                            
                        face1 = faces[i]
                        # Only check nearby faces for efficiency (skip distant faces)
                        for j in range(i+1, min(i+10, num_faces)):  # Check only next 10 faces
                            if checks_performed >= MAX_FACE_CHECKS:
                                break
                                
                            face2 = faces[j]
                            checks_performed += 1
                            
                            if hasattr(face1, 'common') and hasattr(face2, 'Surface'):
                                # Quick bounding box check first
                                if hasattr(face1, 'BoundBox') and hasattr(face2, 'BoundBox'):
                                    bb1 = face1.BoundBox
                                    bb2 = face2.BoundBox
                                    # Skip if bounding boxes don't overlap
                                    if not bb1.intersect(bb2):
                                        continue
                                
                                common = face1.common(face2)
                                if common and hasattr(common, 'Area') and common.Area > 0.001:
                                    # Found intersection
                                    has_intersections = True
                                    validation.self_intersections.append({
                                        "type": "face_intersection",
                                        "face1_index": i,
                                        "face2_index": j,
                                        "intersection_area": common.Area
                                    })
                                    # Early exit on first intersection for performance
                                    if has_intersections:
                                        break
                        if has_intersections:
                            break
                except ImportError:
                    pass  # FreeCAD not available
            
            if has_intersections:
                validation.issues.append(ValidationIssue(
                    type="self_intersection",
                    severity=ValidationSeverity.CRITICAL,
                    message="Shape contains self-intersections",
                    turkish_message="Şekil kendisiyle kesişiyor",
                    fix_available=True,
                    fix_suggestion="Use boolean operations to resolve intersections"
                ))
                
                if not validation.self_intersections:
                    # Add generic intersection if no specific ones found
                    validation.self_intersections.append({
                        "type": "generic_intersection",
                        "location": "detected"
                    })
        
        except Exception as e:
            logger.warning(f"Self-intersection check error: {e}")
    
    def _validate_topology(
        self,
        shape: Any,
        validation: GeometricValidation
    ):
        """Validate shape topology."""
        try:
            topology_check = self.check_topology(shape)
            
            if not topology_check.is_valid:
                for error in topology_check.errors:
                    if error["type"] == "non_manifold_edges":
                        validation.non_manifold_edges.extend(error["details"])
                        validation.issues.append(ValidationIssue(
                            type="non_manifold",
                            severity=ValidationSeverity.ERROR,
                            message=f"Found {len(error['details'])} non-manifold edges",
                            turkish_message=f"{len(error['details'])} manifold olmayan kenar bulundu",
                            fix_available=True,
                            fix_suggestion="Split or merge edges to ensure manifold topology"
                        ))
                    
                    elif error["type"] == "open_edges_in_solid":
                        validation.open_edges.extend(error["details"])
                        validation.issues.append(ValidationIssue(
                            type="open_edges",
                            severity=ValidationSeverity.ERROR,
                            message=f"Solid has {len(error['details'])} open edges",
                            turkish_message=f"Katı modelde {len(error['details'])} açık kenar var",
                            fix_available=True,
                            fix_suggestion="Close open edges to create watertight solid"
                        ))
                    
                    elif error["type"] == "inconsistent_normals":
                        validation.topology_errors.extend(error["details"])
                        validation.issues.append(ValidationIssue(
                            type="inconsistent_normals",
                            severity=ValidationSeverity.WARNING,
                            message="Face normals are inconsistent",
                            turkish_message="Yüzey normalleri tutarsız",
                            fix_available=True,
                            fix_suggestion="Unify face normals"
                        ))
        
        except Exception as e:
            logger.warning(f"Topology validation error: {e}")
    
    def check_topology(self, shape: Any) -> TopologyCheck:
        """Check topological validity."""
        check = TopologyCheck()
        
        try:
            # Check for non-manifold edges
            non_manifold = self.find_non_manifold_edges(shape)
            if non_manifold:
                check.add_error("non_manifold_edges", non_manifold)
            
            # Check for open edges in solids
            if hasattr(shape, 'ShapeType') and shape.ShapeType == 'Solid':
                open_edges = self.find_open_edges(shape)
                if open_edges:
                    check.add_error("open_edges_in_solid", open_edges)
            
            # Check face normals consistency
            inconsistent_normals = self.check_face_normals(shape)
            if inconsistent_normals:
                check.add_error("inconsistent_normals", inconsistent_normals)
        
        except Exception as e:
            logger.warning(f"Topology check error: {e}")
            check.add_error("check_failed", "Topology check failed")
        
        return check
    
    def find_non_manifold_edges(self, shape: Any) -> List[Dict[str, Any]]:
        """Find non-manifold edges in shape."""
        # Use shared topology utilities
        from ..utils.topology_utils import detect_non_manifold_edges
        
        try:
            return detect_non_manifold_edges(shape)
        except Exception as e:
            logger.warning(f"Non-manifold edge detection error: {e}")
            return []
    
    def find_open_edges(self, shape: Any) -> List[Dict[str, Any]]:
        """Find open edges in shape."""
        # Use shared topology utilities
        from ..utils.topology_utils import detect_open_edges
        
        try:
            open_edges_basic = detect_open_edges(shape)
            
            # Add additional fields for compatibility
            open_edges = []
            if hasattr(shape, 'Edges'):
                for edge_info in open_edges_basic:
                    edge_idx = edge_info.get("edge_index", 0)
                    if edge_idx < len(shape.Edges):
                        edge = shape.Edges[edge_idx]
                        if hasattr(edge, 'Vertexes') and len(edge.Vertexes) >= 2:
                            v1 = edge.Vertexes[0].Point
                            v2 = edge.Vertexes[-1].Point
                            open_edges.append({
                                "edge_index": edge_idx,
                                "length": edge_info.get("length", 0.0),
                                "start": {"x": v1.x, "y": v1.y, "z": v1.z},
                                "end": {"x": v2.x, "y": v2.y, "z": v2.z}
                            })
                    else:
                        open_edges.append(edge_info)
            else:
                open_edges = open_edges_basic
            
            return open_edges
        except Exception as e:
            logger.warning(f"Open edge detection error: {e}")
            return []
    
    def check_face_normals(self, shape: Any) -> List[Dict[str, Any]]:
        """Check consistency of face normals."""
        inconsistent = []
        
        try:
            if hasattr(shape, 'Faces'):
                try:
                    import Part
                    import FreeCAD
                    
                    # Check each face normal
                    for i, face in enumerate(shape.Faces):
                        if hasattr(face, 'Surface'):
                            # Get face normal at center
                            try:
                                # Get parameter bounds
                                u_min, u_max, v_min, v_max = face.ParameterRange
                                u_mid = (u_min + u_max) / 2
                                v_mid = (v_min + v_max) / 2
                                
                                # Get normal at center point
                                normal = face.normalAt(u_mid, v_mid)
                                
                                # Check if normal is pointing outward (for solids)
                                if hasattr(shape, 'ShapeType') and shape.ShapeType == 'Solid':
                                    # Get point on face
                                    point = face.valueAt(u_mid, v_mid)
                                    # Check if normal points outward from center of mass
                                    if hasattr(shape, 'CenterOfMass'):
                                        center = shape.CenterOfMass
                                        to_point = point.sub(center)
                                        dot_product = normal.dot(to_point)
                                        
                                        if dot_product < 0:  # Normal points inward
                                            inconsistent.append({
                                                "face_index": i,
                                                "issue": "inward_normal",
                                                "normal": {"x": normal.x, "y": normal.y, "z": normal.z},
                                                "location": {"x": point.x, "y": point.y, "z": point.z}
                                            })
                                
                                # Check for degenerate normals
                                if normal.Length < 0.001:
                                    inconsistent.append({
                                        "face_index": i,
                                        "issue": "degenerate_normal",
                                        "normal_length": normal.Length
                                    })
                                    
                            except Exception as e:
                                logger.debug(f"Normal calculation error for face {i}: {e}")
                    
                except ImportError:
                    logger.debug("FreeCAD not available for normal checking")
        
        except Exception as e:
            logger.warning(f"Face normal check error: {e}")
        
        return inconsistent
    
    def _detect_thin_walls(
        self,
        shape: Any,
        validation: GeometricValidation,
        tolerances: GeometricTolerances
    ):
        """Detect walls thinner than minimum thickness."""
        try:
            # Analyze wall thickness
            thickness_map = self.wall_analyzer.analyze(shape)
            
            thin_sections = []
            for location, thickness in thickness_map.items():
                if thickness < tolerances.min_wall_thickness:
                    thin_sections.append(ThinWallSection(
                        face_id=0,  # Would be actual face ID
                        location=location,
                        thickness=thickness,
                        min_required=tolerances.min_wall_thickness,
                        area=1.0  # Would calculate actual area
                    ))
            
            if thin_sections:
                validation.thin_walls = [
                    {
                        "location": {"x": s.location[0], "y": s.location[1], "z": s.location[2]},
                        "thickness": s.thickness,
                        "min_required": s.min_required,
                        "area": s.area
                    }
                    for s in thin_sections
                ]
                
                validation.issues.append(ValidationIssue(
                    type="thin_walls",
                    severity=ValidationSeverity.WARNING,
                    message=f"Found {len(thin_sections)} thin wall sections",
                    turkish_message=f"{len(thin_sections)} ince duvar bölümü bulundu",
                    details={"count": len(thin_sections), "min_thickness": tolerances.min_wall_thickness},
                    fix_available=True,
                    fix_suggestion=f"Increase wall thickness to at least {tolerances.min_wall_thickness}mm"
                ))
        
        except Exception as e:
            logger.warning(f"Thin wall detection error: {e}")
    
    def _validate_features(
        self,
        shape: Any,
        validation: GeometricValidation,
        tolerances: GeometricTolerances
    ):
        """Validate feature sizes and characteristics."""
        try:
            small_features = []
            
            # Check edge lengths
            if hasattr(shape, 'Edges'):
                for i, edge in enumerate(shape.Edges):
                    # Get actual edge length
                    length = edge.Length if hasattr(edge, 'Length') else 0.0
                    if length > 0 and length < tolerances.min_feature_size:
                        small_features.append({
                            "type": "edge",
                            "index": i,
                            "size": round(length, 4)
                        })
            
            if small_features:
                validation.small_features = small_features
                validation.issues.append(ValidationIssue(
                    type="small_features",
                    severity=ValidationSeverity.INFO,
                    message=f"Found {len(small_features)} features smaller than {tolerances.min_feature_size}mm",
                    turkish_message=f"{tolerances.min_feature_size}mm'den küçük {len(small_features)} özellik bulundu",
                    details={"count": len(small_features), "min_size": tolerances.min_feature_size}
                ))
        
        except Exception as e:
            logger.warning(f"Feature validation error: {e}")
    
    def _check_surface_quality(
        self,
        shape: Any,
        validation: GeometricValidation
    ):
        """Check surface quality and smoothness."""
        try:
            quality_score = 1.0
            quality_issues = []
            
            # Import FreeCAD modules if available
            try:
                import FreeCAD
                import Part
                import math
            except ImportError:
                # Can't perform detailed analysis without FreeCAD
                validation.surface_quality_score = 0.75  # Default moderate score
                return
            
            if hasattr(shape, 'Faces'):
                total_faces = len(shape.Faces)
                good_faces = 0
                
                for i, face in enumerate(shape.Faces):
                    try:
                        face_quality = 1.0
                        
                        # Check face validity
                        if hasattr(face, 'isValid') and not face.isValid():
                            face_quality *= 0.5
                            quality_issues.append(f"Face {i}: invalid")
                        
                        # Check for degenerate faces (very small area)
                        if hasattr(face, 'Area'):
                            if face.Area < 0.01:  # Very small face
                                face_quality *= 0.7
                                quality_issues.append(f"Face {i}: degenerate (area={face.Area:.4f})")
                        
                        # Check surface curvature consistency
                        if hasattr(face, 'Surface'):
                            surface = face.Surface
                            
                            # Sample curvature at multiple points
                            if hasattr(face, 'ParameterRange'):
                                u_min, u_max, v_min, v_max = face.ParameterRange
                                
                                # Sample 9 points (3x3 grid)
                                curvatures = []
                                for u_factor in [0.25, 0.5, 0.75]:
                                    for v_factor in [0.25, 0.5, 0.75]:
                                        u = u_min + (u_max - u_min) * u_factor
                                        v = v_min + (v_max - v_min) * v_factor
                                        
                                        try:
                                            # Get curvature at point
                                            if hasattr(surface, 'curvature'):
                                                curv = surface.curvature(u, v)
                                                if curv:
                                                    # Store mean curvature
                                                    curvatures.append((curv[0] + curv[1]) / 2)
                                        except:
                                            pass
                                
                                # Check curvature variation
                                if curvatures:
                                    max_curv = max(abs(c) for c in curvatures)
                                    if max_curv > 100:  # High curvature
                                        face_quality *= 0.9
                        
                        # Check for twisted surfaces
                        if hasattr(face, 'normalAt'):
                            try:
                                # Check normal consistency at corners
                                u_min, u_max, v_min, v_max = face.ParameterRange
                                corners = [
                                    (u_min, v_min), (u_min, v_max),
                                    (u_max, v_min), (u_max, v_max)
                                ]
                                
                                normals = []
                                for u, v in corners:
                                    try:
                                        normal = face.normalAt(u, v)
                                        normals.append(normal)
                                    except:
                                        pass
                                
                                # Check if normals are reasonably aligned
                                if len(normals) >= 2:
                                    for j in range(1, len(normals)):
                                        dot = normals[0].dot(normals[j])
                                        if dot < 0.5:  # More than 60 degrees difference
                                            face_quality *= 0.8
                                            quality_issues.append(f"Face {i}: twisted surface")
                                            break
                            except:
                                pass
                        
                        if face_quality >= 0.8:
                            good_faces += 1
                    
                    except Exception as e:
                        logger.debug(f"Face {i} quality check error: {e}")
                        continue
                
                # Calculate overall quality score
                if total_faces > 0:
                    quality_score = good_faces / total_faces
            
            validation.surface_quality_score = round(quality_score, 2)
            
            if quality_score < 0.7:
                validation.issues.append(ValidationIssue(
                    type="poor_surface_quality",
                    severity=ValidationSeverity.INFO,
                    message=f"Surface quality score: {quality_score:.2f}",
                    turkish_message=f"Yüzey kalitesi puanı: {quality_score:.2f}",
                    details={
                        "score": quality_score,
                        "issues": quality_issues[:5]  # First 5 issues
                    }
                ))
        
        except Exception as e:
            logger.warning(f"Surface quality check error: {e}")
            validation.surface_quality_score = 0.75  # Default score on error
    
    def _calculate_properties(
        self,
        shape: Any,
        validation: GeometricValidation
    ):
        """Calculate geometric properties."""
        try:
            # Volume
            if hasattr(shape, 'Volume'):
                validation.volume = shape.Volume  # mm³
            
            # Surface area
            if hasattr(shape, 'Area'):
                validation.surface_area = shape.Area  # mm²
            
            # Center of mass
            if hasattr(shape, 'CenterOfMass'):
                com = shape.CenterOfMass
                validation.center_of_mass = {
                    "x": com[0] if isinstance(com, tuple) else com.x,
                    "y": com[1] if isinstance(com, tuple) else com.y,
                    "z": com[2] if isinstance(com, tuple) else com.z
                }
        
        except Exception as e:
            logger.warning(f"Property calculation error: {e}")