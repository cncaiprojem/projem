"""Add composite index for idempotency queries

Revision ID: add_idempotency_composite_index
Revises: 20250825_add_params_hash_and_idempotency_constraint
Create Date: 2025-08-25

This migration adds a composite index on (idempotency_key, user_id, type) 
to optimize idempotency queries that filter by all three columns.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'add_idempotency_composite_idx'
down_revision = '20250825_add_params_hash_and_idempotency_constraint'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add composite index for idempotency queries.
    
    The application queries jobs table with:
    WHERE idempotency_key = ? AND user_id = ? AND type = ?
    
    This composite index significantly improves query performance
    by allowing index-only scans for this specific query pattern.
    """
    # Create composite index for idempotency queries
    # This optimizes the query in designs_v1.py line 249
    op.create_index(
        'ix_jobs_idempotency_user_type',
        'jobs',
        ['idempotency_key', 'user_id', 'type'],
        unique=False,
        postgresql_using='btree',
        postgresql_where=sa.text('idempotency_key IS NOT NULL')
    )
    
    print("✅ Created composite index ix_jobs_idempotency_user_type for optimized idempotency queries")


def downgrade() -> None:
    """
    Remove the composite index.
    """
    op.drop_index('ix_jobs_idempotency_user_type', table_name='jobs')
    
    print("✅ Dropped composite index ix_jobs_idempotency_user_type")