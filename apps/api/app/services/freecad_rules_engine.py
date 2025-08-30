"""
Ultra-Enterprise FreeCAD Rules Engine for Task 7.3

Deterministic normalization and validation engine for FreeCAD script processing.
Implements comprehensive canonicalization and validation for both parametric inputs
and FreeCAD Python scripts with security validation, unit conversions, and PartDesign support.

Features:
- Deterministic normalization for parametric inputs and FreeCAD scripts
- Unit conversion (cm/inch → mm) with 1e-6 rounding
- Turkish to English comment translation
- Security validation using AST parsing
- PartDesign workbench support (Bodies, Sketches, Pads, Pockets, etc.)
- Script mode validation with allowlists for imports and numpy operations
- Manufacturing constraints validation
- Idempotent normalization with SHA256 hashing
- Comprehensive error codes with Turkish messages
- AST-based metadata extraction for robust parsing
"""

from __future__ import annotations

import ast
import hashlib
import re
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from ..core.logging import get_logger

logger = get_logger(__name__)


class NormalizationErrorCode(str, Enum):
    """Error codes for normalization and validation."""
    INVALID_SYNTAX = "INVALID_SYNTAX"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    API_NOT_FOUND = "API_NOT_FOUND"
    API_DEPRECATED = "API_DEPRECATED"
    DIMENSION_ERROR = "DIMENSION_ERROR"
    ANGLE_ERROR = "ANGLE_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    CONSTRAINT_UNSUPPORTED = "CONSTRAINT_UNSUPPORTED"
    SKETCH_UNDERCONSTRAINED = "SKETCH_UNDERCONSTRAINED"
    FEATURE_DEPENDENCY_ERROR = "FEATURE_DEPENDENCY_ERROR"
    SINGLE_SOLID_VIOLATION = "SINGLE_SOLID_VIOLATION"
    PATTERN_ERROR = "PATTERN_ERROR"
    BOOLEAN_BODY_ERROR = "BOOLEAN_BODY_ERROR"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    AMBIGUOUS_INPUT = "AMBIGUOUS_INPUT"
    AI_HINT_REQUIRED = "AI_HINT_REQUIRED"


class ValidationException(Exception):
    """Exception for validation errors with Turkish support."""
    def __init__(
        self,
        code: NormalizationErrorCode,
        message: str,
        turkish_message: str,
        http_status: int = 422,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.code = code
        self.turkish_message = turkish_message
        self.http_status = http_status
        self.details = details or {}


class UnitConversion(BaseModel):
    """Record of a unit conversion applied during normalization."""
    from_unit: str
    to_unit: str = "mm"
    before: float
    after: float
    location: str


class ScriptMetadata(BaseModel):
    """Metadata about a normalized FreeCAD script."""
    modules_used: List[str] = Field(default_factory=list)
    conversions_applied: List[UnitConversion] = Field(default_factory=list)
    api_warnings: List[str] = Field(default_factory=list)
    dims_mm: Dict[str, float] = Field(default_factory=dict)
    script_hash: str = Field(default="")
    partdesign_features: List[Dict[str, Any]] = Field(default_factory=list)
    sketches: List[Dict[str, Any]] = Field(default_factory=list)
    bodies: Dict[str, Any] = Field(default_factory=dict)
    datums: Dict[str, List[str]] = Field(default_factory=dict)
    booleans: List[Dict[str, Any]] = Field(default_factory=list)


class NormalizationResult(BaseModel):
    """Result of normalization process."""
    canonical_params: Optional[Dict[str, Any]] = None
    canonical_script: Optional[str] = None
    script_meta: Optional[ScriptMetadata] = None
    success: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class FreeCADRulesEngine:
    """Deterministic rules engine for FreeCAD normalization and validation."""
    
    # Allowed imports for FreeCAD scripts
    ALLOWED_IMPORTS = {
        "FreeCAD", "App", "Part", "Sketcher", "Draft", 
        "math", "numpy", "np"
    }
    
    # Forbidden names and operations
    FORBIDDEN_NAMES = {
        "__import__", "exec", "eval", "open",  # Removed 'file' - not in Python 3
        "os", "subprocess", "sys.exit", "compile", "globals", "locals"
    }
    
    # Allowed numpy attributes
    NUMPY_ALLOWLIST = {
        "array", "asarray", "linspace", "arange", "zeros", "ones",
        "sqrt", "sin", "cos", "tan", "pi", "dot", "cross",
        "clip", "maximum", "minimum", "abs", "floor", "ceil", "round"
    }
    
    # Allowed Sketcher constraint types
    SKETCHER_CONSTRAINTS = {
        "Distance", "Angle", "Coincident", "Parallel", "Perpendicular",
        "Horizontal", "Vertical", "Tangent", "Equal", "Symmetric"
    }
    
    # Turkish to English glossary for comments
    TURKISH_GLOSSARY = {
        "uzunluk": "length",
        "genişlik": "width",
        "yükseklik": "height",
        "yarıçap": "radius",
        "duvar kalınlığı": "wall thickness",
        "birim": "unit",
        "mm": "mm",
        "cm": "cm",
        "inç": "inch",
        "hata": "error",
        "uyarı": "warning",
        "kalınlık": "thickness",
        "açı": "angle",
        "derece": "degree",
        "çap": "diameter",
        "delik": "hole",
        "cep": "pocket",
        "pad": "pad",
        "döndürme": "revolution",
        "süpürme": "sweep",
        "dizi": "pattern",
        "ayna": "mirror",
        "kesit": "section",
        "profil": "profile",
        "gövde": "body",
        "katı": "solid",
        "yüzey": "surface",
        "kenar": "edge",
        "köşe": "vertex",
        "nokta": "point",
        "düzlem": "plane",
        "eksen": "axis",
        "kısıt": "constraint",
        "boyut": "dimension",
        "ölçü": "measure"
    }
    
    # Comprehensive FreeCAD API registry
    FREECAD_API_REGISTRY = {
        # Part module APIs
        "Part.makeBox": {"min_args": 3, "max_args": 4, "category": "primitive"},
        "Part.makeCylinder": {"min_args": 2, "max_args": 5, "category": "primitive"},
        "Part.makeSphere": {"min_args": 1, "max_args": 4, "category": "primitive"},
        "Part.makeCone": {"min_args": 3, "max_args": 5, "category": "primitive"},
        "Part.makeTorus": {"min_args": 2, "max_args": 5, "category": "primitive"},
        "Part.makePlane": {"min_args": 2, "max_args": 4, "category": "primitive"},
        "Part.makePolygon": {"min_args": 1, "max_args": 2, "category": "wire"},
        "Part.makeHelix": {"min_args": 3, "max_args": 6, "category": "wire"},
        "Part.Circle": {"min_args": 0, "max_args": 3, "category": "geometry"},
        "Part.LineSegment": {"min_args": 0, "max_args": 2, "category": "geometry"},
        "Part.Arc": {"min_args": 3, "max_args": 3, "category": "geometry"},
        "Part.show": {"min_args": 1, "max_args": 2, "category": "display"},
        
        # PartDesign APIs
        "PartDesign::Body": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::Pad": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::Pocket": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::Revolution": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::Loft": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::Pipe": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::LinearPattern": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::PolarPattern": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        "PartDesign::Mirrored": {"min_args": 0, "max_args": 1, "category": "partdesign"},
        
        # Sketcher APIs
        "Sketcher::SketchObject": {"min_args": 0, "max_args": 1, "category": "sketcher"},
        "Sketcher.Constraint": {"min_args": 1, "max_args": 4, "category": "sketcher"},
        
        # Document APIs
        "App.newDocument": {"min_args": 0, "max_args": 1, "category": "document"},
        "App.openDocument": {"min_args": 1, "max_args": 1, "category": "document"},
        "App.getDocument": {"min_args": 1, "max_args": 1, "category": "document"},
        "doc.addObject": {"min_args": 2, "max_args": 2, "category": "document"},
        "doc.removeObject": {"min_args": 1, "max_args": 1, "category": "document"},
        "doc.recompute": {"min_args": 0, "max_args": 0, "category": "document"},
        
        # Boolean operations
        "Part.fuse": {"min_args": 1, "max_args": 2, "category": "boolean"},
        "Part.cut": {"min_args": 2, "max_args": 2, "category": "boolean"},
        "Part.common": {"min_args": 2, "max_args": 2, "category": "boolean"},
    }
    
    # Deprecated FreeCAD API mappings
    DEPRECATED_APIS = {
        "Part.makeCircle": "Use Part.Circle instead",
        "Part.makeLine": "Use Part.LineSegment instead",
        "App.ActiveDocument": "Store document reference explicitly",
        "Part.makeWedge": "Use Part.makeBox with transformation instead",
        "Part.makePrism": "Use Part.makePolygon and extrude instead",
    }
    
    def __init__(self):
        """Initialize the rules engine."""
        self.precision = Decimal('0.000001')  # 1e-6 precision for rounding
    
    def normalize(self, input_data: Dict[str, Any]) -> NormalizationResult:
        """
        Normalize input data (parametric or script) to canonical form.
        
        Args:
            input_data: Input containing either parametric data or FreeCAD script
            
        Returns:
            NormalizationResult with canonical forms
        """
        result = NormalizationResult()
        
        try:
            # Detect input type
            if "script" in input_data or "freecad_script" in input_data:
                # Script mode normalization
                script = input_data.get("script") or input_data.get("freecad_script", "")
                canonical_script, script_meta = self._normalize_script(script)
                result.canonical_script = canonical_script
                result.script_meta = script_meta
                
                # Generate script hash for caching
                script_meta.script_hash = hashlib.sha256(
                    canonical_script.encode('utf-8')
                ).hexdigest()
            else:
                # Parametric mode normalization
                canonical_params = self._normalize_parametric(input_data)
                result.canonical_params = canonical_params
                
        except ValidationException as e:
            result.success = False
            result.errors.append(f"{e.code}: {e.turkish_message}")
            raise
        except Exception as e:
            result.success = False
            result.errors.append(str(e))
            logger.error(f"Normalization failed: {e}")
            raise ValidationException(
                NormalizationErrorCode.INVALID_SYNTAX,
                f"Normalization failed: {e}",
                f"Normalleştirme başarısız: {e}",
                http_status=400
            )
        
        return result
    
    def validate(self, input_data: Dict[str, Any]) -> NormalizationResult:
        """
        Validate input data with comprehensive rules.
        
        Args:
            input_data: Input to validate (already normalized)
            
        Returns:
            NormalizationResult with validation results
        """
        # First normalize
        result = self.normalize(input_data)
        
        if not result.success:
            return result
        
        try:
            if result.canonical_script:
                # Validate script mode
                self._validate_script(result.canonical_script, result.script_meta)
            elif result.canonical_params:
                # Validate parametric mode
                self._validate_parametric(result.canonical_params)
        except ValidationException as e:
            result.success = False
            result.errors.append(f"{e.code}: {e.turkish_message}")
            raise
        
        return result
    
    def _normalize_parametric(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize parametric input to canonical form.
        
        - Convert units to mm
        - Order keys alphabetically
        - Apply numeric rounding
        - Set defaults for missing values
        - Trim strings
        - Normalize enum casing
        """
        canonical = {}
        
        # Extract and normalize dimensions
        for key in ["length", "width", "height", "L", "W", "H"]:
            if key in params:
                value = params[key]
                # Convert to mm if unit is specified
                value_mm = self._convert_to_mm(value, params.get("units", "mm"))
                canonical_key = key[0].lower() if len(key) == 1 else key.lower()
                canonical[canonical_key] = self._round_decimal(value_mm)
        
        # Normalize other numeric values
        for key in ["radius", "r", "thickness", "wall_thickness", "wallthickness", "inner_radius", "innerradius"]:
            if key in params:
                value = params[key]
                value_mm = self._convert_to_mm(value, params.get("units", "mm"))
                canonical_key = key.lower().replace("_", "")
                canonical[canonical_key] = self._round_decimal(value_mm)
        
        # Normalize material
        if "material" in params:
            canonical["material"] = params["material"].strip().lower()
        elif "default_material" in params:
            canonical["material"] = params["default_material"].strip().lower()
        else:
            canonical["material"] = "pla"  # Default material
        
        # Normalize machine
        if "machine" in params:
            canonical["machine"] = params["machine"].strip().lower()
        else:
            canonical["machine"] = "3d_printer"  # Default machine
        
        # Normalize units (always mm after conversion)
        canonical["units"] = "mm"
        
        # Sort keys for determinism
        canonical = dict(sorted(canonical.items()))
        
        return canonical
    
    def _normalize_script(self, script: str) -> Tuple[str, ScriptMetadata]:
        """
        Normalize FreeCAD Python script to canonical form.
        
        Returns:
            Tuple of (canonical_script, metadata)
        """
        meta = ScriptMetadata()
        lines = script.split('\n')
        normalized_lines = []
        
        # Track what we've added
        has_freecad_import = False
        has_part_import = False
        has_sketcher_import = False
        has_draft_import = False
        has_math_import = False
        has_numpy_import = False
        has_document = False
        has_recompute = False
        result_var = None
        
        # Process each line
        for i, line in enumerate(lines):
            # Check for imports
            if "import FreeCAD" in line:
                has_freecad_import = True
                if "as App" not in line:
                    line = "import FreeCAD as App"
            elif "import Part" in line:
                has_part_import = True
            elif "import Sketcher" in line:
                has_sketcher_import = True
            elif "import Draft" in line:
                has_draft_import = True
            elif "import math" in line:
                has_math_import = True
            elif "import numpy" in line:
                has_numpy_import = True
                if "as np" not in line and "import numpy" == line.strip():
                    line = "import numpy as np"
            
            # Check for document creation/access
            if "App.newDocument" in line or "FreeCAD.newDocument" in line:
                has_document = True
                if "doc =" not in line and "doc=" not in line:
                    line = re.sub(
                        r'(App|FreeCAD)\.newDocument\((.*?)\)',
                        r'doc = \1.newDocument(\2)',
                        line
                    )
            elif "App.ActiveDocument" in line or "FreeCAD.ActiveDocument" in line:
                has_document = True
                if not any("doc =" in l or "doc=" in l for l in normalized_lines):
                    # Insert doc assignment before this line
                    normalized_lines.append("doc = App.ActiveDocument")
            
            # Apply unit conversions
            line, conversions = self._apply_unit_conversions(line, i)
            meta.conversions_applied.extend(conversions)
            
            # Translate Turkish comments
            line = self._translate_turkish_comments(line)
            
            # Track result variable - look for assignments that create geometry
            # Common patterns: result = Part.makeBox(...), shape = doc.addObject(...)
            if '=' in line and any(pattern in line for pattern in 
                                  ['Part.make', 'addObject', 'fuse', 'cut', 'common']):
                # Extract variable name from assignment
                match = re.match(r'\s*(\w+)\s*=', line)
                if match and not result_var:  # Only set if not already found
                    result_var = match.group(1)
            
            # Check for recompute
            if "recompute()" in line:
                has_recompute = True
            
            # Strip trailing whitespace
            line = line.rstrip()
            
            normalized_lines.append(line)
        
        # Ensure required imports at the beginning
        import_lines = []
        if not has_freecad_import:
            import_lines.append("import FreeCAD as App")
            meta.modules_used.append("FreeCAD")
        if not has_part_import:
            import_lines.append("import Part")
            meta.modules_used.append("Part")
        
        # Add optional imports if used
        if has_sketcher_import:
            meta.modules_used.append("Sketcher")
        if has_draft_import:
            meta.modules_used.append("Draft")
        if has_math_import:
            meta.modules_used.append("math")
        if has_numpy_import:
            meta.modules_used.append("numpy")
        
        # Ensure document creation
        if not has_document:
            import_lines.append("")
            import_lines.append("doc = App.newDocument()")
        
        # Combine imports with normalized lines
        if import_lines:
            normalized_lines = import_lines + [""] + normalized_lines
        
        # Ensure Part.show(result) if result variable exists
        if result_var and not any("Part.show" in line for line in normalized_lines):
            normalized_lines.append(f"Part.show({result_var})")
        
        # Ensure recompute at the end
        if not has_recompute:
            normalized_lines.append("doc.recompute()")
        
        # Ensure newline at EOF
        canonical_script = '\n'.join(normalized_lines)
        if not canonical_script.endswith('\n'):
            canonical_script += '\n'
        
        # Extract dimensions and features from script
        self._extract_script_metadata(canonical_script, meta)
        
        return canonical_script, meta
    
    def _apply_unit_conversions(
        self, 
        line: str, 
        line_number: int
    ) -> Tuple[str, List[UnitConversion]]:
        """Apply unit conversions to a line of code."""
        conversions = []
        
        # Pattern 1: Variable suffixes (e.g., length_cm, width_inch)
        suffix_pattern = r'(\w+)_(cm|inch|in)\s*=\s*([\d.]+)'
        matches = list(re.finditer(suffix_pattern, line))
        for match in matches:
            var_name = match.group(1)
            unit = match.group(2)
            value = float(match.group(3))
            
            if unit == "cm":
                new_value = value * 10
                from_unit = "cm"
            elif unit in ["inch", "in"]:
                new_value = value * 25.4
                from_unit = "inch"
            else:
                continue
            
            # Round to precision
            new_value = self._round_decimal(new_value)
            
            # Replace in line - match the original string exactly
            line = re.sub(
                f'{var_name}_{unit}\\s*=\\s*{match.group(3)}',
                f'{var_name} = {new_value}',
                line
            )
            
            conversions.append(UnitConversion(
                from_unit=from_unit,
                before=value,
                after=new_value,
                location=f"line {line_number + 1}"
            ))
        
        # Pattern 2: Inline comments (e.g., 12 # cm)
        comment_pattern = r'([\d.]+)\s*#\s*(cm|inch|in)\b'
        matches = list(re.finditer(comment_pattern, line))
        for match in matches:
            value = float(match.group(1))
            unit = match.group(2)
            
            if unit == "cm":
                new_value = value * 10
                from_unit = "cm"
            elif unit in ["inch", "in"]:
                new_value = value * 25.4
                from_unit = "inch"
            else:
                continue
            
            new_value = self._round_decimal(new_value)
            
            # Replace value and remove unit comment - match original string exactly
            line = re.sub(
                f'{match.group(1)}\\s*#\\s*{unit}',
                str(new_value),
                line
            )
            
            conversions.append(UnitConversion(
                from_unit=from_unit,
                before=value,
                after=new_value,
                location=f"line {line_number + 1}"
            ))
        
        # Pattern 3: Helper functions (e.g., cm(10), inch(5))
        helper_pattern = r'(cm|inch|in)\(([\d.]+)\)'
        matches = list(re.finditer(helper_pattern, line))
        for match in matches:
            unit = match.group(1)
            value = float(match.group(2))
            
            if unit == "cm":
                new_value = value * 10
                from_unit = "cm"
            elif unit in ["inch", "in"]:
                new_value = value * 25.4
                from_unit = "inch"
            else:
                continue
            
            new_value = self._round_decimal(new_value)
            
            # Replace with numeric literal - match original string exactly
            line = re.sub(
                f'{unit}\\({match.group(2)}\\)',
                str(new_value),
                line
            )
            
            conversions.append(UnitConversion(
                from_unit=from_unit,
                before=value,
                after=new_value,
                location=f"line {line_number + 1}"
            ))
        
        return line, conversions
    
    def _translate_turkish_comments(self, line: str) -> str:
        """Translate Turkish comments to English."""
        # Check if line has a comment
        if '#' not in line:
            return line
        
        # Split code and comment
        parts = line.split('#', 1)
        if len(parts) != 2:
            return line
        
        code_part = parts[0]
        comment_part = parts[1]
        
        # Translate words in comment
        for turkish, english in self.TURKISH_GLOSSARY.items():
            # Use word boundaries for accurate replacement
            pattern = r'\b' + re.escape(turkish) + r'\b'
            comment_part = re.sub(pattern, english, comment_part, flags=re.IGNORECASE)
        
        return code_part + '#' + comment_part
    
    def _extract_script_metadata(self, script: str, meta: ScriptMetadata):
        """Extract metadata from normalized script using AST parsing for robust extraction."""
        
        class MetadataExtractor(ast.NodeVisitor):
            """AST NodeVisitor for extracting FreeCAD script metadata."""
            
            def __init__(self, metadata: ScriptMetadata):
                self.meta = metadata
                self.current_var = None
                self.var_assignments = {}  # Track variable assignments
                self.solid_count = 0  # Track number of solids created
            
            def visit_Assign(self, node):
                """Track variable assignments and attribute assignments."""
                # Handle simple variable assignments
                if len(node.targets) == 1:
                    target = node.targets[0]
                    
                    # Simple variable assignment: var = value
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        self.current_var = var_name
                        
                        # Track solid creation
                        if isinstance(node.value, ast.Call):
                            func_name = self._get_func_name(node.value)
                            if func_name and any(op in func_name for op in 
                                               ['makeBox', 'makeCylinder', 'makeSphere', 
                                                'makeCone', 'makeTorus', 'fuse', 'cut', 'common']):
                                self.solid_count += 1
                        
                        # Track PartDesign objects
                        if isinstance(node.value, ast.Call):
                            func_name = self._get_func_name(node.value)
                            if func_name and 'newObject' in func_name:
                                if node.value.args and len(node.value.args) > 0:
                                    obj_type = self._get_string_value(node.value.args[0])
                                    if obj_type == 'PartDesign::Pad':
                                        self.var_assignments[var_name] = 'Pad'
                                    elif obj_type == 'PartDesign::Pocket':
                                        self.var_assignments[var_name] = 'Pocket'
                        
                        # Visit the value to extract metadata
                        # Note: We do NOT call generic_visit after this to avoid double processing
                        self.visit(node.value)
                        self.current_var = None
                        return  # Don't call generic_visit to avoid double processing
                    
                    # Attribute assignment: obj.attr = value
                    elif isinstance(target, ast.Attribute):
                        if isinstance(target.value, ast.Name):
                            obj_name = target.value.id
                            attr_name = target.attr
                            
                            # Extract numeric value
                            value = self._get_numeric_value(node.value)
                            
                            # Handle Length assignments for Pad/Pocket
                            if attr_name == 'Length' and value is not None:
                                # Check if this is a Pad or Pocket
                                if obj_name in self.var_assignments:
                                    obj_type = self.var_assignments[obj_name]
                                    if obj_type == 'Pad':
                                        self.meta.dims_mm["pad_length"] = value
                                    elif obj_type == 'Pocket':
                                        self.meta.dims_mm["pocket_depth"] = value
                                elif 'pad' in obj_name.lower():
                                    self.meta.dims_mm["pad_length"] = value
                                elif 'pocket' in obj_name.lower():
                                    self.meta.dims_mm["pocket_depth"] = value
                
                self.generic_visit(node)
            
            def visit_Call(self, node):
                """Extract metadata from function calls."""
                func_name = self._get_func_name(node)
                
                if not func_name:
                    self.generic_visit(node)
                    return
                
                # Extract Part.makeBox dimensions
                if 'makeBox' in func_name:
                    dims = self._extract_numeric_args(node, 3)
                    if len(dims) >= 3:
                        self.meta.dims_mm["length"] = dims[0]
                        self.meta.dims_mm["width"] = dims[1]
                        self.meta.dims_mm["height"] = dims[2]
                
                # Extract Part.makeCylinder dimensions
                elif 'makeCylinder' in func_name:
                    dims = self._extract_numeric_args(node, 2)
                    if len(dims) >= 2:
                        self.meta.dims_mm["radius"] = dims[0]
                        self.meta.dims_mm["cylinder_height"] = dims[1]
                
                # Extract Part.makeSphere dimensions
                elif 'makeSphere' in func_name:
                    dims = self._extract_numeric_args(node, 1)
                    if dims:
                        self.meta.dims_mm["sphere_radius"] = dims[0]
                
                # Extract Part.makeCone dimensions
                elif 'makeCone' in func_name:
                    dims = self._extract_numeric_args(node, 3)
                    if len(dims) >= 3:
                        self.meta.dims_mm["cone_radius1"] = dims[0]
                        self.meta.dims_mm["cone_radius2"] = dims[1]
                        self.meta.dims_mm["cone_height"] = dims[2]
                
                # Extract Part.makeTorus dimensions
                elif 'makeTorus' in func_name:
                    dims = self._extract_numeric_args(node, 2)
                    if len(dims) >= 2:
                        self.meta.dims_mm["torus_radius1"] = dims[0]
                        self.meta.dims_mm["torus_radius2"] = dims[1]
                
                # Extract PartDesign::Body creation
                elif 'addObject' in func_name or 'newObject' in func_name:
                    if node.args:
                        first_arg = self._get_string_value(node.args[0])
                        if first_arg == 'PartDesign::Body':
                            body_name = self._get_string_value(node.args[1]) if len(node.args) > 1 else 'Body'
                            # Initialize names list if it doesn't exist
                            if "names" not in self.meta.bodies:
                                self.meta.bodies["names"] = []
                            self.meta.bodies["names"].append(body_name)
                            self.meta.bodies["count"] = len(self.meta.bodies["names"])
                        
                        elif first_arg == 'PartDesign::Pad':
                            self.meta.partdesign_features.append({"type": "Pad"})
                        
                        elif first_arg == 'PartDesign::Pocket':
                            self.meta.partdesign_features.append({"type": "Pocket"})
                        
                        elif first_arg == 'PartDesign::Revolution':
                            self.meta.partdesign_features.append({"type": "Revolution"})
                        
                        elif first_arg == 'PartDesign::LinearPattern':
                            self.meta.partdesign_features.append({"type": "LinearPattern"})
                        
                        elif first_arg == 'PartDesign::PolarPattern':
                            self.meta.partdesign_features.append({"type": "PolarPattern"})
                
                # Extract Sketcher constraints
                elif 'addConstraint' in func_name:
                    if node.args:
                        constraint_type = self._get_constraint_type(node.args[0])
                        if constraint_type in self.SKETCHER_CONSTRAINTS:
                            if not any(s.get("name") == "MainSketch" for s in self.meta.sketches):
                                self.meta.sketches.append({
                                    "name": "MainSketch",
                                    "constraint_counts": {}
                                })
                            sketch = next(s for s in self.meta.sketches if s["name"] == "MainSketch")
                            sketch["constraint_counts"][constraint_type] = \
                                sketch["constraint_counts"].get(constraint_type, 0) + 1
                
                self.generic_visit(node)
            
            def visit_Attribute(self, node):
                """Track attribute assignments like pad.Length = 10."""
                # Look for patterns like obj.Length = value in parent context
                parent = getattr(node, '_parent', None)
                if parent and isinstance(parent, ast.Assign):
                    if node.attr == 'Length':
                        # Try to get the value being assigned
                        if isinstance(parent.value, (ast.Constant, ast.Num)):
                            value = self._get_numeric_value(parent.value)
                            if value is not None:
                                # Determine what type of object this is
                                if self.current_var and 'pad' in self.current_var.lower():
                                    self.meta.dims_mm["pad_length"] = value
                                elif self.current_var and 'pocket' in self.current_var.lower():
                                    self.meta.dims_mm["pocket_depth"] = value
                
                self.generic_visit(node)
            
            def _get_func_name(self, node):
                """Extract function name from a Call node."""
                if isinstance(node.func, ast.Name):
                    return node.func.id
                elif isinstance(node.func, ast.Attribute):
                    parts = []
                    current = node.func
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    return '.'.join(reversed(parts))
                return None
            
            def _extract_numeric_args(self, node, count):
                """Extract numeric arguments from a function call."""
                values = []
                for i, arg in enumerate(node.args[:count]):
                    value = self._get_numeric_value(arg)
                    if value is not None:
                        values.append(value)
                return values
            
            def _get_numeric_value(self, node):
                """Extract numeric value from an AST node."""
                if isinstance(node, ast.Constant):
                    if isinstance(node.value, (int, float)):
                        return float(node.value)
                elif isinstance(node, ast.Num):  # Python 3.7 compatibility
                    return float(node.n)
                elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                    # Handle negative numbers
                    inner_value = self._get_numeric_value(node.operand)
                    if inner_value is not None:
                        return -inner_value
                elif isinstance(node, ast.Name):
                    # Could track variable values if needed
                    pass
                return None
            
            def _get_string_value(self, node):
                """Extract string value from an AST node."""
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    return node.value
                elif isinstance(node, ast.Str):  # Python 3.7 compatibility
                    return node.s
                return None
            
            def _get_constraint_type(self, node):
                """Extract constraint type from constraint creation."""
                if isinstance(node, ast.Attribute):
                    return node.attr
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    return node.value
                elif isinstance(node, ast.Str):
                    return node.s
                return None
        
        # Parse the script into an AST
        try:
            tree = ast.parse(script)
            
            # Add parent references for context (helps with attribute assignments)
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    child._parent = parent
            
            # Create extractor with reference to engine's constraint list
            extractor = MetadataExtractor(meta)
            extractor.SKETCHER_CONSTRAINTS = self.SKETCHER_CONSTRAINTS
            
            # Visit the AST to extract metadata
            extractor.visit(tree)
            
            # Add solid count to metadata
            meta.bodies["solid_count"] = extractor.solid_count
            
            # Validate single solid rule if we have bodies
            if meta.bodies.get("count", 0) > 0 and extractor.solid_count > 1:
                meta.bodies["single_solid_ok"] = False
            else:
                meta.bodies["single_solid_ok"] = True
                
        except SyntaxError as e:
            logger.warning(f"Failed to parse script for metadata extraction: {e}")
            # Fall back to basic regex extraction for critical items
            self._fallback_regex_extraction(script, meta)
    
    def _fallback_regex_extraction(self, script: str, meta: ScriptMetadata):
        """Fallback regex-based extraction when AST parsing fails."""
        # Basic Part.makeBox extraction
        box_pattern = r'Part\.makeBox\(([\d.]+),\s*([\d.]+),\s*([\d.]+)\)'
        matches = re.finditer(box_pattern, script)
        for match in matches:
            meta.dims_mm["length"] = float(match.group(1))
            meta.dims_mm["width"] = float(match.group(2))
            meta.dims_mm["height"] = float(match.group(3))
        
        # Basic Part.makeCylinder extraction
        cyl_pattern = r'Part\.makeCylinder\(([\d.]+),\s*([\d.]+)\)'
        matches = re.finditer(cyl_pattern, script)
        for match in matches:
            meta.dims_mm["radius"] = float(match.group(1))
            meta.dims_mm["cylinder_height"] = float(match.group(2))
        
        # Basic body count
        body_pattern = r"addObject\(['\"]PartDesign::Body['\"]"
        meta.bodies["count"] = len(re.findall(body_pattern, script))
    
    def _validate_parametric(self, params: Dict[str, Any]):
        """Validate parametric input."""
        # Check required fields
        required_dims = ["l", "w", "h"] if all(k in params for k in ["l", "w", "h"]) \
                       else ["length", "width", "height"] if all(k in params for k in ["length", "width", "height"]) \
                       else ["radius", "height"] if all(k in params for k in ["radius", "height"]) \
                       else None
        
        if not required_dims and not any(k in params for k in ["l", "w", "h", "length", "width", "height", "radius"]):
            raise ValidationException(
                NormalizationErrorCode.AI_HINT_REQUIRED,
                "Missing required dimensions",
                "Gerekli boyutlar eksik: uzunluk, genişlik, yükseklik veya yarıçap/yükseklik gerekli",
                http_status=422,
                details={"missing": ["dimensions"]}
            )
        
        # Check units (should be mm after normalization)
        if params.get("units") != "mm":
            raise ValidationException(
                NormalizationErrorCode.MISSING_REQUIRED,
                "Units not normalized to mm",
                "Birimler mm'ye normalize edilmedi",
                http_status=422
            )
        
        # Check material
        if not params.get("material"):
            raise ValidationException(
                NormalizationErrorCode.AI_HINT_REQUIRED,
                "Missing material specification",
                "Malzeme belirtimi eksik",
                http_status=422,
                details={"missing": ["material"]}
            )
        
        # Check machine
        if not params.get("machine"):
            raise ValidationException(
                NormalizationErrorCode.AI_HINT_REQUIRED,
                "Missing machine specification",
                "Makine belirtimi eksik",
                http_status=422,
                details={"missing": ["machine"]}
            )
        
        # Validate ranges
        for key in ["l", "w", "h", "length", "width", "height", "radius"]:
            if key in params:
                value = params[key]
                if not (0.1 <= value <= 1000):
                    raise ValidationException(
                        NormalizationErrorCode.DIMENSION_ERROR,
                        f"Dimension out of range: {key}={value}mm",
                        f"Boyut limiti aşıldı: {key}={value} mm (izin: 0.1–1000 mm). Öneri: değeri aralığa çekin.",
                        http_status=422,
                        details={"dimension": key, "value": value, "min": 0.1, "max": 1000}
                    )
        
        # Check material-machine compatibility
        material = params.get("material", "").lower()
        machine = params.get("machine", "").lower()
        
        # Simple compatibility checks
        if material == "metal" and machine == "3d_printer":
            raise ValidationException(
                NormalizationErrorCode.MISSING_REQUIRED,
                "Material-machine incompatibility",
                "Malzeme-makine uyumsuzluğu: metal malzeme standart 3D yazıcıda işlenemez",
                http_status=422,
                details={"material": material, "machine": machine}
            )
        
        # Check for ambiguity - Only ambiguous if ALL THREE are provided
        # Having just 2 of these is valid (they define the third)
        has_radius = "radius" in params
        has_inner_radius = "innerradius" in params  # After normalization
        has_wall_thickness = "wallthickness" in params or "thickness" in params
        
        # Ambiguous only if all three are provided (over-constrained)
        if has_radius and has_inner_radius and has_wall_thickness:
            # All three provided - system is over-constrained
            ambiguous_fields = []
            if has_radius: ambiguous_fields.append("radius")
            if has_inner_radius: ambiguous_fields.append("innerradius")
            if has_wall_thickness: ambiguous_fields.append("wallthickness" if "wallthickness" in params else "thickness")
            
            raise ValidationException(
                NormalizationErrorCode.AMBIGUOUS_INPUT,
                "Ambiguous input: all three radius parameters provided (over-constrained)",
                "Belirsiz girdi: üç yarıçap parametresinin hepsi sağlandı (aşırı kısıtlı)",
                http_status=425,
                details={"ambiguous_fields": ambiguous_fields, 
                        "hint": "Provide only 2 of: radius, inner_radius, wall_thickness"}
            )
    
    def _validate_script(self, script: str, meta: ScriptMetadata):
        """Validate FreeCAD Python script."""
        # Parse AST
        try:
            tree = ast.parse(script)
        except SyntaxError as e:
            raise ValidationException(
                NormalizationErrorCode.INVALID_SYNTAX,
                f"Python syntax error: {e}",
                f"Python sözdizimi hatası: {e}. Çözüm: satır {e.lineno} yakınındaki hatayı düzeltin.",
                http_status=400,
                details={"line": e.lineno, "offset": e.offset}
            )
        
        # Security validation
        self._validate_security(tree)
        
        # API compatibility validation
        self._validate_api_compatibility(tree, meta)
        
        # Dimension validation
        self._validate_dimensions(meta)
        
        # PartDesign specific validation
        if meta.bodies.get("count", 0) > 0:
            self._validate_partdesign(script, meta)
    
    def _validate_security(self, tree: ast.AST):
        """Validate script security using AST."""
        
        class SecurityVisitor(ast.NodeVisitor):
            def __init__(self, engine):
                self.engine = engine
                self.imports = set()
                self.names = set()
                self.violations = []
            
            def visit_Import(self, node):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    self.imports.add(module)
                    if module not in FreeCADRulesEngine.ALLOWED_IMPORTS:
                        self.violations.append(f"Forbidden import: {module}")
                self.generic_visit(node)
            
            def visit_ImportFrom(self, node):
                if node.module:
                    module = node.module.split('.')[0]
                    self.imports.add(module)
                    if module not in FreeCADRulesEngine.ALLOWED_IMPORTS:
                        self.violations.append(f"Forbidden import: {module}")
                self.generic_visit(node)
            
            def visit_Name(self, node):
                name = node.id
                self.names.add(name)
                if name in FreeCADRulesEngine.FORBIDDEN_NAMES:
                    self.violations.append(f"Forbidden name: {name}")
                self.generic_visit(node)
            
            def visit_Attribute(self, node):
                # Check for forbidden attribute access
                if isinstance(node.value, ast.Name):
                    obj_name = node.value.id
                    attr_name = node.attr
                    
                    # Check numpy allowlist
                    if obj_name in ["numpy", "np"]:
                        if attr_name not in FreeCADRulesEngine.NUMPY_ALLOWLIST:
                            self.violations.append(
                                f"Forbidden numpy attribute: {attr_name}"
                            )
                    
                    # Check for os, sys, subprocess access
                    if obj_name in ["os", "sys", "subprocess"]:
                        self.violations.append(f"Forbidden module access: {obj_name}")
                    
                    # Check for sys.exit
                    if obj_name == "sys" and attr_name == "exit":
                        self.violations.append("Forbidden: sys.exit")
                
                self.generic_visit(node)
            
            def visit_Call(self, node):
                # Check for dangerous function calls
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in FreeCADRulesEngine.FORBIDDEN_NAMES:
                        self.violations.append(f"Forbidden function call: {func_name}")
                self.generic_visit(node)
        
        visitor = SecurityVisitor(self)
        visitor.visit(tree)
        
        if visitor.violations:
            violation = visitor.violations[0]
            symbol = violation.split(': ')[1] if ': ' in violation else violation
            raise ValidationException(
                NormalizationErrorCode.SECURITY_VIOLATION,
                f"Security violation: {violation}",
                f"Güvenlik ihlali: yasaklı komut/modül kullanımı tespit edildi: {symbol}. "
                f"Öneri: yalnızca izin verilen modülleri (FreeCAD, Part, Sketcher, Draft, math, numpy) "
                f"ve güvenli API'leri kullanın.",
                http_status=403,
                details={"violations": visitor.violations}
            )
    
    def _validate_api_compatibility(self, tree: ast.AST, meta: ScriptMetadata):
        """Validate FreeCAD API compatibility using comprehensive registry."""
        
        class APIVisitor(ast.NodeVisitor):
            def __init__(self, engine, meta):
                self.engine = engine
                self.meta = meta
                self.api_calls = []
                self.missing_apis = []
                self.deprecated_apis = []
                self.invalid_apis = []
            
            def visit_Call(self, node):
                """Validate function calls against API registry."""
                func_name = self._get_func_name(node)
                
                if func_name:
                    self.api_calls.append(func_name)
                    
                    # Check if API is in registry
                    if func_name in self.engine.FREECAD_API_REGISTRY:
                        # Validate argument count
                        api_spec = self.engine.FREECAD_API_REGISTRY[func_name]
                        arg_count = len(node.args)
                        
                        if arg_count < api_spec["min_args"]:
                            self.invalid_apis.append(
                                f"{func_name}: requires at least {api_spec['min_args']} args, got {arg_count}"
                            )
                        elif arg_count > api_spec["max_args"]:
                            self.invalid_apis.append(
                                f"{func_name}: accepts at most {api_spec['max_args']} args, got {arg_count}"
                            )
                    
                    # Check for deprecated APIs
                    elif func_name in self.engine.DEPRECATED_APIS:
                        suggestion = self.engine.DEPRECATED_APIS[func_name]
                        self.deprecated_apis.append(f"{func_name}: {suggestion}")
                        self.meta.api_warnings.append(f"API_DEPRECATED: {func_name} - {suggestion}")
                    
                    # Check for unknown/invalid APIs
                    elif any(part in func_name for part in ['Part.', 'App.', 'Sketcher.', 'PartDesign::']):
                        # It's a FreeCAD API call but not in our registry
                        # Try to find similar API
                        similar = self._find_similar_api(func_name)
                        if similar:
                            self.missing_apis.append(f"{func_name} (did you mean {similar}?)")
                        else:
                            self.missing_apis.append(func_name)
                
                self.generic_visit(node)
            
            def visit_Attribute(self, node):
                """Check for attribute-based API calls."""
                # Build full attribute chain
                chain = []
                current = node
                while isinstance(current, ast.Attribute):
                    chain.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    chain.append(current.id)
                
                chain.reverse()
                full_name = '.'.join(chain)
                
                # Check for deprecated attribute access
                if full_name in self.engine.DEPRECATED_APIS:
                    suggestion = self.engine.DEPRECATED_APIS[full_name]
                    self.deprecated_apis.append(f"{full_name}: {suggestion}")
                    self.meta.api_warnings.append(f"API_DEPRECATED: {full_name} - {suggestion}")
                
                self.generic_visit(node)
            
            def _get_func_name(self, node):
                """Extract function name from Call node."""
                if isinstance(node.func, ast.Name):
                    return node.func.id
                elif isinstance(node.func, ast.Attribute):
                    parts = []
                    current = node.func
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    return '.'.join(reversed(parts))
                return None
            
            def _find_similar_api(self, api_name):
                """Find similar API in registry (simple string similarity)."""
                # Simple similarity check - could be enhanced with Levenshtein distance
                api_parts = api_name.split('.')
                if len(api_parts) >= 2:
                    base = api_parts[0]
                    method = api_parts[-1]
                    
                    # Look for similar methods in same module
                    for registered_api in self.engine.FREECAD_API_REGISTRY:
                        if registered_api.startswith(base + '.'):
                            reg_method = registered_api.split('.')[-1]
                            if reg_method.lower() == method.lower():
                                return registered_api
                            # Check for common typos
                            if method.replace('make', '') == reg_method.replace('make', ''):
                                return registered_api
                return None
        
        visitor = APIVisitor(self, meta)
        visitor.visit(tree)
        
        # Report validation errors
        if visitor.invalid_apis:
            error = visitor.invalid_apis[0]
            raise ValidationException(
                NormalizationErrorCode.API_NOT_FOUND,
                f"Invalid API usage: {error}",
                f"Geçersiz API kullanımı: {error}",
                http_status=422,
                details={"invalid_apis": visitor.invalid_apis}
            )
        
        if visitor.missing_apis:
            api = visitor.missing_apis[0]
            raise ValidationException(
                NormalizationErrorCode.API_NOT_FOUND,
                f"API not found: {api}",
                f"API bulunamadı: {api} FreeCAD 1.1.0 içinde yok veya erişilemez.",
                http_status=422,
                details={"missing_apis": visitor.missing_apis}
            )
    
    def _validate_dimensions(self, meta: ScriptMetadata):
        """Validate dimensions are within limits."""
        for dim_name, value in meta.dims_mm.items():
            if value <= 0:
                continue  # Skip non-positive values (may be valid for some operations)
            
            if not (0.1 <= value <= 1000):
                raise ValidationException(
                    NormalizationErrorCode.DIMENSION_ERROR,
                    f"Dimension out of range: {dim_name}={value}mm",
                    f"Boyut limiti aşıldı: {dim_name}={value} mm (izin: 0.1–1000 mm). "
                    f"Öneri: değeri aralığa çekin.",
                    http_status=422,
                    details={"dimension": dim_name, "value": value, "min": 0.1, "max": 1000}
                )
        
        # Check angles if present
        for feature in meta.partdesign_features:
            if "draft_deg" in feature:
                angle = feature["draft_deg"]
                if not (-45 <= angle <= 45):
                    raise ValidationException(
                        NormalizationErrorCode.ANGLE_ERROR,
                        f"Draft angle out of range: {angle}°",
                        f"Açı limiti aşıldı: draft={angle}° (izin: -45–45°). "
                        f"Öneri: değeri aralığa çekin.",
                        http_status=422,
                        details={"angle": angle, "min": -45, "max": 45}
                    )
            
            if "angle_deg" in feature:
                angle = feature["angle_deg"]
                if feature.get("type") == "Revolution":
                    if not (0 < angle <= 360):
                        raise ValidationException(
                            NormalizationErrorCode.ANGLE_ERROR,
                            f"Revolution angle out of range: {angle}°",
                            f"Açı limiti aşıldı: revolution={angle}° (izin: 0–360°). "
                            f"Öneri: değeri aralığa çekin.",
                            http_status=422,
                            details={"angle": angle, "min": 0, "max": 360}
                        )
    
    def _validate_partdesign(self, script: str, meta: ScriptMetadata):
        """Validate PartDesign specific constraints."""
        # Check for unsupported constraints
        for sketch in meta.sketches:
            for constraint_type in sketch.get("constraint_counts", {}).keys():
                if constraint_type not in self.SKETCHER_CONSTRAINTS:
                    raise ValidationException(
                        NormalizationErrorCode.CONSTRAINT_UNSUPPORTED,
                        f"Unsupported constraint: {constraint_type}",
                        f"Desteklenmeyen Sketcher kısıtı: {constraint_type}. "
                        f"Öneri: izin verilen kısıtları kullanın: "
                        f"{', '.join(self.SKETCHER_CONSTRAINTS)}.",
                        http_status=422,
                        details={"constraint": constraint_type}
                    )
            
            # Check for under-constrained sketches (simplified check)
            dof = sketch.get("dof")
            if dof is not None and dof > 0:
                raise ValidationException(
                    NormalizationErrorCode.SKETCH_UNDERCONSTRAINED,
                    f"Sketch under-constrained: DoF={dof}",
                    f"Belirsizlik: eskiz yeterince kısıtlanmadı (DoF={dof}). "
                    f"Öneri: eksik kısıtları ekleyin veya boyutları netleştirin.",
                    http_status=425,
                    details={"sketch": sketch.get("name"), "dof": dof}
                )
        
        # Check for pattern errors
        for feature in meta.partdesign_features:
            if feature.get("type") == "LinearPattern":
                occurrences = feature.get("occurrences", 1)
                spacing = feature.get("spacing_mm", 1)
                
                if not (1 <= occurrences <= 1000):
                    raise ValidationException(
                        NormalizationErrorCode.PATTERN_ERROR,
                        f"Pattern occurrences out of range: {occurrences}",
                        f"Dizilim özelliği hatası: occurrences={occurrences}. "
                        f"Öneri: adet 1–1000, aralık 0.1–1000 mm, açı 0–360° olmalıdır.",
                        http_status=422,
                        details={"param": "occurrences", "value": occurrences}
                    )
                
                if not (0.1 <= spacing <= 1000):
                    raise ValidationException(
                        NormalizationErrorCode.PATTERN_ERROR,
                        f"Pattern spacing out of range: {spacing}mm",
                        f"Dizilim özelliği hatası: spacing={spacing}mm. "
                        f"Öneri: adet 1–1000, aralık 0.1–1000 mm, açı 0–360° olmalıdır.",
                        http_status=422,
                        details={"param": "spacing", "value": spacing}
                    )
            
            elif feature.get("type") == "PolarPattern":
                occurrences = feature.get("occurrences", 1)
                angle = feature.get("sweep_angle_deg", 360)
                
                if not (1 <= occurrences <= 1000):
                    raise ValidationException(
                        NormalizationErrorCode.PATTERN_ERROR,
                        f"Pattern occurrences out of range: {occurrences}",
                        f"Dizilim özelliği hatası: occurrences={occurrences}. "
                        f"Öneri: adet 1–1000, aralık 0.1–1000 mm, açı 0–360° olmalıdır.",
                        http_status=422,
                        details={"param": "occurrences", "value": occurrences}
                    )
                
                if not (0 <= angle <= 360):
                    raise ValidationException(
                        NormalizationErrorCode.PATTERN_ERROR,
                        f"Pattern angle out of range: {angle}°",
                        f"Dizilim özelliği hatası: angle={angle}°. "
                        f"Öneri: adet 1–1000, aralık 0.1–1000 mm, açı 0–360° olmalıdır.",
                        http_status=422,
                        details={"param": "angle", "value": angle}
                    )
        
        # Check single solid rule (simplified - would need actual geometry check)
        if meta.bodies.get("single_solid_ok") is False:
            body_name = meta.bodies.get("names", ["Body"])[0]
            raise ValidationException(
                NormalizationErrorCode.SINGLE_SOLID_VIOLATION,
                f"Body contains multiple solids",
                f"Tek katı kuralı ihlali: Body '{body_name}' birden fazla ayrı katı içeriyor. "
                f"Öneri: özellikleri birleştirerek tek bir sürekli katı oluşturun veya ayrı Body kullanın.",
                http_status=422,
                details={"body": body_name}
            )
    
    def _convert_to_mm(self, value: float, unit: str) -> float:
        """Convert a value from the given unit to millimeters."""
        if unit == "mm":
            return value
        elif unit == "cm":
            return value * 10
        elif unit in ["inch", "in"]:
            return value * 25.4
        else:
            # Unknown unit, assume mm
            return value
    
    def _round_decimal(self, value: float) -> float:
        """Round a value to 1e-6 precision using Decimal."""
        d = Decimal(str(value))
        return float(d.quantize(self.precision, rounding=ROUND_HALF_UP))


# Create singleton instance
freecad_rules_engine = FreeCADRulesEngine()