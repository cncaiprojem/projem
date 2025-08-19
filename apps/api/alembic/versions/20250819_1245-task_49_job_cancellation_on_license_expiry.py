"""Task 4.9: Add job cancellation fields for license expiry handling

Revision ID: task_49_job_cancellation
Revises: 20250819_1230-task_48_license_notification_duplicate_prevention
Create Date: 2025-08-19 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'task_49_job_cancellation'
down_revision = '20250819_1230-task_48_license_notification_duplicate_prevention'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add job cancellation fields for license expiry handling."""
    
    # Add cancel_requested field to jobs table
    op.add_column('jobs', sa.Column(
        'cancel_requested',
        sa.Boolean(),
        nullable=False,
        server_default='false',
        comment='Flag to request graceful job cancellation'
    ))
    
    # Add cancellation_reason field to jobs table
    op.add_column('jobs', sa.Column(
        'cancellation_reason',
        sa.String(255),
        nullable=True,
        comment='Reason for job cancellation (e.g., license_expired, user_requested)'
    ))
    
    # Add indexes for efficient querying
    op.create_index(
        'idx_jobs_cancel_requested',
        'jobs',
        ['cancel_requested'],
        postgresql_where=sa.text('cancel_requested = true')
    )
    
    op.create_index(
        'idx_jobs_user_status_cancel',
        'jobs',
        ['user_id', 'status', 'cancel_requested']
    )


def downgrade() -> None:
    """Remove job cancellation fields."""
    
    # Drop indexes
    op.drop_index('idx_jobs_user_status_cancel', table_name='jobs')
    op.drop_index('idx_jobs_cancel_requested', table_name='jobs')
    
    # Drop columns
    op.drop_column('jobs', 'cancellation_reason')
    op.drop_column('jobs', 'cancel_requested')