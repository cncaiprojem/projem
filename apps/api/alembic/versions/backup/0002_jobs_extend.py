"""extend jobs

Revision ID: 0002_jobs_extend
Revises: 0001_init
Create Date: 2025-08-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_jobs_extend"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("error_code", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("error_message", sa.Text, nullable=True))
        batch.add_column(sa.Column("artefacts", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("artefacts")
        batch.drop_column("error_message")
        batch.drop_column("error_code")
