"""
Test Suite for PR #407 Code Review Fixes

Tests the comprehensive enterprise-grade fixes applied to address:
1. Security hardening in worker_script.py fallback path validation
2. Simplified temp file handling in bom.py using TemporaryDirectory
3. FreeCAD Vector.getAngle() usage in geometry_validator.py
4. Extracted helper methods in standard_parts.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Use shared test utility for robust path setup
# See test_utils.py for PathValidator mock configuration notes
from test_utils import setup_test_paths
project_root = setup_test_paths()


class TestPR407SecurityFixes(unittest.TestCase):
    """Test security improvements in path validation."""
    
    def setUp(self):
        """Create mock args for FreeCADWorker initialization."""
        class MockArgs:
            def __init__(self):
                self.metrics_interval = 1.0
                self.cpu_seconds = 20
                self.mem_mb = 2048
                self.output_dir = "/tmp/output"
                self.debug = False
        
        self.mock_args = MockArgs()
    
    def test_worker_script_realpath_validation(self):
        """Test that worker_script uses os.path.realpath for symlink attack prevention."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        processor = FreeCADWorker(self.mock_args)
        
        # Test with a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a test file
            test_file = Path(temp_dir) / "test.fcstd"
            test_file.write_text("test")
            
            # Mock PathValidator as None to test fallback path validation
            with patch('app.services.freecad.worker_script.PathValidator', None):
                # Should use os.path.realpath and commonpath for validation
                result = processor._validate_path_security(
                    str(test_file),
                    temp_dir,
                    "test"
                )
                
                # Result should be the real path
                self.assertEqual(result, os.path.realpath(str(test_file)))
    
    def test_worker_script_rejects_outside_paths(self):
        """Test that paths outside allowed directory are rejected."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        processor = FreeCADWorker(self.mock_args)
        
        with tempfile.TemporaryDirectory() as allowed_dir:
            with tempfile.TemporaryDirectory() as other_dir:
                # Create a file in other directory
                outside_file = Path(other_dir) / "outside.fcstd"
                outside_file.write_text("test")
                
                # Mock PathValidator being None to test fallback
                with patch('app.services.freecad.worker_script.PathValidator', None):
                    # Should reject path outside allowed directory
                    with self.assertRaises(ValueError) as ctx:
                        processor._validate_path_security(
                            str(outside_file),
                            allowed_dir,
                            "test"
                        )
                    
                    self.assertIn("Path outside allowed directory", str(ctx.exception))


class TestPR407TempFileHandling(unittest.TestCase):
    """Test simplified temp file handling improvements."""
    
    @patch('app.services.freecad.bom.logger')
    def test_bom_uses_temporary_directory(self, mock_logger):
        """Test that BOM uses TemporaryDirectory for automatic cleanup."""
        from app.services.freecad.bom import BOMExtractor
        
        # Create mock FreeCAD objects
        mock_shape = Mock()
        mock_shape.exportBrep = Mock(side_effect=lambda path: Path(path).write_text("BREP_DATA"))
        mock_shape.exportBrepToString = None  # Force fallback to disk-based export
        
        mock_obj = Mock()
        mock_obj.Shape = mock_shape
        mock_obj.Name = "TestPart"
        mock_obj.Label = "Test Part"
        mock_obj.TypeId = "Part::Feature"
        
        extractor = BOMExtractor()
        
        # The _compute_fingerprint method should use TemporaryDirectory
        # Patch hasattr to ensure we use the disk-based export path
        with patch('builtins.hasattr', side_effect=lambda obj, attr: 
                   attr == 'exportBrep' if obj == mock_shape else True):
            # The method should handle temp file cleanup automatically
            # No manual cleanup code should be needed
            fingerprint = extractor._compute_fingerprint(mock_obj)
        
        # Verify exportBrep was called with a temporary path
        mock_shape.exportBrep.assert_called_once()
        temp_path = mock_shape.exportBrep.call_args[0][0]
        
        # The temp directory should be cleaned up automatically
        # We can't check if it's deleted since it happens after context exit
        # But we can verify it was in a temp directory
        self.assertIn(tempfile.gettempdir(), temp_path)


class TestPR407VectorMethods(unittest.TestCase):
    """Test FreeCAD Vector built-in method usage."""
    
    def test_geometry_validator_uses_vector_getangle(self):
        """Test that geometry_validator uses FreeCAD Vector.getAngle() method."""
        # Mock FreeCAD module and Vector class
        mock_vector = Mock()
        mock_vector.getAngle = Mock(return_value=0.5236)  # 30 degrees in radians
        mock_vector.dot = Mock(return_value=0.866)  # cos(30°)
        
        mock_freecad = Mock()
        mock_freecad.Vector = Mock(return_value=mock_vector)
        
        with patch.dict('sys.modules', {'FreeCAD': mock_freecad}):
            from app.services.freecad.geometry_validator import GeometryValidator
            
            validator = GeometryValidator()
            
            # Create mock face
            mock_face = Mock()
            mock_face.ParameterRange = (0, 1, 0, 1)
            mock_normal = Mock()
            mock_normal.getAngle = mock_vector.getAngle
            mock_normal.dot = mock_vector.dot
            mock_face.normalAt = Mock(return_value=mock_normal)
            
            # Test draft angle calculation
            pull_direction = (0, 0, 1)  # Z-axis pull
            min_draft = 2.0
            
            result = validator._check_draft_angle(mock_face, pull_direction, min_draft)
            
            # Verify FreeCAD.Vector was called to create pull vector
            mock_freecad.Vector.assert_called_with(0, 0, 1)
            
            # Verify getAngle was called on the normal
            mock_normal.getAngle.assert_called_once()
            
            # Verify dot was called for parallel face detection
            mock_normal.dot.assert_called_once()


class TestPR407ExtractedMethods(unittest.TestCase):
    """Test extracted helper methods in standard_parts.py."""
    
    def test_approximate_thread_pitch_method(self):
        """Test the extracted _approximate_thread_pitch method."""
        from app.services.freecad.standard_parts import StandardPartsLibrary
        
        library = StandardPartsLibrary()
        
        # Test small diameter (< 1.0)
        pitch = library._approximate_thread_pitch(0.5)
        self.assertEqual(pitch, 0.2)
        
        # Test medium diameter (1.0 - 3.0)
        pitch = library._approximate_thread_pitch(2.0)
        self.assertAlmostEqual(pitch, 0.4, places=2)
        
        # Test large diameter (> 3.0)
        pitch = library._approximate_thread_pitch(10.0)
        expected = 0.5 + (10.0 - 3.0) * 0.15
        self.assertAlmostEqual(pitch, expected, places=2)
    
    def test_approximate_head_dimensions_method(self):
        """Test the extracted _approximate_head_dimensions method."""
        from app.services.freecad.standard_parts import StandardPartsLibrary
        
        library = StandardPartsLibrary()
        
        # Test standard M8 approximation
        head_diameter, head_height = library._approximate_head_dimensions(8.0)
        
        # Check head diameter (width across flats)
        expected_diameter = 8.0 * 1.5 + 1.0  # 13.0
        self.assertAlmostEqual(head_diameter, expected_diameter, places=2)
        
        # Check head height
        expected_height = 8.0 * 0.6 + 0.4  # 5.2
        self.assertAlmostEqual(head_height, expected_height, places=2)
    
    def test_parse_fastener_uses_helper_methods(self):
        """Test that _parse_fastener_size uses the extracted helper methods."""
        from app.services.freecad.standard_parts import StandardPartsLibrary
        
        library = StandardPartsLibrary()
        
        # Mock the helper methods to verify they're called
        library._approximate_thread_pitch = Mock(return_value=1.25)
        library._approximate_head_dimensions = Mock(return_value=(15.0, 6.0))
        
        # Parse a non-standard size (not in METRIC_COARSE_PITCH table)
        result = library._parse_fastener_size("M9x30")
        
        # Verify helper methods were called
        library._approximate_thread_pitch.assert_called_once_with(9.0)
        library._approximate_head_dimensions.assert_called_once_with(9.0)
        
        # Check result
        self.assertEqual(result["diameter"], 9.0)
        self.assertEqual(result["length"], 30.0)
        self.assertEqual(result["thread_pitch"], 1.25)
        self.assertEqual(result["head_diameter"], 15.0)
        self.assertEqual(result["head_height"], 6.0)


class TestPR407Integration(unittest.TestCase):
    """Integration tests for all PR #407 fixes."""
    
    def test_all_modules_import_successfully(self):
        """Test that all modified modules import without errors."""
        try:
            from app.services.freecad import worker_script
            from app.services.freecad import bom
            from app.services.freecad import geometry_validator
            from app.services.freecad import standard_parts
            
            # All imports successful
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import module: {e}")
    
    def test_no_deprecated_patterns(self):
        """Verify that deprecated patterns have been replaced."""
        import ast
        import inspect
        
        # Check worker_script.py doesn't use Path.resolve() in fallback
        from app.services.freecad import worker_script
        source = inspect.getsource(worker_script.FreeCADWorker._validate_path_security)
        self.assertNotIn("Path(path).resolve()", source)
        self.assertIn("os.path.realpath", source)
        
        # Check bom.py uses TemporaryDirectory
        from app.services.freecad import bom
        source = inspect.getsource(bom.BOMGenerator)
        self.assertIn("TemporaryDirectory", source)
        
        # Check geometry_validator.py uses getAngle
        from app.services.freecad import geometry_validator
        source = inspect.getsource(geometry_validator.GeometryValidator._check_draft_angle)
        self.assertIn("getAngle", source)
        self.assertNotIn("math.acos(clamped_dot)", source)
        
        # Check standard_parts.py has extracted methods
        from app.services.freecad import standard_parts
        self.assertTrue(hasattr(standard_parts.StandardPartsLibrary, '_approximate_thread_pitch'))
        self.assertTrue(hasattr(standard_parts.StandardPartsLibrary, '_approximate_head_dimensions'))


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)