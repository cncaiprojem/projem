"""add task_id to jobs

Revision ID: 0003_jobs_task_id
Revises: 0002_jobs_extend
Create Date: 2025-08-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_jobs_task_id"
down_revision = "0002_jobs_extend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("task_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("task_id")


