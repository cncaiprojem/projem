"""
Test suite for PR #408 path validation security fix.

This test specifically validates that the fallback path validation in
worker_script.py correctly handles relative paths by joining them with
the allowed directory instead of resolving them relative to the current
working directory.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Use shared test utility for robust path setup
# See test_utils.py for PathValidator mock configuration notes
from test_utils import setup_test_paths, cleanup_test_artifacts
project_root = setup_test_paths()


class TestPR408PathValidationFix(unittest.TestCase):
    """Test the path validation security fix for PR #408."""
    
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
    
    def test_relative_path_validation_in_fallback(self):
        """
        Test that relative paths are properly handled in the fallback validation.
        
        The bug was that relative paths were resolved using os.path.realpath
        directly, which would resolve them relative to the current working directory
        instead of the allowed directory. The fix ensures relative paths are
        joined with the allowed directory first.
        """
        from app.services.freecad.worker_script import FreeCADWorker
        
        processor = FreeCADWorker(self.mock_args)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a subdirectory structure
            allowed_dir = Path(temp_dir) / "allowed"
            allowed_dir.mkdir()
            
            # Create a file in the allowed directory
            test_file = allowed_dir / "test.fcstd"
            test_file.write_text("test content")
            
            # Create another directory that should not be accessible
            forbidden_dir = Path(temp_dir) / "forbidden"
            forbidden_dir.mkdir()
            forbidden_file = forbidden_dir / "secret.fcstd"
            forbidden_file.write_text("secret")
            
            # Mock PathValidator as None to test fallback path validation
            with patch('app.services.freecad.worker_script.PathValidator', None):
                # Test 1: Absolute path within allowed directory should work
                result = processor._validate_path_security(
                    str(test_file),
                    str(allowed_dir),
                    "test file"
                )
                self.assertEqual(os.path.realpath(str(test_file)), result)
                
                # Test 2: Relative path should be resolved relative to allowed_dir
                # This is the key test for the bug fix
                relative_path = "test.fcstd"
                result = processor._validate_path_security(
                    relative_path,
                    str(allowed_dir),
                    "test file"
                )
                self.assertEqual(os.path.realpath(str(test_file)), result)
                
                # Test 3: Path outside allowed directory should fail
                with self.assertRaises(ValueError) as cm:
                    processor._validate_path_security(
                        str(forbidden_file),
                        str(allowed_dir),
                        "forbidden file"
                    )
                self.assertIn("outside allowed directory", str(cm.exception))
                
                # Test 4: Relative path with directory traversal should fail
                with self.assertRaises(ValueError) as cm:
                    processor._validate_path_security(
                        "../forbidden/secret.fcstd",
                        str(allowed_dir),
                        "traversal attempt"
                    )
                self.assertIn("outside allowed directory", str(cm.exception))
                
                # Test 5: Nested relative path within allowed dir should work
                nested_dir = allowed_dir / "nested"
                nested_dir.mkdir()
                nested_file = nested_dir / "nested.fcstd"
                nested_file.write_text("nested content")
                
                result = processor._validate_path_security(
                    "nested/nested.fcstd",
                    str(allowed_dir),
                    "nested file"
                )
                self.assertEqual(os.path.realpath(str(nested_file)), result)
    
    def test_symlink_attack_prevention(self):
        """Test that symlink attacks are properly prevented."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        # Skip this test on Windows if symlinks aren't supported
        if os.name == 'nt':
            try:
                # Try to create a test symlink
                with tempfile.TemporaryDirectory() as test_dir:
                    test_path = Path(test_dir) / "test"
                    test_path.touch()
                    link_path = Path(test_dir) / "link"
                    link_path.symlink_to(test_path)
            except OSError:
                self.skipTest("Symlinks not supported on this Windows system")
        
        processor = FreeCADWorker(self.mock_args)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create allowed and forbidden directories
            allowed_dir = Path(temp_dir) / "allowed"
            allowed_dir.mkdir()
            
            forbidden_dir = Path(temp_dir) / "forbidden"
            forbidden_dir.mkdir()
            forbidden_file = forbidden_dir / "secret.txt"
            forbidden_file.write_text("secret data")
            
            # Create a symlink in allowed directory pointing to forbidden file
            symlink_path = allowed_dir / "link_to_secret.txt"
            try:
                symlink_path.symlink_to(forbidden_file)
            except OSError:
                self.skipTest("Cannot create symlinks on this system")
            
            # Mock PathValidator as None to test fallback path validation
            with patch('app.services.freecad.worker_script.PathValidator', None):
                # The symlink should be resolved and detected as outside allowed dir
                with self.assertRaises(ValueError) as cm:
                    processor._validate_path_security(
                        str(symlink_path),
                        str(allowed_dir),
                        "symlink attack"
                    )
                self.assertIn("outside allowed directory", str(cm.exception))
    
    def test_edge_cases(self):
        """Test edge cases in path validation."""
        from app.services.freecad.worker_script import FreeCADWorker
        
        processor = FreeCADWorker(self.mock_args)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            allowed_dir = Path(temp_dir) / "allowed"
            allowed_dir.mkdir()
            
            # Mock PathValidator as None to test fallback path validation
            with patch('app.services.freecad.worker_script.PathValidator', None):
                # Test empty path
                with self.assertRaises(ValueError) as cm:
                    processor._validate_path_security("", str(allowed_dir), "empty path")
                self.assertIn("cannot be empty", str(cm.exception))
                
                # Test path with only dots - "." resolves to allowed_dir itself (valid)
                result = processor._validate_path_security(".", str(allowed_dir), "dot path")
                self.assertEqual(os.path.realpath(str(allowed_dir)), result)
                
                # Test path with double dots - tries to go outside allowed_dir (invalid)
                with self.assertRaises(ValueError) as cm:
                    processor._validate_path_security("..", str(allowed_dir), "double dot")
                self.assertIn("outside allowed directory", str(cm.exception))
                
                # Test None path (should raise ValueError)
                with self.assertRaises(ValueError) as cm:
                    processor._validate_path_security(None, str(allowed_dir), "none path")
                self.assertIn("cannot be empty", str(cm.exception))


if __name__ == "__main__":
    unittest.main()