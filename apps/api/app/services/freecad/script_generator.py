"""
FreeCAD Script Generator for Task 7.2

Parses AI responses to extract FreeCAD Python scripts with:
- AST-based security validation
- Dimension bounds checking
- Units normalization
- Script templates for common operations

TODO: Consider consolidating with AIAdapter's script validation logic
      to avoid code duplication. Currently this module is used mainly for
      testing while AIAdapter handles production script validation.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)


class ScriptTemplate(str, Enum):
    """Common FreeCAD script templates."""
    CYLINDER = "cylinder"
    BOX = "box"
    SPHERE = "sphere"
    FLANGE = "flange"
    SHAFT = "shaft"
    GEAR = "gear"
    BEARING = "bearing"
    ASSEMBLY = "assembly"
    SKETCH = "sketch"


class GeneratedScript(BaseModel):
    """Generated FreeCAD script with metadata."""
    script: str = Field(description="Complete FreeCAD Python script")
    template_used: Optional[ScriptTemplate] = Field(default=None)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    imports: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    has_assembly: bool = Field(default=False)
    has_sketch: bool = Field(default=False)
    estimated_complexity: int = Field(default=1, ge=1, le=10)


class FreeCADScriptGenerator:
    """Generate and validate FreeCAD scripts from AI responses."""
    
    # Script templates
    TEMPLATES = {
        ScriptTemplate.CYLINDER: """import FreeCAD as App
import Part

doc = App.newDocument("{name}")
cylinder = Part.makeCylinder({radius}, {height})
Part.show(cylinder)
doc.recompute()""",
        
        ScriptTemplate.BOX: """import FreeCAD as App
import Part

doc = App.newDocument("{name}")
box = Part.makeBox({length}, {width}, {height})
Part.show(box)
doc.recompute()""",
        
        ScriptTemplate.SPHERE: """import FreeCAD as App
import Part

doc = App.newDocument("{name}")
sphere = Part.makeSphere({radius})
Part.show(sphere)
doc.recompute()""",
        
        ScriptTemplate.FLANGE: """import FreeCAD as App
import Part

doc = App.newDocument("{name}")
outer_d = {outer_diameter}
inner_d = {inner_diameter}
thickness = {thickness}

outer = Part.makeCylinder(outer_d/2.0, thickness)
inner = Part.makeCylinder(inner_d/2.0, thickness)
flange = outer.cut(inner)

Part.show(flange)
doc.recompute()""",
        
        ScriptTemplate.SHAFT: """import FreeCAD as App
import Part

doc = App.newDocument("{name}")
diameter = {diameter}
length = {length}

shaft = Part.makeCylinder(diameter/2.0, length)
Part.show(shaft)
doc.recompute()""",
        
        ScriptTemplate.GEAR: """import FreeCAD as App
import Part
import math

doc = App.newDocument("{name}")
module = {module}
teeth = {teeth}
thickness = {thickness}

# Simplified gear representation
pitch_radius = module * teeth / 2.0
outer_radius = pitch_radius + module
inner_radius = pitch_radius - 1.25 * module

outer = Part.makeCylinder(outer_radius, thickness)
inner = Part.makeCylinder(inner_radius * 0.3, thickness)
gear = outer.cut(inner)

Part.show(gear)
doc.recompute()""",
        
        ScriptTemplate.BEARING: """import FreeCAD as App
import Part

doc = App.newDocument("{name}")
outer_d = {outer_diameter}
inner_d = {inner_diameter}
width = {width}

# Simplified bearing representation
outer_race = Part.makeCylinder(outer_d/2.0, width)
inner_hole = Part.makeCylinder(inner_d/2.0, width)
bearing = outer_race.cut(inner_hole)

# Add groove representation
groove_d = (outer_d + inner_d) / 2.0
groove = Part.makeTorus(groove_d/2.0, width/4.0)
groove.translate(App.Vector(0, 0, width/2.0))

Part.show(bearing)
doc.recompute()""",
        
        ScriptTemplate.ASSEMBLY: """import FreeCAD as App
import Part

doc = App.newDocument("{name}")

# Create assembly parts
{parts_creation}

# Position parts
{parts_positioning}

# Create assembly
assembly = doc.addObject("App::DocumentObjectGroup", "Assembly")
{add_to_assembly}

doc.recompute()""",
        
        ScriptTemplate.SKETCH: """import FreeCAD as App
import Sketcher

doc = App.newDocument("{name}")
sketch = doc.addObject("Sketcher::SketchObject", "Sketch")

# Add geometry
{geometry_commands}

# Add constraints
{constraint_commands}

doc.recompute()"""
    }
    
    def __init__(self):
        """Initialize script generator."""
        self.dimension_bounds = {
            "min": 0.1,    # mm
            "max": 1000.0  # mm
        }
    
    def generate_from_template(
        self,
        template: ScriptTemplate,
        parameters: Dict[str, Any],
        name: str = "generated"
    ) -> GeneratedScript:
        """
        Generate script from template with parameters.
        
        Args:
            template: Template to use
            parameters: Template parameters
            name: Document name
            
        Returns:
            Generated script with metadata
        """
        if template not in self.TEMPLATES:
            raise ValueError(f"Unknown template: {template}")
        
        # Get template
        script_template = self.TEMPLATES[template]
        
        # Normalize dimensions
        normalized_params = self._normalize_dimensions(parameters)
        normalized_params["name"] = name
        
        # Fill template
        try:
            script = script_template.format(**normalized_params)
        except KeyError as e:
            logger.error(f"Missing template parameter: {e}")
            # Return a basic script with error comment
            script = f"""import FreeCAD as App
# Error: Missing parameter {e}
# Required parameters: {list(parameters.keys())}
doc = App.newDocument("{name}")
doc.recompute()"""
        
        # Extract imports
        imports = self._extract_imports(script)
        
        # Estimate complexity
        complexity = self._estimate_complexity(script)
        
        return GeneratedScript(
            script=script,
            template_used=template,
            parameters=normalized_params,
            imports=imports,
            warnings=[],
            has_assembly="Assembly" in script or "App::Link" in script,
            has_sketch="Sketcher" in script,
            estimated_complexity=complexity
        )
    
    def parse_and_validate(
        self,
        script: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> GeneratedScript:
        """
        Parse and validate AI-generated script.
        
        Args:
            script: FreeCAD Python script
            parameters: Optional parameters dict
            
        Returns:
            Validated script with metadata
            
        Raises:
            ValueError: If script validation fails
        """
        # Basic cleanup
        script = script.strip()
        
        # Validate syntax
        try:
            tree = ast.parse(script)
        except SyntaxError as e:
            raise ValueError(f"Invalid Python syntax: {e}")
        
        # Security validation
        violations = self._validate_security(tree)
        if violations:
            raise ValueError(f"Security violations: {'; '.join(violations)}")
        
        # Extract dimensions and validate bounds
        dimensions, warnings = self._extract_and_validate_dimensions(tree)
        
        # Normalize units in script
        normalized_script = self._normalize_units_in_script(script)
        
        # Extract imports
        imports = self._extract_imports(normalized_script)
        
        # Detect features
        has_assembly = self._detect_assembly(normalized_script)
        has_sketch = self._detect_sketch(normalized_script)
        
        # Estimate complexity
        complexity = self._estimate_complexity(normalized_script)
        
        return GeneratedScript(
            script=normalized_script,
            template_used=None,
            parameters=parameters or dimensions,
            imports=imports,
            warnings=warnings,
            has_assembly=has_assembly,
            has_sketch=has_sketch,
            estimated_complexity=complexity
        )
    
    def _normalize_dimensions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize dimensions to mm."""
        normalized = {}
        
        for key, value in params.items():
            if isinstance(value, (int, float)):
                # Ensure within bounds
                if value < self.dimension_bounds["min"]:
                    logger.warning(f"Dimension {key}={value} below minimum, using {self.dimension_bounds['min']}")
                    normalized[key] = self.dimension_bounds["min"]
                elif value > self.dimension_bounds["max"]:
                    logger.warning(f"Dimension {key}={value} above maximum, using {self.dimension_bounds['max']}")
                    normalized[key] = self.dimension_bounds["max"]
                else:
                    normalized[key] = float(value)
            else:
                normalized[key] = value
        
        return normalized
    
    def _validate_security(self, tree: ast.AST) -> List[str]:
        """Validate script security using AST."""
        violations = []
        
        # Allowed modules
        allowed_modules = {
            'FreeCAD', 'App', 'Part', 'PartDesign', 
            'Sketcher', 'Draft', 'Import', 'Mesh', 
            'math', 'numpy', 'Base', 'Vector'
        }
        
        # Forbidden calls
        forbidden_calls = {
            '__import__', 'exec', 'eval', 'compile',
            'open', 'file', 'input', 'os', 'subprocess'
        }
        
        class SecurityChecker(ast.NodeVisitor):
            def visit_Import(self, node):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if module not in allowed_modules:
                        violations.append(f"Forbidden import: {module}")
            
            def visit_ImportFrom(self, node):
                if node.module:
                    module = node.module.split('.')[0]
                    if module not in allowed_modules:
                        violations.append(f"Forbidden import: {module}")
            
            def visit_Call(self, node):
                if isinstance(node.func, ast.Name):
                    if node.func.id in forbidden_calls:
                        violations.append(f"Forbidden call: {node.func.id}")
                elif isinstance(node.func, ast.Attribute):
                    # Check for file I/O operations
                    if node.func.attr in ['export', 'save', 'write', 'dump']:
                        violations.append(f"File I/O not allowed: {node.func.attr}")
                self.generic_visit(node)
        
        checker = SecurityChecker()
        checker.visit(tree)
        
        return violations
    
    def _extract_and_validate_dimensions(
        self,
        tree: ast.AST
    ) -> Tuple[Dict[str, float], List[str]]:
        """Extract dimensions from AST and validate bounds."""
        dimensions = {}
        warnings = []
        
        class DimensionExtractor(ast.NodeVisitor):
            def visit_Assign(self, node):
                # Look for dimension assignments
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if isinstance(node.value, ast.Constant):
                            if isinstance(node.value.value, (int, float)):
                                value = float(node.value.value)
                                dimensions[target.id] = value
                                
                                # Validate bounds
                                if value < 0.1:
                                    warnings.append(
                                        f"Dimension {target.id}={value}mm below minimum (0.1mm)"
                                    )
                                elif value > 1000:
                                    warnings.append(
                                        f"Dimension {target.id}={value}mm above maximum (1000mm)"
                                    )
                self.generic_visit(node)
        
        extractor = DimensionExtractor()
        extractor.visit(tree)
        
        return dimensions, warnings
    
    def _normalize_units_in_script(self, script: str) -> str:
        """Normalize units in script text to mm."""
        # Pattern for detecting dimensions with units
        patterns = [
            (r'(\d+(?:\.\d+)?)\s*cm\b', lambda m: str(float(m.group(1)) * 10)),
            (r'(\d+(?:\.\d+)?)\s*m\b', lambda m: str(float(m.group(1)) * 1000)),
            (r'(\d+(?:\.\d+)?)\s*(?:in|inch|inches|")\b', lambda m: str(float(m.group(1)) * 25.4)),
            (r'(\d+(?:\.\d+)?)\s*ft\b', lambda m: str(float(m.group(1)) * 304.8)),
        ]
        
        normalized = script
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        
        return normalized
    
    def _extract_imports(self, script: str) -> List[str]:
        """Extract import statements from script."""
        imports = []
        
        # Match import patterns
        import_pattern = re.compile(r'^import\s+(\S+)(?:\s+as\s+\S+)?', re.MULTILINE)
        from_pattern = re.compile(r'^from\s+(\S+)\s+import', re.MULTILINE)
        
        for match in import_pattern.finditer(script):
            imports.append(match.group(1))
        
        for match in from_pattern.finditer(script):
            imports.append(match.group(1))
        
        return list(set(imports))
    
    def _detect_assembly(self, script: str) -> bool:
        """Detect if script creates an assembly."""
        assembly_indicators = [
            "Assembly",
            "App::Link",
            "App::DocumentObjectGroup",
            "addObject.*Assembly",
            "ConstraintSystem"
        ]
        
        for indicator in assembly_indicators:
            if re.search(indicator, script):
                return True
        
        return False
    
    def _detect_sketch(self, script: str) -> bool:
        """Detect if script uses sketcher."""
        return "Sketcher" in script or "SketchObject" in script
    
    def _estimate_complexity(self, script: str) -> int:
        """Estimate script complexity (1-10)."""
        lines = len(script.splitlines())
        
        # Count operations
        operations = {
            "basic": ["makeCylinder", "makeBox", "makeSphere"],
            "medium": ["cut", "fuse", "common", "makeLoft"],
            "complex": ["makeThickness", "makeChamfer", "makeFillet", "sweep"]
        }
        
        complexity = 1
        
        # Lines of code
        if lines > 50:
            complexity += 2
        elif lines > 20:
            complexity += 1
        
        # Operations
        for op_type, op_list in operations.items():
            for op in op_list:
                if op in script:
                    if op_type == "basic":
                        complexity += 1
                    elif op_type == "medium":
                        complexity += 2
                    elif op_type == "complex":
                        complexity += 3
        
        # Features
        if self._detect_assembly(script):
            complexity += 2
        if self._detect_sketch(script):
            complexity += 1
        
        # Loops and conditionals
        if "for " in script or "while " in script:
            complexity += 1
        if "if " in script:
            complexity += 1
        
        return min(complexity, 10)