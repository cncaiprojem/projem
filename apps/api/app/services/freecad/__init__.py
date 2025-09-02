"""
FreeCAD services package for Task 7.2 and Task 7.6

Provides:
- AI-powered FreeCAD script generation with Turkish language support
- Parametric modeling pipeline with deterministic outputs
- Geometry validation with manufacturing constraints
- Standard parts library (DIN/ISO)
- Assembly4 support with kinematics
- Collision detection
- BOM extraction
- Exploded view generation
"""

# Task 7.2 imports
from .script_generator import FreeCADScriptGenerator, GeneratedScript, ScriptTemplate
from .geometry_validator import GeometryValidator, ValidationResult, ManufacturingConstraints, ExportFormat
from .standard_parts import StandardPartsLibrary, StandardPart, FCStdTemplate, PartCategory, StandardType

# Task 7.6 imports
from .exporter import DeterministicExporter, deterministic_exporter
from .a4_assembly import (
    Assembly4Manager, assembly4_manager,
    JointType, Component, Joint, LCS,
    DOFAnalysis, KinematicFrame
)
from .collision import CollisionDetector, collision_detector, CollisionPair, AABB
from .bom import BOMExtractor, bom_extractor, BillOfMaterials, BOMItem
from .exploded_view import (
    ExplodedViewGenerator, exploded_view_generator,
    ExplodedView, ExplodedComponent, ExplodedViewConfig
)

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
    "StandardType",
    
    # Deterministic export
    "DeterministicExporter",
    "deterministic_exporter",
    
    # Assembly4
    "Assembly4Manager",
    "assembly4_manager",
    "JointType",
    "Component",
    "Joint",
    "LCS",
    "DOFAnalysis",
    "KinematicFrame",
    
    # Collision detection
    "CollisionDetector",
    "collision_detector",
    "CollisionPair",
    "AABB",
    
    # BOM extraction
    "BOMExtractor",
    "bom_extractor",
    "BillOfMaterials",
    "BOMItem",
    
    # Exploded views
    "ExplodedViewGenerator",
    "exploded_view_generator",
    "ExplodedView",
    "ExplodedComponent",
    "ExplodedViewConfig"
]