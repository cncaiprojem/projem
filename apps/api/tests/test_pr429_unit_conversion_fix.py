"""
Test fixes for PR #429 - Unit conversion enum AttributeError and duplicated dictionaries.

This test verifies:
1. Units enum members are correctly named (singular, not plural)
2. Unit conversion uses centralized UNIT_CONVERSION_FACTORS
3. STL, STEP, DXF, and IFC handlers all use the same conversion logic
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

import sys
from pathlib import Path
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.upload_normalization_service import (
    Units,
    UNIT_CONVERSION_FACTORS,
    STLHandler,
    STEPHandler,
    DXFHandler,
    IFCHandler,
    NormalizationConfig,
    GeometryMetrics
)


class TestPR429UnitConversionFixes:
    """Test suite for PR #429 critical unit conversion fixes."""
    
    def test_units_enum_has_correct_singular_names(self):
        """Verify Units enum uses singular forms, not plural."""
        # These should exist (singular forms)
        assert Units.MILLIMETER == "mm"
        assert Units.METER == "m"
        assert Units.INCH == "inch"
        assert Units.FOOT == "ft"
        assert Units.CENTIMETER == "cm"
        assert Units.UNKNOWN == "unknown"
        
        # These should NOT exist (plural forms that caused AttributeError)
        with pytest.raises(AttributeError):
            _ = Units.INCHES
        with pytest.raises(AttributeError):
            _ = Units.METERS
        with pytest.raises(AttributeError):
            _ = Units.CENTIMETERS
            
    def test_centralized_unit_conversion_factors_exists(self):
        """Verify centralized UNIT_CONVERSION_FACTORS constant exists and is correct."""
        assert UNIT_CONVERSION_FACTORS is not None
        assert isinstance(UNIT_CONVERSION_FACTORS, dict)
        
        # Verify all expected units are present with correct conversion factors
        assert UNIT_CONVERSION_FACTORS["mm"] == 1.0  # Base unit
        assert UNIT_CONVERSION_FACTORS["m"] == 1000.0  # 1 meter = 1000 mm
        assert UNIT_CONVERSION_FACTORS["inch"] == 25.4  # 1 inch = 25.4 mm
        assert UNIT_CONVERSION_FACTORS["ft"] == 304.8  # 1 foot = 304.8 mm
        assert UNIT_CONVERSION_FACTORS["cm"] == 10.0  # 1 cm = 10 mm
        assert UNIT_CONVERSION_FACTORS["unknown"] == 1.0  # No conversion
        
    @patch('app.services.upload_normalization_service.TRIMESH_AVAILABLE', True)
    @patch('app.services.upload_normalization_service.trimesh')
    def test_stl_handler_uses_correct_unit_enum_members(self, mock_trimesh):
        """Test STL handler uses singular Units enum members correctly."""
        # Setup mock mesh
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = True
        mock_mesh.is_winding_consistent = True
        mock_mesh.is_manifold = True
        mock_mesh.bounds = [[0, 0, 0], [100, 100, 100]]
        mock_mesh.volume = 1000.0
        mock_mesh.area = 600.0
        mock_mesh.center_mass = [50, 50, 50]
        mock_trimesh.load.return_value = mock_mesh
        
        handler = STLHandler()
        config = NormalizationConfig(
            target_units=Units.MILLIMETER,  # Using correct singular form
            normalize_orientation=False,
            repair_mesh=False
        )
        
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"dummy stl content")
            
        try:
            # Test conversion from inch to mm
            metrics = handler.normalize(
                doc={'doc_name': 'test', 'has_shape': True},
                config=config,
                file_path=tmp_path,
                original_units=Units.INCH  # Using correct singular form
            )
            
            # Verify scale was applied using centralized factors
            expected_scale = UNIT_CONVERSION_FACTORS["inch"] / UNIT_CONVERSION_FACTORS["mm"]
            assert expected_scale == 25.4  # inch to mm conversion
            mock_mesh.apply_scale.assert_called_once_with(expected_scale)
            
        finally:
            tmp_path.unlink(missing_ok=True)
            
    @patch('app.services.upload_normalization_service.freecad_service')
    def test_step_handler_uses_centralized_factors(self, mock_freecad):
        """Test STEP handler uses centralized unit conversion factors."""
        mock_freecad.execute_script.return_value = {
            'success': True,
            'warnings': [],
            'metrics': {
                'bbox_min': [0, 0, 0],
                'bbox_max': [100, 100, 100],
                'volume': 1000000,
                'surface_area': 60000,
                'center_of_mass': [50, 50, 50]
            }
        }
        
        handler = STEPHandler()
        config = NormalizationConfig(
            target_units=Units.MILLIMETER,
            normalize_orientation=True
        )
        
        # The normalize method should use UNIT_CONVERSION_FACTORS in the script
        metrics = handler.normalize(
            doc={'doc_name': 'test'},
            config=config,
            file_path=Path('/tmp/test.step'),
            original_units=Units.METER
        )
        
        # Verify the script was called
        mock_freecad.execute_script.assert_called_once()
        script_content = mock_freecad.execute_script.call_args[0][0]
        
        # Check that the script references centralized factors
        assert str(UNIT_CONVERSION_FACTORS) in script_content
        
    @patch('app.services.upload_normalization_service.freecad_service')
    def test_dxf_handler_uses_centralized_factors(self, mock_freecad):
        """Test DXF handler uses centralized unit conversion factors."""
        mock_freecad.execute_script.return_value = {
            'success': True,
            'warnings': [],
            'metrics': {
                'bbox_min': [0, 0, 0],
                'bbox_max': [100, 100, 100],
                'volume': 0,
                'surface_area': 10000,
                'center_of_mass': None
            }
        }
        
        handler = DXFHandler()
        config = NormalizationConfig(
            target_units=Units.MILLIMETER,
            merge_duplicates=True
        )
        
        metrics = handler.normalize(
            doc={'doc_name': 'test'},
            config=config,
            file_path=Path('/tmp/test.dxf'),
            original_units=Units.INCH
        )
        
        # Verify the script was called
        mock_freecad.execute_script.assert_called_once()
        script_content = mock_freecad.execute_script.call_args[0][0]
        
        # Check that the script uses centralized factors
        assert str(UNIT_CONVERSION_FACTORS) in script_content
        
    @patch('app.services.upload_normalization_service.freecad_service')
    def test_ifc_handler_uses_centralized_factors(self, mock_freecad):
        """Test IFC handler uses centralized unit conversion factors."""
        mock_freecad.execute_script.return_value = {
            'success': True,
            'warnings': [],
            'bom': [],
            'metrics': {
                'bbox_min': [0, 0, 0],
                'bbox_max': [1000, 1000, 1000],
                'volume': 1000000000,
                'surface_area': 6000000,
                'center_of_mass': [500, 500, 500]
            }
        }
        
        handler = IFCHandler()
        config = NormalizationConfig(
            target_units=Units.CENTIMETER,
            normalize_orientation=False
        )
        
        metrics = handler.normalize(
            doc={'doc_name': 'test'},
            config=config,
            file_path=Path('/tmp/test.ifc'),
            original_units=Units.METER
        )
        
        # Verify the script was called
        mock_freecad.execute_script.assert_called_once()
        script_content = mock_freecad.execute_script.call_args[0][0]
        
        # Check that the script uses centralized factors
        assert str(UNIT_CONVERSION_FACTORS) in script_content
        
    def test_unit_conversion_calculation_correctness(self):
        """Test that unit conversion calculations are correct using centralized factors."""
        test_cases = [
            # (from_unit, to_unit, expected_scale_factor)
            (Units.INCH, Units.MILLIMETER, 25.4),  # inch to mm
            (Units.MILLIMETER, Units.INCH, 1/25.4),  # mm to inch
            (Units.METER, Units.MILLIMETER, 1000.0),  # m to mm
            (Units.MILLIMETER, Units.METER, 0.001),  # mm to m
            (Units.CENTIMETER, Units.MILLIMETER, 10.0),  # cm to mm
            (Units.MILLIMETER, Units.CENTIMETER, 0.1),  # mm to cm
            (Units.FOOT, Units.MILLIMETER, 304.8),  # ft to mm
            (Units.MILLIMETER, Units.FOOT, 1/304.8),  # mm to ft
            (Units.INCH, Units.METER, 25.4/1000),  # inch to m
            (Units.METER, Units.INCH, 1000/25.4),  # m to inch
        ]
        
        for from_unit, to_unit, expected_scale in test_cases:
            # Calculate scale factor using centralized factors
            source_factor = UNIT_CONVERSION_FACTORS[from_unit.value]
            target_factor = UNIT_CONVERSION_FACTORS[to_unit.value]
            calculated_scale = source_factor / target_factor
            
            assert abs(calculated_scale - expected_scale) < 1e-9, \
                f"Conversion from {from_unit.value} to {to_unit.value} failed: " \
                f"expected {expected_scale}, got {calculated_scale}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])