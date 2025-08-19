"""dead_jobs table

Revision ID: 0004_dead_jobs
Revises: 0003_jobs_task_id
Create Date: 2025-08-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_dead_jobs"
down_revision = "0003_jobs_task_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dead_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, nullable=False),
        sa.Column("task", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("dead_jobs")
