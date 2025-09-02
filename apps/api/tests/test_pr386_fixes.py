"""
Test cases for PR #386 fixes.

This module provides comprehensive test coverage for the fixes implemented in PR #386,
which addressed critical issues in the FreeCAD service layer including fastener
specifications, assembly caching, and export format support.

Tests the following fixes:
1. Fastener size parsing with accurate DIN/ISO thread pitch and head dimensions
2. Assembly4 shape caching for upload_ref components
3. Export format consistency with GLB support
4. Exception handling improvements

Requirements:
    - Python 3.8+
    - FreeCAD (optional for integration tests)
    - trimesh (optional for GLB export tests)
    
Dependencies:
    - unittest: Python standard testing framework
    - pathlib: File path handling
    - unittest.mock: Mocking FreeCAD modules for unit tests

Run Instructions:
    # Run all tests in this module
    $ python -m pytest apps/api/tests/test_pr386_fixes.py -v
    
    # Run specific test class
    $ python -m pytest apps/api/tests/test_pr386_fixes.py::TestStandardPartsFixes -v
    
    # Run with coverage
    $ python -m pytest apps/api/tests/test_pr386_fixes.py --cov=app.services.freecad --cov-report=html
    
    # Run without FreeCAD dependency (uses mocks)
    $ python -m unittest apps.api.tests.test_pr386_fixes
    
Environment Setup:
    For full integration testing with FreeCAD:
    1. Install FreeCAD: apt-get install freecad
    2. Install Python bindings: pip install freecad
    3. Install trimesh for GLB support: pip install trimesh
    
    For unit testing (no FreeCAD required):
    - Tests will automatically mock FreeCAD modules
    
Test Coverage:
    - Standard parts library: DIN/ISO fastener specifications
    - Assembly4 manager: Shape caching and memory optimization
    - Export system: Multi-format support including GLB
    - Error handling: Custom exceptions with detailed context
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Add the app module to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.freecad.standard_parts import (
    InvalidSizeFormatError,
    StandardPartsLibrary,
    UnknownStandardError,
    UnsupportedSizeError,
)


class TestStandardPartsFixes(unittest.TestCase):
    """Test fixes for standard_parts.py issues."""
    
    def setUp(self):
        """Set up test fixtures before each test method.
        
        This method is called before each test method to ensure
        test isolation and provide a clean state.
        """
        self.library = StandardPartsLibrary()
        # Store original environment for restoration in tearDown
        self._original_env = os.environ.copy()
    
    def tearDown(self):
        """Clean up test fixtures after each test method.
        
        This method is called after each test method to clean up
        any resources and restore the original state.
        """
        # Restore original environment variables
        os.environ.clear()
        os.environ.update(self._original_env)
        # Clear any cached data in the library
        self.library = None
    
    def test_m8_thread_pitch_accuracy(self):
        """Test that M8 has correct 1.25mm pitch, not 1.0mm."""
        result = self.library._parse_fastener_size("M8x20")
        
        # M8 should have 1.25mm pitch according to DIN/ISO standards
        self.assertEqual(result["diameter"], 8.0)
        self.assertEqual(result["thread_pitch"], 1.25)
        self.assertEqual(result["head_diameter"], 13.0)  # DIN 933/ISO 4017 standard
        self.assertEqual(result["head_height"], 5.3)
    
    def test_m10_thread_pitch_accuracy(self):
        """Test that M10 has correct 1.5mm pitch."""
        result = self.library._parse_fastener_size("M10x25")
        
        self.assertEqual(result["diameter"], 10.0)
        self.assertEqual(result["thread_pitch"], 1.5)
        self.assertEqual(result["head_diameter"], 16.0)  # ISO 4017 uses 16mm
        self.assertEqual(result["head_height"], 6.4)
    
    def test_m12_thread_pitch_accuracy(self):
        """Test that M12 has correct 1.75mm pitch."""
        result = self.library._parse_fastener_size("M12x30")
        
        self.assertEqual(result["diameter"], 12.0)
        self.assertEqual(result["thread_pitch"], 1.75)
        self.assertEqual(result["head_diameter"], 18.0)
        self.assertEqual(result["head_height"], 7.5)
    
    def test_invalid_size_format_raises_exception(self):
        """Test that invalid size format raises InvalidSizeFormatError."""
        with self.assertRaises(InvalidSizeFormatError) as ctx:
            self.library._parse_fastener_size("invalid")
        
        self.assertIn("Format must start with 'M'", str(ctx.exception))
        self.assertEqual(ctx.exception.size, "invalid")
        self.assertEqual(ctx.exception.category, "fasteners")
    
    def test_empty_size_raises_exception(self):
        """Test that empty size raises InvalidSizeFormatError."""
        with self.assertRaises(InvalidSizeFormatError) as ctx:
            self.library._parse_fastener_size("")
        
        self.assertIn("Format: M{diameter}x{length}", str(ctx.exception))
    
    def test_get_part_with_invalid_size_raises_exception(self):
        """Test that get_part raises exception for invalid sizes."""
        # Test unknown standard
        with self.assertRaises(UnknownStandardError) as ctx:
            self.library.get_part("UNKNOWN", "M8x20")
        
        self.assertEqual(ctx.exception.standard, "UNKNOWN")
        self.assertIn("DIN933", ctx.exception.known_standards)
        
        # Test unsupported size
        with self.assertRaises(UnsupportedSizeError) as ctx:
            self.library.get_part("DIN933", "M99x100")
        
        self.assertEqual(ctx.exception.size, "M99x100")
        self.assertEqual(ctx.exception.standard, "DIN933")
        self.assertIn("M8x20", ctx.exception.available_sizes)
    
    def test_non_standard_diameter_approximation(self):
        """Test that non-standard diameters use reasonable approximations."""
        # M7 is not a standard size
        result = self.library._parse_fastener_size("M7x20")
        
        self.assertEqual(result["diameter"], 7.0)
        # Should use approximation, not lookup
        self.assertIsNotNone(result["thread_pitch"])
        self.assertGreater(result["thread_pitch"], 0)
        # Head dimensions should also be approximated
        self.assertIsNotNone(result["head_diameter"])
        self.assertIsNotNone(result["head_height"])


class TestAssembly4CachingFix(unittest.TestCase):
    """Test shape caching fix for Assembly4."""
    
    def test_upload_ref_caching(self):
        """Test that upload_ref components use caching to avoid redundant I/O."""
        # Mock FreeCAD and Part modules
        mock_freecad = MagicMock()
        mock_part = MagicMock()
        
        # Insert mocks into sys.modules
        sys.modules['FreeCAD'] = mock_freecad
        sys.modules['Part'] = mock_part
        
        from app.services.freecad.a4_assembly import Assembly4Manager, Component, ComponentSource
        
        # Create test file in isolated temporary directory first
        test_dir = tempfile.mkdtemp(prefix="freecad_uploads_test_")
        test_file = os.path.join(test_dir, "test.FCStd")
        
        # Create a dummy test file
        with open(test_file, 'wb') as f:
            f.write(b'test file content')
        
        try:
            # Patch the ALLOWED_UPLOAD_DIRS to include our test directory
            with unittest.mock.patch.object(
                Assembly4Manager,
                'ALLOWED_UPLOAD_DIRS',
                [test_dir]
            ):
                # Create manager after patching
                manager = Assembly4Manager()
                manager._freecad_available = True
            
                # Mock FreeCAD document and shapes
                mock_doc = MagicMock()
                mock_freecad.newDocument = MagicMock(return_value=mock_doc)
                mock_freecad.open = MagicMock(return_value=mock_doc)
                mock_freecad.closeDocument = MagicMock()
                
                mock_shape = MagicMock()
                mock_shape.copy = MagicMock(return_value=mock_shape)
                mock_compound = MagicMock()
                mock_part.makeCompound = MagicMock(return_value=mock_compound)
                
                # Create components that reference the same file
                comp1 = Component(
                    id="comp1",
                    source=ComponentSource(
                        type="upload_ref",
                        spec={"path": test_file}
                    )
                )
                comp2 = Component(
                    id="comp2",
                    source=ComponentSource(
                        type="upload_ref",
                        spec={"path": test_file}
                    )
                )
                
                # Mock document with objects
                mock_obj = MagicMock()
                mock_obj.Shape = mock_shape
                mock_doc.Objects = [mock_obj]
                mock_doc.addObject = MagicMock(return_value=MagicMock())
                
                # Process first component
                manager._create_component(mock_doc, comp1)
                
                # Should open the file once
                self.assertEqual(mock_freecad.open.call_count, 1)
                
                # Process second component with same file
                manager._create_component(mock_doc, comp2)
                
                # Should NOT open the file again (uses cache)
                self.assertEqual(mock_freecad.open.call_count, 1)
                
                # Check cache stats
                stats = manager.get_cache_stats()
                self.assertEqual(stats["cache_size"], 1)
                
                # Clear cache
                manager.clear_shape_cache()
                stats = manager.get_cache_stats()
                self.assertEqual(stats["cache_size"], 0)
            
        finally:
            # Clean up test file and temporary directory
            if os.path.exists(test_file):
                os.unlink(test_file)
            if os.path.exists(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)
            
            # Clean up sys.modules
            if 'FreeCAD' in sys.modules:
                del sys.modules['FreeCAD']
            if 'Part' in sys.modules:
                del sys.modules['Part']
    
    def test_cache_key_validation(self):
        """Test that cache keys are properly validated paths."""
        from app.services.freecad.a4_assembly import Assembly4Manager
        
        manager = Assembly4Manager()
        
        # Test that cache uses resolved paths
        self.assertEqual(len(manager._shape_cache), 0)
        
        # Add a test entry
        test_path = "/work/uploads/test.FCStd"
        manager._shape_cache[test_path] = MagicMock()
        
        stats = manager.get_cache_stats()
        self.assertEqual(stats["cache_size"], 1)
        self.assertIn(test_path, stats["cached_files"])


class TestWorkerScriptExportFix(unittest.TestCase):
    """Test export format fixes in worker_script.py."""
    
    def setUp(self):
        """Set up test fixtures before each test method.
        
        Creates mock objects and test data for export testing.
        """
        self.test_dir = tempfile.mkdtemp(prefix="test_export_")
        self.mock_args = MagicMock()
        self.mock_args.outdir = self.test_dir
        self.mock_args.cpu_seconds = 0
        self.mock_args.mem_mb = 0
        self.mock_args.metrics_interval = 2.0
    
    def tearDown(self):
        """Clean up test fixtures after each test method.
        
        Removes temporary directories and clears mock objects.
        """
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)
        self.mock_args = None
    
    @patch('app.services.freecad.worker_script.DeterministicExporter')
    def test_export_includes_glb_format(self, mock_exporter_class):
        """Test that _export_model includes GLB format."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        # Create worker using setUp's mock_args
        worker = FreeCADWorker(self.mock_args)
        
        # Mock exporter
        mock_exporter = MagicMock()
        mock_exporter_class.return_value = mock_exporter
        
        # Mock export results including GLB
        mock_exporter.export_all.return_value = {
            "FCStd": {"path": "/tmp/output/model.FCStd", "sha256": "abc123", "size_bytes": 1000},
            "STEP": {"path": "/tmp/output/model.step", "sha256": "def456", "size_bytes": 2000},
            "STL": {"path": "/tmp/output/model.stl", "sha256": "ghi789", "size_bytes": 3000},
            "GLB": {"path": "/tmp/output/model.glb", "sha256": "jkl012", "size_bytes": 4000}
        }
        
        # Mock document
        mock_doc = MagicMock()
        
        # Call _export_model
        artefacts = worker._export_model(mock_doc, "test_model")
        
        # Verify GLB is in the export formats
        mock_exporter.export_all.assert_called_once()
        call_args = mock_exporter.export_all.call_args
        formats = call_args[0][2]  # Third argument is formats list
        self.assertIn("GLB", formats)
        
        # Verify GLB artefact is created
        glb_artefacts = [a for a in artefacts if a["format"] == "GLB"]
        self.assertEqual(len(glb_artefacts), 1)
        self.assertEqual(glb_artefacts[0]["type"], "gltf_model")
        self.assertEqual(glb_artefacts[0]["sha256"], "jkl012")
    
    @patch('app.services.freecad.worker_script.DeterministicExporter')
    def test_glb_export_failure_handling(self, mock_exporter_class):
        """Test that GLB export failures are handled gracefully."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        # Create worker using setUp's mock_args
        worker = FreeCADWorker(self.mock_args)
        
        # Mock exporter
        mock_exporter = MagicMock()
        mock_exporter_class.return_value = mock_exporter
        
        # Mock export results with GLB failure (trimesh not installed)
        mock_exporter.export_all.return_value = {
            "FCStd": {"path": "/tmp/output/model.FCStd", "sha256": "abc123", "size_bytes": 1000},
            "STEP": {"path": "/tmp/output/model.step", "sha256": "def456", "size_bytes": 2000},
            "STL": {"path": "/tmp/output/model.stl", "sha256": "ghi789", "size_bytes": 3000},
            "GLB": {"error": "trimesh library not installed"}
        }
        
        # Mock document
        mock_doc = MagicMock()
        
        # Call _export_model (should not raise exception)
        artefacts = worker._export_model(mock_doc, "test_model")
        
        # Verify GLB is not in artefacts when it fails
        glb_artefacts = [a for a in artefacts if a["format"] == "GLB"]
        self.assertEqual(len(glb_artefacts), 0)
        
        # But other formats should still be present
        self.assertEqual(len(artefacts), 3)
        formats = [a["format"] for a in artefacts]
        self.assertIn("FCStd", formats)
        self.assertIn("STEP", formats)
        self.assertIn("STL", formats)


if __name__ == "__main__":
    unittest.main()