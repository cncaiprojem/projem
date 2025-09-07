"""
Task 7.18: Security Validator Service

Comprehensive input validation for FreeCAD operations including:
- Path traversal prevention
- Document property sanitization
- Material/Assembly4 validation
- OCCT geometry bounds checking
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, ConfigDict

from ..core.constants import FREECAD_VERSION, OCCT_VERSION
from ..core.logging import get_logger
from ..core.security_config import GeometryLimits, get_security_config

logger = get_logger(__name__)


class ValidationResult(BaseModel):
    """Result of a validation check."""
    model_config = ConfigDict(validate_assignment=True)
    
    is_valid: bool = Field(description="Whether validation passed")
    errors: List[str] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    sanitized_value: Optional[Any] = Field(default=None, description="Sanitized value")
    
    def add_error(self, message: str) -> None:
        """Add validation error."""
        self.errors.append(message)
        self.is_valid = False
    
    def add_warning(self, message: str) -> None:
        """Add validation warning."""
        self.warnings.append(message)


class PathValidator:
    """Validator for file paths and URLs."""
    
    # Dangerous path patterns
    DANGEROUS_PATTERNS = [
        r'\.\.',  # Parent directory traversal
        r'~',      # Home directory reference
        r'\$',     # Environment variable
        r'%',      # Windows environment variable
        r'\\\\',   # UNC path
        r'//',     # Protocol-relative URL
        r'file://',  # File protocol
        r':[0-9]+',  # Port numbers in paths
    ]
    
    # Allowed file extensions for CAD files
    ALLOWED_EXTENSIONS = {
        '.fcstd', '.fcstd1',  # FreeCAD
        '.step', '.stp',       # STEP
        '.iges', '.igs',       # IGES
        '.stl',                # STL
        '.obj',                # OBJ
        '.brep', '.brp',       # BREP
        '.dxf',                # DXF
        '.svg',                # SVG (for sketches)
    }
    
    @classmethod
    def validate_path(cls, path: Union[str, Path]) -> ValidationResult:
        """Validate a file path for security issues."""
        result = ValidationResult(is_valid=True)
        
        if not path:
            result.add_error("Path cannot be empty")
            return result
        
        path_str = str(path)
        
        # Check for dangerous patterns
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, path_str, re.IGNORECASE):
                result.add_error(f"Dangerous pattern detected: {pattern}")
        
        # Check for absolute paths outside sandbox
        path_obj = Path(path_str)
        if path_obj.is_absolute():
            security_config = get_security_config()
            sandbox_dir = security_config.sandbox_dir
            
            try:
                # Resolve and check if path is within sandbox
                resolved = path_obj.resolve()
                sandbox_dir_resolved = str(sandbox_dir.resolve())
                
                # Add trailing separator to prevent path traversal attacks
                # This prevents /tmp/sandbox-evil from matching /tmp/sandbox
                import os
                if not str(resolved).startswith(os.path.join(sandbox_dir_resolved, '')):
                    result.add_error(f"Path outside sandbox: {resolved}")
            except (OSError, RuntimeError) as e:
                result.add_error(f"Invalid path: {e}")
        
        # Validate file extension if it's a file
        if path_obj.suffix:
            if path_obj.suffix.lower() not in cls.ALLOWED_EXTENSIONS:
                result.add_warning(
                    f"Unusual file extension: {path_obj.suffix}"
                )
        
        # Sanitize path
        if result.is_valid:
            # Remove any remaining dangerous characters
            sanitized = re.sub(r'[<>:"|?*]', '_', path_str)
            result.sanitized_value = sanitized
        
        return result
    
    @classmethod
    def validate_url(cls, url: str) -> ValidationResult:
        """Validate a URL for security issues."""
        result = ValidationResult(is_valid=True)
        
        if not url:
            result.add_error("URL cannot be empty")
            return result
        
        try:
            parsed = urlparse(url)
            
            # Check protocol
            if parsed.scheme not in ['http', 'https', 'ftp']:
                result.add_error(f"Invalid protocol: {parsed.scheme}")
            
            # Check for local/private addresses
            if parsed.hostname:
                if parsed.hostname in ['localhost', '127.0.0.1', '0.0.0.0']:
                    result.add_warning("URL points to localhost")
                
                # Check for private IP ranges
                if re.match(r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', 
                           parsed.hostname):
                    result.add_warning("URL points to private network")
            
            # Check for suspicious ports
            if parsed.port and parsed.port not in [80, 443, 21, 22]:
                result.add_warning(f"Unusual port: {parsed.port}")
            
        except Exception as e:
            result.add_error(f"Invalid URL: {e}")
        
        return result


class DocumentPropertyValidator:
    """Validator for FreeCAD document properties."""
    
    # Maximum lengths for properties
    MAX_LENGTHS = {
        'Label': 255,
        'Description': 1000,
        'Author': 100,
        'Company': 100,
        'License': 50,
        'Comment': 500,
    }
    
    # Dangerous property content patterns
    DANGEROUS_CONTENT = [
        r'<script',     # Script injection
        r'javascript:', # JavaScript protocol
        r'data:',       # Data URL
        r'vbscript:',   # VBScript protocol
        r'on\w+\s*=',   # Event handlers
        r'expression\(', # CSS expressions
    ]
    
    @classmethod
    def validate_property(
        cls, 
        name: str, 
        value: Any
    ) -> ValidationResult:
        """Validate a document property."""
        result = ValidationResult(is_valid=True)
        
        # Check property name
        if not re.match(r'^[A-Za-z][A-Za-z0-9_]*$', name):
            result.add_error(f"Invalid property name: {name}")
        
        # Validate based on type
        if isinstance(value, str):
            # Check length
            max_length = cls.MAX_LENGTHS.get(name, 1000)
            if len(value) > max_length:
                result.add_warning(
                    f"Property {name} exceeds max length {max_length}"
                )
                value = value[:max_length]
            
            # Check for dangerous content
            for pattern in cls.DANGEROUS_CONTENT:
                if re.search(pattern, value, re.IGNORECASE):
                    result.add_error(
                        f"Dangerous content in property {name}: {pattern}"
                    )
            
            # Sanitize
            if result.is_valid:
                # Remove control characters
                sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
                # Escape HTML entities
                sanitized = sanitized.replace('<', '&lt;').replace('>', '&gt;')
                result.sanitized_value = sanitized
        
        elif isinstance(value, (int, float)):
            # Check for reasonable ranges
            if abs(value) > 1e10:
                result.add_warning(f"Large numeric value in {name}: {value}")
        
        elif isinstance(value, bool):
            # Booleans are safe
            result.sanitized_value = value
        
        elif isinstance(value, (list, dict)):
            # Complex types need deeper validation
            if len(str(value)) > 10000:
                result.add_error(f"Complex property {name} is too large")
        
        else:
            result.add_warning(f"Unknown property type for {name}: {type(value)}")
        
        return result
    
    @classmethod
    def sanitize_document_properties(
        cls, 
        properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Sanitize all document properties."""
        sanitized = {}
        
        for name, value in properties.items():
            result = cls.validate_property(name, value)
            
            if result.is_valid and result.sanitized_value is not None:
                sanitized[name] = result.sanitized_value
            elif result.is_valid:
                sanitized[name] = value
            else:
                logger.warning(
                    f"Skipping invalid property {name}",
                    errors=result.errors
                )
        
        return sanitized


class MaterialValidator:
    """Validator for Material Framework definitions."""
    
    # Allowed material properties
    ALLOWED_PROPERTIES = {
        'Density', 'YoungsModulus', 'PoissonRatio',
        'ThermalExpansion', 'SpecificHeat', 'ThermalConductivity',
        'UltimateTensileStrength', 'YieldStrength', 'Hardness',
        'Color', 'Transparency', 'Reflectivity'
    }
    
    # Valid units for properties
    VALID_UNITS = {
        'Density': ['kg/m^3', 'g/cm^3'],
        'YoungsModulus': ['Pa', 'GPa', 'MPa'],
        'ThermalConductivity': ['W/m-K'],
        'Temperature': ['K', 'C', 'F'],
    }
    
    @classmethod
    def validate_material(
        cls, 
        material_data: Dict[str, Any]
    ) -> ValidationResult:
        """Validate material definition."""
        result = ValidationResult(is_valid=True)
        
        # Check required fields
        if 'Name' not in material_data:
            result.add_error("Material must have a Name")
        
        # Validate properties
        if 'Properties' in material_data:
            for prop_name, prop_value in material_data['Properties'].items():
                # Check if property is allowed
                if prop_name not in cls.ALLOWED_PROPERTIES:
                    result.add_warning(f"Unknown material property: {prop_name}")
                
                # Validate property value
                if isinstance(prop_value, dict):
                    # Check for value and unit
                    if 'Value' not in prop_value:
                        result.add_error(f"Property {prop_name} missing value")
                    
                    if 'Unit' in prop_value:
                        # Validate unit
                        valid_units = cls.VALID_UNITS.get(prop_name, [])
                        if valid_units and prop_value['Unit'] not in valid_units:
                            result.add_warning(
                                f"Invalid unit for {prop_name}: {prop_value['Unit']}"
                            )
        
        # Check for executable content
        material_str = str(material_data)
        if 'exec' in material_str or 'eval' in material_str:
            result.add_error("Material contains executable code")
        
        return result


class Assembly4Validator:
    """Validator for Assembly4 constraints and operations."""
    
    # Allowed constraint types
    ALLOWED_CONSTRAINTS = {
        'Placement', 'Coincident', 'Parallel', 'Perpendicular',
        'Angle', 'Distance', 'Symmetric', 'Tangent'
    }
    
    # Maximum constraints per assembly
    MAX_CONSTRAINTS = 1000
    
    @classmethod
    def validate_constraint(
        cls, 
        constraint: Dict[str, Any]
    ) -> ValidationResult:
        """Validate Assembly4 constraint."""
        result = ValidationResult(is_valid=True)
        
        # Check constraint type
        constraint_type = constraint.get('Type')
        if constraint_type not in cls.ALLOWED_CONSTRAINTS:
            result.add_error(f"Invalid constraint type: {constraint_type}")
        
        # Check for local document links only
        if 'LinkedObject' in constraint:
            link = constraint['LinkedObject']
            if link.startswith('http://') or link.startswith('file://'):
                result.add_error("External links not allowed in constraints")
        
        # Check for expressions
        if 'Expression' in constraint:
            expression = constraint['Expression']
            # Block Python expressions
            if 'python' in expression.lower() or 'exec' in expression:
                result.add_error("Python expressions not allowed in constraints")
        
        return result
    
    @classmethod
    def validate_assembly(
        cls, 
        assembly_data: Dict[str, Any]
    ) -> ValidationResult:
        """Validate complete assembly."""
        result = ValidationResult(is_valid=True)
        
        # Check constraint count
        constraints = assembly_data.get('Constraints', [])
        if len(constraints) > cls.MAX_CONSTRAINTS:
            result.add_error(
                f"Too many constraints: {len(constraints)} > {cls.MAX_CONSTRAINTS}"
            )
        
        # Validate each constraint
        for constraint in constraints:
            constraint_result = cls.validate_constraint(constraint)
            if not constraint_result.is_valid:
                result.errors.extend(constraint_result.errors)
                result.is_valid = False
        
        # Check for FeaturePython from untrusted sources
        if 'FeaturePython' in assembly_data:
            result.add_error("FeaturePython objects not allowed")
        
        return result


class GeometryValidator:
    """Validator for OCCT geometry operations."""
    
    def __init__(self, limits: Optional[GeometryLimits] = None):
        self.limits = limits or get_security_config().geometry_limits
    
    def validate_geometry_bounds(
        self, 
        geometry_data: Dict[str, Any]
    ) -> ValidationResult:
        """Validate geometry complexity and bounds."""
        result = ValidationResult(is_valid=True)
        
        # Check face count
        face_count = geometry_data.get('FaceCount', 0)
        if face_count > self.limits.max_faces:
            result.add_error(
                f"Too many faces: {face_count} > {self.limits.max_faces}"
            )
        
        # Check edge count
        edge_count = geometry_data.get('EdgeCount', 0)
        if edge_count > self.limits.max_edges:
            result.add_error(
                f"Too many edges: {edge_count} > {self.limits.max_edges}"
            )
        
        # Check vertex count
        vertex_count = geometry_data.get('VertexCount', 0)
        if vertex_count > self.limits.max_vertices:
            result.add_error(
                f"Too many vertices: {vertex_count} > {self.limits.max_vertices}"
            )
        
        # Check mesh triangle count
        if 'MeshData' in geometry_data:
            triangle_count = geometry_data['MeshData'].get('TriangleCount', 0)
            if triangle_count > self.limits.max_mesh_triangles:
                result.add_error(
                    f"Too many triangles: {triangle_count} > {self.limits.max_mesh_triangles}"
                )
        
        # Check bounding box for reasonable size
        if 'BoundingBox' in geometry_data:
            bbox = geometry_data['BoundingBox']
            size_x = abs(bbox.get('MaxX', 0) - bbox.get('MinX', 0))
            size_y = abs(bbox.get('MaxY', 0) - bbox.get('MinY', 0))
            size_z = abs(bbox.get('MaxZ', 0) - bbox.get('MinZ', 0))
            
            max_dimension = 10000  # 10 meters
            if any(size > max_dimension for size in [size_x, size_y, size_z]):
                result.add_warning(f"Very large geometry detected: {size_x}x{size_y}x{size_z}")
        
        return result
    
    def validate_step_import(self, step_content: str) -> ValidationResult:
        """Validate STEP file content."""
        result = ValidationResult(is_valid=True)
        
        # Check file size
        if len(step_content) > self.limits.max_file_size_mb * 1024 * 1024:
            result.add_error("STEP file too large")
        
        # Check for valid STEP header
        if not step_content.startswith("ISO-10303-21;"):
            result.add_error("Invalid STEP file header")
        
        # Check for suspicious content
        suspicious_patterns = [
            r'FILE_SCHEMA.*MACRO',  # Macro definitions
            r'EXTERNAL_SOURCE',      # External references
        ]
        
        for pattern in suspicious_patterns:
            if re.search(pattern, step_content, re.IGNORECASE):
                result.add_warning(f"Suspicious STEP content: {pattern}")
        
        return result


class InputValidator:
    """Main input validation service."""
    
    def __init__(self):
        self.path_validator = PathValidator()
        self.property_validator = DocumentPropertyValidator()
        self.material_validator = MaterialValidator()
        self.assembly_validator = Assembly4Validator()
        self.geometry_validator = GeometryValidator()
    
    def validate_job_input(self, job_data: Dict[str, Any]) -> ValidationResult:
        """Validate complete job input."""
        result = ValidationResult(is_valid=True)
        
        # Validate file paths
        if 'input_file' in job_data:
            path_result = self.path_validator.validate_path(job_data['input_file'])
            if not path_result.is_valid:
                result.errors.extend(path_result.errors)
                result.is_valid = False
        
        # Validate properties
        if 'properties' in job_data:
            sanitized_props = self.property_validator.sanitize_document_properties(
                job_data['properties']
            )
            job_data['properties'] = sanitized_props
        
        # Validate material if present
        if 'material' in job_data:
            material_result = self.material_validator.validate_material(
                job_data['material']
            )
            if not material_result.is_valid:
                result.errors.extend(material_result.errors)
                result.is_valid = False
        
        # Validate assembly if present
        if 'assembly' in job_data:
            assembly_result = self.assembly_validator.validate_assembly(
                job_data['assembly']
            )
            if not assembly_result.is_valid:
                result.errors.extend(assembly_result.errors)
                result.is_valid = False
        
        return result


# Global validator instance
_input_validator: Optional[InputValidator] = None


def get_input_validator() -> InputValidator:
    """Get global input validator instance."""
    global _input_validator
    if _input_validator is None:
        _input_validator = InputValidator()
    return _input_validator