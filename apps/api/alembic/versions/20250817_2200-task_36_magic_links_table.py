"""Task 3.6: Add magic_links table for ultra enterprise passwordless authentication

Revision ID: 20250817_2200_task_36_magic_links_table
Revises: 20250817_2100-task_35_oidc_accounts_table
Create Date: 2025-08-17 22:00:00.000000

This migration creates the magic_links table with banking-level security features:
- Single-use enforcement with unique nonce tracking
- 15-minute expiration with cryptographic validation
- Complete audit trail for issuance and consumption
- IP address and device fingerprint security tracking
- Automatic cleanup mechanisms for expired links
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = "20250817_2200_task_36_magic_links_table"
down_revision = "20250817_2100-task_35_oidc_accounts_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create magic_links table with ultra enterprise security features."""

    # Create magic_links table
    op.create_table(
        "magic_links",
        # Primary key
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
            comment="Unique magic link ID",
        ),
        # Target email
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=False,
            comment="Target email address for magic link",
        ),
        # Security nonce for single-use enforcement
        sa.Column(
            "nonce",
            sa.String(length=64),
            nullable=False,
            comment="Cryptographically secure nonce for single-use enforcement",
        ),
        # Token issuance tracking
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            default=sa.text("CURRENT_TIMESTAMP"),
            comment="Token issuance timestamp",
        ),
        # Token consumption tracking
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Token consumption timestamp",
        ),
        # Security audit fields - request
        sa.Column(
            "ip_address", postgresql.INET(), nullable=True, comment="IP address of token request"
        ),
        sa.Column("user_agent", sa.Text(), nullable=True, comment="User agent of token request"),
        sa.Column(
            "device_fingerprint",
            sa.String(length=512),
            nullable=True,
            comment="Device fingerprint for consumption verification",
        ),
        # Security audit fields - consumption
        sa.Column(
            "consumed_ip_address",
            postgresql.INET(),
            nullable=True,
            comment="IP address of token consumption",
        ),
        sa.Column(
            "consumed_user_agent",
            sa.Text(),
            nullable=True,
            comment="User agent of token consumption",
        ),
        sa.Column(
            "consumed_device_fingerprint",
            sa.String(length=512),
            nullable=True,
            comment="Device fingerprint of token consumption",
        ),
        # Invalidation tracking
        sa.Column(
            "invalidated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Token invalidation timestamp",
        ),
        sa.Column(
            "invalidation_reason",
            sa.String(length=100),
            nullable=True,
            comment="Reason for token invalidation",
        ),
        # Attempt tracking for security monitoring
        sa.Column(
            "consumption_attempts",
            sa.Integer(),
            nullable=False,
            default=0,
            comment="Number of consumption attempts",
        ),
        # Security metadata
        sa.Column(
            "security_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Additional security metadata as JSON",
        ),
        # Timestamps from TimestampMixin
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            default=sa.text("CURRENT_TIMESTAMP"),
            comment="Record creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            default=sa.text("CURRENT_TIMESTAMP"),
            comment="Record last update timestamp",
        ),
        # Primary key constraint
        sa.PrimaryKeyConstraint("id", name="pk_magic_links"),
        # Unique constraints
        sa.UniqueConstraint("nonce", name="uq_magic_links_nonce"),
        # Check constraints for data integrity
        sa.CheckConstraint(
            "consumption_attempts >= 0", name="ck_magic_links_consumption_attempts_non_negative"
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name="ck_magic_links_consumed_after_issued",
        ),
        sa.CheckConstraint(
            "invalidated_at IS NULL OR invalidated_at >= issued_at",
            name="ck_magic_links_invalidated_after_issued",
        ),
        sa.CheckConstraint(
            "invalidation_reason IS NULL OR invalidation_reason IN ('expired', 'consumed', 'security_revoked', 'admin_revoked')",
            name="ck_magic_links_invalidation_reason_valid",
        ),
    )

    # Create performance and security indexes

    # Primary lookup indexes
    op.create_index("idx_magic_links_email_issued", "magic_links", ["email", "issued_at"])
    op.create_index("idx_magic_links_nonce_unique", "magic_links", ["nonce"], unique=True)
    op.create_index("idx_magic_links_issued_at", "magic_links", ["issued_at"])

    # Consumption tracking indexes
    op.create_index(
        "idx_magic_links_consumed_at",
        "magic_links",
        ["consumed_at"],
        postgresql_where=sa.text("consumed_at IS NOT NULL"),
    )

    # Security monitoring indexes
    op.create_index(
        "idx_magic_links_ip_address",
        "magic_links",
        ["ip_address"],
        postgresql_where=sa.text("ip_address IS NOT NULL"),
    )

    # Active links index for rate limiting
    op.create_index(
        "idx_magic_links_active",
        "magic_links",
        ["email", "issued_at"],
        postgresql_where=sa.text("consumed_at IS NULL AND invalidated_at IS NULL"),
    )

    # Cleanup index for expired links
    op.create_index(
        "idx_magic_links_expired",
        "magic_links",
        ["issued_at"],
        postgresql_where=sa.text("consumed_at IS NULL AND invalidated_at IS NULL"),
    )

    # Create automatic timestamp update trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION update_magic_links_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("""
        CREATE TRIGGER trigger_magic_links_updated_at
            BEFORE UPDATE ON magic_links
            FOR EACH ROW
            EXECUTE FUNCTION update_magic_links_updated_at();
    """)

    # Create cleanup function for expired magic links
    op.execute("""
        CREATE OR REPLACE FUNCTION cleanup_expired_magic_links()
        RETURNS INTEGER AS $$
        DECLARE
            cleanup_count INTEGER;
        BEGIN
            -- Mark expired magic links as invalidated
            UPDATE magic_links 
            SET invalidated_at = CURRENT_TIMESTAMP,
                invalidation_reason = 'expired'
            WHERE consumed_at IS NULL 
              AND invalidated_at IS NULL
              AND issued_at < CURRENT_TIMESTAMP - INTERVAL '24 hours';
            
            GET DIAGNOSTICS cleanup_count = ROW_COUNT;
            
            -- Log cleanup operation
            INSERT INTO audit_logs (
                user_id, action, description, details, created_at
            ) VALUES (
                NULL, 
                'magic_links_cleanup',
                'Expired magic links cleaned up',
                json_build_object('cleanup_count', cleanup_count),
                CURRENT_TIMESTAMP
            );
            
            RETURN cleanup_count;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    """Drop magic_links table and related functions."""

    # Drop cleanup function
    op.execute("DROP FUNCTION IF EXISTS cleanup_expired_magic_links()")

    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trigger_magic_links_updated_at ON magic_links")
    op.execute("DROP FUNCTION IF EXISTS update_magic_links_updated_at()")

    # Drop indexes (will be dropped with table, but explicit for clarity)
    op.drop_index("idx_magic_links_expired", table_name="magic_links")
    op.drop_index("idx_magic_links_active", table_name="magic_links")
    op.drop_index("idx_magic_links_ip_address", table_name="magic_links")
    op.drop_index("idx_magic_links_consumed_at", table_name="magic_links")
    op.drop_index("idx_magic_links_issued_at", table_name="magic_links")
    op.drop_index("idx_magic_links_nonce_unique", table_name="magic_links")
    op.drop_index("idx_magic_links_email_issued", table_name="magic_links")

    # Drop magic_links table
    op.drop_table("magic_links")
