"""init tables

Revision ID: 0001_init
Revises:
Create Date: 2025-08-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="engineer"),
        sa.Column("locale", sa.String(length=10), nullable=False, server_default="tr"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("metrics", sa.JSON, nullable=True),
    )
    op.create_index("ix_jobs_idempotency_key", "jobs", ["idempotency_key"], unique=False)

    op.create_table(
        "artefacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("artefacts")
    op.drop_index("ix_jobs_idempotency_key", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
