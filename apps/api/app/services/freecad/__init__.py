"""
FreeCAD services package for Task 7.2

Provides AI-powered FreeCAD script generation with Turkish language support.
"""

from .script_generator import FreeCADScriptGenerator, GeneratedScript, ScriptTemplate
from .geometry_validator import GeometryValidator, ValidationResult, ManufacturingConstraints, ExportFormat
from .standard_parts import StandardPartsLibrary, StandardPart, FCStdTemplate, PartCategory, StandardType

__all__ = [
    # Script generation
    "FreeCADScriptGenerator",
    "GeneratedScript",
    "ScriptTemplate",
    
    # Geometry validation
    "GeometryValidator",
    "ValidationResult",
    "ManufacturingConstraints",
    "ExportFormat",
    
    # Standard parts
    "StandardPartsLibrary",
    "StandardPart",
    "FCStdTemplate",
    "PartCategory",
    "StandardType"
]