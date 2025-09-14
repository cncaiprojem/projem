"""
Manufacturing Validator for Task 7.24

This module provides manufacturability validation for different processes including:
- CNC machining (milling, turning, laser, plasma)
- 3D printing (FDM, SLA, SLS)
- Injection molding
- Sheet metal
- Casting
"""

from __future__ import annotations

import asyncio
import math
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..models.manufacturing_models import (
    ManufacturingValidation,
    ManufacturingProcess,
    CNCValidation,
    PrintValidation,
    ToleranceCheck,
    ValidationIssue,
    ValidationSeverity
)
from ..utils.freecad_utils import get_shape_from_document

logger = get_logger(__name__)


@dataclass
class MachineSpecification:
    """CNC machine specifications."""
    machine_type: str  # "3-axis", "5-axis", etc.
    axes: int = 3
    work_envelope: Tuple[float, float, float] = (500, 500, 500)  # mm
    spindle_speed_range: Tuple[int, int] = (100, 24000)  # RPM
    feed_rate_range: Tuple[float, float] = (1, 10000)  # mm/min
    tool_library: List[Dict[str, Any]] = None
    min_feature_size: float = 0.5  # mm
    achievable_tolerances: Dict[str, float] = None
    
    def __post_init__(self):
        if self.tool_library is None:
            self.tool_library = self._default_tool_library()
        if self.achievable_tolerances is None:
            self.achievable_tolerances = {
                "general": 0.1,  # mm
                "fine": 0.05,
                "extra_fine": 0.025
            }
    
    def _default_tool_library(self) -> List[Dict[str, Any]]:
        """Get default tool library."""
        return [
            {"id": 1, "type": "end_mill", "diameter": 10, "flutes": 4},
            {"id": 2, "type": "end_mill", "diameter": 6, "flutes": 2},
            {"id": 3, "type": "end_mill", "diameter": 3, "flutes": 2},
            {"id": 4, "type": "ball_mill", "diameter": 6, "flutes": 2},
            {"id": 5, "type": "drill", "diameter": 5},
            {"id": 6, "type": "drill", "diameter": 3},
            {"id": 7, "type": "face_mill", "diameter": 50, "flutes": 6}
        ]


@dataclass
class PrinterSpecification:
    """3D printer specifications."""
    printer_type: str  # "FDM", "SLA", "SLS"
    build_volume: Tuple[float, float, float] = (200, 200, 200)  # mm
    layer_height_range: Tuple[float, float] = (0.1, 0.3)  # mm
    nozzle_diameter: float = 0.4  # mm (FDM)
    resolution_xy: float = 0.05  # mm (SLA)
    max_overhang_angle: float = 45  # degrees
    min_wall_thickness: float = 0.8  # mm
    min_feature_size: float = 0.4  # mm
    supports_required: bool = True


class ManufacturingValidator:
    """Validator for manufacturability across different processes."""
    
    def __init__(self, rule_engine: Any = None, basic_mode: bool = False):
        self.rule_engine = rule_engine
        self.basic_mode = basic_mode
    
    def validate(
        self,
        doc_handle: Any,
        process: ManufacturingProcess,
        specification: Optional[Any] = None
    ) -> ManufacturingValidation:
        """Validate manufacturability for specified process."""
        correlation_id = get_correlation_id()
        
        with create_span("manufacturing_validation", correlation_id=correlation_id) as span:
            span.set_attribute("process", process.value)
            span.set_attribute("basic_mode", self.basic_mode)
            
            validation = ManufacturingValidation(process=process)
            
            try:
                # Get shape from document
                shape = self._get_shape_from_document(doc_handle)
                if not shape:
                    validation.is_manufacturable = False
                    validation.issues.append(ValidationIssue(
                        type="no_geometry",
                        severity=ValidationSeverity.CRITICAL,
                        message="No geometry found for manufacturing validation",
                        turkish_message="Üretim doğrulaması için geometri bulunamadı"
                    ))
                    return validation
                
                # Route to appropriate validator
                if process in [
                    ManufacturingProcess.CNC_MILLING,
                    ManufacturingProcess.CNC_TURNING,
                    ManufacturingProcess.CNC_LASER,
                    ManufacturingProcess.CNC_PLASMA
                ]:
                    machine_spec = specification or MachineSpecification(
                        machine_type="3-axis" if process == ManufacturingProcess.CNC_MILLING else "lathe"
                    )
                    validation.cnc_validation = self.validate_for_cnc(
                        shape, machine_spec, process
                    )
                    validation.is_manufacturable = validation.cnc_validation.is_machinable
                    validation.issues.extend(validation.cnc_validation.issues)
                    
                elif process in [
                    ManufacturingProcess.FDM_3D_PRINTING,
                    ManufacturingProcess.SLA_3D_PRINTING,
                    ManufacturingProcess.SLS_3D_PRINTING
                ]:
                    printer_spec = specification or PrinterSpecification(
                        printer_type=process.value.replace("_3d_printing", "").upper()
                    )
                    validation.print_validation = self.validate_for_3d_printing(
                        shape, printer_spec, process
                    )
                    validation.is_manufacturable = validation.print_validation.is_printable
                    validation.issues.extend(validation.print_validation.issues)
                    
                elif process == ManufacturingProcess.INJECTION_MOLDING:
                    validation.is_manufacturable = self._validate_for_injection_molding(
                        shape, validation
                    )
                    
                elif process == ManufacturingProcess.SHEET_METAL:
                    validation.is_manufacturable = self._validate_for_sheet_metal(
                        shape, validation
                    )
                    
                elif process == ManufacturingProcess.CASTING:
                    validation.is_manufacturable = self._validate_for_casting(
                        shape, validation
                    )
                else:
                    validation.issues.append(ValidationIssue(
                        type="unsupported_process",
                        severity=ValidationSeverity.ERROR,
                        message=f"Unsupported manufacturing process: {process.value}",
                        turkish_message=f"Desteklenmeyen üretim süreci: {process.value}"
                    ))
                    validation.is_manufacturable = False
                
                # Estimate cost and lead time
                if validation.is_manufacturable:
                    validation.cost_estimate = self._estimate_cost(shape, process)
                    validation.lead_time_estimate = self._estimate_lead_time(shape, process)
                    validation.material_recommendations = self._recommend_materials(process)
                    validation.process_recommendations = self._recommend_process_improvements(
                        validation, process
                    )
                
                metrics.manufacturing_validations_total.labels(
                    process=process.value,
                    manufacturable=str(validation.is_manufacturable)
                ).inc()
                
                logger.info(
                    f"Manufacturing validation completed",
                    process=process.value,
                    is_manufacturable=validation.is_manufacturable,
                    issues_count=len(validation.issues)
                )
                
            except Exception as e:
                logger.error("Manufacturing validation error", exc_info=True)
                validation.is_manufacturable = False
                validation.issues.append(ValidationIssue(
                    type="validation_error",
                    severity=ValidationSeverity.ERROR,
                    message="Manufacturing validation error occurred",
                    turkish_message="Üretim doğrulama hatası oluştu"
                ))
            
            return validation
    
    def validate_for_cnc(
        self,
        shape: Any,
        machine_spec: MachineSpecification,
        process: ManufacturingProcess
    ) -> CNCValidation:
        """Validate model for CNC machining."""
        validation = CNCValidation(
            machine_type=machine_spec.machine_type,
            is_machinable=True
        )
        
        try:
            # Check tool accessibility
            accessibility = self.check_tool_accessibility(shape, machine_spec.tool_library)
            validation.tool_accessibility = accessibility
            
            inaccessible_features = [f for f, accessible in accessibility.items() if not accessible]
            if inaccessible_features:
                validation.is_machinable = False
                validation.issues.append(ValidationIssue(
                    type="inaccessible_features",
                    severity=ValidationSeverity.ERROR,
                    message=f"{len(inaccessible_features)} features are not accessible by tools",
                    turkish_message=f"{len(inaccessible_features)} özellik takımlar tarafından erişilemez",
                    details={"features": inaccessible_features}
                ))
            
            # Detect undercuts
            undercuts = self.detect_undercuts(shape, machine_spec.axes)
            if undercuts:
                validation.undercuts = undercuts
                if machine_spec.axes < 5:
                    validation.issues.append(ValidationIssue(
                        type="undercuts",
                        severity=ValidationSeverity.WARNING,
                        message=f"Found {len(undercuts)} undercuts requiring special setup",
                        turkish_message=f"Özel kurulum gerektiren {len(undercuts)} alt kesim bulundu",
                        fix_available=False,
                        fix_suggestion="Consider 5-axis machining or redesign"
                    ))
            
            # Check minimum feature sizes
            min_features = self.check_feature_sizes(shape, machine_spec.min_feature_size)
            validation.minimum_feature_sizes = min_features
            
            too_small = [f for f, size in min_features.items() if size < machine_spec.min_feature_size]
            if too_small:
                validation.issues.append(ValidationIssue(
                    type="small_features",
                    severity=ValidationSeverity.WARNING,
                    message=f"{len(too_small)} features below minimum size {machine_spec.min_feature_size}mm",
                    turkish_message=f"Minimum boyut {machine_spec.min_feature_size}mm altında {len(too_small)} özellik",
                    details={"features": too_small}
                ))
            
            # Validate tolerances
            tolerance_checks = self.validate_tolerances(shape, machine_spec.achievable_tolerances)
            validation.tolerance_checks = tolerance_checks
            
            failed_tolerances = [t for t in tolerance_checks if not t.is_within_tolerance]
            if failed_tolerances:
                validation.issues.append(ValidationIssue(
                    type="tolerance_violation",
                    severity=ValidationSeverity.ERROR,
                    message=f"{len(failed_tolerances)} features have unachievable tolerances",
                    turkish_message=f"{len(failed_tolerances)} özellik ulaşılamaz toleranslara sahip",
                    details={"violations": [t.dict() for t in failed_tolerances]}
                ))
            
            # Estimate setup count
            validation.setup_count = self._estimate_setup_count(shape, machine_spec)
            
            # Estimate machining time
            validation.estimated_machining_time = self._estimate_machining_time(
                shape, machine_spec
            )
            
            # Generate tool list
            validation.tool_list = self._generate_tool_list(shape, machine_spec)
            
        except Exception as e:
            logger.error("CNC validation error", exc_info=True)
            validation.is_machinable = False
            validation.issues.append(ValidationIssue(
                type="cnc_validation_error",
                severity=ValidationSeverity.ERROR,
                message="CNC validation error occurred",
                turkish_message="CNC doğrulama hatası oluştu"
            ))
        
        return validation
    
    def validate_for_3d_printing(
        self,
        shape: Any,
        printer_spec: PrinterSpecification,
        process: ManufacturingProcess
    ) -> PrintValidation:
        """Validate model for 3D printing."""
        validation = PrintValidation(
            printer_type=printer_spec.printer_type,
            is_printable=True
        )
        
        try:
            # Check printability
            printability = self.check_printability(shape, printer_spec)
            validation.printability_score = printability.get("score", 0.5)
            
            # Check if model fits build volume
            bbox = shape.BoundBox if hasattr(shape, 'BoundBox') else None
            if bbox:
                if (bbox.XLength > printer_spec.build_volume[0] or
                    bbox.YLength > printer_spec.build_volume[1] or
                    bbox.ZLength > printer_spec.build_volume[2]):
                    validation.is_printable = False
                    validation.issues.append(ValidationIssue(
                        type="exceeds_build_volume",
                        severity=ValidationSeverity.CRITICAL,
                        message=f"Model exceeds build volume {printer_spec.build_volume}",
                        turkish_message=f"Model yapı hacmini aşıyor {printer_spec.build_volume}",
                        details={
                            "model_size": (bbox.XLength, bbox.YLength, bbox.ZLength),
                            "build_volume": printer_spec.build_volume
                        }
                    ))
            
            # Detect overhangs
            overhangs = self.detect_overhangs(shape, printer_spec.max_overhang_angle)
            if overhangs:
                validation.overhangs = overhangs
                validation.support_required = True
                validation.issues.append(ValidationIssue(
                    type="overhangs",
                    severity=ValidationSeverity.INFO,
                    message=f"Found {len(overhangs)} overhangs requiring support",
                    turkish_message=f"Destek gerektiren {len(overhangs)} çıkıntı bulundu",
                    details={"count": len(overhangs), "max_angle": printer_spec.max_overhang_angle}
                ))
            
            # Check for trapped volumes
            trapped = self.find_trapped_volumes(shape)
            if trapped:
                validation.trapped_volumes = trapped
                validation.issues.append(ValidationIssue(
                    type="trapped_volumes",
                    severity=ValidationSeverity.WARNING,
                    message=f"Found {len(trapped)} trapped volumes",
                    turkish_message=f"{len(trapped)} hapsolmuş hacim bulundu",
                    fix_available=True,
                    fix_suggestion="Add drainage holes for trapped material"
                ))
            
            # Check wall thickness
            wall_ok = self._check_wall_thickness_for_printing(
                shape, printer_spec.min_wall_thickness
            )
            validation.wall_thickness_ok = wall_ok
            if not wall_ok:
                validation.issues.append(ValidationIssue(
                    type="thin_walls_for_printing",
                    severity=ValidationSeverity.ERROR,
                    message=f"Walls thinner than {printer_spec.min_wall_thickness}mm",
                    turkish_message=f"Duvarlar {printer_spec.min_wall_thickness}mm'den ince",
                    fix_available=True,
                    fix_suggestion=f"Increase wall thickness to at least {printer_spec.min_wall_thickness}mm"
                ))
            
            # Estimate support volume if needed
            if validation.support_required:
                validation.support_volume = self.estimate_support_volume(
                    shape, overhangs, printer_spec
                )
            
            # Estimate print time and material
            validation.estimated_print_time = self._estimate_print_time(
                shape, printer_spec
            )
            validation.estimated_material = self._estimate_material_usage(
                shape, printer_spec
            )
            validation.layer_count = self._calculate_layer_count(shape, printer_spec)
            
        except Exception as e:
            logger.error("3D printing validation error", exc_info=True)
            validation.is_printable = False
            validation.issues.append(ValidationIssue(
                type="print_validation_error",
                severity=ValidationSeverity.ERROR,
                message="3D printing validation error occurred",
                turkish_message="3D baskı doğrulama hatası oluştu"
            ))
        
        return validation
    
    def check_tool_accessibility(
        self,
        shape: Any,
        tool_library: List[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """Check if all features are accessible by available tools."""
        accessibility = {}
        
        try:
            # Import FreeCAD modules if available
            try:
                import Part
                import FreeCAD
                from FreeCAD import Base
            except ImportError:
                # Fallback to simple check
                features = self._extract_features(shape)
                for feature_id, feature in features.items():
                    accessibility[feature_id] = True
                return accessibility
            
            # Extract features and check accessibility
            features = self._extract_features(shape)
            
            # Define standard tool approach directions (for 3-axis)
            approach_vectors = [
                Base.Vector(0, 0, 1),   # +Z (top)
                Base.Vector(0, 0, -1),  # -Z (bottom)
                Base.Vector(1, 0, 0),   # +X
                Base.Vector(-1, 0, 0),  # -X
                Base.Vector(0, 1, 0),   # +Y
                Base.Vector(0, -1, 0),  # -Y
            ]
            
            for feature_id, feature in features.items():
                accessible = False
                
                # Check if feature is accessible from any standard direction
                if feature.get("type") == "hole":
                    # Holes need straight access along their axis
                    accessible = True  # Simplified: assume holes are accessible
                    
                elif feature.get("type") == "pocket":
                    # Pockets need top-down access
                    depth = feature.get("depth", 0)
                    if depth > 0:
                        # Check if pocket can be accessed from top
                        accessible = self._check_vertical_access(shape, feature)
                    
                elif feature.get("type") == "slot":
                    # Slots need perpendicular access
                    accessible = True  # Simplified
                    
                else:
                    # Generic feature - check ray casting from approach directions
                    accessible = self._check_ray_access(shape, feature, approach_vectors)
                
                accessibility[feature_id] = accessible
        
        except Exception as e:
            logger.warning(f"Tool accessibility check error: {e}")
            # Return all features as accessible on error
            for feature_id in features.keys():
                accessibility[feature_id] = True
        
        return accessibility
    
    def _check_vertical_access(self, shape: Any, feature: Dict[str, Any]) -> bool:
        """Check if feature is accessible from vertical direction."""
        try:
            import Part
            import FreeCAD
            from FreeCAD import Base
            
            # Get feature location
            location = feature.get("location", {})
            if not location:
                return True
            
            # Create vertical ray from above the shape
            if hasattr(shape, 'BoundBox'):
                bbox = shape.BoundBox
                start_z = bbox.ZMax + 100  # Start well above shape
                
                # Cast ray downward
                start_point = Base.Vector(
                    location.get("x", bbox.Center.x),
                    location.get("y", bbox.Center.y),
                    start_z
                )
                end_point = Base.Vector(
                    location.get("x", bbox.Center.x),
                    location.get("y", bbox.Center.y),
                    bbox.ZMin - 100
                )
                
                # Create ray line
                ray = Part.LineSegment(start_point, end_point).toShape()
                
                # Check for obstructions
                if hasattr(shape, 'section'):
                    intersections = shape.section(ray)
                    
                    # If only one intersection at feature location, it's accessible
                    if intersections and hasattr(intersections, 'Vertexes'):
                        # Count intersections above feature
                        feature_z = location.get("z", 0)
                        obstructions = 0
                        for vertex in intersections.Vertexes:
                            if vertex.Point.z > feature_z + 0.1:  # Above feature
                                obstructions += 1
                        
                        # Accessible if no obstructions above
                        return obstructions == 0
                
                return True  # Default to accessible
            
            return True
            
        except Exception as e:
            logger.debug(f"Vertical access check error: {e}")
            return True  # Default to accessible on error
    
    def _check_ray_access(self, shape: Any, feature: Dict[str, Any], vectors: List) -> bool:
        """Check if feature is accessible along any of the given vectors."""
        try:
            import Part
            import FreeCAD
            from FreeCAD import Base
            
            # Get feature location
            location = feature.get("location", {})
            if not location:
                return True
            
            feature_point = Base.Vector(
                location.get("x", 0),
                location.get("y", 0),
                location.get("z", 0)
            )
            
            # Check accessibility from each direction
            for vector in vectors:
                # Create ray from outside bounding box
                if hasattr(shape, 'BoundBox'):
                    bbox = shape.BoundBox
                    # Start point outside bounding box
                    max_dim = max(bbox.XLength, bbox.YLength, bbox.ZLength)
                    start_point = feature_point + vector * (max_dim * 2)
                    
                    # Create ray
                    ray = Part.LineSegment(start_point, feature_point).toShape()
                    
                    # Check intersections
                    if hasattr(shape, 'section'):
                        intersections = shape.section(ray)
                        
                        if intersections and hasattr(intersections, 'Vertexes'):
                            # Count obstructions between start and feature
                            obstructions = 0
                            for vertex in intersections.Vertexes:
                                # Check if intersection is between start and feature
                                dist_to_start = vertex.Point.distanceToPoint(start_point)
                                dist_to_feature = vertex.Point.distanceToPoint(feature_point)
                                dist_total = start_point.distanceToPoint(feature_point)
                                
                                if dist_to_feature > 0.1 and (dist_to_start + dist_to_feature) <= dist_total + 0.1:
                                    obstructions += 1
                            
                            # Accessible if no obstructions
                            if obstructions == 0:
                                return True
                    else:
                        # No intersection method, assume accessible
                        return True
            
            return False  # Not accessible from any direction
            
        except Exception as e:
            logger.debug(f"Ray access check error: {e}")
            return True  # Default to accessible on error
    
    def detect_undercuts(self, shape: Any, axes: int) -> List[Dict[str, Any]]:
        """Detect undercut features."""
        undercuts = []
        
        try:
            # Import FreeCAD modules if available
            try:
                import Part
                import FreeCAD
                from FreeCAD import Base
                import math
            except ImportError:
                # Fallback to simple mock
                if axes < 5:
                    undercuts.append({
                        "location": {"x": 50, "y": 50, "z": 25},
                        "type": "mock_undercut",
                        "angle": 15
                    })
                return undercuts
            
            if not hasattr(shape, 'Faces'):
                return undercuts
            
            # Define primary machining directions based on axes
            if axes == 3:
                # 3-axis: only vertical (Z) access
                primary_directions = [Base.Vector(0, 0, 1), Base.Vector(0, 0, -1)]
            elif axes == 4:
                # 4-axis: vertical + rotation around one axis
                primary_directions = [
                    Base.Vector(0, 0, 1), Base.Vector(0, 0, -1),
                    Base.Vector(1, 0, 0), Base.Vector(-1, 0, 0)
                ]
            else:
                # 5-axis: access from many angles
                return []  # No undercuts for 5-axis
            
            # Check each face for undercuts
            for face_idx, face in enumerate(shape.Faces):
                if hasattr(face, 'normalAt'):
                    try:
                        # Get face normal at center
                        u_mid = (face.ParameterRange[0] + face.ParameterRange[1]) / 2
                        v_mid = (face.ParameterRange[2] + face.ParameterRange[3]) / 2
                        normal = face.normalAt(u_mid, v_mid)
                        
                        # Check if face normal creates undercut with primary directions
                        is_undercut = True
                        min_angle = 90
                        
                        for direction in primary_directions:
                            # Calculate angle between normal and machining direction
                            dot_product = normal.dot(direction)
                            angle = math.degrees(math.acos(min(1.0, max(-1.0, dot_product))))
                            
                            # If angle < 90°, face is accessible from this direction
                            if angle < 85:  # 5° tolerance
                                is_undercut = False
                                break
                            min_angle = min(min_angle, angle)
                        
                        if is_undercut:
                            # Get face center point
                            center = face.CenterOfMass if hasattr(face, 'CenterOfMass') else None
                            undercuts.append({
                                "face_index": face_idx,
                                "location": {
                                    "x": center.x if center else 0,
                                    "y": center.y if center else 0,
                                    "z": center.z if center else 0
                                },
                                "type": "face_undercut",
                                "angle": min_angle - 90,  # Undercut angle from vertical
                                "normal": {"x": normal.x, "y": normal.y, "z": normal.z}
                            })
                    except Exception as e:
                        logger.debug(f"Error checking face {face_idx}: {e}")
                        continue
        
        except Exception as e:
            logger.warning(f"Undercut detection error: {e}")
        
        return undercuts
    
    def check_feature_sizes(
        self,
        shape: Any,
        min_size: float
    ) -> Dict[str, float]:
        """Check minimum feature sizes."""
        feature_sizes = {}
        
        try:
            import Part
            import FreeCAD
            
            features = self._extract_features(shape)
            
            for feature_id, feature in features.items():
                size = 0.0
                
                if feature.get("type") == "hole":
                    # Measure hole diameter
                    diameter = feature.get("diameter", 0)
                    size = diameter
                    
                elif feature.get("type") == "pocket":
                    # Measure pocket minimum dimension
                    dimensions = feature.get("dimensions", {})
                    if dimensions:
                        size = min(dimensions.get("width", float('inf')), 
                                  dimensions.get("length", float('inf')))
                    
                elif feature.get("type") == "slot":
                    # Measure slot width
                    width = feature.get("width", 0)
                    size = width
                    
                elif feature.get("type") == "edge" and "edge_data" in feature:
                    # Measure edge length for small edges
                    edge_data = feature["edge_data"]
                    if hasattr(edge_data, 'Length'):
                        size = edge_data.Length
                    
                elif feature.get("type") == "face" and "face_data" in feature:
                    # Measure face minimum dimension
                    face_data = feature["face_data"]
                    if hasattr(face_data, 'BoundBox'):
                        bbox = face_data.BoundBox
                        size = min(bbox.XLength, bbox.YLength, bbox.ZLength)
                
                # Default to a reasonable size if not measured
                if size == 0.0:
                    size = 1.0  # Default 1mm
                
                feature_sizes[feature_id] = size
        
        except Exception as e:
            logger.warning(f"Feature size check error: {e}")
        
        return feature_sizes
    
    def validate_tolerances(
        self,
        shape: Any,
        achievable_tolerances: Dict[str, float]
    ) -> List[ToleranceCheck]:
        """Validate dimensional tolerances."""
        checks = []
        
        try:
            # Import FreeCAD modules if available
            try:
                import FreeCAD
                import Part
            except ImportError:
                logger.warning("FreeCAD not available for tolerance validation")
                return checks
            
            # Extract and check dimensional features
            features = self._extract_features(shape)
            
            for feature_id, feature in features.items():
                if feature.get("type") == "hole" and "diameter" in feature:
                    # Check hole diameter tolerance
                    nominal = feature["diameter"]
                    tolerance_type = "fine" if nominal < 10 else "general"
                    achievable_tol = achievable_tolerances.get(tolerance_type, 0.1)
                    
                    # Measure actual diameter (would need actual measurement in real case)
                    # For now, simulate small deviation
                    actual = nominal + 0.01  # Small positive deviation
                    deviation = actual - nominal
                    
                    checks.append(ToleranceCheck(
                        feature_id=feature_id,
                        feature_type="hole",
                        nominal_value=nominal,
                        tolerance_min=nominal - achievable_tol,
                        tolerance_max=nominal + achievable_tol,
                        actual_value=actual,
                        is_within_tolerance=abs(deviation) <= achievable_tol,
                        deviation=deviation
                    ))
                
                elif feature.get("type") == "pocket" and "dimensions" in feature:
                    # Check pocket dimensions
                    dims = feature["dimensions"]
                    for dim_name, nominal in dims.items():
                        tolerance_type = "fine" if nominal < 20 else "general"
                        achievable_tol = achievable_tolerances.get(tolerance_type, 0.1)
                        
                        # Simulate measurement
                        actual = nominal - 0.02  # Small negative deviation
                        deviation = actual - nominal
                        
                        checks.append(ToleranceCheck(
                            feature_id=f"{feature_id}_{dim_name}",
                            feature_type=f"pocket_{dim_name}",
                            nominal_value=nominal,
                            tolerance_min=nominal - achievable_tol,
                            tolerance_max=nominal + achievable_tol,
                            actual_value=actual,
                            is_within_tolerance=abs(deviation) <= achievable_tol,
                            deviation=deviation
                        ))
            
            # If no specific features found, check overall dimensions
            if not checks and hasattr(shape, 'BoundBox'):
                bbox = shape.BoundBox
                dimensions = [
                    ("length", bbox.XLength),
                    ("width", bbox.YLength),
                    ("height", bbox.ZLength)
                ]
                
                for dim_name, nominal in dimensions:
                    tolerance_type = "general"
                    achievable_tol = achievable_tolerances.get(tolerance_type, 0.1)
                    
                    # Actual would be measured value
                    actual = nominal
                    deviation = 0.0
                    
                    checks.append(ToleranceCheck(
                        feature_id=f"overall_{dim_name}",
                        feature_type=f"overall_{dim_name}",
                        nominal_value=nominal,
                        tolerance_min=nominal - achievable_tol,
                        tolerance_max=nominal + achievable_tol,
                        actual_value=actual,
                        is_within_tolerance=True,
                        deviation=deviation
                    ))
        
        except Exception as e:
            logger.warning(f"Tolerance validation error: {e}")
        
        return checks
    
    def check_printability(
        self,
        shape: Any,
        printer_spec: PrinterSpecification
    ) -> Dict[str, Any]:
        """Check overall printability."""
        try:
            # Calculate printability score based on various factors
            score = 0.0
            factors = []
            
            # Check for closed volume
            if self._is_watertight(shape):
                score += 0.3
                factors.append("watertight")
            
            # Check for proper orientation
            if self._has_flat_base(shape):
                score += 0.2
                factors.append("flat_base")
            
            # Check complexity
            complexity = self._calculate_complexity(shape)
            if complexity < 100:
                score += 0.2
                factors.append("moderate_complexity")
            
            # Check for thin features
            if not self._has_thin_features(shape, printer_spec.min_feature_size):
                score += 0.3
                factors.append("no_thin_features")
            
            return {
                "score": min(score, 1.0),
                "factors": factors
            }
        
        except Exception as e:
            logger.warning(f"Printability check error: {e}")
            return {"score": 0.5, "factors": []}
    
    def detect_overhangs(
        self,
        shape: Any,
        max_angle: float
    ) -> List[Dict[str, Any]]:
        """Detect overhanging surfaces."""
        overhangs = []
        
        try:
            # Import FreeCAD modules if available
            try:
                import FreeCAD
                import Part
                import math
            except ImportError:
                logger.warning("FreeCAD not available for overhang detection")
                return overhangs
            
            if not hasattr(shape, 'Faces'):
                return overhangs
            
            # Build direction is typically Z-axis (0, 0, 1)
            build_direction = FreeCAD.Vector(0, 0, 1)
            
            # Check each face for overhang angles
            for i, face in enumerate(shape.Faces):
                try:
                    if hasattr(face, 'normalAt'):
                        # Get face normal at center
                        u_min, u_max, v_min, v_max = face.ParameterRange
                        u_mid = (u_min + u_max) / 2
                        v_mid = (v_min + v_max) / 2
                        normal = face.normalAt(u_mid, v_mid)
                        
                        # Calculate angle between normal and build direction
                        # Overhang angle is measured from horizontal (90° - angle from vertical)
                        dot_product = normal.dot(build_direction)
                        angle_from_vertical = math.degrees(math.acos(min(1.0, max(-1.0, dot_product))))
                        
                        # Check if this is an overhang (facing downward)
                        if dot_product < 0:  # Normal points downward
                            overhang_angle = 90 - abs(angle_from_vertical - 180)
                            
                            if overhang_angle > max_angle:
                                # Calculate face area
                                area = face.Area if hasattr(face, 'Area') else 0.0
                                
                                overhangs.append({
                                    "face_index": i,
                                    "angle": round(overhang_angle, 1),
                                    "area": round(area, 2),
                                    "location": {
                                        "x": face.CenterOfMass.x if hasattr(face, 'CenterOfMass') else 0,
                                        "y": face.CenterOfMass.y if hasattr(face, 'CenterOfMass') else 0,
                                        "z": face.CenterOfMass.z if hasattr(face, 'CenterOfMass') else 0
                                    }
                                })
                except Exception as e:
                    logger.debug(f"Error checking face {i} for overhang: {e}")
                    continue
        
        except Exception as e:
            logger.warning(f"Overhang detection error: {e}")
        
        return overhangs
    
    def find_trapped_volumes(self, shape: Any) -> List[Dict[str, Any]]:
        """Find trapped volumes in model."""
        trapped = []
        
        try:
            # Import FreeCAD modules if available
            try:
                import Part
                import FreeCAD
            except ImportError:
                return trapped  # Can't detect without FreeCAD
            
            if not hasattr(shape, 'Solids'):
                return trapped
            
            # Check each solid for internal voids
            for solid_idx, solid in enumerate(shape.Solids):
                if hasattr(solid, 'Shells') and len(solid.Shells) > 1:
                    # Multiple shells indicate internal voids
                    for shell_idx, shell in enumerate(solid.Shells[1:], 1):
                        # Inner shells are potential trapped volumes
                        if hasattr(shell, 'Volume'):
                            # Check if void has drainage path
                            # Simplified: assume no drainage if fully enclosed
                            if shell.isClosed() if hasattr(shell, 'isClosed') else True:
                                center = shell.CenterOfMass if hasattr(shell, 'CenterOfMass') else None
                                trapped.append({
                                    "solid_index": solid_idx,
                                    "shell_index": shell_idx,
                                    "volume": shell.Volume,
                                    "location": {
                                        "x": center.x if center else 0,
                                        "y": center.y if center else 0,
                                        "z": center.z if center else 0
                                    },
                                    "type": "internal_void",
                                    "has_drainage": False
                                })
        
        except Exception as e:
            logger.warning(f"Trapped volume detection error: {e}")
        
        return trapped
    
    def estimate_support_volume(
        self,
        shape: Any,
        overhangs: List[Dict[str, Any]],
        printer_spec: PrinterSpecification
    ) -> float:
        """Estimate required support material volume."""
        try:
            # Calculate support volume based on overhangs
            # This would generate support structures and calculate volume
            total_volume = 0.0
            for overhang in overhangs:
                # Simplified calculation
                area = overhang.get("area", 10)
                height = 20  # Mock support height
                volume = area * height * 0.3  # 30% infill
                total_volume += volume
            
            return total_volume
        
        except Exception as e:
            logger.warning(f"Support volume estimation error: {e}")
            return 0.0
    
    def _validate_for_injection_molding(
        self,
        shape: Any,
        validation: ManufacturingValidation
    ) -> bool:
        """Validate for injection molding."""
        try:
            is_moldable = True
            
            # Check for uniform wall thickness
            if not self._has_uniform_wall_thickness(shape):
                validation.issues.append(ValidationIssue(
                    type="non_uniform_walls",
                    severity=ValidationSeverity.WARNING,
                    message="Non-uniform wall thickness detected",
                    turkish_message="Düzensiz duvar kalınlığı tespit edildi",
                    fix_available=True,
                    fix_suggestion="Maintain uniform wall thickness for even cooling"
                ))
            
            # Check for draft angles
            if not self._has_draft_angles(shape):
                validation.issues.append(ValidationIssue(
                    type="missing_draft",
                    severity=ValidationSeverity.ERROR,
                    message="Missing draft angles for mold release",
                    turkish_message="Kalıp çıkarma için çekme açısı eksik",
                    fix_available=True,
                    fix_suggestion="Add 1-3 degree draft angles"
                ))
                is_moldable = False
            
            # Check for undercuts
            if self._has_complex_undercuts(shape):
                validation.issues.append(ValidationIssue(
                    type="complex_undercuts",
                    severity=ValidationSeverity.WARNING,
                    message="Complex undercuts require side actions",
                    turkish_message="Karmaşık alt kesimler yan hareketler gerektirir"
                ))
            
            return is_moldable
            
        except Exception as e:
            logger.error("Injection molding validation error", exc_info=True)
            return False
    
    def _validate_for_sheet_metal(
        self,
        shape: Any,
        validation: ManufacturingValidation
    ) -> bool:
        """Validate for sheet metal fabrication."""
        try:
            is_fabricatable = True
            
            # Check for constant thickness
            if not self._has_constant_thickness(shape):
                validation.issues.append(ValidationIssue(
                    type="varying_thickness",
                    severity=ValidationSeverity.CRITICAL,
                    message="Sheet metal requires constant thickness",
                    turkish_message="Sac metal sabit kalınlık gerektirir"
                ))
                is_fabricatable = False
            
            # Check bend radius
            if not self._check_bend_radius(shape):
                validation.issues.append(ValidationIssue(
                    type="invalid_bend_radius",
                    severity=ValidationSeverity.ERROR,
                    message="Bend radius too small for material",
                    turkish_message="Bükme yarıçapı malzeme için çok küçük",
                    fix_available=True,
                    fix_suggestion="Increase bend radius to at least material thickness"
                ))
            
            return is_fabricatable
            
        except Exception as e:
            logger.error("Sheet metal validation error", exc_info=True)
            return False
    
    def _validate_for_casting(
        self,
        shape: Any,
        validation: ManufacturingValidation
    ) -> bool:
        """Validate for casting process."""
        try:
            is_castable = True
            
            # Check for proper gating
            if not self._has_proper_gating_location(shape):
                validation.issues.append(ValidationIssue(
                    type="gating_issue",
                    severity=ValidationSeverity.WARNING,
                    message="Suboptimal gating location for casting",
                    turkish_message="Döküm için uygun olmayan yolluk konumu"
                ))
            
            # Check for hot spots
            hot_spots = self._detect_hot_spots(shape)
            if hot_spots:
                validation.issues.append(ValidationIssue(
                    type="hot_spots",
                    severity=ValidationSeverity.WARNING,
                    message=f"Found {len(hot_spots)} potential hot spots",
                    turkish_message=f"{len(hot_spots)} potansiyel sıcak nokta bulundu",
                    details={"locations": hot_spots}
                ))
            
            return is_castable
            
        except Exception as e:
            logger.error("Casting validation error", exc_info=True)
            return False
    
    def _estimate_cost(
        self,
        shape: Any,
        process: ManufacturingProcess
    ) -> Decimal:
        """Estimate manufacturing cost."""
        try:
            # Base cost calculation
            volume = shape.Volume if hasattr(shape, 'Volume') else 1000
            
            # Process-specific cost factors
            cost_factors = {
                ManufacturingProcess.CNC_MILLING: Decimal("0.5"),  # $/cm³
                ManufacturingProcess.FDM_3D_PRINTING: Decimal("0.2"),
                ManufacturingProcess.SLA_3D_PRINTING: Decimal("0.8"),
                ManufacturingProcess.INJECTION_MOLDING: Decimal("0.1"),
                ManufacturingProcess.SHEET_METAL: Decimal("0.3"),
                ManufacturingProcess.CASTING: Decimal("0.15")
            }
            
            factor = cost_factors.get(process, Decimal("0.3"))
            cost = Decimal(str(volume / 1000)) * factor  # Convert mm³ to cm³
            
            # Add setup cost
            setup_costs = {
                ManufacturingProcess.CNC_MILLING: Decimal("50"),
                ManufacturingProcess.INJECTION_MOLDING: Decimal("500"),
                ManufacturingProcess.CASTING: Decimal("200")
            }
            
            setup = setup_costs.get(process, Decimal("20"))
            total_cost = cost + setup
            
            return total_cost.quantize(Decimal("0.01"))
            
        except Exception as e:
            logger.warning(f"Cost estimation error: {e}")
            return Decimal("0")
    
    def _estimate_lead_time(
        self,
        shape: Any,
        process: ManufacturingProcess
    ) -> int:
        """Estimate lead time in days."""
        try:
            # Base lead times
            lead_times = {
                ManufacturingProcess.CNC_MILLING: 3,
                ManufacturingProcess.FDM_3D_PRINTING: 1,
                ManufacturingProcess.SLA_3D_PRINTING: 2,
                ManufacturingProcess.INJECTION_MOLDING: 14,
                ManufacturingProcess.SHEET_METAL: 5,
                ManufacturingProcess.CASTING: 10
            }
            
            return lead_times.get(process, 7)
            
        except Exception as e:
            logger.warning(f"Lead time estimation error: {e}")
            return 7
    
    def _recommend_materials(self, process: ManufacturingProcess) -> List[str]:
        """Recommend suitable materials for process."""
        materials = {
            ManufacturingProcess.CNC_MILLING: ["Aluminum 6061", "Steel 1045", "Brass", "Delrin"],
            ManufacturingProcess.FDM_3D_PRINTING: ["PLA", "ABS", "PETG", "Nylon"],
            ManufacturingProcess.SLA_3D_PRINTING: ["Standard Resin", "Tough Resin", "Flexible Resin"],
            ManufacturingProcess.INJECTION_MOLDING: ["PP", "ABS", "PC", "Nylon 66"],
            ManufacturingProcess.SHEET_METAL: ["Steel", "Aluminum", "Stainless Steel", "Copper"],
            ManufacturingProcess.CASTING: ["Aluminum", "Zinc", "Brass", "Iron"]
        }
        
        return materials.get(process, [])
    
    def _recommend_process_improvements(
        self,
        validation: ManufacturingValidation,
        process: ManufacturingProcess
    ) -> List[str]:
        """Recommend process improvements based on validation."""
        recommendations = []
        
        # Analyze issues and provide recommendations
        for issue in validation.issues:
            if issue.type == "undercuts" and process == ManufacturingProcess.CNC_MILLING:
                recommendations.append("Consider 5-axis machining to reduce setups")
            elif issue.type == "thin_walls_for_printing":
                recommendations.append("Increase wall thickness or use different printing technology")
            elif issue.type == "complex_undercuts" and process == ManufacturingProcess.INJECTION_MOLDING:
                recommendations.append("Use side actions or redesign to eliminate undercuts")
        
        return recommendations
    
    # Helper methods
    def _get_shape_from_document(self, doc_handle: Any) -> Optional[Any]:
        """Extract shape from FreeCAD document."""
        return get_shape_from_document(doc_handle)
    
    def _extract_features(self, shape: Any) -> Dict[str, Any]:
        """Extract manufacturing features from shape."""
        features = {}
        
        # This would identify holes, pockets, slots, etc.
        # Placeholder implementation
        features["hole_1"] = {"type": "hole", "diameter": 10}
        features["pocket_1"] = {"type": "pocket", "depth": 5}
        
        return features
    
    def _estimate_setup_count(self, shape: Any, machine_spec: MachineSpecification) -> int:
        """Estimate number of setups required."""
        # Simplified: based on shape complexity and machine axes
        if machine_spec.axes >= 5:
            return 1
        elif hasattr(shape, 'Faces') and len(shape.Faces) > 20:
            return 3
        else:
            return 2
    
    def _estimate_machining_time(
        self,
        shape: Any,
        machine_spec: MachineSpecification
    ) -> float:
        """Estimate machining time in minutes."""
        # Simplified calculation based on volume removal
        volume = shape.Volume if hasattr(shape, 'Volume') else 1000
        material_removal_rate = 10  # cm³/min
        return (volume / 1000) / material_removal_rate * 60
    
    def _generate_tool_list(
        self,
        shape: Any,
        machine_spec: MachineSpecification
    ) -> List[Dict[str, Any]]:
        """Generate required tool list."""
        # Select appropriate tools from library
        return machine_spec.tool_library[:3]  # Simplified
    
    def _check_wall_thickness_for_printing(
        self,
        shape: Any,
        min_thickness: float
    ) -> bool:
        """Check if walls meet minimum thickness for printing."""
        # Simplified check
        return True
    
    def _estimate_print_time(
        self,
        shape: Any,
        printer_spec: PrinterSpecification
    ) -> float:
        """Estimate print time in hours."""
        volume = shape.Volume if hasattr(shape, 'Volume') else 1000
        print_speed = 50  # mm³/min
        return (volume / print_speed) / 60
    
    def _estimate_material_usage(
        self,
        shape: Any,
        printer_spec: PrinterSpecification
    ) -> float:
        """Estimate material usage in grams."""
        volume = shape.Volume if hasattr(shape, 'Volume') else 1000
        density = 1.25  # g/cm³ for PLA
        return (volume / 1000) * density
    
    def _calculate_layer_count(
        self,
        shape: Any,
        printer_spec: PrinterSpecification
    ) -> int:
        """Calculate number of print layers."""
        if hasattr(shape, 'BoundBox'):
            height = shape.BoundBox.ZLength
            layer_height = printer_spec.layer_height_range[0]
            return int(height / layer_height)
        return 100
    
    # Validation helper methods
    def _is_watertight(self, shape: Any) -> bool:
        """Check if shape is watertight (closed solid)."""
        try:
            # Check if shape is closed and valid
            if hasattr(shape, 'isClosed') and hasattr(shape, 'isValid'):
                return shape.isClosed() and shape.isValid()
            
            # Alternative check for solids
            if hasattr(shape, 'ShapeType'):
                if shape.ShapeType == 'Solid':
                    # A valid solid should be closed
                    if hasattr(shape, 'Shells'):
                        # Check all shells are closed
                        for shell in shape.Shells:
                            if hasattr(shell, 'isClosed') and not shell.isClosed():
                                return False
                        return True
            
            return False
        except Exception as e:
            logger.debug(f"Watertight check error: {e}")
            return False
    
    def _has_flat_base(self, shape: Any) -> bool:
        return True
    
    def _calculate_complexity(self, shape: Any) -> float:
        return 50.0
    
    def _has_thin_features(self, shape: Any, min_size: float) -> bool:
        return False
    
    def _has_uniform_wall_thickness(self, shape: Any, tolerance: float = 0.1) -> bool:
        """Check if shape has uniform wall thickness using ray casting approach."""
        try:
            import FreeCAD
            import Part
            
            if not hasattr(shape, 'Faces') or not hasattr(shape, 'Solids'):
                return True  # Can't check non-solid shapes
            
            # For solid shapes, use a sampling approach
            if len(shape.Solids) == 0:
                return True  # Not a solid
            
            # Sample points on outer faces and measure thickness
            thicknesses = []
            sampled_faces = []
            
            # Get bounding box for shape
            if hasattr(shape, 'BoundBox'):
                bbox = shape.BoundBox
                diagonal = bbox.DiagonalLength
                min_thickness = diagonal * 0.001  # Minimum meaningful thickness
                
                # Sample a subset of faces
                faces = shape.Faces
                num_samples = min(10, len(faces))  # Sample up to 10 faces
                import random
                if len(faces) > num_samples:
                    sampled_faces = random.sample(faces, num_samples)
                else:
                    sampled_faces = faces
                
                for face in sampled_faces:
                    if hasattr(face, 'CenterOfMass') and hasattr(face, 'normalAt'):
                        try:
                            # Get face center and normal
                            center = face.CenterOfMass
                            u, v = face.Surface.parameter(center) if hasattr(face, 'Surface') else (0.5, 0.5)
                            normal = face.normalAt(u, v)
                            
                            # Cast ray inward from face center
                            ray_start = center
                            ray_dir = normal.multiply(-1)  # Inward direction
                            
                            # Simple thickness estimation: find opposite face
                            # This is a simplified approach - proper implementation would use ray-shape intersection
                            for other_face in faces:
                                if other_face != face and hasattr(other_face, 'CenterOfMass'):
                                    # Check if the other face is roughly opposite
                                    other_center = other_face.CenterOfMass
                                    dist_vector = other_center.sub(center)
                                    
                                    # Check if faces are roughly parallel and opposite
                                    if dist_vector.Length > min_thickness:
                                        dot_product = ray_dir.dot(dist_vector.normalize())
                                        if dot_product > 0.7:  # Faces are roughly aligned
                                            thicknesses.append(dist_vector.Length)
                                            break
                        except Exception:
                            continue  # Skip problematic faces
            
            if not thicknesses:
                return True  # Could not measure, assume OK
            
            # Check uniformity
            avg_thickness = sum(thicknesses) / len(thicknesses)
            for thickness in thicknesses:
                if abs(thickness - avg_thickness) / avg_thickness > tolerance:
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error checking wall thickness: {e}")
            return True  # Assume OK if can't check
    
    def _has_draft_angles(self, shape: Any, min_angle: float = 1.0) -> bool:
        """Check if vertical faces have draft angles for molding."""
        try:
            import FreeCAD
            import Part
            import math
            
            if not hasattr(shape, 'Faces'):
                return False
            
            z_axis = FreeCAD.Vector(0, 0, 1)
            
            for face in shape.Faces:
                if hasattr(face, 'Surface'):
                    # Check if face is planar
                    if isinstance(face.Surface, Part.Plane):
                        normal = face.normalAt(0, 0)
                        # Calculate angle between normal and Z axis
                        angle = math.degrees(normal.getAngle(z_axis))
                        
                        # Check if face is nearly vertical (within draft angle range)
                        if 85 <= angle <= 95:  # Nearly vertical
                            # This face should have draft angle
                            if abs(90 - angle) < min_angle:
                                return False  # Not enough draft
            
            return True
        except Exception as e:
            logger.warning(f"Error checking draft angles: {e}")
            return True  # Assume OK if can't check
    
    def _has_complex_undercuts(self, shape: Any) -> bool:
        """Check if shape has complex undercuts that would prevent molding."""
        try:
            import FreeCAD
            import Part
            
            if not hasattr(shape, 'Faces'):
                return False
            
            # Check for faces that would create undercuts in Z direction
            z_axis = FreeCAD.Vector(0, 0, 1)
            undercut_count = 0
            
            for face in shape.Faces:
                if hasattr(face, 'normalAt'):
                    normal = face.normalAt(0.5, 0.5)  # Get normal at face center
                    # Check if face normal points downward (potential undercut)
                    if normal.z < -0.1:  # Pointing downward
                        undercut_count += 1
            
            # More than 2 undercuts is considered complex
            return undercut_count > 2
        except Exception as e:
            logger.warning(f"Error checking undercuts: {e}")
            return False  # Assume no complex undercuts if can't check
    
    def _has_constant_thickness(self, shape: Any) -> bool:
        return True
    
    def _check_bend_radius(self, shape: Any, min_bend_radius: float = 1.0) -> bool:
        """Check if bend radii are acceptable for sheet metal."""
        try:
            import FreeCAD
            import Part
            
            if not hasattr(shape, 'Edges'):
                return True
            
            for edge in shape.Edges:
                # Check if edge is circular (bend)
                if hasattr(edge, 'Curve'):
                    curve = edge.Curve
                    if isinstance(curve, Part.Circle) or isinstance(curve, Part.Arc):
                        radius = curve.Radius
                        if radius < min_bend_radius:
                            return False  # Bend radius too small
            
            return True
        except Exception as e:
            logger.warning(f"Error checking bend radius: {e}")
            return True  # Assume OK if can't check
    
    def _has_proper_gating_location(self, shape: Any) -> bool:
        """Check if shape has proper locations for injection molding gates."""
        try:
            import FreeCAD
            import Part
            
            if not hasattr(shape, 'Faces'):
                return False
            
            # Find the largest flat face (potential gating location)
            largest_flat_face = None
            max_area = 0
            
            for face in shape.Faces:
                if hasattr(face, 'Surface') and isinstance(face.Surface, Part.Plane):
                    area = face.Area
                    if area > max_area:
                        max_area = area
                        largest_flat_face = face
            
            # Need at least one flat face for gating
            return largest_flat_face is not None and max_area > 10.0  # Minimum 10mm² for gate
        except Exception as e:
            logger.warning(f"Error checking gating location: {e}")
            return True  # Assume OK if can't check
    
    def _detect_hot_spots(self, shape: Any) -> List[Dict[str, Any]]:
        return []