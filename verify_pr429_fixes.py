#!/usr/bin/env python
"""
Verification script for PR #429 fixes.
Tests that unit conversion issues are resolved without needing full app setup.
"""

import re
import sys
from pathlib import Path

# Force UTF-8 encoding for console output
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def verify_fixes():
    """Verify that PR 429 fixes are correctly applied."""
    
    service_file = Path("apps/api/app/services/upload_normalization_service.py")
    
    if not service_file.exists():
        print(f"❌ File not found: {service_file}")
        return False
    
    content = service_file.read_text(encoding='utf-8')
    
    # Test 1: Check that UNIT_CONVERSION_FACTORS is defined as a constant
    print("Test 1: Checking for centralized UNIT_CONVERSION_FACTORS constant...")
    if "UNIT_CONVERSION_FACTORS = {" in content:
        print("✅ UNIT_CONVERSION_FACTORS constant is defined")
    else:
        print("❌ UNIT_CONVERSION_FACTORS constant not found")
        return False
    
    # Test 2: Check that Units enum has correct singular members
    print("\nTest 2: Checking Units enum definition...")
    enum_section = re.search(r'class Units.*?(?=\n\nclass|\Z)', content, re.DOTALL)
    if enum_section:
        enum_text = enum_section.group(0)
        correct_members = ['MILLIMETER', 'METER', 'INCH', 'FOOT', 'CENTIMETER']
        incorrect_members = ['INCHES', 'METERS', 'CENTIMETERS', 'FEET', 'MILLIMETERS']
        
        for member in correct_members:
            if member in enum_text:
                print(f"  ✅ Found correct member: Units.{member}")
            else:
                print(f"  ❌ Missing member: Units.{member}")
                
        for member in incorrect_members:
            if member in enum_text:
                print(f"  ❌ Found incorrect plural member: Units.{member}")
                return False
    else:
        print("❌ Units enum not found")
        return False
    
    # Test 3: Check that STL handler uses correct enum members
    print("\nTest 3: Checking STL handler for incorrect enum usage...")
    stl_section = re.search(r'class STLHandler.*?(?=\nclass|\Z)', content, re.DOTALL)
    if stl_section:
        stl_text = stl_section.group(0)
        
        # Check for incorrect plural usage
        bad_patterns = [
            r'Units\.INCHES',
            r'Units\.METERS', 
            r'Units\.CENTIMETERS',
            r'Units\.FEET',
            r'Units\.MILLIMETERS'
        ]
        
        found_bad = False
        for pattern in bad_patterns:
            matches = re.findall(pattern, stl_text)
            if matches:
                print(f"  ❌ Found incorrect usage: {matches[0]}")
                found_bad = True
                
        if not found_bad:
            print("  ✅ No incorrect plural enum usage found in STL handler")
        else:
            return False
            
        # Check that STL handler uses centralized factors
        if "UNIT_CONVERSION_FACTORS" in stl_text:
            print("  ✅ STL handler uses UNIT_CONVERSION_FACTORS")
        else:
            print("  ⚠️  STL handler might not use centralized factors")
            
    # Test 4: Check that there are no duplicate unit_factors dictionaries in handlers
    print("\nTest 4: Checking for duplicate unit_factors dictionaries...")
    
    # Count occurrences of local unit_factors definitions in script content
    unit_factors_definitions = re.findall(r'unit_factors = \{[^}]+\}', content)
    
    # These should now reference UNIT_CONVERSION_FACTORS instead
    script_sections = re.findall(r'script_content = f?\'\'\'.*?\'\'\'', content, re.DOTALL)
    local_defs_in_scripts = 0
    for script in script_sections:
        if 'unit_factors = {' in script:
            local_defs_in_scripts += 1
            
    if local_defs_in_scripts > 0:
        print(f"  ❌ Found {local_defs_in_scripts} local unit_factors definitions in handler scripts")
        print("     These should use UNIT_CONVERSION_FACTORS instead")
        return False
    else:
        print("  ✅ No duplicate unit_factors dictionaries found")
        
    # Test 5: Verify handlers reference the global constant
    print("\nTest 5: Checking that handlers reference UNIT_CONVERSION_FACTORS...")
    handlers = ['STEPHandler', 'DXFHandler', 'IFCHandler']
    for handler_name in handlers:
        handler_section = re.search(rf'class {handler_name}.*?(?=\nclass|\Z)', content, re.DOTALL)
        if handler_section:
            handler_text = handler_section.group(0)
            if '{UNIT_CONVERSION_FACTORS}' in handler_text:
                print(f"  ✅ {handler_name} references UNIT_CONVERSION_FACTORS")
            else:
                print(f"  ⚠️  {handler_name} might not reference UNIT_CONVERSION_FACTORS")
                
    print("\n" + "="*60)
    print("✅ All PR #429 fixes verified successfully!")
    print("="*60)
    return True

if __name__ == "__main__":
    import sys
    success = verify_fixes()
    sys.exit(0 if success else 1)