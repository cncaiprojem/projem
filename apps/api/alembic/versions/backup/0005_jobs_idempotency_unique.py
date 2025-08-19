"""unique index on jobs.idempotency_key (nullable)

Revision ID: 0005_jobs_idempotency_unique
Revises: 0004_dead_jobs
Create Date: 2025-08-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_jobs_idempotency_unique"
down_revision = "0004_dead_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_jobs_idempotency_key",
        "jobs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_idempotency_key", table_name="jobs")
