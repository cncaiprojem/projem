#!/usr/bin/env python3
"""
Verify PR #410 security fix in a4_assembly.py
"""

import os
import sys
import re
from pathlib import Path

# Set UTF-8 encoding for Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def verify_secure_patterns():
    """Verify that the security fixes have been applied correctly."""
    
    # Read the a4_assembly.py file
    file_path = Path("apps/api/app/services/freecad/a4_assembly.py")
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return False
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    errors = []
    
    # Check 1: No vulnerable Path().resolve() patterns
    vulnerable_pattern = r'Path\([^)]*\)\.resolve\(\)'
    if re.search(vulnerable_pattern, content):
        errors.append("❌ Found vulnerable Path().resolve() pattern")
    else:
        print("✅ No vulnerable Path().resolve() patterns found")
    
    # Check 2: Uses os.path.realpath for secure resolution
    if 'os.path.realpath' not in content:
        errors.append("❌ Missing os.path.realpath for secure path resolution")
    else:
        count = content.count('os.path.realpath')
        print(f"✅ Uses os.path.realpath ({count} occurrences)")
    
    # Check 3: Uses os.path.commonpath for containment check
    if 'os.path.commonpath' not in content:
        errors.append("❌ Missing os.path.commonpath for secure containment check")
    else:
        print("✅ Uses os.path.commonpath for secure containment check")
    
    # Check 4: Proper handling of relative paths
    if 'os.path.join' not in content:
        errors.append("❌ Missing os.path.join for proper relative path handling")
    else:
        print("✅ Uses os.path.join for proper relative path handling")
    
    # Check 5: Checks for absolute paths
    if 'os.path.isabs' not in content:
        errors.append("❌ Missing os.path.isabs check")
    else:
        print("✅ Checks for absolute paths with os.path.isabs")
    
    # Check 6: Empty path validation
    if 'Path cannot be empty' not in content:
        errors.append("❌ Missing empty path validation")
    else:
        print("✅ Validates against empty paths")
    
    # Check specific vulnerable lines that were fixed
    lines = content.split('\n')
    
    # Check around line 193 (initialization)
    init_section = '\n'.join(lines[190:200])
    if 'Path(d).resolve()' in init_section:
        errors.append("❌ Line ~193: Still using vulnerable Path().resolve() in initialization")
    elif 'os.path.realpath' in init_section:
        print("✅ Line ~193: Fixed - uses os.path.realpath in initialization")
    
    # Check fallback validation section (around line 753)
    if len(lines) > 760:
        fallback_section = '\n'.join(lines[750:785])
        if 'Path(file_path).resolve()' in fallback_section:
            errors.append("❌ Line ~753: Still using vulnerable Path().resolve() in fallback validation")
        elif 'os.path.realpath' in fallback_section and 'os.path.commonpath' in fallback_section:
            print("✅ Line ~753: Fixed - uses secure pattern in fallback validation")
    
    # Report results
    if errors:
        print("\n⚠️  Security Issues Found:")
        for error in errors:
            print(f"  {error}")
        return False
    else:
        print("\n✅ All security checks passed!")
        print("The PR #410 security fix has been successfully applied.")
        return True


def compare_with_worker_script():
    """Compare security patterns with worker_script.py."""
    
    worker_path = Path("apps/api/app/services/freecad/worker_script.py")
    a4_path = Path("apps/api/app/services/freecad/a4_assembly.py")
    
    if not worker_path.exists() or not a4_path.exists():
        print("Could not find both files for comparison")
        return
    
    print("\n📊 Comparing security patterns with worker_script.py:")
    
    with open(worker_path, 'r', encoding='utf-8') as f:
        worker_content = f.read()
    
    with open(a4_path, 'r', encoding='utf-8') as f:
        a4_content = f.read()
    
    # Extract the fallback validation section from worker_script
    worker_lines = worker_content.split('\n')
    worker_fallback = '\n'.join(worker_lines[1170:1210])
    
    # Check that both use the same security patterns
    patterns = [
        ('os.path.realpath', 'Using os.path.realpath for symlink resolution'),
        ('os.path.commonpath', 'Using os.path.commonpath for containment check'),
        ('os.path.join', 'Properly joining relative paths'),
        ('os.path.isabs', 'Checking for absolute paths'),
    ]
    
    for pattern, description in patterns:
        in_worker = pattern in worker_fallback
        in_a4 = pattern in a4_content
        
        if in_worker and in_a4:
            print(f"  ✅ Both files: {description}")
        elif in_worker and not in_a4:
            print(f"  ⚠️  Missing in a4_assembly.py: {description}")
        elif not in_worker and in_a4:
            print(f"  ℹ️  Only in a4_assembly.py: {description}")


if __name__ == "__main__":
    print("=" * 60)
    print("PR #410 Security Fix Verification")
    print("=" * 60)
    
    success = verify_secure_patterns()
    compare_with_worker_script()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ VERIFICATION PASSED: Security fix is correctly applied")
    else:
        print("❌ VERIFICATION FAILED: Security issues remain")
    print("=" * 60)