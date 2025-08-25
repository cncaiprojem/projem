"""Add params_hash and named idempotency constraint for PR281

Revision ID: pr281_params_hash
Revises: 20250824_add_jobtype_assembly
Create Date: 2025-08-25 16:00:00

This migration addresses PR #281 feedback:
1. Adds params_hash column to jobs table for performance optimization
2. Adds named unique constraint on idempotency_key for database-agnostic error handling
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import json
import hashlib

# Try to import the batch update utility
try:
    from alembic.utils.batch_update import execute_params_hash_batch_update
    USE_BATCH_UTILITY = True
except ImportError:
    # Fallback to local implementation if utility not available
    USE_BATCH_UTILITY = False


# Revision identifiers
revision = 'pr281_params_hash'
down_revision = '20250824_add_jobtype_assembly'
branch_labels = None
depends_on = None


def get_constraint_name(connection, table_name: str, column_name: str) -> str:
    """
    Programmatically find the unique constraint name for a column.
    This makes the migration more robust across different environments.
    
    Args:
        connection: Database connection
        table_name: Name of the table
        column_name: Name of the column with unique constraint
        
    Returns:
        Name of the unique constraint or None if not found
    """
    # Query to find unique constraint on the column
    # This works for PostgreSQL - other databases may need different queries
    result = connection.execute(sa.text("""
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
            AND tc.table_schema = ccu.table_schema
        WHERE tc.table_name = :table_name
        AND ccu.column_name = :column_name
        AND tc.constraint_type = 'UNIQUE'
        AND tc.table_schema = current_schema()
    """), {'table_name': table_name, 'column_name': column_name})
    
    row = result.first()
    return row[0] if row else None


def _execute_batch_update(connection, batch_updates):
    """
    Execute batch updates efficiently using PostgreSQL's UPDATE ... FROM (VALUES ...) syntax.
    This significantly improves performance compared to individual UPDATE statements.
    
    Args:
        connection: Database connection
        batch_updates: List of (params_hash, job_id) tuples to update
    """
    if not batch_updates:
        return
    
    # Build the VALUES clause for batch update
    # Using PostgreSQL's UPDATE ... FROM (VALUES ...) syntax for efficiency
    values_list = []
    params = {}
    
    for i, (params_hash, job_id) in enumerate(batch_updates):
        values_list.append(f"(:hash_{i}, :id_{i})")
        params[f"hash_{i}"] = params_hash
        params[f"id_{i}"] = job_id
    
    values_clause = ", ".join(values_list)
    
    # Execute batch update using UPDATE ... FROM (VALUES ...) syntax
    # This is much more efficient than individual updates
    sql = sa.text(f"""
        UPDATE jobs 
        SET params_hash = batch_data.hash
        FROM (VALUES {values_clause}) AS batch_data(hash, id)
        WHERE jobs.id = batch_data.id
    """)
    
    connection.execute(sql, params)


def upgrade() -> None:
    """
    Add params_hash column and named unique constraint for idempotency.
    
    Performance optimization: Store hash of params to avoid recalculating on each check.
    Portability: Named constraint allows database-agnostic error handling.
    """
    
    # Add params_hash column to store pre-calculated hash of job parameters
    op.add_column('jobs', sa.Column(
        'params_hash',
        sa.String(64),  # SHA-256 produces 64 character hex string
        nullable=True,
        comment='SHA-256 hash of params for efficient idempotency checks'
    ))
    
    # Create index on params_hash for fast lookups
    op.create_index(
        'idx_jobs_params_hash',
        'jobs',
        ['params_hash'],
        postgresql_where='params_hash IS NOT NULL'
    )
    
    # Drop the existing unnamed unique constraint on idempotency_key
    # Programmatically find the constraint name to make migration more robust
    connection = op.get_bind()
    constraint_name = get_constraint_name(connection, 'jobs', 'idempotency_key')
    
    if constraint_name:
        op.drop_constraint(constraint_name, 'jobs', type_='unique')
    else:
        # Fallback to common naming patterns if constraint not found
        # Try PostgreSQL's default naming convention
        try:
            op.drop_constraint('jobs_idempotency_key_key', 'jobs', type_='unique')
        except sa.exc.ProgrammingError as e:
            # Constraint likely does not exist, which is acceptable. Log for visibility.
            print(f"Warning: Could not drop constraint 'jobs_idempotency_key_key', it may not exist: {e}")
            pass
    
    # Create a named unique constraint for database-agnostic error handling
    op.create_unique_constraint(
        'uq_jobs_idempotency_key',  # Named constraint for portable error handling
        'jobs',
        ['idempotency_key']
    )
    
    # Populate params_hash for existing jobs (optional, can be done separately)
    # This is a data migration that calculates hash for existing records
    # CRITICAL: Database column naming clarification:
    # - The actual database column is named 'input_params'
    # - The SQLAlchemy model property is named 'params' for Python code
    # - The mapping is done via: params: Mapped[dict] = mapped_column(..., name="input_params")
    # - Always use 'input_params' in raw SQL/database operations
    # - Always use 'params' when working with SQLAlchemy ORM models in Python
    # 
    # IMPORTANT: We need to match the application's canonical JSON format for consistency
    # The application uses: json.dumps(params, sort_keys=True, separators=(',', ':'))
    # PostgreSQL's jsonb_build_object with ordered keys approximates this behavior
    connection = op.get_bind()
    
    # For PostgreSQL, use batch updates for performance optimization
    # This ensures existing jobs will have the same hash as newly created ones
    if connection.dialect.name == 'postgresql':
        # Fetch all jobs with idempotency keys
        result = connection.execute(sa.text(
            "SELECT id, input_params FROM jobs WHERE idempotency_key IS NOT NULL"
        ))
        
        # Collect all updates in batches for efficient processing
        batch_size = 1000  # Process 1000 rows at a time
        batch_updates = []
        
        for row in result:
            job_id = row[0]
            params = row[1] if row[1] is not None else {}
            
            # Calculate hash using the same canonical format as the application
            # This ensures consistency between migration and runtime
            params_hash = hashlib.sha256(
                json.dumps(params, sort_keys=True, separators=(',', ':')).encode()
            ).hexdigest()
            
            batch_updates.append((params_hash, job_id))
            
            # Execute batch when it reaches the batch size
            if len(batch_updates) >= batch_size:
                _execute_batch_update(connection, batch_updates)
                batch_updates = []
        
        # Execute any remaining updates
        if batch_updates:
            if USE_BATCH_UTILITY:
                # Use the utility module for better maintainability
                execute_params_hash_batch_update(connection, batch_updates)
            else:
                # Use local implementation as fallback
                _execute_batch_update(connection, batch_updates)
    else:
        # For other databases, skip the data migration
        # The application will calculate hashes for new jobs going forward
        print("Warning: Skipping params_hash backfill for non-PostgreSQL database")


def downgrade() -> None:
    """
    Remove params_hash column and revert to unnamed unique constraint.
    """
    
    # Drop the named unique constraint
    # Use try-except in case the constraint doesn't exist
    try:
        op.drop_constraint('uq_jobs_idempotency_key', 'jobs', type_='unique')
    except sa.exc.ProgrammingError:
        # If the named constraint doesn't exist, try to find it programmatically
        connection = op.get_bind()
        constraint_name = get_constraint_name(connection, 'jobs', 'idempotency_key')
        if constraint_name:
            op.drop_constraint(constraint_name, 'jobs', type_='unique')
    
    # Recreate the unnamed unique constraint (as it was before)
    op.create_unique_constraint(None, 'jobs', ['idempotency_key'])
    
    # Drop the index on params_hash
    op.drop_index('idx_jobs_params_hash', table_name='jobs')
    
    # Drop the params_hash column
    op.drop_column('jobs', 'params_hash')