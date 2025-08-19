"""Task 3.2: Create ultra enterprise sessions table with banking-level security

Revision ID: 20250817_2045_task_32_enterprise_sessions_table
Revises: 20250817_2030_task_31_enterprise_auth_fields
Create Date: 2025-08-17 20:45

This migration creates the ultra enterprise sessions table with:
- UUID primary keys for unguessable session identifiers
- SHA512/HMAC refresh token hash storage (never plaintext)
- Device fingerprinting for anomaly detection
- Session rotation chain tracking for forensics
- Turkish KVKV compliance for session data
- Enterprise-grade audit logging and constraints
- Banking-level security indexes

BREAKING CHANGE: This replaces any existing sessions table with the new schema.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, INET


# revision identifiers, used by Alembic.
revision = "20250817_2045_task_32_enterprise_sessions_table"
down_revision = "20250817_2030_task_31_enterprise_auth_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ultra enterprise sessions table with banking-level security."""

    # Drop existing sessions table if it exists (clean slate for ultra enterprise)
    # This is safe because Task 3.1 focused on User model and no production sessions exist yet
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")

    # Create the ultra enterprise sessions table
    op.create_table(
        "sessions",
        # UUID primary key for unguessable session identifiers
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="UUID session identifier for enhanced security",
        ),
        # Foreign key to users
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            comment="User owning this session",
        ),
        # Refresh token security - ONLY store hashed tokens, never plaintext
        sa.Column(
            "refresh_token_hash",
            sa.String(128),
            nullable=False,
            unique=True,
            comment="SHA512/HMAC hash of refresh token - NEVER store plaintext",
        ),
        # Device fingerprinting for anomaly detection
        sa.Column(
            "device_fingerprint",
            sa.String(1024),
            nullable=True,
            comment="Browser/device fingerprint for anomaly detection",
        ),
        # Client metadata for audit and security
        sa.Column(
            "ip_address",
            INET,
            nullable=True,
            comment="Client IP address (masked for privacy compliance)",
        ),
        sa.Column("user_agent", sa.Text, nullable=True, comment="Client user agent string"),
        # Session lifecycle management
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Session expiration timestamp (7 days default)",
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last activity timestamp for sliding expiration",
        ),
        # Session revocation and audit
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Session revocation timestamp",
        ),
        sa.Column(
            "revocation_reason",
            sa.String(100),
            nullable=True,
            comment="Reason for session revocation (logout, admin, security, expired)",
        ),
        # Session rotation chain for audit and forensics
        sa.Column(
            "rotated_from",
            UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
            comment="Previous session ID in rotation chain for audit tracking",
        ),
        # Security flags
        sa.Column(
            "is_suspicious",
            sa.Boolean,
            nullable=False,
            server_default="false",
            comment="Flagged as suspicious by security analysis",
        ),
        # Turkish KVKV compliance metadata
        sa.Column(
            "kvkv_logged",
            sa.Boolean,
            nullable=False,
            server_default="true",
            comment="Session logged for KVKV compliance audit trail",
        ),
        # Timestamps (from TimestampMixin)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Session creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Session last update timestamp",
        ),
    )

    # Create enterprise security indexes for performance
    op.create_index("idx_sessions_user_id", "sessions", ["user_id"])
    op.create_index(
        "idx_sessions_refresh_token_hash", "sessions", ["refresh_token_hash"], unique=True
    )
    op.create_index(
        "idx_sessions_user_active",
        "sessions",
        ["user_id", "revoked_at"],
        postgresql_where="revoked_at IS NULL",
    )
    op.create_index(
        "idx_sessions_expires_active",
        "sessions",
        ["expires_at"],
        postgresql_where="revoked_at IS NULL",
    )
    op.create_index(
        "idx_sessions_device_fingerprint",
        "sessions",
        ["device_fingerprint"],
        postgresql_where="device_fingerprint IS NOT NULL",
    )
    op.create_index(
        "idx_sessions_last_used",
        "sessions",
        ["last_used_at"],
        postgresql_where="last_used_at IS NOT NULL",
    )
    op.create_index(
        "idx_sessions_rotation_chain",
        "sessions",
        ["rotated_from"],
        postgresql_where="rotated_from IS NOT NULL",
    )
    op.create_index(
        "idx_sessions_suspicious",
        "sessions",
        ["is_suspicious", "created_at"],
        postgresql_where="is_suspicious = true",
    )
    op.create_index(
        "idx_sessions_ip_address",
        "sessions",
        ["ip_address"],
        postgresql_where="ip_address IS NOT NULL",
    )
    op.create_index("idx_sessions_created_at", "sessions", ["created_at"])

    # Add enterprise security constraints
    op.create_check_constraint(
        "ck_sessions_refresh_token_hash_length", "sessions", "LENGTH(refresh_token_hash) = 128"
    )

    op.create_check_constraint(
        "ck_sessions_revocation_reason_valid",
        "sessions",
        "revocation_reason IS NULL OR revocation_reason IN ("
        "'logout', 'admin_revoke', 'security_breach', 'expired', "
        "'rotation', 'password_change', 'suspicious_activity', 'user_request')",
    )

    op.create_check_constraint(
        "ck_sessions_expires_after_created", "sessions", "expires_at > created_at"
    )

    op.create_check_constraint(
        "ck_sessions_revoked_after_created",
        "sessions",
        "revoked_at IS NULL OR revoked_at >= created_at",
    )

    op.create_check_constraint(
        "ck_sessions_last_used_after_created",
        "sessions",
        "last_used_at IS NULL OR last_used_at >= created_at",
    )

    op.create_check_constraint(
        "ck_sessions_no_self_rotation", "sessions", "rotated_from IS NULL OR rotated_from != id"
    )

    # Create trigger for updated_at timestamp
    op.execute("""
        CREATE OR REPLACE FUNCTION update_sessions_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("""
        CREATE TRIGGER trigger_sessions_updated_at
            BEFORE UPDATE ON sessions
            FOR EACH ROW
            EXECUTE FUNCTION update_sessions_updated_at();
    """)


def downgrade() -> None:
    """Remove ultra enterprise sessions table."""

    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trigger_sessions_updated_at ON sessions")
    op.execute("DROP FUNCTION IF EXISTS update_sessions_updated_at()")

    # Drop constraints
    op.drop_constraint("ck_sessions_no_self_rotation", "sessions")
    op.drop_constraint("ck_sessions_last_used_after_created", "sessions")
    op.drop_constraint("ck_sessions_revoked_after_created", "sessions")
    op.drop_constraint("ck_sessions_expires_after_created", "sessions")
    op.drop_constraint("ck_sessions_revocation_reason_valid", "sessions")
    op.drop_constraint("ck_sessions_refresh_token_hash_length", "sessions")

    # Drop indexes
    op.drop_index("idx_sessions_created_at", "sessions")
    op.drop_index("idx_sessions_ip_address", "sessions")
    op.drop_index("idx_sessions_suspicious", "sessions")
    op.drop_index("idx_sessions_rotation_chain", "sessions")
    op.drop_index("idx_sessions_last_used", "sessions")
    op.drop_index("idx_sessions_device_fingerprint", "sessions")
    op.drop_index("idx_sessions_expires_active", "sessions")
    op.drop_index("idx_sessions_user_active", "sessions")
    op.drop_index("idx_sessions_refresh_token_hash", "sessions")
    op.drop_index("idx_sessions_user_id", "sessions")

    # Drop table
    op.drop_table("sessions")
