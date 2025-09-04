"""Test PathValidator caching in Assembly4Manager."""

import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from apps.api.app.services.freecad.a4_assembly import Assembly4Manager

# See test_utils.py for PathValidator mock configuration notes


class TestAssembly4Cache(unittest.TestCase):
    """Test PathValidator caching implementation."""
    
    @patch('apps.api.app.services.freecad.a4_assembly.PathValidator')
    def test_path_validator_caching(self, mock_path_validator_class):
        """Test that PathValidator instances are cached and reused."""
        # Create mock PathValidator instance
        mock_validator = Mock()
        mock_validator.validate_path.return_value = Path('/tmp/freecad_uploads/test.step')
        mock_path_validator_class.return_value = mock_validator
        
        # Create Assembly4Manager instance
        manager = Assembly4Manager()
        
        # Clear any existing cache
        manager.path_validators.clear()
        
        # First call should create new validator
        result1 = manager._validate_upload_path('/tmp/freecad_uploads/test.step')
        self.assertEqual(mock_path_validator_class.call_count, 1)
        self.assertEqual(len(manager.path_validators), 1)
        
        # Second call with same directories should reuse cached validator
        result2 = manager._validate_upload_path('/tmp/freecad_uploads/another.step')
        self.assertEqual(mock_path_validator_class.call_count, 1)  # Still 1, not 2
        self.assertEqual(len(manager.path_validators), 1)
        
        # Verify both calls returned valid paths
        self.assertIsInstance(result1, Path)
        self.assertIsInstance(result2, Path)
        
        # Verify the validator was called twice
        self.assertEqual(mock_validator.validate_path.call_count, 2)
    
    @patch('apps.api.app.services.freecad.a4_assembly.PathValidator', None)
    def test_path_validator_fallback(self):
        """Test fallback validation when PathValidator is not available."""
        # Create Assembly4Manager instance
        manager = Assembly4Manager()
        
        # Create test directory path
        test_dir = Path('/tmp/freecad_uploads')
        test_file = test_dir / 'test.step'
        
        # Mock resolved directories - use the test directory
        manager._resolved_upload_dirs = [test_dir]
        
        # Test valid path - mock the file path resolution to match allowed directory
        with patch.object(Path, 'resolve') as mock_resolve:
            # When resolving the file path, return a path within allowed directory
            mock_resolve.return_value = test_file
            result = manager._validate_upload_path(str(test_file))
            self.assertEqual(result, test_file)
        
        # Test invalid path (outside allowed directories)
        invalid_path = Path('/etc/passwd')
        with patch.object(Path, 'resolve') as mock_resolve:
            # When resolving the invalid path, return a path outside allowed directories
            mock_resolve.return_value = invalid_path
            with self.assertRaises(ValueError) as ctx:
                manager._validate_upload_path(str(invalid_path))
            self.assertIn('outside allowed directories', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()