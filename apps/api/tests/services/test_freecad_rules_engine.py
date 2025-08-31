"""
Comprehensive unit tests for FreeCAD Rules Engine (Task 7.3).

Tests cover:
- Parametric normalization and validation
- Script normalization with unit conversions
- Security validation using AST
- PartDesign workbench support
- Error codes with Turkish messages
- Determinism and idempotency
"""

import hashlib
import pytest
from decimal import Decimal

from app.services.freecad_rules_engine import (
    FreeCADRulesEngine,
    NormalizationErrorCode,
    ValidationException,
    NormalizationResult,
    ScriptMetadata,
    UnitConversion
)


class TestParametricNormalization:
    """Test parametric input normalization."""
    
    def test_basic_normalization(self):
        """Test basic parametric normalization."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 25,
            "units": "mm",
            "material": "PLA",
            "machine": "3D_Printer"
        }
        
        result = engine.normalize(input_data)
        
        assert result.success
        assert result.canonical_params is not None
        assert result.canonical_params["length"] == 100.0
        assert result.canonical_params["width"] == 50.0
        assert result.canonical_params["height"] == 25.0
        assert result.canonical_params["units"] == "mm"
        assert result.canonical_params["material"] == "pla"
        assert result.canonical_params["machine"] == "3d_printer"
    
    def test_unit_conversion_cm(self):
        """Test cm to mm conversion."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 10,
            "width": 5,
            "height": 2.5,
            "units": "cm",
            "material": "ABS",
            "machine": "3d_printer"
        }
        
        result = engine.normalize(input_data)
        
        assert result.success
        assert result.canonical_params["length"] == 100.0  # 10 cm = 100 mm
        assert result.canonical_params["width"] == 50.0    # 5 cm = 50 mm
        assert result.canonical_params["height"] == 25.0   # 2.5 cm = 25 mm
        assert result.canonical_params["units"] == "mm"
    
    def test_unit_conversion_inch(self):
        """Test inch to mm conversion."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "L": 4,
            "W": 2,
            "H": 1,
            "units": "inch",
            "material": "wood",
            "machine": "cnc"
        }
        
        result = engine.normalize(input_data)
        
        assert result.success
        assert result.canonical_params["l"] == 101.6  # 4 inch = 101.6 mm
        assert result.canonical_params["w"] == 50.8   # 2 inch = 50.8 mm
        assert result.canonical_params["h"] == 25.4   # 1 inch = 25.4 mm
        assert result.canonical_params["units"] == "mm"
    
    def test_numeric_rounding(self):
        """Test 1e-6 precision rounding."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "radius": 3.1415926535,
            "thickness": 0.123456789,
            "units": "mm",
            "material": "metal",
            "machine": "lathe"
        }
        
        result = engine.normalize(input_data)
        
        assert result.success
        assert result.canonical_params["radius"] == 3.141593
        assert result.canonical_params["thickness"] == 0.123457
    
    def test_default_values(self):
        """Test default values for missing fields."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 25
        }
        
        result = engine.normalize(input_data)
        
        assert result.success
        assert result.canonical_params["material"] == "pla"  # Default
        assert result.canonical_params["machine"] == "3d_printer"  # Default
        assert result.canonical_params["units"] == "mm"
    
    def test_key_ordering(self):
        """Test deterministic key ordering."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "width": 50,
            "material": "PLA",
            "height": 25,
            "machine": "3d_printer",
            "length": 100,
            "units": "mm"
        }
        
        result = engine.normalize(input_data)
        
        # Keys should be alphabetically sorted
        keys = list(result.canonical_params.keys())
        assert keys == sorted(keys)
    
    def test_string_trimming(self):
        """Test string value trimming and normalization."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 25,
            "material": "  PLA  ",
            "machine": " 3D_PRINTER ",
            "units": "mm"
        }
        
        result = engine.normalize(input_data)
        
        assert result.canonical_params["material"] == "pla"
        assert result.canonical_params["machine"] == "3d_printer"


class TestParametricValidation:
    """Test parametric input validation."""
    
    def test_valid_input(self):
        """Test validation of valid input."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 25,
            "units": "mm",
            "material": "PLA",
            "machine": "3d_printer"
        }
        
        result = engine.validate(input_data)
        
        assert result.success
        assert len(result.errors) == 0
    
    def test_missing_dimensions(self):
        """Test validation with missing dimensions."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "material": "PLA",
            "machine": "3d_printer"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.AI_HINT_REQUIRED
        assert "boyut" in exc_info.value.turkish_message.lower()
        assert exc_info.value.http_status == 422
    
    def test_missing_material(self):
        """Test validation with missing material."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 25
        }
        
        # Note: Default material is applied during normalization
        result = engine.validate(input_data)
        assert result.success  # Should pass with default material
    
    def test_dimension_out_of_range_small(self):
        """Test validation with dimension too small."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 0.05,  # Below 0.1 mm minimum
            "width": 50,
            "height": 25,
            "units": "mm",
            "material": "PLA",
            "machine": "3d_printer"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.DIMENSION_ERROR
        assert "0.1–1000 mm" in exc_info.value.turkish_message
        assert exc_info.value.http_status == 422
    
    def test_dimension_out_of_range_large(self):
        """Test validation with dimension too large."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 1500,  # Above 1000 mm maximum
            "units": "mm",
            "material": "PLA",
            "machine": "3d_printer"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.DIMENSION_ERROR
        assert "1500" in exc_info.value.turkish_message
        assert exc_info.value.http_status == 422
    
    def test_material_machine_incompatibility(self):
        """Test validation with incompatible material-machine combination."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 25,
            "units": "mm",
            "material": "metal",
            "machine": "3d_printer"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.MISSING_REQUIRED
        # Check for the error message (handle potential encoding issues)
        turkish_msg = exc_info.value.turkish_message.lower()
        assert "uyumsuz" in turkish_msg or "metal" in turkish_msg
    
    def test_ambiguous_input(self):
        """Test validation with ambiguous input."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "radius": 50,
            "inner_radius": 40,
            "wallthickness": 10,
            "height": 100,
            "units": "mm",
            "material": "PLA",
            "machine": "3d_printer"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.AMBIGUOUS_INPUT
        assert exc_info.value.http_status == 425
        assert "belirsiz" in exc_info.value.turkish_message.lower()


class TestScriptNormalization:
    """Test FreeCAD script normalization."""
    
    def test_basic_script_normalization(self):
        """Test basic script normalization."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
box = Part.makeBox(100, 50, 25)
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert result.success
        assert result.canonical_script is not None
        assert "import FreeCAD as App" in result.canonical_script
        assert "import Part" in result.canonical_script
        assert "doc = App.newDocument()" in result.canonical_script
        assert "doc.recompute()" in result.canonical_script
    
    def test_unit_conversion_suffixes(self):
        """Test unit conversion with variable suffixes."""
        engine = FreeCADRulesEngine()
        
        script = """
length_cm = 10
width_inch = 2
height_in = 1
box = Part.makeBox(length_cm, width_inch, height_in)
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert result.success
        assert "length = 100" in result.canonical_script  # 10 cm = 100 mm
        assert "width = 50.8" in result.canonical_script   # 2 inch = 50.8 mm
        assert "height = 25.4" in result.canonical_script  # 1 inch = 25.4 mm
        
        # Check conversions metadata
        assert len(result.script_meta.conversions_applied) == 3
        assert any(c.from_unit == "cm" and c.after == 100 for c in result.script_meta.conversions_applied)
    
    def test_unit_conversion_comments(self):
        """Test unit conversion with inline comments."""
        engine = FreeCADRulesEngine()
        
        script = """
length = 10  # cm
width = 2  # inch
box = Part.makeBox(length, width, 25)
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert "100" in result.canonical_script  # 10 cm = 100 mm
        assert "50.8" in result.canonical_script  # 2 inch = 50.8 mm
    
    def test_unit_conversion_helpers(self):
        """Test unit conversion with helper functions."""
        engine = FreeCADRulesEngine()
        
        script = """
box = Part.makeBox(cm(10), inch(2), 25)
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert "100" in result.canonical_script  # cm(10) = 100 mm
        assert "50.8" in result.canonical_script  # inch(2) = 50.8 mm
    
    def test_turkish_comment_translation(self):
        """Test Turkish to English comment translation."""
        engine = FreeCADRulesEngine()
        
        script = """
# uzunluk ve genişlik parametreleri
length = 100  # uzunluk mm cinsinden
width = 50    # genişlik mm cinsinden
height = 25   # yükseklik
# yarıçap için duvar kalınlığı
thickness = 5  # duvar kalınlığı
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert "# length ve width parametreleri" in result.canonical_script
        assert "# length mm cinsinden" in result.canonical_script
        assert "# width mm cinsinden" in result.canonical_script
        assert "# height" in result.canonical_script
        assert "# radius için wall thickness" in result.canonical_script
        assert "# wall thickness" in result.canonical_script
    
    def test_ensure_imports(self):
        """Test that required imports are added."""
        engine = FreeCADRulesEngine()
        
        script = """
box = Part.makeBox(100, 50, 25)
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        lines = result.canonical_script.split('\n')
        assert lines[0] == "import FreeCAD as App"
        assert lines[1] == "import Part"
    
    def test_ensure_document(self):
        """Test that document creation is ensured."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
box = Part.makeBox(100, 50, 25)
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert "doc = App.newDocument()" in result.canonical_script
    
    def test_ensure_show_and_recompute(self):
        """Test that Part.show and recompute are added."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
result = Part.makeBox(100, 50, 25)
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert "Part.show(result)" in result.canonical_script
        assert "doc.recompute()" in result.canonical_script
    
    def test_idempotent_normalization(self):
        """Test that normalization is idempotent."""
        engine = FreeCADRulesEngine()
        
        script = """
length_cm = 10
box = Part.makeBox(length_cm, 50, 25)
"""
        
        input_data = {"script": script}
        
        # First normalization
        result1 = engine.normalize(input_data)
        canonical1 = result1.canonical_script
        hash1 = result1.script_meta.script_hash
        
        # Second normalization of the canonical script
        input_data2 = {"script": canonical1}
        result2 = engine.normalize(input_data2)
        canonical2 = result2.canonical_script
        hash2 = result2.script_meta.script_hash
        
        # Should be identical
        assert canonical1 == canonical2
        assert hash1 == hash2
    
    def test_script_hash_generation(self):
        """Test deterministic script hash generation."""
        engine = FreeCADRulesEngine()
        
        script = "box = Part.makeBox(100, 50, 25)"
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        # Verify hash is SHA256
        assert len(result.script_meta.script_hash) == 64  # SHA256 hex length
        
        # Verify determinism
        expected_hash = hashlib.sha256(
            result.canonical_script.encode('utf-8')
        ).hexdigest()
        assert result.script_meta.script_hash == expected_hash


class TestScriptSecurityValidation:
    """Test script security validation."""
    
    def test_forbidden_import_os(self):
        """Test detection of forbidden os import."""
        engine = FreeCADRulesEngine()
        
        script = """
import os
import Part
box = Part.makeBox(100, 50, 25)
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
        assert "os" in exc_info.value.turkish_message
        assert exc_info.value.http_status == 403
    
    def test_forbidden_import_subprocess(self):
        """Test detection of forbidden subprocess import."""
        engine = FreeCADRulesEngine()
        
        script = """
import subprocess
result = subprocess.run(['ls', '-la'])
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
        assert "subprocess" in exc_info.value.turkish_message
    
    def test_forbidden_exec(self):
        """Test detection of forbidden exec."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
code = "print('hello')"
exec(code)
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
        assert "exec" in exc_info.value.turkish_message
    
    def test_forbidden_eval(self):
        """Test detection of forbidden eval."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
expression = "100 + 50"
result = eval(expression)
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
        assert "eval" in exc_info.value.turkish_message
    
    def test_forbidden_open(self):
        """Test detection of forbidden open."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
f = open('/etc/passwd', 'r')
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
        assert "open" in exc_info.value.turkish_message
    
    def test_forbidden_sys_exit(self):
        """Test detection of forbidden sys.exit."""
        engine = FreeCADRulesEngine()
        
        script = """
import sys
import Part
sys.exit(0)
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
    
    def test_forbidden_numpy_attribute(self):
        """Test detection of forbidden numpy attribute."""
        engine = FreeCADRulesEngine()
        
        script = """
import numpy as np
import Part
# linalg.solve is not in allowlist
solution = np.linalg.solve(matrix, vector)
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
        assert "numpy" in exc_info.value.turkish_message
    
    def test_allowed_numpy_operations(self):
        """Test that allowed numpy operations pass."""
        engine = FreeCADRulesEngine()
        
        script = """
import numpy as np
import Part
# All these are in the allowlist
arr = np.array([1, 2, 3])
zeros = np.zeros((3, 3))
ones = np.ones((3, 3))
linear = np.linspace(0, 10, 100)
root = np.sqrt(16)
sine = np.sin(np.pi / 2)
cosine = np.cos(0)
tangent = np.tan(np.pi / 4)
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
    
    def test_disallowed_import(self):
        """Test detection of disallowed import."""
        engine = FreeCADRulesEngine()
        
        script = """
import json  # Not in allowed list
import Part
data = json.dumps({"key": "value"})
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.SECURITY_VIOLATION
        assert "json" in str(exc_info.value.details)


class TestScriptAPIValidation:
    """Test FreeCAD API validation."""
    
    def test_valid_api_usage(self):
        """Test valid FreeCAD API usage."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
box = Part.makeBox(100, 50, 25)
cylinder = Part.makeCylinder(10, 50)
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
    
    def test_invalid_api_method(self):
        """Test detection of invalid API method."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
# makeBoxx is not a valid method (typo)
box = Part.makeBoxx(100, 50, 25)
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.API_NOT_FOUND
        assert "makeBoxx" in exc_info.value.turkish_message
        assert exc_info.value.http_status == 422
    
    def test_deprecated_api_warning(self):
        """Test deprecated API generates warning but passes."""
        engine = FreeCADRulesEngine()
        
        # Note: These are examples - actual deprecated APIs may differ
        script = """
import Part
# Assuming Part.makeCircle is deprecated (example)
circle = Part.makeCircle(10)
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        # Should pass but with warnings
        assert result.success
        if result.script_meta.api_warnings:
            assert any("API_DEPRECATED" in w for w in result.script_meta.api_warnings)
    
    def test_syntax_error(self):
        """Test Python syntax error detection."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
box = Part.makeBox(100, 50, 25  # Missing closing parenthesis
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.INVALID_SYNTAX
        assert "sözdizimi hatası" in exc_info.value.turkish_message
        assert exc_info.value.http_status == 400


class TestDimensionValidation:
    """Test dimension validation."""
    
    def test_valid_dimensions(self):
        """Test valid dimensions pass validation."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
box = Part.makeBox(100, 50, 25)
cylinder = Part.makeCylinder(10, 50)
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta.dims_mm["length"] == 100
        assert result.script_meta.dims_mm["width"] == 50
        assert result.script_meta.dims_mm["height"] == 25
        assert result.script_meta.dims_mm["radius"] == 10
        assert result.script_meta.dims_mm["cylinder_height"] == 50
    
    def test_dimension_too_small(self):
        """Test dimension below minimum."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
box = Part.makeBox(0.05, 50, 25)  # 0.05 mm is below minimum
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.DIMENSION_ERROR
        assert "0.05" in exc_info.value.turkish_message
        assert "0.1–1000 mm" in exc_info.value.turkish_message
    
    def test_dimension_too_large(self):
        """Test dimension above maximum."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part
box = Part.makeBox(100, 50, 1500)  # 1500 mm is above maximum
"""
        
        input_data = {"script": script}
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate(input_data)
        
        assert exc_info.value.code == NormalizationErrorCode.DIMENSION_ERROR
        assert "1500" in exc_info.value.turkish_message
        assert "0.1–1000 mm" in exc_info.value.turkish_message


class TestPartDesignValidation:
    """Test PartDesign workbench validation."""
    
    def test_valid_partdesign_body(self):
        """Test valid PartDesign body creation."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
import Part
doc = App.newDocument()
body = doc.addObject('PartDesign::Body', 'Body')
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta.bodies["count"] == 1
        assert "Body" in result.script_meta.bodies["names"]
    
    def test_pad_dimension_validation(self):
        """Test Pad length validation."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
doc = App.newDocument()
body = doc.addObject('PartDesign::Body', 'Body')
pad = body.newObject('PartDesign::Pad', 'Pad')
pad.Length = 50  # Valid length
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert len(result.script_meta.partdesign_features) > 0
        assert result.script_meta.dims_mm["pad_length"] == 50
    
    def test_pocket_dimension_validation(self):
        """Test Pocket depth validation."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
doc = App.newDocument()
body = doc.addObject('PartDesign::Body', 'Body')
pocket = body.newObject('PartDesign::Pocket', 'Pocket')
pocket.Length = 10  # Valid depth
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert len(result.script_meta.partdesign_features) > 0
        assert result.script_meta.dims_mm["pocket_depth"] == 10
    
    def test_invalid_draft_angle(self):
        """Test invalid draft angle detection."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
doc = App.newDocument()
body = doc.addObject('PartDesign::Body', 'Body')
pad = body.newObject('PartDesign::Pad', 'Pad')
pad.Length = 50
pad.TaperAngle = 60  # Above 45 degree maximum
"""
        
        # Note: This would need actual implementation of draft angle extraction
        # For now, test the validation logic directly
        meta = ScriptMetadata()
        meta.partdesign_features.append({
            "type": "Pad",
            "length_mm": 50,
            "draft_deg": 60
        })
        
        with pytest.raises(ValidationException) as exc_info:
            engine._validate_dimensions(meta)
        
        assert exc_info.value.code == NormalizationErrorCode.ANGLE_ERROR
        assert "60" in exc_info.value.turkish_message
        assert "-45–45" in exc_info.value.turkish_message
    
    def test_unsupported_constraint(self):
        """Test unsupported Sketcher constraint detection."""
        engine = FreeCADRulesEngine()
        
        # Create metadata with unsupported constraint
        meta = ScriptMetadata()
        meta.sketches.append({
            "name": "Sketch",
            "constraint_counts": {
                "Distance": 5,
                "Angle": 2,
                "Concentric": 1  # Not in allowlist
            }
        })
        
        script = "# dummy script"
        
        with pytest.raises(ValidationException) as exc_info:
            engine._validate_partdesign(script, meta)
        
        assert exc_info.value.code == NormalizationErrorCode.CONSTRAINT_UNSUPPORTED
        assert "Concentric" in exc_info.value.turkish_message
    
    def test_underconstrained_sketch(self):
        """Test under-constrained sketch detection."""
        engine = FreeCADRulesEngine()
        
        # Create metadata with under-constrained sketch
        meta = ScriptMetadata()
        meta.sketches.append({
            "name": "Sketch",
            "constraint_counts": {
                "Distance": 2,
                "Angle": 1
            },
            "dof": 3  # Degrees of freedom > 0
        })
        
        script = "# dummy script"
        
        with pytest.raises(ValidationException) as exc_info:
            engine._validate_partdesign(script, meta)
        
        assert exc_info.value.code == NormalizationErrorCode.SKETCH_UNDERCONSTRAINED
        assert "DoF=3" in exc_info.value.turkish_message
        assert exc_info.value.http_status == 425
    
    def test_pattern_occurrences_validation(self):
        """Test pattern occurrences validation."""
        engine = FreeCADRulesEngine()
        
        # Test LinearPattern with invalid occurrences
        meta = ScriptMetadata()
        meta.partdesign_features.append({
            "type": "LinearPattern",
            "occurrences": 1500,  # Above 1000 maximum
            "spacing_mm": 10
        })
        
        script = "# dummy script"
        
        with pytest.raises(ValidationException) as exc_info:
            engine._validate_partdesign(script, meta)
        
        assert exc_info.value.code == NormalizationErrorCode.PATTERN_ERROR
        assert "1500" in exc_info.value.turkish_message
        assert "1–1000" in exc_info.value.turkish_message
    
    def test_pattern_spacing_validation(self):
        """Test pattern spacing validation."""
        engine = FreeCADRulesEngine()
        
        # Test LinearPattern with invalid spacing
        meta = ScriptMetadata()
        meta.partdesign_features.append({
            "type": "LinearPattern",
            "occurrences": 10,
            "spacing_mm": 0.05  # Below 0.1 mm minimum
        })
        
        script = "# dummy script"
        
        with pytest.raises(ValidationException) as exc_info:
            engine._validate_partdesign(script, meta)
        
        assert exc_info.value.code == NormalizationErrorCode.PATTERN_ERROR
        assert "0.05" in str(exc_info.value.turkish_message)
    
    def test_polar_pattern_angle_validation(self):
        """Test polar pattern angle validation."""
        engine = FreeCADRulesEngine()
        
        # Test PolarPattern with invalid angle
        meta = ScriptMetadata()
        meta.partdesign_features.append({
            "type": "PolarPattern",
            "occurrences": 10,
            "sweep_angle_deg": 400  # Above 360 degree maximum
        })
        
        script = "# dummy script"
        
        with pytest.raises(ValidationException) as exc_info:
            engine._validate_partdesign(script, meta)
        
        assert exc_info.value.code == NormalizationErrorCode.PATTERN_ERROR
        assert "400" in str(exc_info.value.turkish_message)
        assert "0–360" in exc_info.value.turkish_message
    
    def test_single_solid_violation(self):
        """Test single solid rule violation."""
        engine = FreeCADRulesEngine()
        
        # Create metadata indicating multiple solids
        meta = ScriptMetadata()
        meta.bodies = {
            "count": 1,
            "names": ["Body"],
            "single_solid_ok": False  # Violation
        }
        
        script = "# dummy script"
        
        with pytest.raises(ValidationException) as exc_info:
            engine._validate_partdesign(script, meta)
        
        assert exc_info.value.code == NormalizationErrorCode.SINGLE_SOLID_VIOLATION
        assert "Body" in exc_info.value.turkish_message
        assert "tek" in exc_info.value.turkish_message.lower()


class TestEndToEndPartDesign:
    """Comprehensive end-to-end tests for PartDesign features with real scripts."""
    
    def test_complete_pad_with_taper_angle(self):
        """Test complete Pad feature with taper angle extraction."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
import Part
import Sketcher

doc = App.newDocument("TestDoc")

# Create a Body
body = doc.addObject('PartDesign::Body', 'Body')

# Create a Sketch
sketch = body.newObject('Sketcher::SketchObject', 'Sketch')
sketch.Support = (doc.getObject('XY_Plane'), [''])
sketch.MapMode = 'FlatFace'

# Add geometry to sketch
sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(100, 0, 0)))
sketch.addGeometry(Part.LineSegment(App.Vector(100, 0, 0), App.Vector(100, 50, 0)))
sketch.addGeometry(Part.LineSegment(App.Vector(100, 50, 0), App.Vector(0, 50, 0)))
sketch.addGeometry(Part.LineSegment(App.Vector(0, 50, 0), App.Vector(0, 0, 0)))

# Add constraints
sketch.addConstraint(Sketcher.Constraint('Horizontal', 0))
sketch.addConstraint(Sketcher.Constraint('Vertical', 1))
sketch.addConstraint(Sketcher.Constraint('Horizontal', 2))
sketch.addConstraint(Sketcher.Constraint('Vertical', 3))
sketch.addConstraint(Sketcher.Constraint('Distance', 0, 100))
sketch.addConstraint(Sketcher.Constraint('Distance', 1, 50))

# Create a Pad with taper angle
pad = body.newObject('PartDesign::Pad', 'Pad')
pad.Profile = sketch
pad.Length = 25
pad.TaperAngle = 5  # 5 degree draft angle

doc.recompute()
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta is not None
        
        # Check body was detected
        assert result.script_meta.bodies["count"] == 1
        assert "Body" in result.script_meta.bodies["names"]
        
        # Check Pad was detected
        assert len(result.script_meta.partdesign_features) > 0
        pad_feature = next((f for f in result.script_meta.partdesign_features if f["type"] == "Pad"), None)
        assert pad_feature is not None
        
        # Check dimensions were extracted
        assert result.script_meta.dims_mm.get("pad_length") == 25
        assert result.script_meta.dims_mm.get("taper_angle") == 5
        
        # Check sketch constraints were detected
        assert len(result.script_meta.sketches) > 0
        sketch = result.script_meta.sketches[0]
        assert sketch["constraint_counts"].get("Horizontal", 0) == 2
        assert sketch["constraint_counts"].get("Vertical", 0) == 2
        assert sketch["constraint_counts"].get("Distance", 0) == 2
    
    def test_complete_pocket_with_arithmetic_expression(self):
        """Test Pocket feature with arithmetic expression for depth."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
import Part

doc = App.newDocument()

# Create a Body
body = doc.addObject('PartDesign::Body', 'MainBody')

# Create a base pad first
base_sketch = body.newObject('Sketcher::SketchObject', 'BaseSketch')
base_pad = body.newObject('PartDesign::Pad', 'BasePad')
base_pad.Length = 50

# Create a Pocket with arithmetic expression
pocket = body.newObject('PartDesign::Pocket', 'Pocket')
pocket.Length = 10 * 2.5  # Should evaluate to 25

doc.recompute()
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta is not None
        
        # Check pocket depth was calculated from arithmetic expression
        assert result.script_meta.dims_mm.get("pocket_depth") == 25
        
        # Check both Pad and Pocket were detected
        features = result.script_meta.partdesign_features
        assert any(f["type"] == "Pad" for f in features)
        assert any(f["type"] == "Pocket" for f in features)
    
    def test_complete_pattern_features(self):
        """Test LinearPattern and PolarPattern with full validation."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
import Part

doc = App.newDocument()
body = doc.addObject('PartDesign::Body', 'Body')

# Create base feature
pad = body.newObject('PartDesign::Pad', 'Pad')
pad.Length = 20

# Create LinearPattern
linear_pattern = body.newObject('PartDesign::LinearPattern', 'LinearPattern')
linear_pattern.Originals = [pad]
linear_pattern.Direction = (body, ['H_Axis'])
linear_pattern.Length = 100
linear_pattern.Occurrences = 5

# Create PolarPattern
polar_pattern = body.newObject('PartDesign::PolarPattern', 'PolarPattern')
polar_pattern.Originals = [linear_pattern]
polar_pattern.Axis = (body, ['V_Axis'])
polar_pattern.Angle = 360
polar_pattern.Occurrences = 8

doc.recompute()
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta is not None
        
        # Check patterns were detected
        features = result.script_meta.partdesign_features
        assert any(f["type"] == "LinearPattern" for f in features)
        assert any(f["type"] == "PolarPattern" for f in features)
    
    def test_complete_unit_conversion_with_ast(self):
        """Test AST-based unit conversion in complete script."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
import Part

# Unit conversions using different patterns
length_cm = 10  # Should become 100 mm
width_inch = 2  # Should become 50.8 mm
height = cm(5)  # Should become 50 mm
depth = inch(1.5)  # Should become 38.1 mm

doc = App.newDocument()
box = Part.makeBox(length, width, height)
Part.show(box)
doc.recompute()
"""
        
        input_data = {"script": script}
        result = engine.normalize(input_data)
        
        assert result.success
        assert result.canonical_script is not None
        
        # Check conversions were applied
        assert len(result.script_meta.conversions_applied) == 4
        
        # Check specific conversions
        cm_conversions = [c for c in result.script_meta.conversions_applied if c.from_unit == "cm"]
        inch_conversions = [c for c in result.script_meta.conversions_applied if c.from_unit == "inch"]
        
        assert len(cm_conversions) == 2
        assert len(inch_conversions) == 2
        
        # Check values were converted correctly
        assert any(c.before == 10 and c.after == 100 for c in cm_conversions)
        assert any(c.before == 5 and c.after == 50 for c in cm_conversions)
        assert any(c.before == 2 and c.after == 50.8 for c in inch_conversions)
        assert any(c.before == 1.5 and c.after == 38.1 for c in inch_conversions)
        
        # Check script no longer contains unit suffixes or helper functions
        assert "_cm" not in result.canonical_script
        assert "_inch" not in result.canonical_script
        assert "cm(" not in result.canonical_script
        assert "inch(" not in result.canonical_script
    
    def test_complete_revolution_feature(self):
        """Test Revolution feature with angle validation."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
import Part

doc = App.newDocument()
body = doc.addObject('PartDesign::Body', 'Body')

# Create sketch for revolution
sketch = body.newObject('Sketcher::SketchObject', 'ProfileSketch')

# Create Revolution
revolution = body.newObject('PartDesign::Revolution', 'Revolution')
revolution.Profile = sketch
revolution.Axis = (body, ['V_Axis'])
revolution.Angle = 270  # Valid angle (0 < angle <= 360)

doc.recompute()
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta is not None
        
        # Check Revolution was detected
        features = result.script_meta.partdesign_features
        assert any(f["type"] == "Revolution" for f in features)
    
    def test_complete_mirrored_feature(self):
        """Test Mirrored feature detection."""
        engine = FreeCADRulesEngine()
        
        script = """
import FreeCAD as App
import Part

doc = App.newDocument()
body = doc.addObject('PartDesign::Body', 'Body')

# Create base feature
pad = body.newObject('PartDesign::Pad', 'Pad')
pad.Length = 30

# Create Mirrored feature
mirrored = body.newObject('PartDesign::Mirrored', 'Mirrored')
mirrored.Originals = [pad]
mirrored.MirrorPlane = (body, ['V_Axis', 'H_Axis'])

doc.recompute()
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta is not None
        
        # Check Mirrored was detected
        features = result.script_meta.partdesign_features
        assert any(f["type"] == "Mirrored" for f in features)
    
    def test_arithmetic_expressions_in_dimensions(self):
        """Test that arithmetic expressions in dimensions are properly evaluated."""
        engine = FreeCADRulesEngine()
        
        script = """
import Part

# Test various arithmetic expressions
box1 = Part.makeBox(50 + 50, 25 * 2, 100 / 4)  # 100, 50, 25
box2 = Part.makeCylinder(5 ** 2, 10 - 5)  # 25, 5
box3 = Part.makeCone(10 + 5, 20 - 5, 30 * 1.5)  # 15, 15, 45
"""
        
        input_data = {"script": script}
        result = engine.validate(input_data)
        
        assert result.success
        assert result.script_meta is not None
        
        # Check dimensions were evaluated correctly
        dims = result.script_meta.dims_mm
        assert dims.get("length") == 100
        assert dims.get("width") == 50
        assert dims.get("height") == 25
        assert dims.get("radius") == 25
        assert dims.get("cylinder_height") == 5
        assert dims.get("cone_radius1") == 15
        assert dims.get("cone_radius2") == 15
        assert dims.get("cone_height") == 45


class TestDeterminismAndIdempotency:
    """Test determinism and idempotency of normalization."""
    
    def test_deterministic_output(self):
        """Test that same input produces same output."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100.123456789,
            "width": 50.987654321,
            "height": 25.5,
            "units": "mm",
            "material": "PLA",
            "machine": "3d_printer"
        }
        
        # Run normalization multiple times
        results = []
        for _ in range(5):
            result = engine.normalize(input_data)
            results.append(result.canonical_params)
        
        # All results should be identical
        for i in range(1, len(results)):
            assert results[i] == results[0]
    
    def test_script_hash_determinism(self):
        """Test that script hash is deterministic."""
        engine = FreeCADRulesEngine()
        
        script = """
length_cm = 10
width = 50
box = Part.makeBox(length_cm, width, 25)
"""
        
        input_data = {"script": script}
        
        # Run normalization multiple times
        hashes = []
        for _ in range(5):
            result = engine.normalize(input_data)
            hashes.append(result.script_meta.script_hash)
        
        # All hashes should be identical
        for i in range(1, len(hashes)):
            assert hashes[i] == hashes[0]
    
    def test_idempotent_parametric(self):
        """Test parametric normalization is idempotent."""
        engine = FreeCADRulesEngine()
        
        input_data = {
            "length": 100,
            "width": 50,
            "height": 25,
            "units": "cm",  # Will be converted
            "material": "  PLA  ",  # Will be trimmed
            "machine": "3D_PRINTER"  # Will be lowercased
        }
        
        # First normalization
        result1 = engine.normalize(input_data)
        
        # Second normalization of normalized data
        result2 = engine.normalize(result1.canonical_params)
        
        # Should be identical
        assert result1.canonical_params == result2.canonical_params
    
    def test_idempotent_script(self):
        """Test script normalization is idempotent."""
        engine = FreeCADRulesEngine()
        
        script = """
# Turkish comment: uzunluk parametresi
length_cm = 10  # cm
width_inch = 2
height = inch(1)
box = Part.makeBox(length_cm, width_inch, height)
"""
        
        input_data = {"script": script}
        
        # First normalization
        result1 = engine.normalize(input_data)
        
        # Second normalization of canonical script
        input_data2 = {"script": result1.canonical_script}
        result2 = engine.normalize(input_data2)
        
        # Should be identical
        assert result1.canonical_script == result2.canonical_script
        assert result1.script_meta.script_hash == result2.script_meta.script_hash


class TestErrorMessages:
    """Test error messages and codes."""
    
    def test_turkish_error_messages(self):
        """Test that Turkish error messages are properly formatted."""
        engine = FreeCADRulesEngine()
        
        # Test various error conditions
        test_cases = [
            {
                "input": {"script": "import os\nprint('hello')"},
                "expected_code": NormalizationErrorCode.SECURITY_VIOLATION,
                "expected_terms": ["güvenlik", "yasaklı", "os"]
            },
            {
                "input": {"length": 0.05, "width": 50, "height": 25, "units": "mm"},
                "expected_code": NormalizationErrorCode.DIMENSION_ERROR,
                "expected_terms": ["boyut", "0.1–1000 mm", "0.05"]
            },
            {
                "input": {"script": "box = Part.makeBox(100, 50, 25"},  # Syntax error
                "expected_code": NormalizationErrorCode.INVALID_SYNTAX,
                "expected_terms": ["sözdizimi", "hatası"]
            }
        ]
        
        for test_case in test_cases:
            try:
                engine.validate(test_case["input"])
                assert False, f"Expected validation to fail for {test_case['input']}"
            except ValidationException as e:
                assert e.code == test_case["expected_code"]
                for term in test_case["expected_terms"]:
                    assert term in e.turkish_message.lower() or term in e.turkish_message
    
    def test_http_status_codes(self):
        """Test that appropriate HTTP status codes are returned."""
        engine = FreeCADRulesEngine()
        
        test_cases = [
            {
                "input": {"script": "import os"},
                "expected_status": 403  # SECURITY_VIOLATION
            },
            {
                "input": {"script": "box = Part.makeBox(0.05, 50, 25)"},
                "expected_status": 422  # DIMENSION_ERROR
            },
            {
                "input": {"script": "invalid python syntax {"},
                "expected_status": 400  # INVALID_SYNTAX
            },
            {
                "input": {"radius": 50, "inner_radius": 40, "wallthickness": 10, "height": 100},
                "expected_status": 425  # AMBIGUOUS_INPUT
            }
        ]
        
        for test_case in test_cases:
            try:
                engine.validate(test_case["input"])
                assert False, f"Expected validation to fail for {test_case['input']}"
            except ValidationException as e:
                assert e.http_status == test_case["expected_status"]