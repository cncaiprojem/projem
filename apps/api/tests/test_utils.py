"""
Shared test utilities for FreeCAD API tests.

This module provides common functions and patterns used across test files,
ensuring consistency and reducing duplication in test setup and teardown.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def setup_test_paths() -> Path:
    """
    Setup Python path for test imports in a robust and consistent way.
    
    This function adds the necessary directories to sys.path to allow
    imports of the main application modules from test files. It uses
    absolute paths and ensures idempotent behavior (safe to call multiple times).
    
    Returns:
        Path: The project root directory for reference
        
    Example:
        >>> from test_utils import setup_test_paths
        >>> project_root = setup_test_paths()
        >>> from app.services.freecad.worker_script import FreeCADWorker
    """
    # Get the tests directory (parent of this file)
    tests_dir = Path(__file__).parent.absolute()
    
    # Get the api directory (parent of tests)
    api_dir = tests_dir.parent
    
    # Get the project root (parent of parent of api)
    project_root = api_dir.parent.parent
    
    # Add api directory to path if not already present
    # This allows imports like "from app.services.freecad import ..."
    api_dir_str = str(api_dir)
    if api_dir_str not in sys.path:
        sys.path.insert(0, api_dir_str)
    
    # Also add project root for imports that start from apps
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    
    return project_root


def get_test_data_path(filename: Optional[str] = None) -> Path:
    """
    Get the path to the test data directory.
    
    Args:
        filename: Optional filename within the test data directory
        
    Returns:
        Path: Path to test data directory or specific file
        
    Example:
        >>> from test_utils import get_test_data_path
        >>> data_dir = get_test_data_path()
        >>> test_file = get_test_data_path("sample.fcstd")
    """
    tests_dir = Path(__file__).parent.absolute()
    test_data_dir = tests_dir / "test_data"
    
    # Create test data directory if it doesn't exist
    test_data_dir.mkdir(exist_ok=True)
    
    if filename:
        return test_data_dir / filename
    return test_data_dir


def cleanup_test_artifacts(*paths: Path) -> None:
    """
    Clean up test artifacts safely.
    
    Args:
        *paths: Variable number of Path objects to clean up
        
    Example:
        >>> from test_utils import cleanup_test_artifacts
        >>> test_file = Path("/tmp/test.txt")
        >>> cleanup_test_artifacts(test_file)
    """
    for path in paths:
        if path and path.exists():
            try:
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except (OSError, PermissionError):
                # Ignore cleanup errors in tests
                pass


# Test constants that are commonly used
TEST_FILE_LINE_COUNT = 60  # Standard number of lines for file reading tests
TEST_TIMEOUT = 30  # Standard timeout for async operations in seconds
MOCK_USER_ID = "test-user-123"  # Standard mock user ID
MOCK_JOB_ID = "job-456"  # Standard mock job ID


class TestDataGenerator:
    """Helper class for generating consistent test data."""
    
    @staticmethod
    def create_test_file_with_lines(path: Path, line_count: int = TEST_FILE_LINE_COUNT) -> Path:
        """
        Create a test file with a specific number of lines.
        
        Args:
            path: Path where the file should be created
            line_count: Number of lines to write (default: TEST_FILE_LINE_COUNT)
            
        Returns:
            Path: The path to the created file
            
        Example:
            >>> from test_utils import TestDataGenerator
            >>> generator = TestDataGenerator()
            >>> test_file = generator.create_test_file_with_lines(Path("/tmp/test.txt"))
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            for i in range(line_count):
                f.write(f"Line {i + 1}: Test data for validation\n")
        return path
    
    @staticmethod
    def create_mock_freecad_document(name: str = "TestDoc") -> dict:
        """
        Create a mock FreeCAD document structure for testing.
        
        Args:
            name: Name of the document
            
        Returns:
            dict: Mock document structure
        """
        return {
            "Name": name,
            "Objects": [],
            "Properties": {},
            "Label": name,
            "FileName": f"{name}.FCStd"
        }