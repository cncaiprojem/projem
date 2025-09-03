#!/usr/bin/env python3
"""
Verify PR #430 fixes are correctly applied.
"""

import ast
import sys
import io
from pathlib import Path

# Force UTF-8 encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def check_fixes():
    """Check all PR #430 fixes."""
    file_path = Path("apps/api/app/services/upload_normalization_service.py")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return False
    
    content = file_path.read_text()
    
    # Parse the file
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"❌ Syntax error in file: {e}")
        return False
    
    all_passed = True
    
    # 1. Check comment about MatrixOfInertia is accurate
    if "eigenvalue decomposition which is complex and not always reliable" in content:
        print("✅ MatrixOfInertia comment accurately reflects implementation")
    else:
        print("❌ MatrixOfInertia comment still misleading")
        all_passed = False
    
    # 2. Check float comparison uses epsilon
    if "abs(scale_factor - 1.0) > EPSILON_FLOAT_COMPARISON" in content:
        print("✅ Float comparison uses epsilon for precision")
    else:
        print("❌ Float comparison still uses direct equality check")
        all_passed = False
    
    # 3. Check test file doesn't have sys.path manipulation
    test_path = Path("apps/api/tests/test_pr429_unit_conversion_fix.py")
    if test_path.exists():
        test_content = test_path.read_text()
        if "sys.path.insert" not in test_content:
            print("✅ Test file imports correctly without sys.path manipulation")
        else:
            print("❌ Test file still modifies sys.path")
            all_passed = False
    
    # 4. Check markdown file has no trailing space
    md_path = Path("PR429_FIXES_SUMMARY.md")
    if md_path.exists():
        md_content = md_path.read_text()
        lines = md_content.split('\n')
        has_trailing_space = False
        for i, line in enumerate(lines, 1):
            if line.endswith(' '):
                print(f"❌ Line {i} has trailing space: '{line}'")
                has_trailing_space = True
                all_passed = False
        if not has_trailing_space:
            print("✅ Markdown file has no trailing spaces")
    
    # 5. Verify EPSILON_FLOAT_COMPARISON is defined
    if "EPSILON_FLOAT_COMPARISON" in content:
        print("✅ EPSILON_FLOAT_COMPARISON constant is defined")
    else:
        print("❌ EPSILON_FLOAT_COMPARISON constant not found")
        all_passed = False
    
    # 6. Check that the comment doesn't promise inertia matrix implementation
    if "For now, use" not in content:
        print("✅ Comment doesn't promise future implementation")
    else:
        print("❌ Comment still contains 'For now' promise")
        all_passed = False
    
    return all_passed

if __name__ == "__main__":
    print("Verifying PR #430 fixes...")
    print("=" * 60)
    
    if check_fixes():
        print("\n✅ All PR #430 fixes are correctly applied!")
        sys.exit(0)
    else:
        print("\n❌ Some fixes are missing or incorrect")
        sys.exit(1)