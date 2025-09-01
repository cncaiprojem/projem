"""
Simple Integration Test for PR #407 Code Review Fixes

Validates that the enterprise-grade fixes have been applied correctly:
1. worker_script.py uses os.path.realpath in fallback
2. bom.py uses TemporaryDirectory
3. geometry_validator.py uses FreeCAD Vector methods
4. standard_parts.py has extracted helper methods
"""

import os
import re
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_worker_script_security():
    """Verify worker_script.py uses os.path.realpath for security."""
    file_path = Path(__file__).parent.parent / "app/services/freecad/worker_script.py"
    content = file_path.read_text()
    
    # Check for os.path.realpath usage in fallback
    assert "os.path.realpath" in content, "worker_script.py should use os.path.realpath"
    assert "os.path.commonpath" in content, "worker_script.py should use os.path.commonpath"
    
    # Verify old insecure pattern is not present
    assert "Path(path).resolve()" not in content, "Should not use Path.resolve() in fallback"
    
    print("[OK] worker_script.py: Security hardening verified")


def test_bom_temp_directory():
    """Verify bom.py uses TemporaryDirectory for cleanup."""
    file_path = Path(__file__).parent.parent / "app/services/freecad/bom.py"
    content = file_path.read_text()
    
    # Check for TemporaryDirectory usage
    assert "TemporaryDirectory" in content, "bom.py should use TemporaryDirectory"
    assert "prefix='freecad_brep_'" in content, "Should use descriptive prefix"
    
    # Verify the context manager pattern
    assert "with tempfile.TemporaryDirectory" in content, "Should use context manager"
    
    # Check that manual cleanup is removed
    assert "os_module.unlink(tmp_path)" not in content, "Should not have manual cleanup"
    
    print("[OK] bom.py: TemporaryDirectory usage verified")


def test_geometry_validator_vector_methods():
    """Verify geometry_validator.py uses FreeCAD Vector methods."""
    file_path = Path(__file__).parent.parent / "app/services/freecad/geometry_validator.py"
    content = file_path.read_text()
    
    # Check for FreeCAD Vector usage
    assert "FreeCAD.Vector" in content, "Should create FreeCAD Vector"
    assert "getAngle" in content, "Should use Vector.getAngle() method"
    assert "normal.dot(pull_vector)" in content, "Should use Vector.dot() method"
    
    # Verify old manual calculation is removed
    assert "math.acos(clamped_dot)" not in content, "Should not use manual acos calculation"
    
    print("[OK] geometry_validator.py: FreeCAD Vector methods verified")


def test_standard_parts_helper_methods():
    """Verify standard_parts.py has extracted helper methods."""
    file_path = Path(__file__).parent.parent / "app/services/freecad/standard_parts.py"
    content = file_path.read_text()
    
    # Check for extracted helper methods
    assert "def _approximate_thread_pitch" in content, "Should have _approximate_thread_pitch method"
    assert "def _approximate_head_dimensions" in content, "Should have _approximate_head_dimensions method"
    
    # Verify the methods are called
    assert "self._approximate_thread_pitch(diameter)" in content, "Should call helper method"
    assert "self._approximate_head_dimensions(diameter)" in content, "Should call helper method"
    
    # Check for proper return types
    assert "-> float:" in content, "Thread pitch method should return float"
    assert "-> Tuple[float, float]:" in content, "Head dimensions should return tuple"
    
    print("[OK] standard_parts.py: Helper methods extracted and verified")


def test_all_files_compile():
    """Verify all modified files compile without syntax errors."""
    files = [
        "app/services/freecad/worker_script.py",
        "app/services/freecad/bom.py",
        "app/services/freecad/geometry_validator.py",
        "app/services/freecad/standard_parts.py"
    ]
    
    base_path = Path(__file__).parent.parent
    
    for file_rel in files:
        file_path = base_path / file_rel
        try:
            compile(file_path.read_text(), str(file_path), 'exec')
            print(f"[OK] {file_rel}: Compiles successfully")
        except SyntaxError as e:
            raise AssertionError(f"Syntax error in {file_rel}: {e}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("PR #407 Code Review Fixes - Integration Tests")
    print("=" * 60)
    
    try:
        test_worker_script_security()
        test_bom_temp_directory()
        test_geometry_validator_vector_methods()
        test_standard_parts_helper_methods()
        test_all_files_compile()
        
        print("=" * 60)
        print("[SUCCESS] ALL TESTS PASSED - PR #407 fixes verified!")
        print("=" * 60)
        
        print("\nSummary of fixes applied:")
        print("1. [OK] worker_script.py: Enhanced security with os.path.realpath")
        print("2. [OK] bom.py: Simplified with TemporaryDirectory context manager")
        print("3. [OK] geometry_validator.py: Using FreeCAD's Vector.getAngle()")
        print("4. [OK] standard_parts.py: Extracted helper methods for clarity")
        
    except AssertionError as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()