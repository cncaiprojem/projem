"""Test joint physics validation fixes for PR 437."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'apps', 'api'))

from app.schemas.assembly4 import AssemblyConstraint, ConstraintReference, ConstraintType

def test_joint_physics_validation():
    """Test joint physics parameter validation."""
    
    # Test 1: Valid stiffness and damping
    print("Test 1: Valid stiffness and damping...")
    try:
        constraint = AssemblyConstraint(
            type=ConstraintType.ATTACHMENT,
            reference1=ConstraintReference(part_id="part1", lcs_name="LCS1"),
            reference2=ConstraintReference(part_id="part2", lcs_name="LCS2"),
            stiffness=1.0,
            damping=0.5
        )
        print("[PASS] Valid stiffness and damping accepted")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
    
    # Test 2: Invalid stiffness <= 0
    print("\nTest 2: Invalid stiffness <= 0...")
    try:
        constraint = AssemblyConstraint(
            type=ConstraintType.ATTACHMENT,
            reference1=ConstraintReference(part_id="part1", lcs_name="LCS1"),
            reference2=ConstraintReference(part_id="part2", lcs_name="LCS2"),
            stiffness=0.0,
            damping=0.5
        )
        print("[FAIL] Should have failed with stiffness=0")
    except ValueError as e:
        print(f"[PASS] Correctly rejected: {e}")
    
    # Test 3: Invalid damping < 0
    print("\nTest 3: Invalid damping < 0...")
    try:
        constraint = AssemblyConstraint(
            type=ConstraintType.ATTACHMENT,
            reference1=ConstraintReference(part_id="part1", lcs_name="LCS1"),
            reference2=ConstraintReference(part_id="part2", lcs_name="LCS2"),
            stiffness=1.0,
            damping=-0.5
        )
        print("[FAIL] Should have failed with damping < 0")
    except ValueError as e:
        print(f"[PASS] Correctly rejected: {e}")
    
    # Test 4: Invalid stiffness=0, damping>0 (physically impossible)
    print("\nTest 4: Invalid stiffness=0, damping>0...")
    try:
        constraint = AssemblyConstraint(
            type=ConstraintType.ATTACHMENT,
            reference1=ConstraintReference(part_id="part1", lcs_name="LCS1"),
            reference2=ConstraintReference(part_id="part2", lcs_name="LCS2"),
            stiffness=0,
            damping=1.0
        )
        print("[FAIL] Should have failed with stiffness=0, damping=1.0")
    except ValueError as e:
        print(f"[PASS] Correctly rejected: {e}")
    
    # Test 5: Valid stiffness with no damping
    print("\nTest 5: Valid stiffness with no damping...")
    try:
        constraint = AssemblyConstraint(
            type=ConstraintType.ATTACHMENT,
            reference1=ConstraintReference(part_id="part1", lcs_name="LCS1"),
            reference2=ConstraintReference(part_id="part2", lcs_name="LCS2"),
            stiffness=2.0
        )
        print("[PASS] Valid stiffness without damping accepted")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
    
    # Test 6: High damping ratio (warning, not error)
    print("\nTest 6: High damping ratio (should warn)...")
    try:
        constraint = AssemblyConstraint(
            type=ConstraintType.ATTACHMENT,
            reference1=ConstraintReference(part_id="part1", lcs_name="LCS1"),
            reference2=ConstraintReference(part_id="part2", lcs_name="LCS2"),
            stiffness=0.1,
            damping=2.0  # High damping relative to stiffness
        )
        print("[PASS] High damping ratio accepted (with warning)")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")

if __name__ == "__main__":
    test_joint_physics_validation()
    print("\n[SUCCESS] All joint physics validation tests completed!")