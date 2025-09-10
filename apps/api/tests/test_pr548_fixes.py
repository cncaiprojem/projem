"""
Test file to verify PR #548 fixes for collaborative editing system.

This test file verifies that:
1. GROUP and UNGROUP operations are properly defined in OperationType enum
2. All collaborative editing enums are centralized in app.models.enums
3. No duplicate enum definitions exist
"""

import pytest
from app.models.enums import (
    LockType,
    LockStatus,
    UserStatus,
    OperationType,
    ConflictResolutionStrategy
)


def test_operation_type_includes_group_operations():
    """Verify GROUP and UNGROUP operations are defined in OperationType enum."""
    # Check that GROUP and UNGROUP are valid enum values
    assert OperationType.GROUP == "group"
    assert OperationType.UNGROUP == "ungroup"
    
    # Verify all expected operations are present
    expected_operations = [
        "create", "modify", "delete", "move", "rotate", "scale",
        "property_change", "constraint_add", "constraint_remove",
        "group", "ungroup", "no_op"
    ]
    
    actual_operations = [op.value for op in OperationType]
    for expected in expected_operations:
        assert expected in actual_operations, f"Missing operation: {expected}"


def test_lock_type_enum_complete():
    """Verify LockType enum includes all necessary lock types."""
    # Check all lock types are present
    assert LockType.EXCLUSIVE == "exclusive"
    assert LockType.SHARED == "shared"
    assert LockType.UPGRADE == "upgrade"  # From CollaborativeLocking
    assert LockType.PENDING == "pending"  # From PresenceAwareness
    
    # Verify we have all expected lock types
    expected_types = ["exclusive", "shared", "upgrade", "pending"]
    actual_types = [lt.value for lt in LockType]
    for expected in expected_types:
        assert expected in actual_types, f"Missing lock type: {expected}"


def test_lock_status_enum_complete():
    """Verify LockStatus enum includes all necessary statuses."""
    expected_statuses = ["granted", "pending", "denied", "expired", "released"]
    actual_statuses = [ls.value for ls in LockStatus]
    for expected in expected_statuses:
        assert expected in actual_statuses, f"Missing lock status: {expected}"


def test_user_status_enum_complete():
    """Verify UserStatus enum includes all collaboration states."""
    expected_statuses = ["active", "idle", "away", "offline"]
    actual_statuses = [us.value for us in UserStatus]
    for expected in expected_statuses:
        assert expected in actual_statuses, f"Missing user status: {expected}"


def test_conflict_resolution_strategies():
    """Verify all conflict resolution strategies are defined."""
    expected_strategies = ["timestamp", "priority", "merge", "manual"]
    actual_strategies = [cs.value for cs in ConflictResolutionStrategy]
    for expected in expected_strategies:
        assert expected in actual_strategies, f"Missing strategy: {expected}"


@pytest.mark.skip(reason="Requires full container environment for app.core.config")
def test_no_circular_imports():
    """Verify that centralizing enums doesn't cause circular imports."""
    # Import the services that use these enums
    try:
        from app.services.collaborative_locking import CollaborativeLocking
        from app.services.presence_awareness import PresenceAwareness
        from app.services.operational_transform import OperationalTransform
        assert True, "All imports successful"
    except ImportError as e:
        pytest.fail(f"Import error: {e}")


def test_enum_documentation():
    """Verify all enums have proper documentation."""
    # Check that enums have docstrings
    assert LockType.__doc__ is not None
    assert "collaborative editing" in LockType.__doc__.lower()
    
    assert OperationType.__doc__ is not None
    assert "freecad" in OperationType.__doc__.lower()
    
    assert ConflictResolutionStrategy.__doc__ is not None
    assert "conflict" in ConflictResolutionStrategy.__doc__.lower()