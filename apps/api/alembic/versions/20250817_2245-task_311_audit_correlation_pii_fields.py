"""Task 3.11: Add correlation ID and PII masking fields to audit and security models

Revision ID: task_311_audit_correlation_pii_fields
Revises: task_36_magic_links_table
Create Date: 2025-08-17 22:45:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "task_311_audit_correlation_pii_fields"
down_revision = "task_36_magic_links_table"
branch_labels = None
depends_on = None


def upgrade():
    """Add correlation ID and PII masking fields for Task 3.11 compliance."""

    # Add new fields to audit_logs table
    op.add_column(
        "audit_logs",
        sa.Column(
            "correlation_id",
            sa.String(255),
            nullable=True,
            comment="Request correlation ID for tracing across services",
        ),
    )
    op.add_column(
        "audit_logs",
        sa.Column(
            "session_id",
            sa.String(255),
            nullable=True,
            comment="Session ID for user session tracking",
        ),
    )
    op.add_column(
        "audit_logs",
        sa.Column("resource", sa.String(255), nullable=True, comment="Resource being audited"),
    )
    op.add_column(
        "audit_logs",
        sa.Column(
            "ip_masked", sa.String(45), nullable=True, comment="KVKV-compliant masked IP address"
        ),
    )
    op.add_column(
        "audit_logs",
        sa.Column(
            "ua_masked", sa.Text(), nullable=True, comment="KVKV-compliant masked user agent"
        ),
    )

    # Add new fields to security_events table
    op.add_column(
        "security_events",
        sa.Column(
            "session_id",
            sa.String(255),
            nullable=True,
            comment="Session ID for user session tracking",
        ),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "correlation_id",
            sa.String(255),
            nullable=True,
            comment="Request correlation ID for tracing across services",
        ),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "resource", sa.String(255), nullable=True, comment="Resource being accessed or affected"
        ),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "ip_masked",
            sa.String(45),
            nullable=True,
            comment="KVKV-compliant masked IP address (privacy-preserving)",
        ),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "ua_masked", sa.Text(), nullable=True, comment="KVKV-compliant masked user agent string"
        ),
    )
    op.add_column(
        "security_events",
        sa.Column("metadata", JSONB(), nullable=True, comment="Additional security event metadata"),
    )

    # Remove old ip and ua columns from security_events (replaced with masked versions)
    op.drop_column("security_events", "ip")
    op.drop_column("security_events", "ua")

    # Create indexes for new correlation and session ID fields
    op.create_index(
        "idx_audit_logs_correlation_id",
        "audit_logs",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )
    op.create_index(
        "idx_audit_logs_session_id",
        "audit_logs",
        ["session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    op.create_index(
        "idx_security_events_correlation_id",
        "security_events",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )
    op.create_index(
        "idx_security_events_session_id",
        "security_events",
        ["session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    op.create_index(
        "idx_security_events_ip_masked_created",
        "security_events",
        ["ip_masked", "created_at"],
        postgresql_where=sa.text("ip_masked IS NOT NULL"),
    )


def downgrade():
    """Remove correlation ID and PII masking fields."""

    # Drop indexes
    op.drop_index("idx_security_events_ip_masked_created", table_name="security_events")
    op.drop_index("idx_security_events_session_id", table_name="security_events")
    op.drop_index("idx_security_events_correlation_id", table_name="security_events")
    op.drop_index("idx_audit_logs_session_id", table_name="audit_logs")
    op.drop_index("idx_audit_logs_correlation_id", table_name="audit_logs")

    # Restore old columns to security_events (note: data will be lost)
    op.add_column("security_events", sa.Column("ip", sa.dialects.postgresql.INET(), nullable=True))
    op.add_column("security_events", sa.Column("ua", sa.Text(), nullable=True))

    # Remove new columns from security_events
    op.drop_column("security_events", "metadata")
    op.drop_column("security_events", "ua_masked")
    op.drop_column("security_events", "ip_masked")
    op.drop_column("security_events", "resource")
    op.drop_column("security_events", "correlation_id")
    op.drop_column("security_events", "session_id")

    # Remove new columns from audit_logs
    op.drop_column("audit_logs", "ua_masked")
    op.drop_column("audit_logs", "ip_masked")
    op.drop_column("audit_logs", "resource")
    op.drop_column("audit_logs", "session_id")
    op.drop_column("audit_logs", "correlation_id")
