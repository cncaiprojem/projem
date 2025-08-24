"""Add JobType.ASSEMBLY enum value for Task 7.1

Revision ID: add_jobtype_assembly_001
Revises: 
Create Date: 2025-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_jobtype_assembly_001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ASSEMBLY to job_type enum."""
    # PostgreSQL enum alteration requires raw SQL
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'assembly' AFTER 'model'")


def downgrade() -> None:
    """
    Note: PostgreSQL doesn't support removing enum values easily.
    This would require recreating the enum type and all dependent columns.
    For safety, we'll just log a warning.
    """
    # We can't easily remove enum values in PostgreSQL
    # This would require:
    # 1. Creating a new enum without 'assembly'
    # 2. Altering all columns using job_type to use the new enum
    # 3. Dropping the old enum
    # 4. Renaming the new enum to job_type
    # 
    # For production systems, it's safer to leave the enum value
    # and handle it at the application level
    pass