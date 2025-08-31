"""Test cases for strict dimension validation in FreeCAD Rules Engine."""

import pytest

from app.services.freecad_rules_engine import FreeCADRulesEngine, ValidationException


class TestDimensionValidation:
    """Test cases for strict dimension validation."""
    
    def test_complete_box_dimensions_lwh(self):
        """Test that complete box dimensions with l, w, h are accepted."""
        engine = FreeCADRulesEngine()
        params = {
            "l": 100,
            "w": 50,
            "h": 25,
            "units": "mm",
            "material": "aluminum"
        }
        result = engine.validate({"params": params})
        assert result.success
    
    def test_complete_box_dimensions_full(self):
        """Test that complete box dimensions with length, width, height are accepted."""
        engine = FreeCADRulesEngine()
        params = {
            "length": 100,
            "width": 50,
            "height": 25,
            "units": "mm",
            "material": "aluminum"
        }
        result = engine.validate({"params": params})
        assert result.success
    
    def test_complete_cylinder_dimensions(self):
        """Test that complete cylinder dimensions are accepted."""
        engine = FreeCADRulesEngine()
        params = {
            "radius": 30,
            "height": 50,
            "units": "mm",
            "material": "steel"
        }
        result = engine.validate({"params": params})
        assert result.success
    
    def test_incomplete_box_dimensions_partial_lwh(self):
        """Test that partial box dimensions (only l and w) are rejected."""
        engine = FreeCADRulesEngine()
        params = {
            "l": 100,
            "w": 50,
            # Missing "h"
            "units": "mm",
            "material": "aluminum"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate({"params": params})
        
        assert "Incomplete set of dimensions provided" in str(exc_info.value)
        assert set(exc_info.value.details["provided_keys"]) == {"l", "w"}
    
    def test_incomplete_box_dimensions_partial_full(self):
        """Test that partial box dimensions (only length) are rejected."""
        engine = FreeCADRulesEngine()
        params = {
            "length": 100,
            # Missing "width" and "height"
            "units": "mm",
            "material": "aluminum"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate({"params": params})
        
        assert "Incomplete set of dimensions provided" in str(exc_info.value)
        assert exc_info.value.details["provided_keys"] == ["length"]
    
    def test_incomplete_cylinder_dimensions(self):
        """Test that partial cylinder dimensions (only radius) are rejected."""
        engine = FreeCADRulesEngine()
        params = {
            "radius": 30,
            # Missing "height"
            "units": "mm",
            "material": "steel"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate({"params": params})
        
        assert "Incomplete set of dimensions provided" in str(exc_info.value)
        assert exc_info.value.details["provided_keys"] == ["radius"]
    
    def test_mixed_dimension_keys_rejected(self):
        """Test that mixing dimension key styles (l with length) is rejected."""
        engine = FreeCADRulesEngine()
        params = {
            "l": 100,
            "length": 100,  # Mixing styles
            "width": 50,
            "units": "mm",
            "material": "aluminum"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate({"params": params})
        
        assert "Incomplete set of dimensions provided" in str(exc_info.value)
    
    def test_no_dimensions_provided(self):
        """Test that no dimensions triggers different error message."""
        engine = FreeCADRulesEngine()
        params = {
            "units": "mm",
            "material": "aluminum"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate({"params": params})
        
        assert "Missing required dimensions" in str(exc_info.value)
        assert exc_info.value.details["missing"] == ["dimensions"]
    
    def test_only_one_dimension_type(self):
        """Test that providing only 'h' without 'l' and 'w' is rejected."""
        engine = FreeCADRulesEngine()
        params = {
            "h": 25,
            # Missing "l" and "w" 
            "units": "mm",
            "material": "aluminum"
        }
        
        with pytest.raises(ValidationException) as exc_info:
            engine.validate({"params": params})
        
        assert "Incomplete set of dimensions provided" in str(exc_info.value)
        assert exc_info.value.details["provided_keys"] == ["h"]