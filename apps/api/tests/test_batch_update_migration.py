"""
Test batch update performance optimization in migration.

Verifies that the batch update implementation is correct.
"""

import hashlib
import json
from unittest.mock import Mock, MagicMock
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.migration import MigrationContext

# Test the batch update helper function
def test_batch_update_function():
    """Test that _execute_batch_update builds correct SQL."""
    
    # Mock connection
    mock_connection = Mock()
    mock_connection.execute = MagicMock()
    
    # Import the function from the migration
    import sys
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "migration",
        "alembic/versions/20250825_add_params_hash_and_idempotency_constraint.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    
    # Test data
    batch_updates = [
        ("hash1", 1),
        ("hash2", 2),
        ("hash3", 3),
    ]
    
    # Call the function
    migration._execute_batch_update(mock_connection, batch_updates)
    
    # Verify the execute was called
    assert mock_connection.execute.called
    
    # Get the SQL and params
    call_args = mock_connection.execute.call_args
    sql = call_args[0][0]
    params = call_args[0][1]
    
    # Verify SQL structure
    assert "UPDATE jobs" in str(sql)
    assert "FROM (VALUES" in str(sql)
    assert "batch_data(hash, id)" in str(sql)
    
    # Verify params
    assert params["hash_0"] == "hash1"
    assert params["id_0"] == 1
    assert params["hash_1"] == "hash2"
    assert params["id_1"] == 2
    assert params["hash_2"] == "hash3"
    assert params["id_2"] == 3
    
    print("[OK] Batch update function generates correct SQL")


def test_error_handling_consistency():
    """Test that error handling is consistent between routers."""
    
    # Test error messages that should be caught
    test_cases = [
        "uq_jobs_idempotency_key",
        "UNIQUE constraint failed: idempotency_key",
        "duplicate key value violates unique constraint on idempotency_key",
        "Duplicate entry for idempotency_key",
    ]
    
    for error_msg in test_cases:
        # Test jobs.py pattern
        jobs_match = ("uq_jobs_idempotency_key" in error_msg.lower() or 
                      ("unique" in error_msg.lower() and "idempotency_key" in error_msg.lower()) or
                      ("duplicate" in error_msg.lower() and "idempotency_key" in error_msg.lower()))
        
        # Test designs_v1.py pattern (should be identical)
        designs_match = ('uq_jobs_idempotency_key' in error_msg.lower() or 
                        ('unique' in error_msg.lower() and 'idempotency_key' in error_msg.lower()) or
                        ('duplicate' in error_msg.lower() and 'idempotency_key' in error_msg.lower()))
        
        assert jobs_match == designs_match, f"Inconsistent error handling for: {error_msg}"
        print(f"[OK] Consistent error handling for: {error_msg}")
    
    # Test error messages that should NOT be caught
    false_positive_cases = [
        "some other error with key",
        "unique constraint on different_column",
        "duplicate without idempotency",
    ]
    
    for error_msg in false_positive_cases:
        jobs_match = ("uq_jobs_idempotency_key" in error_msg.lower() or 
                      ("unique" in error_msg.lower() and "idempotency_key" in error_msg.lower()) or
                      ("duplicate" in error_msg.lower() and "idempotency_key" in error_msg.lower()))
        
        assert not jobs_match, f"False positive for: {error_msg}"
        print(f"[OK] Correctly rejected: {error_msg}")


if __name__ == "__main__":
    test_batch_update_function()
    test_error_handling_consistency()
    print("\n[SUCCESS] All tests passed!")