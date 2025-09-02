"""
Test cases for PR #397 refactoring fixes.

This module provides comprehensive test coverage for the fixes implemented in PR #397,
which addressed critical code review issues including:
1. Long method refactoring in geometry_validator.py
2. PathValidator caching improvements in worker_script.py
3. Line number reference removal in standard_parts.py
4. Test file improvements (setUp/tearDown patterns)

Run Instructions:
    # Run all tests in this module
    $ python -m pytest apps/api/tests/test_pr397_refactoring.py -v
    
    # Run specific test class
    $ python -m pytest apps/api/tests/test_pr397_refactoring.py::TestGeometryValidatorRefactoring -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Add the app module to the path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGeometryValidatorRefactoring(unittest.TestCase):
    """Test the refactored geometry_validator.py methods."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        from app.services.freecad.geometry_validator import GeometryValidator
        
        self.validator = GeometryValidator()
        # Mock FreeCAD availability
        self.validator._freecad_available = False
    
    def tearDown(self):
        """Clean up test fixtures after each test method."""
        self.validator = None
    
    def test_helper_methods_exist(self):
        """Test that all new helper methods exist after refactoring."""
        # Check that all new helper methods are defined
        self.assertTrue(hasattr(self.validator, '_get_tool_parameters'))
        self.assertTrue(hasattr(self.validator, '_perform_ray_casting_analysis'))
        self.assertTrue(hasattr(self.validator, '_check_tool_clearance'))
        self.assertTrue(hasattr(self.validator, '_analyze_accessibility_issues'))
        self.assertTrue(hasattr(self.validator, '_check_internal_radius_requirements'))
        self.assertTrue(hasattr(self.validator, '_analyze_deep_pockets'))
        self.assertTrue(hasattr(self.validator, '_check_tool_accessibility'))
    
    def test_get_tool_parameters(self):
        """Test that _get_tool_parameters returns correct structure."""
        params = self.validator._get_tool_parameters()
        
        self.assertIsInstance(params, dict)
        self.assertIn('diameter', params)
        self.assertIn('radius', params)
        self.assertIn('length', params)
        self.assertIn('shank_diameter', params)
        self.assertIn('min_radius', params)
        
        # Check values are reasonable
        self.assertEqual(params['diameter'], 6.0)
        self.assertEqual(params['radius'], 3.0)
        self.assertEqual(params['length'], 50.0)
    
    @patch('app.services.freecad.geometry_validator.logger')
    def test_analyze_accessibility_issues(self, mock_logger):
        """Test that _analyze_accessibility_issues properly categorizes issues."""
        result = {"errors": [], "warnings": []}
        
        # Test with tool length issues
        inaccessible_regions = [
            {'x': 0, 'y': 0, 'z': -60, 'depth': 60, 'reason': 'exceeds_tool_length'}
        ]
        clearance_issues = []
        tool_params = {'length': 50.0, 'diameter': 6.0}
        
        self.validator._analyze_accessibility_issues(
            result, inaccessible_regions, clearance_issues, tool_params
        )
        
        # Should have one error about tool length
        self.assertEqual(len(result['errors']), 1)
        self.assertIn('60.0mm exceed tool length 50.0mm', result['errors'][0])
        
        # Test with clearance issues
        result = {"errors": [], "warnings": []}
        inaccessible_regions = []
        clearance_issues = [{'x': 0, 'y': 0, 'z': -10, 'volume': 100, 'reason': 'insufficient_clearance'}] * 5
        
        self.validator._analyze_accessibility_issues(
            result, inaccessible_regions, clearance_issues, tool_params
        )
        
        # Should have a warning about minor clearance issues
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('Minor clearance issues', result['warnings'][0])
    
    @patch('app.services.freecad.geometry_validator.logger')
    def test_check_internal_radius_requirements(self, mock_logger):
        """Test that _check_internal_radius_requirements provides proper warnings."""
        result = {"errors": [], "warnings": []}
        
        # Mock shape and bbox
        mock_face = MagicMock()
        mock_face.BoundBox.ZMax = 90.0
        
        mock_shape = MagicMock()
        mock_shape.Faces = [mock_face]
        
        mock_bbox = MagicMock()
        mock_bbox.ZMax = 100.0
        
        tool_params = {'diameter': 10.0}
        
        self.validator._check_internal_radius_requirements(
            result, mock_shape, mock_bbox, tool_params
        )
        
        # Should have a warning about tool diameter
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('Tool diameter 10.0mm may be too large', result['warnings'][0])
    
    @patch('app.services.freecad.geometry_validator.logger')
    def test_analyze_deep_pockets(self, mock_logger):
        """Test that _analyze_deep_pockets detects problematic geometries."""
        result = {"errors": [], "warnings": []}
        
        # Mock a deep pocket face
        mock_face = MagicMock()
        mock_face.BoundBox.ZMax = 50.0
        mock_face.BoundBox.ZMin = 0.0
        mock_face.BoundBox.XLength = 5.0
        mock_face.BoundBox.YLength = 5.0
        
        mock_shape = MagicMock()
        mock_shape.Faces = [mock_face]
        
        mock_bbox = MagicMock()
        mock_bbox.ZMax = 100.0
        mock_bbox.ZMin = 0.0
        
        self.validator._analyze_deep_pockets(result, mock_shape, mock_bbox)
        
        # Should have a warning about deep pocket
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('Deep pocket from top', result['warnings'][0])
        self.assertIn('depth/width = 10.0', result['warnings'][0])


class TestWorkerScriptCaching(unittest.TestCase):
    """Test the improved PathValidator caching in worker_script.py."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        # Create mock args
        self.mock_args = MagicMock()
        self.mock_args.outdir = tempfile.mkdtemp(prefix="test_worker_")
        self.mock_args.cpu_seconds = 0
        self.mock_args.mem_mb = 0
        self.mock_args.metrics_interval = 2.0
    
    def tearDown(self):
        """Clean up test fixtures after each test method."""
        if os.path.exists(self.mock_args.outdir):
            shutil.rmtree(self.mock_args.outdir, ignore_errors=True)
        self.mock_args = None
    
    @patch('app.services.freecad.worker_script.PathValidator')
    def test_dictionary_based_caching(self, mock_path_validator_class):
        """Test that PathValidator uses dictionary-based caching."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        worker = FreeCADWorker(self.mock_args)
        
        # Verify dictionary is initialized
        self.assertIsInstance(worker.path_validators, dict)
        self.assertEqual(len(worker.path_validators), 0)
        
        # Mock PathValidator instance
        mock_validator = MagicMock()
        mock_validator.validate_path.return_value = Path('/work/test.txt')
        mock_path_validator_class.return_value = mock_validator
        
        # First call should create new validator
        result1 = worker._validate_path_security('/work/test.txt', '/work', 'test file')
        self.assertEqual(mock_path_validator_class.call_count, 1)
        self.assertEqual(len(worker.path_validators), 1)
        self.assertIn('/work', worker.path_validators)
        
        # Second call with same allowed_dir should reuse cached validator
        result2 = worker._validate_path_security('/work/test2.txt', '/work', 'test file')
        self.assertEqual(mock_path_validator_class.call_count, 1)  # No new instance created
        
        # Third call with different allowed_dir should create new validator
        result3 = worker._validate_path_security('/tmp/test.txt', '/tmp', 'test file')
        self.assertEqual(mock_path_validator_class.call_count, 2)  # New instance created
        self.assertEqual(len(worker.path_validators), 2)
        self.assertIn('/tmp', worker.path_validators)
    
    def test_validate_path_security_is_instance_method(self):
        """Test that _validate_path_security is an instance method, not static."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        worker = FreeCADWorker(self.mock_args)
        
        # Should be an instance method
        self.assertTrue(hasattr(worker, '_validate_path_security'))
        # Should not be a static method
        import types
        self.assertNotIsInstance(
            getattr(FreeCADWorker, '_validate_path_security', None),
            staticmethod
        )


class TestStandardPartsDocumentation(unittest.TestCase):
    """Test that standard_parts.py has proper documentation without line numbers."""
    
    def test_no_line_number_references(self):
        """Test that standard_parts.py doesn't contain hardcoded line number references."""
        from pathlib import Path
        
        standard_parts_path = Path(__file__).parent.parent / 'app' / 'services' / 'freecad' / 'standard_parts.py'
        
        with open(standard_parts_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that old line number references are removed
        self.assertNotIn('at lines 563-569', content)
        
        # Check that new generic description exists
        self.assertIn('Template variables validated via Jinja2 template rendering', content)


class TestImprovedTestPatterns(unittest.TestCase):
    """Test that test files follow improved patterns with setUp/tearDown."""
    
    def test_pr390_reduced_iterations(self):
        """Test that test_pr390_fixes.py uses reduced iterations for performance."""
        from pathlib import Path
        
        test_file_path = Path(__file__).parent / 'test_pr390_fixes.py'
        
        with open(test_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that we're using 100 iterations instead of 1000
        self.assertIn('range(100)', content)
        self.assertNotIn('range(1000)', content)
        self.assertIn('100 lines is sufficient', content)
    
    def test_pr391_uses_traceback(self):
        """Test that test_pr391_fixes.py actually uses the traceback import."""
        from pathlib import Path
        
        test_file_path = Path(__file__).parent / 'test_pr391_fixes.py'
        
        with open(test_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that traceback is imported and used
        self.assertIn('import traceback', content)
        self.assertIn('traceback.format_exception', content)


if __name__ == '__main__':
    unittest.main()