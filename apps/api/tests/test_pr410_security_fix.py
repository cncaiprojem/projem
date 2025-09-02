"""
Test suite for PR #410 security fixes
Verifies path traversal vulnerability fixes in a4_assembly.py
"""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_a4_assembly_secure_path_validation():
    """Test that a4_assembly.py uses secure path validation."""
    
    # Create a temporary directory structure for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create allowed directory
        allowed_dir = Path(temp_dir) / "allowed"
        allowed_dir.mkdir()
        
        # Create a file in allowed directory
        allowed_file = allowed_dir / "test.txt"
        allowed_file.write_text("test")
        
        # Create a directory outside allowed area
        outside_dir = Path(temp_dir) / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("secret")
        
        # Mock the Assembly4Manager class to test path validation
        from app.services.freecad.a4_assembly import Assembly4Manager
        
        # Test with PathValidator not available (fallback mode)
        with patch('app.services.freecad.a4_assembly.PathValidator', None):
            assembly = Assembly4Manager()
            assembly.ALLOWED_UPLOAD_DIRS = [str(allowed_dir)]
            assembly._resolved_upload_dirs = [Path(os.path.realpath(str(allowed_dir)))]
            
            # Test 1: Valid path within allowed directory
            valid_path = assembly._validate_file_path(str(allowed_file))
            assert valid_path == Path(os.path.realpath(str(allowed_file)))
            
            # Test 2: Relative path within allowed directory
            rel_path = "test.txt"
            valid_rel = assembly._validate_file_path(rel_path)
            assert valid_rel == Path(os.path.realpath(str(allowed_file)))
            
            # Test 3: Path traversal attempt should fail
            traversal_path = "../outside/secret.txt"
            with pytest.raises(ValueError, match="outside allowed directories"):
                assembly._validate_file_path(traversal_path)
            
            # Test 4: Absolute path outside allowed directory should fail
            with pytest.raises(ValueError, match="outside allowed directories"):
                assembly._validate_file_path(str(outside_file))
            
            # Test 5: Empty path should fail
            with pytest.raises(ValueError, match="Path cannot be empty"):
                assembly._validate_file_path("")
            
            # Test 6: None path should fail
            with pytest.raises(ValueError, match="Path cannot be empty"):
                assembly._validate_file_path(None)


def test_a4_assembly_symlink_attack_prevention():
    """Test that symlink attacks are prevented."""
    
    # This test requires symlink support
    if not hasattr(os, 'symlink'):
        pytest.skip("Symlinks not supported on this platform")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create allowed directory
        allowed_dir = Path(temp_dir) / "allowed"
        allowed_dir.mkdir()
        
        # Create a sensitive file outside allowed area
        outside_dir = Path(temp_dir) / "outside"
        outside_dir.mkdir()
        sensitive_file = outside_dir / "sensitive.txt"
        sensitive_file.write_text("sensitive data")
        
        # Create a symlink inside allowed directory pointing outside
        symlink_path = allowed_dir / "evil_link.txt"
        try:
            symlink_path.symlink_to(sensitive_file)
        except OSError:
            pytest.skip("Cannot create symlinks (permission denied)")
        
        from app.services.freecad.a4_assembly import Assembly4Manager
        
        # Test with PathValidator not available (fallback mode)
        with patch('app.services.freecad.a4_assembly.PathValidator', None):
            assembly = Assembly4Manager()
            assembly.ALLOWED_UPLOAD_DIRS = [str(allowed_dir)]
            assembly._resolved_upload_dirs = [Path(os.path.realpath(str(allowed_dir)))]
            
            # Attempting to access the symlink should fail
            # because realpath resolves it to outside the allowed directory
            with pytest.raises(ValueError, match="outside allowed directories"):
                assembly._validate_file_path(str(symlink_path))


def test_a4_assembly_initialization_uses_realpath():
    """Test that A4Assembly initialization uses os.path.realpath."""
    
    from app.services.freecad.a4_assembly import Assembly4Manager
    
    with tempfile.TemporaryDirectory() as temp_dir:
        test_dirs = [
            str(Path(temp_dir) / "dir1"),
            str(Path(temp_dir) / "dir2"),
        ]
        
        # Create the directories
        for d in test_dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        
        # Mock the ALLOWED_UPLOAD_DIRS
        with patch.object(Assembly4Manager, 'ALLOWED_UPLOAD_DIRS', test_dirs):
            assembly = Assembly4Manager()
            
            # Verify that _resolved_upload_dirs uses realpath
            for resolved_dir in assembly._resolved_upload_dirs:
                # Check that the path is absolute and resolved
                assert resolved_dir.is_absolute()
                # Verify it matches realpath resolution
                original = next(d for d in test_dirs if Path(d).name == resolved_dir.name)
                assert str(resolved_dir) == os.path.realpath(original)


def test_secure_pattern_matches_worker_script():
    """Verify that the security pattern in a4_assembly matches worker_script."""
    
    # Read both files to check the pattern
    import inspect
    from app.services.freecad.a4_assembly import Assembly4Manager
    
    # Get the source code of the _validate_file_path method
    source = inspect.getsource(Assembly4Manager._validate_file_path)
    
    # Check for secure patterns
    assert "os.path.realpath" in source, "Should use os.path.realpath for secure path resolution"
    assert "os.path.commonpath" in source, "Should use os.path.commonpath for secure containment check"
    assert "Path(file_path).resolve()" not in source, "Should NOT use vulnerable Path.resolve()"
    
    # Check for proper relative path handling
    assert "os.path.join" in source, "Should properly join relative paths"
    assert "os.path.isabs" in source, "Should check for absolute paths"


if __name__ == "__main__":
    # Run the tests
    test_a4_assembly_secure_path_validation()
    test_a4_assembly_symlink_attack_prevention()
    test_a4_assembly_initialization_uses_realpath()
    test_secure_pattern_matches_worker_script()
    print("✅ All PR #410 security tests passed!")