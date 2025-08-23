"""task_64_add_job_orchestration_fields

Revision ID: task_64_orchestration
Revises: 20250819_task_411_concurrency_uniqueness_guards
Create Date: 2025-08-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'task_64_orchestration'
down_revision: Union[str, None] = '20250819_task_411_concurrency_uniqueness_guards'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add job orchestration fields for Task 6.4."""
    
    # Add attempts column
    op.add_column('jobs', sa.Column(
        'attempts',
        sa.Integer(),
        nullable=False,
        server_default='0',
        comment='Number of execution attempts'
    ))
    
    # Add cancel_requested column
    op.add_column('jobs', sa.Column(
        'cancel_requested',
        sa.Boolean(),
        nullable=False,
        server_default='false',
        comment='Flag for cooperative cancellation'
    ))
    
    # Add check constraint for attempts
    op.create_check_constraint(
        'ck_jobs_attempts_non_negative',
        'jobs',
        'attempts >= 0'
    )
    
    # Add index for cancel_requested (only for true values to optimize queries)
    op.create_index(
        'idx_jobs_cancel_requested',
        'jobs',
        ['cancel_requested'],
        postgresql_where='cancel_requested = true'
    )


def downgrade() -> None:
    """Remove job orchestration fields."""
    
    # Drop index
    op.drop_index('idx_jobs_cancel_requested', table_name='jobs')
    
    # Drop check constraint
    op.drop_constraint('ck_jobs_attempts_non_negative', 'jobs', type_='check')
    
    # Drop columns
    op.drop_column('jobs', 'cancel_requested')
    op.drop_column('jobs', 'attempts')