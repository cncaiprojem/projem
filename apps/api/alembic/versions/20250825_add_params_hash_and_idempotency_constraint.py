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
        except:
            # If that fails, try other common patterns
            pass
    
    # Create a named unique constraint for database-agnostic error handling
    op.create_unique_constraint(
        'uq_jobs_idempotency_key',  # Named constraint for portable error handling
        'jobs',
        ['idempotency_key']
    )
    
    # Populate params_hash for existing jobs (optional, can be done separately)
    # This is a data migration that calculates hash for existing records
    # Fixed: Changed 'input_params' to 'params' (the actual column name)
    op.execute("""
        UPDATE jobs 
        SET params_hash = encode(
            digest(
                CASE 
                    WHEN params IS NOT NULL 
                    THEN params::text 
                    ELSE '{}'::text 
                END, 
                'sha256'
            ), 
            'hex'
        )
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    """
    Remove params_hash column and revert to unnamed unique constraint.
    """
    
    # Drop the named unique constraint
    # Use try-except in case the constraint doesn't exist
    try:
        op.drop_constraint('uq_jobs_idempotency_key', 'jobs', type_='unique')
    except:
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