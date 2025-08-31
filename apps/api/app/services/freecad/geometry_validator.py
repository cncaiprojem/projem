"""
Geometry Validator for Task 7.2 and Task 7.6

Validates generated FreeCAD shapes with:
- Shape validity checks (isValid, isClosed, isNull)
- Non-manifold geometry detection
- Manufacturing constraints validation per material/process
- Export format validation
- Min wall thickness by material: aluminum 0.8mm, steel 0.5mm, abs 1.2mm, pla 0.8mm
- Draft angles for injection molding
- Tool accessibility for CNC/milling
- Overhang detection for 3D printing
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)


class ExportFormat(str, Enum):
    """Supported export formats."""
    STEP = "STEP"
    IGES = "IGES"
    BREP = "BREP"
    STL = "STL"
    OBJ = "OBJ"
    FCStd = "FCStd"


class ManufacturingConstraints(BaseModel):
    """Manufacturing constraints for validation."""
    min_wall_thickness: float = Field(default=1.0, description="Minimum wall thickness in mm")
    min_draft_angle: float = Field(default=1.0, description="Minimum draft angle in degrees")
    max_aspect_ratio: float = Field(default=10.0, description="Maximum aspect ratio")
    max_overhang_angle: float = Field(default=45.0, description="Maximum overhang angle for 3D printing")
    tool_access_required: bool = Field(default=True, description="Check for tool accessibility")
    
    def validate_thickness(self, thickness: float) -> Tuple[bool, Optional[str]]:
        """Validate wall thickness."""
        if thickness < self.min_wall_thickness:
            return False, f"Wall thickness {thickness}mm below minimum {self.min_wall_thickness}mm"
        return True, None
    
    def validate_draft(self, angle: float) -> Tuple[bool, Optional[str]]:
        """Validate draft angle."""
        if abs(angle) < self.min_draft_angle:
            return False, f"Draft angle {angle}° below minimum {self.min_draft_angle}°"
        return True, None


class ValidationResult(BaseModel):
    """Geometry validation result."""
    is_valid: bool = Field(description="Overall validity")
    is_closed: bool = Field(description="Whether shape is closed")
    is_null: bool = Field(description="Whether shape is null")
    is_manifold: bool = Field(description="Whether geometry is manifold")
    volume: Optional[float] = Field(default=None, description="Volume in mm³")
    area: Optional[float] = Field(default=None, description="Surface area in mm²")
    center_of_mass: Optional[List[float]] = Field(default=None, description="Center of mass [x, y, z]")
    bounding_box: Optional[Dict[str, float]] = Field(default=None, description="Bounding box dimensions")
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    manufacturing_issues: List[str] = Field(default_factory=list)
    export_formats: List[ExportFormat] = Field(default_factory=list)


class GeometryValidator:
    """Validate FreeCAD geometry for correctness and manufacturability."""
    
    # Material-specific minimum wall thickness (mm)
    WALL_THICKNESS_BY_MATERIAL = {
        "aluminum": 0.8,
        "steel": 0.5,
        "abs": 1.2,
        "pla": 0.8,
        "petg": 1.0,
        "nylon": 1.0,
        "brass": 0.6,
        "copper": 0.6,
    }
    
    # Process-specific draft angles (degrees)
    DRAFT_ANGLE_BY_PROCESS = {
        "injection_molding": {"min": 1.0, "recommended": 2.0},
        "die_casting": {"min": 1.5, "recommended": 3.0},
        "vacuum_forming": {"min": 3.0, "recommended": 5.0},
    }
    
    def __init__(self, constraints: Optional[ManufacturingConstraints] = None):
        """
        Initialize geometry validator.
        
        Args:
            constraints: Manufacturing constraints to apply
        """
        self.constraints = constraints or ManufacturingConstraints()
        self._freecad_available = self._check_freecad()
    
    def _check_freecad(self) -> bool:
        """Check if FreeCAD is available for validation."""
        try:
            import FreeCAD
            return True
        except ImportError:
            logger.warning("FreeCAD not available, using mock validation")
            return False
    
    def validate_shape(self, shape: Any) -> ValidationResult:
        """
        Validate FreeCAD shape object.
        
        Args:
            shape: FreeCAD shape object
            
        Returns:
            Validation result with warnings and errors
        """
        if self._freecad_available:
            return self._validate_real_shape(shape)
        else:
            return self._validate_mock_shape(shape)
    
    def _validate_real_shape(self, shape: Any) -> ValidationResult:
        """Validate real FreeCAD shape."""
        import FreeCAD
        import Part
        
        result = ValidationResult(
            is_valid=True,
            is_closed=False,
            is_null=False,
            is_manifold=True
        )
        
        try:
            # Basic validity checks
            result.is_valid = shape.isValid()
            result.is_closed = shape.isClosed()
            result.is_null = shape.isNull()
            
            if result.is_null:
                result.errors.append("Shape is null (no geometry)")
                result.is_valid = False
                return result
            
            if not result.is_valid:
                result.errors.append("Shape is invalid")
                
                # Try to fix
                try:
                    fixed = shape.fix(0.1, 0.1, 0.1)
                    if fixed.isValid():
                        result.warnings.append("Shape was invalid but has been fixed")
                        shape = fixed
                        result.is_valid = True
                except Exception as e:
                    result.errors.append(f"Failed to fix invalid shape: {e}")
            
            # Check for non-manifold geometry
            if hasattr(shape, 'Shells'):
                for shell in shape.Shells:
                    if not shell.isValid():
                        result.is_manifold = False
                        result.errors.append("Non-manifold geometry detected")
                        break
            
            # Calculate properties
            try:
                if shape.Volume > 0:
                    result.volume = shape.Volume
                else:
                    result.warnings.append("Shape has zero or negative volume")
                
                result.area = shape.Area
                
                if hasattr(shape, 'CenterOfMass'):
                    com = shape.CenterOfMass
                    result.center_of_mass = [com.x, com.y, com.z]
                
                # Bounding box
                bbox = shape.BoundBox
                result.bounding_box = {
                    "x_min": bbox.XMin,
                    "x_max": bbox.XMax,
                    "y_min": bbox.YMin,
                    "y_max": bbox.YMax,
                    "z_min": bbox.ZMin,
                    "z_max": bbox.ZMax,
                    "length": bbox.XLength,
                    "width": bbox.YLength,
                    "height": bbox.ZLength
                }
                
                # Check aspect ratio
                max_dim = max(bbox.XLength, bbox.YLength, bbox.ZLength)
                min_dim = min(
                    (d for d in [bbox.XLength, bbox.YLength, bbox.ZLength] 
                    if d > 0.01),
                    default=0.0
                )
                if min_dim > 0:
                    aspect_ratio = max_dim / min_dim
                    if aspect_ratio > self.constraints.max_aspect_ratio:
                        result.manufacturing_issues.append(
                            f"Aspect ratio {aspect_ratio:.1f} exceeds maximum {self.constraints.max_aspect_ratio}"
                        )
                
            except Exception as e:
                result.warnings.append(f"Could not calculate properties: {e}")
            
            # Manufacturing constraints validation
            if result.is_valid and result.is_closed:
                self._validate_manufacturing_constraints(shape, result)
            
            # Export format validation
            result.export_formats = self._get_valid_export_formats(shape)
            
        except Exception as e:
            logger.error(f"Shape validation failed: {e}")
            result.errors.append(f"Validation error: {e}")
            result.is_valid = False
        
        return result
    
    def _validate_mock_shape(self, shape: Any) -> ValidationResult:
        """Raise exception when FreeCAD is not available for validation.
        
        This method ensures data integrity by preventing the use of mock data
        in production environments where FreeCAD is not installed.
        
        Args:
            shape: The shape object that requires validation
            
        Raises:
            RuntimeError: Always raises as FreeCAD is required for proper validation
        """
        logger.error("FreeCAD is required for geometry validation but is not available")
        raise RuntimeError(
            "FreeCAD is required for geometry validation but is not installed or available. "
            "Please ensure FreeCAD is properly installed in the container/environment."
        )
    
    def _validate_manufacturing_constraints(self, shape: Any, result: ValidationResult):
        """Validate manufacturing constraints on shape."""
        try:
            import Part
            
            # Check wall thickness using improved method
            if hasattr(shape, 'Faces') and len(shape.Faces) > 1:
                try:
                    # Use distToShape() for accurate wall thickness measurement
                    # This method finds the minimum distance between faces
                    min_thickness = float('inf')
                    
                    # Compare pairs of faces to find minimum thickness
                    faces = list(shape.Faces)
                    for i, face1 in enumerate(faces[:-1]):
                        for face2 in faces[i+1:]:
                            try:
                                # distToShape returns (distance, list_of_solutions, ...)
                                # We only need the distance value
                                dist_result = face1.distToShape(face2)
                                if isinstance(dist_result, tuple) and len(dist_result) > 0:
                                    distance = dist_result[0]
                                    if distance < min_thickness and distance > 0:
                                        min_thickness = distance
                            except Exception as e:
                                logger.debug(f"Could not compute distance between faces: {e}")
                    
                    # Validate the minimum thickness found
                    if min_thickness != float('inf'):
                        is_valid, error_msg = self.constraints.validate_thickness(min_thickness)
                        if not is_valid:
                            result.manufacturing_issues.append(error_msg)
                    else:
                        # Fallback to simplified method if distToShape fails
                        for face in shape.Faces:
                            if face.Area > 0 and hasattr(face, 'Length'):
                                approx_thickness = face.Area / face.Length
                                is_valid, error_msg = self.constraints.validate_thickness(approx_thickness)
                                if not is_valid:
                                    result.manufacturing_issues.append(error_msg)
                                    break  # Report first violation only to avoid spam
                                    
                except Exception as e:
                    logger.warning(f"Wall thickness check failed, using fallback: {e}")
                    # Fallback to area/perimeter ratio method
                    for face in shape.Faces:
                        if face.Area > 0 and hasattr(face, 'Length'):
                            approx_thickness = face.Area / face.Length
                            is_valid, error_msg = self.constraints.validate_thickness(approx_thickness)
                            if not is_valid:
                                result.manufacturing_issues.append(error_msg)
                                break
            
            # Check draft angles for vertical faces
            if hasattr(shape, 'Faces'):
                for face in shape.Faces:
                    try:
                        # Get face normal
                        if hasattr(face, 'normalAt'):
                            normal = face.normalAt(0, 0)
                            # Check if face is nearly vertical
                            z_component = abs(normal.z)
                            if z_component < 0.1:  # Nearly vertical
                                # Calculate draft angle from vertical
                                angle = math.degrees(math.asin(z_component))
                                is_valid, error_msg = self.constraints.validate_draft(angle)
                                if not is_valid:
                                    result.manufacturing_issues.append(error_msg)
                    except Exception as e:
                        logger.debug(f"Could not check draft angle: {e}")
            
            # Check for undercuts/overhangs (for 3D printing)
            if hasattr(shape, 'Faces'):
                for face in shape.Faces:
                    try:
                        if hasattr(face, 'normalAt'):
                            normal = face.normalAt(0, 0)
                            # Check downward-facing surfaces
                            if normal.z < 0:
                                overhang_angle = math.degrees(math.acos(abs(normal.z)))
                                if overhang_angle > self.constraints.max_overhang_angle:
                                    result.manufacturing_issues.append(
                                        f"Overhang angle {overhang_angle:.1f}° exceeds maximum {self.constraints.max_overhang_angle}°"
                                    )
                    except Exception as e:
                        logger.debug(f"Could not check overhang: {e}")
            
            # Tool access check (simplified)
            if self.constraints.tool_access_required:
                # Check for deep pockets or internal features
                if result.bounding_box:
                    bbox = result.bounding_box
                    depth = bbox.get("height", 0)
                    width = min(bbox.get("length", 100), bbox.get("width", 100))
                    if width > 0 and depth / width > 5:
                        result.manufacturing_issues.append(
                            f"Deep feature detected (depth/width = {depth/width:.1f}), may have tool access issues"
                        )
            
        except Exception as e:
            logger.error(f"Manufacturing constraints validation failed: {e}")
            result.warnings.append(f"Could not validate manufacturing constraints: {e}")
    
    def _get_valid_export_formats(self, shape: Any) -> List[ExportFormat]:
        """Determine valid export formats for shape."""
        formats = []
        
        # Basic formats always supported for valid shapes
        if hasattr(shape, 'isValid') and shape.isValid():
            formats.extend([
                ExportFormat.STEP,
                ExportFormat.IGES,
                ExportFormat.BREP,
                ExportFormat.FCStd
            ])
            
            # STL requires closed shape
            if hasattr(shape, 'isClosed') and shape.isClosed():
                formats.append(ExportFormat.STL)
                formats.append(ExportFormat.OBJ)
        
        return formats
    
    def validate_for_export(
        self,
        shape: Any,
        format: ExportFormat
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate shape for specific export format.
        
        Args:
            shape: FreeCAD shape
            format: Target export format
            
        Returns:
            (is_valid, error_message)
        """
        # First do general validation
        result = self.validate_shape(shape)
        
        if not result.is_valid:
            return False, "Shape is not valid for export"
        
        # Format-specific validation
        if format in [ExportFormat.STL, ExportFormat.OBJ]:
            if not result.is_closed:
                return False, f"{format} requires closed solid geometry"
            if not result.is_manifold:
                return False, f"{format} requires manifold geometry"
        
        elif format == ExportFormat.STEP:
            # STEP is more tolerant but still needs valid geometry
            if result.is_null:
                return False, "Cannot export null geometry to STEP"
        
        elif format == ExportFormat.IGES:
            # IGES is also tolerant
            if result.is_null:
                return False, "Cannot export null geometry to IGES"
        
        elif format == ExportFormat.BREP:
            # BREP is FreeCAD native, very tolerant
            pass
        
        elif format == ExportFormat.FCStd:
            # Native format, always works if shape exists
            pass
        
        else:
            return False, f"Unknown export format: {format}"
        
        return True, None
    
    def validate_manufacturability(
        self,
        shape: Any,
        material: str,
        process: str
    ) -> Dict[str, Any]:
        """
        Validate shape manufacturability for specific material and process.
        Task 7.6 requirement.
        
        Args:
            shape: FreeCAD shape object
            material: Material name (e.g., "aluminum", "steel", "abs", "pla")
            process: Manufacturing process (e.g., "milling", "injection_molding", "3d_printing")
            
        Returns:
            Dictionary with valid flag, warnings, and errors
        """
        result = {
            "valid": True,
            "warnings": [],
            "errors": []
        }
        
        # Normalize inputs
        material_lower = material.lower()
        process_lower = process.lower()
        
        # Get material-specific constraints
        min_wall = self.WALL_THICKNESS_BY_MATERIAL.get(material_lower, 1.0)
        
        # Basic shape validation first
        validation = self.validate_shape(shape)
        if not validation.is_valid:
            result["valid"] = False
            result["errors"].extend(validation.errors)
            return result
        
        try:
            import Part
            
            # Wall thickness check with material-specific limits
            if hasattr(shape, 'Faces') and len(shape.Faces) > 1:
                min_thickness = self._measure_min_wall_thickness(shape)
                if min_thickness < min_wall:
                    result["errors"].append(
                        f"Min wall thickness {min_thickness:.2f}mm < {min_wall}mm required for {material}"
                    )
                    result["valid"] = False
            
            # Process-specific checks
            if process_lower == "injection_molding":
                # Check draft angles
                draft_spec = self.DRAFT_ANGLE_BY_PROCESS.get("injection_molding", {})
                min_draft = draft_spec.get("min", 1.0)
                recommended_draft = draft_spec.get("recommended", 2.0)
                
                draft_issues = self._check_draft_angles(shape, min_draft, recommended_draft)
                if draft_issues["errors"]:
                    result["errors"].extend(draft_issues["errors"])
                    result["valid"] = False
                result["warnings"].extend(draft_issues["warnings"])
                
            elif process_lower in ["milling", "cnc"]:
                # Tool accessibility check
                access_issues = self._check_tool_accessibility(shape)
                if access_issues["errors"]:
                    result["errors"].extend(access_issues["errors"])
                    result["valid"] = False
                result["warnings"].extend(access_issues["warnings"])
                
                # Check for minimum internal fillet radius
                min_fillet = 0.5  # mm, typical for small end mills
                fillet_issues = self._check_internal_fillets(shape, min_fillet)
                result["warnings"].extend(fillet_issues)
                
            elif process_lower == "3d_printing":
                # Overhang detection
                max_overhang = 45.0  # degrees
                overhang_issues = self._check_overhangs(shape, max_overhang)
                if overhang_issues:
                    result["warnings"].append(f"Overhangs > {max_overhang}° detected, supports needed")
                
                # Bridge detection
                max_bridge = 10.0  # mm
                bridge_issues = self._check_bridges(shape, max_bridge)
                if bridge_issues:
                    result["warnings"].append(f"Bridges > {max_bridge}mm detected, may sag")
                
        except Exception as e:
            logger.error(f"Manufacturability validation failed: {e}")
            result["errors"].append(f"Validation error: {str(e)}")
            result["valid"] = False
        
        return result
    
    def _measure_min_wall_thickness(self, shape: Any) -> float:
        """Measure minimum wall thickness using face-to-face distance."""
        min_thickness = float('inf')
        
        try:
            faces = list(shape.Faces)
            for i, face1 in enumerate(faces[:-1]):
                for face2 in faces[i+1:]:
                    try:
                        dist_result = face1.distToShape(face2)
                        if isinstance(dist_result, tuple) and len(dist_result) > 0:
                            distance = dist_result[0]
                            if 0 < distance < min_thickness:
                                min_thickness = distance
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Wall thickness measurement error: {e}")
        
        return min_thickness if min_thickness != float('inf') else 0.0
    
    def _check_draft_angles(self, shape: Any, min_angle: float, recommended: float) -> Dict[str, List[str]]:
        """Check draft angles for injection molding."""
        result = {"errors": [], "warnings": []}
        
        try:
            import FreeCAD
            
            for face in shape.Faces:
                if hasattr(face, 'normalAt'):
                    # Sample multiple points on face
                    u_min, u_max, v_min, v_max = face.ParameterRange
                    for u in [u_min, (u_min + u_max) / 2, u_max]:
                        for v in [v_min, (v_min + v_max) / 2, v_max]:
                            try:
                                normal = face.normalAt(u, v)
                                # Check if face is nearly vertical
                                z_component = abs(normal.z)
                                if z_component < 0.1:  # Nearly vertical
                                    angle = math.degrees(math.asin(z_component))
                                    if angle < min_angle:
                                        result["errors"].append(
                                            f"Face with draft angle {angle:.1f}° < minimum {min_angle}°"
                                        )
                                    elif angle < recommended:
                                        result["warnings"].append(
                                            f"Face with draft angle {angle:.1f}° < recommended {recommended}°"
                                        )
                            except Exception:
                                pass
        except Exception as e:
            logger.debug(f"Draft angle check error: {e}")
        
        return result
    
    def _check_tool_accessibility(self, shape: Any) -> Dict[str, List[str]]:
        """
        Check tool accessibility for CNC operations.
        
        Note: This is a basic implementation that only checks accessibility
        along the Z-axis for 3-axis milling operations. It detects deep pockets
        and undercuts by analyzing the depth-to-width ratio of features.
        
        For full 5-axis accessibility analysis, more sophisticated algorithms
        would be needed to check approach angles from multiple directions.
        """
        result = {"errors": [], "warnings": []}
        
        try:
            # Basic approach: check along ±Z axis for 3-axis mill
            bbox = shape.BoundBox
            
            # Ray test from top and bottom
            for face in shape.Faces:
                # Check if face is in a deep pocket
                face_bbox = face.BoundBox
                depth_from_top = bbox.ZMax - face_bbox.ZMax
                depth_from_bottom = face_bbox.ZMin - bbox.ZMin
                
                min_opening = min(face_bbox.XLength, face_bbox.YLength)
                
                if min_opening > 0:
                    if depth_from_top / min_opening > 5:
                        result["warnings"].append(
                            f"Deep pocket detected (depth/width = {depth_from_top/min_opening:.1f})"
                        )
                    if depth_from_bottom / min_opening > 5:
                        result["warnings"].append(
                            f"Deep undercut detected (depth/width = {depth_from_bottom/min_opening:.1f})"
                        )
        except Exception as e:
            logger.debug(f"Tool accessibility check error: {e}")
        
        return result
    
    def _check_internal_fillets(self, shape: Any, min_radius: float) -> List[str]:
        """Check for minimum internal fillet radius."""
        warnings = []
        
        try:
            # Check edges for sharp internal corners
            for edge in shape.Edges:
                if hasattr(edge, 'Curve'):
                    # Skip if already filleted (circular arc)
                    if edge.Curve.__class__.__name__ == 'Circle':
                        if edge.Curve.Radius < min_radius:
                            warnings.append(
                                f"Internal fillet radius {edge.Curve.Radius:.2f}mm < tool radius {min_radius}mm"
                            )
        except Exception as e:
            logger.debug(f"Fillet check error: {e}")
        
        return warnings
    
    def _check_overhangs(self, shape: Any, max_angle: float) -> List[str]:
        """Check for overhangs that need support in 3D printing."""
        issues = []
        
        try:
            for face in shape.Faces:
                if hasattr(face, 'normalAt'):
                    u_min, u_max, v_min, v_max = face.ParameterRange
                    normal = face.normalAt((u_min + u_max) / 2, (v_min + v_max) / 2)
                    
                    # Check downward-facing surfaces
                    if normal.z < 0:
                        overhang_angle = math.degrees(math.acos(abs(normal.z)))
                        if overhang_angle > max_angle:
                            issues.append(f"Overhang at {overhang_angle:.1f}°")
        except Exception as e:
            logger.debug(f"Overhang check error: {e}")
        
        return issues
    
    def _check_bridges(self, shape: Any, max_length: float) -> List[str]:
        """Check for unsupported bridges in 3D printing."""
        issues = []
        
        try:
            # Simplified: check horizontal edges
            for edge in shape.Edges:
                if hasattr(edge, 'Length'):
                    # Check if edge is horizontal
                    v1 = edge.Vertexes[0].Point
                    v2 = edge.Vertexes[-1].Point
                    if abs(v1.z - v2.z) < 0.1:  # Nearly horizontal
                        if edge.Length > max_length:
                            issues.append(f"Bridge length {edge.Length:.1f}mm")
        except Exception as e:
            logger.debug(f"Bridge check error: {e}")
        
        return issues