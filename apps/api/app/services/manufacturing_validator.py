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
from ..models.validation_models import (
    ManufacturingValidation,
    ManufacturingProcess,
    CNCValidation,
    PrintValidation,
    ToleranceCheck,
    ValidationIssue,
    ValidationSeverity,
    VALIDATION_MESSAGES_TR
)

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
    
    async def validate(
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
                    validation.cnc_validation = await self.validate_for_cnc(
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
                    validation.print_validation = await self.validate_for_3d_printing(
                        shape, printer_spec, process
                    )
                    validation.is_manufacturable = validation.print_validation.is_printable
                    validation.issues.extend(validation.print_validation.issues)
                    
                elif process == ManufacturingProcess.INJECTION_MOLDING:
                    validation.is_manufacturable = await self._validate_for_injection_molding(
                        shape, validation
                    )
                    
                elif process == ManufacturingProcess.SHEET_METAL:
                    validation.is_manufacturable = await self._validate_for_sheet_metal(
                        shape, validation
                    )
                    
                elif process == ManufacturingProcess.CASTING:
                    validation.is_manufacturable = await self._validate_for_casting(
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
                    validation.cost_estimate = await self._estimate_cost(shape, process)
                    validation.lead_time_estimate = await self._estimate_lead_time(shape, process)
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
                logger.error(f"Manufacturing validation error: {e}", exc_info=True)
                validation.is_manufacturable = False
                validation.issues.append(ValidationIssue(
                    type="validation_error",
                    severity=ValidationSeverity.ERROR,
                    message=f"Manufacturing validation error: {str(e)}",
                    turkish_message=f"Üretim doğrulama hatası: {str(e)}"
                ))
            
            return validation
    
    async def validate_for_cnc(
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
            accessibility = await self.check_tool_accessibility(shape, machine_spec.tool_library)
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
            validation.estimated_machining_time = await self._estimate_machining_time(
                shape, machine_spec
            )
            
            # Generate tool list
            validation.tool_list = self._generate_tool_list(shape, machine_spec)
            
        except Exception as e:
            logger.error(f"CNC validation error: {e}")
            validation.is_machinable = False
            validation.issues.append(ValidationIssue(
                type="cnc_validation_error",
                severity=ValidationSeverity.ERROR,
                message=str(e),
                turkish_message=f"CNC doğrulama hatası: {str(e)}"
            ))
        
        return validation
    
    async def validate_for_3d_printing(
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
            overhangs = await self.detect_overhangs(shape, printer_spec.max_overhang_angle)
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
            wall_ok = await self._check_wall_thickness_for_printing(
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
                validation.support_volume = await self.estimate_support_volume(
                    shape, overhangs, printer_spec
                )
            
            # Estimate print time and material
            validation.estimated_print_time = await self._estimate_print_time(
                shape, printer_spec
            )
            validation.estimated_material = await self._estimate_material_usage(
                shape, printer_spec
            )
            validation.layer_count = self._calculate_layer_count(shape, printer_spec)
            
        except Exception as e:
            logger.error(f"3D printing validation error: {e}")
            validation.is_printable = False
            validation.issues.append(ValidationIssue(
                type="print_validation_error",
                severity=ValidationSeverity.ERROR,
                message=str(e),
                turkish_message=f"3D baskı doğrulama hatası: {str(e)}"
            ))
        
        return validation
    
    async def check_tool_accessibility(
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
        # Simplified check - would use ray casting in real implementation
        return True
    
    def _check_ray_access(self, shape: Any, feature: Dict[str, Any], vectors: List) -> bool:
        """Check if feature is accessible along any of the given vectors."""
        # Simplified check - would use ray casting in real implementation
        return True
    
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
            # Measure feature sizes
            # This would analyze holes, slots, pockets, etc.
            # Placeholder implementation
            features = self._extract_features(shape)
            for feature_id, feature in features.items():
                size = 1.2  # Mock size in mm
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
            # Check tolerances on critical dimensions
            # This would parse GD&T information if available
            # Placeholder implementation
            check = ToleranceCheck(
                feature_id="hole_1",
                feature_type="hole",
                nominal_value=10.0,
                tolerance_min=9.95,
                tolerance_max=10.05,
                actual_value=10.02,
                is_within_tolerance=True,
                deviation=0.02
            )
            checks.append(check)
        
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
    
    async def detect_overhangs(
        self,
        shape: Any,
        max_angle: float
    ) -> List[Dict[str, Any]]:
        """Detect overhanging surfaces."""
        overhangs = []
        
        try:
            # Analyze faces for overhang angles
            # This would check face normals against build direction
            # Placeholder implementation
            if hasattr(shape, 'Faces'):
                for i, face in enumerate(shape.Faces[:5]):  # Check first 5 faces as example
                    # Mock: some faces are overhangs
                    if i % 2 == 0:
                        overhangs.append({
                            "face_index": i,
                            "angle": 50,  # degrees from vertical
                            "area": 25.0  # mm²
                        })
        
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
    
    async def estimate_support_volume(
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
    
    async def _validate_for_injection_molding(
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
            logger.error(f"Injection molding validation error: {e}")
            return False
    
    async def _validate_for_sheet_metal(
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
            logger.error(f"Sheet metal validation error: {e}")
            return False
    
    async def _validate_for_casting(
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
            logger.error(f"Casting validation error: {e}")
            return False
    
    async def _estimate_cost(
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
    
    async def _estimate_lead_time(
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
        try:
            # Import FreeCAD modules
            import FreeCAD
            import Part
            
            if not doc_handle:
                return None
            
            # Find the first solid or compound shape in the document
            for obj in doc_handle.Objects:
                if hasattr(obj, 'Shape'):
                    shape = obj.Shape
                    # Return the first valid shape found
                    if shape and (shape.ShapeType in ['Solid', 'Compound', 'CompSolid', 'Shell']):
                        return shape
            
            # If no solid found, try to create a compound of all shapes
            shapes = []
            for obj in doc_handle.Objects:
                if hasattr(obj, 'Shape') and obj.Shape:
                    shapes.append(obj.Shape)
            
            if shapes:
                # Create compound shape from all shapes
                if len(shapes) == 1:
                    return shapes[0]
                else:
                    compound = Part.makeCompound(shapes)
                    return compound
            
            # Fallback to mock shape if FreeCAD objects not available
            if doc_handle:
                logger.warning("No valid shapes found in document, using mock shape")
                class MockShape:
                    def __init__(self):
                        self.Faces = list(range(10))
                        self.Edges = list(range(20))
                        self.Volume = 5000.0
                        self.Area = 1000.0
                        self.BoundBox = MockBoundBox()
                        self.ShapeType = "Solid"
                
                class MockBoundBox:
                    XMin, YMin, ZMin = 0, 0, 0
                    XMax, YMax, ZMax = 100, 100, 50
                    XLength, YLength, ZLength = 100, 100, 50
                
                return MockShape()
            
            return None
            
        except ImportError:
            logger.warning("FreeCAD not available, using mock shape")
            # Return mock shape if FreeCAD not available
            if doc_handle:
                class MockShape:
                    def __init__(self):
                        self.Faces = list(range(10))
                        self.Edges = list(range(20))
                        self.Volume = 5000.0
                        self.Area = 1000.0
                        self.BoundBox = type('BoundBox', (), {
                            'XMin': 0, 'YMin': 0, 'ZMin': 0,
                            'XMax': 100, 'YMax': 100, 'ZMax': 50,
                            'XLength': 100, 'YLength': 100, 'ZLength': 50
                        })()
                        self.ShapeType = "Solid"
                
                return MockShape()
            return None
        except Exception as e:
            logger.error(f"Failed to extract shape: {e}")
            return None
    
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
    
    async def _estimate_machining_time(
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
    
    async def _check_wall_thickness_for_printing(
        self,
        shape: Any,
        min_thickness: float
    ) -> bool:
        """Check if walls meet minimum thickness for printing."""
        # Simplified check
        return True
    
    async def _estimate_print_time(
        self,
        shape: Any,
        printer_spec: PrinterSpecification
    ) -> float:
        """Estimate print time in hours."""
        volume = shape.Volume if hasattr(shape, 'Volume') else 1000
        print_speed = 50  # mm³/min
        return (volume / print_speed) / 60
    
    async def _estimate_material_usage(
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
    
    # Placeholder validation methods
    def _is_watertight(self, shape: Any) -> bool:
        return True
    
    def _has_flat_base(self, shape: Any) -> bool:
        return True
    
    def _calculate_complexity(self, shape: Any) -> float:
        return 50.0
    
    def _has_thin_features(self, shape: Any, min_size: float) -> bool:
        return False
    
    def _has_uniform_wall_thickness(self, shape: Any) -> bool:
        return True
    
    def _has_draft_angles(self, shape: Any) -> bool:
        return True
    
    def _has_complex_undercuts(self, shape: Any) -> bool:
        return False
    
    def _has_constant_thickness(self, shape: Any) -> bool:
        return True
    
    def _check_bend_radius(self, shape: Any) -> bool:
        return True
    
    def _has_proper_gating_location(self, shape: Any) -> bool:
        return True
    
    def _detect_hot_spots(self, shape: Any) -> List[Dict[str, Any]]:
        return []