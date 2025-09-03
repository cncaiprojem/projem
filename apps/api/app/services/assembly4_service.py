"""Assembly4 Service for FreeCAD-based assembly operations.

This service handles Assembly4-specific operations including:
- Assembly creation and management
- Part positioning and constraints
- CAM path generation with proper cut mode handling
- Export and validation
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
import logging
import json

from app.core.exceptions import ValidationError
from app.services.freecad.a4_assembly import assembly4_manager

logger = logging.getLogger(__name__)

# FreeCAD Path Workbench cut mode mapping
# Based on FreeCAD Path operations terminology
CUT_MODE_MAP = {
    "climb": "Climb",           # Climb milling
    "conventional": "Conventional",  # Conventional milling
    "cw": "CW",                 # Clockwise
    "ccw": "CCW",               # Counter-clockwise
    "inside": "Inside",         # Inside cut
    "outside": "Outside",       # Outside cut
    # Legacy mappings for backward compatibility
    "clockwise": "CW",
    "counterclockwise": "CCW",
    "counter-clockwise": "CCW",
}

# Spindle direction mapping
SPINDLE_DIRECTION_MAP = {
    "forward": "Forward",       # M3 - Standard CW rotation
    "reverse": "Reverse",       # M4 - CCW rotation
    "cw": "Forward",           # Alias for forward
    "ccw": "Reverse",          # Alias for reverse
    "m3": "Forward",           # G-code M3
    "m4": "Reverse",           # G-code M4
}

class Assembly4Service:
    """Service for handling Assembly4 operations in FreeCAD."""
    
    def __init__(self):
        """Initialize the Assembly4 service."""
        self.manager = assembly4_manager
        
    def create_assembly(
        self,
        name: str,
        parts: List[Dict[str, Any]],
        constraints: Optional[List[Dict[str, Any]]] = None,
        cam_settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create an Assembly4 assembly with parts and constraints.
        
        Args:
            name: Name for the assembly
            parts: List of part definitions
            constraints: Optional list of assembly constraints
            cam_settings: Optional CAM/Path operation settings
            
        Returns:
            Dictionary with assembly details and generated paths
            
        Raises:
            ValidationError: If assembly creation fails
        """
        try:
            logger.info(f"Creating Assembly4: {name}")
            
            # Process CAM settings if provided
            if cam_settings:
                cam_settings = self._process_cam_settings(cam_settings)
            
            # Create assembly using the manager
            result = self.manager.create_assembly(
                name=name,
                parts=parts,
                constraints=constraints or [],
                cam_settings=cam_settings
            )
            
            logger.info(f"Assembly4 created successfully: {name}")
            return result
            
        except Exception as e:
            error_msg = f"Assembly4 oluşturma başarısız: {str(e)}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
    
    def _process_cam_settings(self, cam_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Process and validate CAM settings for Path operations.
        
        Args:
            cam_settings: Raw CAM settings from request
            
        Returns:
            Processed CAM settings with proper FreeCAD values
        """
        processed = cam_settings.copy()
        
        # Process cut mode - map to proper FreeCAD values
        if "cut_mode" in processed:
            cut_mode = processed["cut_mode"].lower()
            # Use the mapping dictionary instead of capitalize()
            # This ensures correct FreeCAD Path values
            if cut_mode in CUT_MODE_MAP:
                processed["cut_mode"] = CUT_MODE_MAP[cut_mode]
            else:
                # Default to Climb if not recognized
                logger.warning(f"Unknown cut_mode: {cut_mode}, defaulting to Climb")
                processed["cut_mode"] = "Climb"
        
        # Process spindle direction
        if "spindle_direction" in processed:
            spindle_dir = processed["spindle_direction"].lower()
            if spindle_dir in SPINDLE_DIRECTION_MAP:
                processed["spindle_direction"] = SPINDLE_DIRECTION_MAP[spindle_dir]
            else:
                # Default to Forward (M3)
                logger.warning(f"Unknown spindle_direction: {spindle_dir}, defaulting to Forward")
                processed["spindle_direction"] = "Forward"
        
        # Process cut direction for profile operations
        if "cut_direction" in processed:
            cut_dir = processed["cut_direction"].lower()
            if cut_dir in ["cw", "clockwise"]:
                processed["cut_direction"] = "CW"
            elif cut_dir in ["ccw", "counter-clockwise", "counterclockwise"]:
                processed["cut_direction"] = "CCW"
            else:
                logger.warning(f"Unknown cut_direction: {cut_dir}, keeping as-is")
        
        # Validate feed rates and speeds
        if "feed_rate" in processed:
            try:
                processed["feed_rate"] = float(processed["feed_rate"])
                if processed["feed_rate"] <= 0:
                    raise ValueError("Feed rate must be positive")
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid feed_rate: {e}")
                processed["feed_rate"] = 100.0  # Default feed rate
        
        if "spindle_speed" in processed:
            try:
                processed["spindle_speed"] = float(processed["spindle_speed"])
                if processed["spindle_speed"] <= 0:
                    raise ValueError("Spindle speed must be positive")
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid spindle_speed: {e}")
                processed["spindle_speed"] = 1000.0  # Default spindle speed
        
        return processed
    
    def add_part(
        self,
        assembly_id: str,
        part: Dict[str, Any],
        position: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Add a part to an existing assembly.
        
        Args:
            assembly_id: ID of the assembly
            part: Part definition
            position: Optional position (x, y, z)
            
        Returns:
            Updated assembly information
        """
        try:
            result = self.manager.add_part_to_assembly(
                assembly_id=assembly_id,
                part=part,
                position=position
            )
            return result
        except Exception as e:
            error_msg = f"Parça ekleme başarısız: {str(e)}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
    
    def apply_constraint(
        self,
        assembly_id: str,
        constraint: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply a constraint to assembly parts.
        
        Args:
            assembly_id: ID of the assembly
            constraint: Constraint definition
            
        Returns:
            Updated assembly information
        """
        try:
            # Validate constraint before applying
            if "type" not in constraint:
                raise ValidationError("Constraint type is required")
            
            if "parts" not in constraint or len(constraint["parts"]) < 2:
                raise ValidationError("At least two parts required for constraint")
            
            # Validate imported object shape before accessing
            for part_ref in constraint.get("parts", []):
                if isinstance(part_ref, dict) and "shape" in part_ref:
                    if not self._validate_shape(part_ref["shape"]):
                        logger.warning(f"Invalid shape for part: {part_ref.get('name', 'unknown')}")
            
            result = self.manager.apply_constraint(
                assembly_id=assembly_id,
                constraint=constraint
            )
            return result
        except Exception as e:
            error_msg = f"Kısıt uygulama başarısız: {str(e)}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
    
    def _validate_shape(self, shape: Any) -> bool:
        """Validate that a shape object is valid.
        
        Args:
            shape: Shape object to validate
            
        Returns:
            True if shape is valid, False otherwise
        """
        if shape is None:
            return False
        
        # Check for basic shape properties
        try:
            # In FreeCAD, valid shapes have Volume and Area properties
            if hasattr(shape, "Volume") and hasattr(shape, "Area"):
                return True
        except Exception:
            pass
        
        return False
    
    def _validate_sub_object(self, sub_obj: Any) -> bool:
        """Validate sub-object before accessing Label attribute.
        
        Args:
            sub_obj: Sub-object to validate
            
        Returns:
            True if sub_obj has Label attribute, False otherwise
        """
        if sub_obj is None:
            return False
        
        # Check if sub_obj has Label attribute
        if not hasattr(sub_obj, "Label"):
            logger.warning("Sub-object missing Label attribute")
            return False
        
        return True
    
    def generate_cam_paths(
        self,
        assembly_id: str,
        operation: str,
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate CAM paths for assembly.
        
        Args:
            assembly_id: ID of the assembly
            operation: Type of CAM operation
            settings: CAM operation settings
            
        Returns:
            Generated G-code and path information
        """
        try:
            # Process CAM settings
            processed_settings = self._process_cam_settings(settings)
            
            result = self.manager.generate_paths(
                assembly_id=assembly_id,
                operation=operation,
                settings=processed_settings
            )
            return result
        except Exception as e:
            error_msg = f"CAM yolu oluşturma başarısız: {str(e)}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
    
    def export_assembly(
        self,
        assembly_id: str,
        format: str = "step",
        include_paths: bool = False
    ) -> Path:
        """Export assembly in specified format.
        
        Args:
            assembly_id: ID of the assembly
            format: Export format (step, stl, fcstd)
            include_paths: Whether to include CAM paths
            
        Returns:
            Path to exported file
        """
        try:
            export_path = self.manager.export_assembly(
                assembly_id=assembly_id,
                format=format,
                include_paths=include_paths
            )
            return export_path
        except Exception as e:
            error_msg = f"Assembly dışa aktarma başarısız: {str(e)}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
    
    def get_assembly_info(self, assembly_id: str) -> Dict[str, Any]:
        """Get detailed information about an assembly.
        
        Args:
            assembly_id: ID of the assembly
            
        Returns:
            Assembly details including parts and constraints
        """
        try:
            info = self.manager.get_assembly_info(assembly_id)
            return info
        except Exception as e:
            error_msg = f"Assembly bilgisi alınamadı: {str(e)}"
            logger.error(error_msg)
            raise ValidationError(error_msg)


# Service singleton
assembly4_service = Assembly4Service()