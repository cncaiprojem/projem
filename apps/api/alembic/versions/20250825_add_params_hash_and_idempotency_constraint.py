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
    # CRITICAL: Using 'input_params' which is the ACTUAL database column name
    # The SQLAlchemy model has: params: Mapped[dict] = mapped_column(..., name="input_params")
    # This means the Python property is 'params' but the database column is 'input_params'
    # 
    # IMPORTANT: We need to match the application's canonical JSON format for consistency
    # The application uses: json.dumps(params, sort_keys=True, separators=(',', ':'))
    # PostgreSQL's jsonb_build_object with ordered keys approximates this behavior
    connection = op.get_bind()
    
    # For PostgreSQL, use a Python-based approach to ensure exact hash match
    # This ensures existing jobs will have the same hash as newly created ones
    if connection.dialect.name == 'postgresql':
        # Fetch all jobs with idempotency keys
        result = connection.execute(sa.text(
            "SELECT id, input_params FROM jobs WHERE idempotency_key IS NOT NULL"
        ))
        
        for row in result:
            job_id = row[0]
            params = row[1] if row[1] is not None else {}
            
            # Calculate hash using the same canonical format as the application
            # This ensures consistency between migration and runtime
            params_hash = hashlib.sha256(
                json.dumps(params, sort_keys=True, separators=(',', ':')).encode()
            ).hexdigest()
            
            # Update the job with the calculated hash
            connection.execute(sa.text(
                "UPDATE jobs SET params_hash = :hash WHERE id = :id"
            ), {'hash': params_hash, 'id': job_id})
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