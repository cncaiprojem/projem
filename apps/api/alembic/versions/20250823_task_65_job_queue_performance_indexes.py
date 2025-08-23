"""task_65_job_queue_performance_indexes

Revision ID: task_65_queue_indexes
Revises: task_64_job_type_enum
Create Date: 2025-08-23 15:00:00.000000

Add composite indexes for job queue performance optimization.
Based on PR #227 Gemini Code Assist feedback.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'task_65_queue_indexes'
down_revision: Union[str, None] = 'task_64_job_type_enum'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add composite indexes for efficient job queue position calculation.
    
    These indexes optimize the queries in JobQueueService.get_queue_position():
    1. Index for queue position calculation (ahead_count query)
    2. Index for running jobs count query
    
    Based on PR #227 feedback from Gemini Code Assist.
    """
    
    # Composite index for queue position calculation
    # Optimizes: WHERE type IN (...) AND status IN (...) AND (priority > ... OR (priority = ... AND created_at < ...))
    op.create_index(
        'ix_jobs_queue_position',
        'jobs',
        ['type', 'status', 'priority', 'created_at'],
        if_not_exists=True,
        postgresql_using='btree'
    )
    
    # Additional index for type and status combination
    # Optimizes: WHERE type IN (...) AND status = 'running'
    op.create_index(
        'ix_jobs_type_status',
        'jobs',
        ['type', 'status'],
        if_not_exists=True,
        postgresql_using='btree'
    )
    
    # Index for priority-based queries with status filter
    # Provides additional optimization for high-priority job queries
    op.create_index(
        'ix_jobs_status_priority_created',
        'jobs',
        ['status', 'priority', 'created_at'],
        if_not_exists=True,
        postgresql_using='btree'
    )


def downgrade() -> None:
    """Remove the composite indexes."""
    
    op.drop_index('ix_jobs_status_priority_created', table_name='jobs', if_exists=True)
    op.drop_index('ix_jobs_type_status', table_name='jobs', if_exists=True)
    op.drop_index('ix_jobs_queue_position', table_name='jobs', if_exists=True)