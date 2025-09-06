#!/usr/bin/env python3
"""
Test to verify PR #473 batch delete error handling fix.
Ensures that _process_batch_delete_errors returns the actual number of successful deletions,
not 0 when partial errors occur.
"""

import unittest
from unittest.mock import MagicMock, patch, Mock
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock boto3 before importing storage_client
sys.modules['boto3'] = Mock()
from app.services.storage_client import StorageClient


class TestBatchDeleteErrorHandling(unittest.TestCase):
    """Test batch delete error handling returns correct counts."""
    
    def setUp(self):
        """Set up test client."""
        with patch('app.services.storage_client.Minio'):
            self.client = StorageClient(
                endpoint="test.minio.local",
                access_key="test",
                secret_key="test",
                secure=False
            )
    
    def test_no_errors_returns_full_batch_size(self):
        """Test that no errors returns the full batch size."""
        errors = []  # No errors
        result = self.client._process_batch_delete_errors(
            errors=iter(errors),
            bucket="test-bucket",
            batch_size=1000
        )
        self.assertEqual(result, 1000, "Should return full batch size when no errors")
    
    def test_partial_errors_returns_successful_count(self):
        """Test that partial errors return actual successful count."""
        # Create mock errors
        mock_errors = []
        for i in range(5):  # 5 errors out of 1000
            error = MagicMock()
            error.object_name = f"failed-object-{i}"
            error.error_message = "Permission denied"
            mock_errors.append(error)
        
        with patch('app.services.storage_client.logger') as mock_logger:
            result = self.client._process_batch_delete_errors(
                errors=iter(mock_errors),
                bucket="test-bucket",
                batch_size=1000
            )
            
            # Should return 995 (1000 - 5 errors)
            self.assertEqual(result, 995, "Should return 995 when 5 out of 1000 failed")
            
            # Verify logging was called
            self.assertEqual(mock_logger.warning.call_count, 5, "Should log 5 warnings")
            mock_logger.info.assert_called_once()
            
            # Check the info log contains correct counts
            info_call = mock_logger.info.call_args
            self.assertEqual(info_call[0][0], "Batch delete completed with errors")
            self.assertEqual(info_call[1]['batch_size'], 1000)
            self.assertEqual(info_call[1]['errors'], 5)
            self.assertEqual(info_call[1]['successful'], 995)
    
    def test_all_errors_returns_zero(self):
        """Test that all errors returns 0."""
        # Create mock errors for all objects
        mock_errors = []
        for i in range(1000):  # All 1000 failed
            error = MagicMock()
            error.object_name = f"failed-object-{i}"
            error.error_message = "Access denied"
            mock_errors.append(error)
        
        with patch('app.services.storage_client.logger'):
            result = self.client._process_batch_delete_errors(
                errors=iter(mock_errors),
                bucket="test-bucket",
                batch_size=1000
            )
            
            # Should return 0 when all failed
            self.assertEqual(result, 0, "Should return 0 when all deletions failed")
    
    def test_single_error_returns_correct_count(self):
        """Test that a single error out of many returns correct count."""
        # Single error
        error = MagicMock()
        error.object_name = "single-failed-object"
        error.error_message = "Not found"
        
        with patch('app.services.storage_client.logger'):
            result = self.client._process_batch_delete_errors(
                errors=iter([error]),
                bucket="test-bucket",
                batch_size=100
            )
            
            # Should return 99 (100 - 1 error)
            self.assertEqual(result, 99, "Should return 99 when 1 out of 100 failed")
    
    def test_empty_batch_returns_zero(self):
        """Test that empty batch (batch_size=0) returns 0."""
        errors = []
        result = self.client._process_batch_delete_errors(
            errors=iter(errors),
            bucket="test-bucket",
            batch_size=0
        )
        self.assertEqual(result, 0, "Should return 0 for empty batch")


if __name__ == '__main__':
    unittest.main()