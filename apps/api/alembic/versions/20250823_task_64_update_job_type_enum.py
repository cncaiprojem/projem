"""task_64_update_job_type_enum

Revision ID: task_64_job_type_enum
Revises: task_64_orchestration
Create Date: 2025-08-23 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'task_64_job_type_enum'
down_revision: Union[str, None] = 'task_64_orchestration'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add new job types for Task 6.3 specification."""
    
    # PostgreSQL-specific way to add enum values
    # Note: ALTER TYPE ... ADD VALUE cannot be executed inside a transaction block
    # So we use raw SQL with autocommit
    
    op.execute("COMMIT")  # End the current transaction
    
    # Add new job type values if they don't exist
    new_values = ['ai', 'model', 'cam', 'sim', 'report', 'erp']
    
    for value in new_values:
        op.execute(f"""
            DO $$ 
            BEGIN
                ALTER TYPE jobtype ADD VALUE IF NOT EXISTS '{value}';
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """)


def downgrade() -> None:
    """
    Note: PostgreSQL doesn't support removing enum values.
    The enum values will remain but won't be used.
    """
    pass