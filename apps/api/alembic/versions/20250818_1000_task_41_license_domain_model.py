"""Task 4.1: License domain model and state transitions

Ultra-enterprise license schema with:
- 3m/6m/12m duration types
- JSONB scope for flexible features
- State machine (active/expired/canceled)
- Audit trail with hash-chain integrity
- Banking-grade constraints and indexes

Revision ID: task_41_license_domain
Revises: 20250818_0000-task_37_mfa_totp_tables
Create Date: 2025-08-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250818_1000_task_41'
down_revision: Union[str, None] = '20250818_0000_task_37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create license and license_audit tables with enterprise constraints."""
    
    # Drop existing license table if it exists (from old implementation)
    op.execute("DROP TABLE IF EXISTS licenses CASCADE")
    
    # Create licenses table
    op.create_table('licenses',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, 
                 comment='Unique license identifier'),
        sa.Column('user_id', sa.BigInteger(), nullable=False, 
                 comment='User who owns this license'),
        sa.Column('type', sa.String(length=10), nullable=False, 
                 comment='License duration type: 3m, 6m, or 12m'),
        sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), 
                 server_default=sa.text("'{}'"), nullable=False, 
                 comment='License scope: features, limits, permissions as JSONB'),
        sa.Column('status', sa.String(length=20), nullable=False, 
                 comment='License status: active, expired, canceled'),
        sa.Column('reason', sa.Text(), nullable=True, 
                 comment='Reason for cancellation (if canceled)'),
        sa.Column('starts_at', sa.DateTime(timezone=True), 
                 server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False, 
                 comment='License start timestamp (UTC)'),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False, 
                 comment='License expiry timestamp (UTC)'),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True, 
                 comment='When license was canceled (if applicable)'),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                 server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), 
                 server_default=sa.text('CURRENT_TIMESTAMP'), 
                 onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("type IN ('3m', '6m', '12m')", 
                          name='ck_licenses_valid_type'),
        sa.CheckConstraint("status IN ('active', 'expired', 'canceled')", 
                          name='ck_licenses_valid_status'),
        sa.CheckConstraint('ends_at > starts_at', 
                          name='ck_licenses_valid_period'),
        sa.CheckConstraint("(status != 'canceled' OR canceled_at IS NOT NULL)", 
                          name='ck_licenses_canceled_has_timestamp'),
        sa.CheckConstraint("(status != 'canceled' OR reason IS NOT NULL)", 
                          name='ck_licenses_canceled_has_reason'),
        sa.CheckConstraint("(status = 'canceled' OR (canceled_at IS NULL AND reason IS NULL))", 
                          name='ck_licenses_non_canceled_no_cancel_fields')
    )
    
    # Create indexes for licenses table
    op.create_index('idx_licenses_user_id', 'licenses', ['user_id'])
    op.create_index('idx_licenses_status', 'licenses', ['status'])
    op.create_index('idx_licenses_ends_at', 'licenses', ['ends_at'])
    op.create_index('idx_licenses_status_ends_at', 'licenses', ['status', 'ends_at'])
    op.create_index('idx_licenses_user_status', 'licenses', ['user_id', 'status'])
    
    # Partial unique index: only one active license per user
    op.create_index(
        'uq_licenses_one_active_per_user', 
        'licenses', 
        ['user_id'],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND ends_at > CURRENT_TIMESTAMP")
    )
    
    # Index for active licenses nearing expiry
    op.create_index(
        'idx_licenses_active_expiring',
        'licenses',
        ['ends_at'],
        postgresql_where=sa.text("status = 'active'")
    )
    
    # GIN index for JSONB scope queries
    op.create_index(
        'idx_licenses_scope',
        'licenses',
        ['scope'],
        postgresql_using='gin'
    )
    
    # Create license_audit table for audit trail
    op.create_table('license_audit',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False,
                 comment='Unique audit record identifier'),
        sa.Column('license_id', sa.BigInteger(), nullable=False,
                 comment='License being audited'),
        sa.Column('user_id', sa.BigInteger(), nullable=True,
                 comment='User who performed the action (null for system actions)'),
        sa.Column('event_type', sa.String(length=50), nullable=False,
                 comment='Event type: license_assigned, license_extended, license_canceled, license_expired'),
        sa.Column('old_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                 comment='License state before the event'),
        sa.Column('new_state', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                 comment='License state after the event'),
        sa.Column('delta', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                 comment='Specific changes made (e.g., extension duration, cancellation reason)'),
        sa.Column('actor_type', sa.String(length=20), 
                 server_default=sa.text("'user'"), nullable=False,
                 comment='Actor type: user, system, admin, api'),
        sa.Column('actor_id', sa.String(length=100), nullable=True,
                 comment='Actor identifier (user_id, system_process, api_key, etc.)'),
        sa.Column('ip_address', sa.String(length=45), nullable=True,
                 comment='IP address of the request (anonymized for KVKV)'),
        sa.Column('user_agent', sa.String(length=500), nullable=True,
                 comment='User agent string'),
        sa.Column('previous_hash', sa.String(length=64), nullable=True,
                 comment='SHA-256 hash of the previous audit record'),
        sa.Column('current_hash', sa.String(length=64), nullable=False,
                 comment='SHA-256 hash of this audit record'),
        sa.Column('audit_metadata', postgresql.JSONB(astext_type=sa.Text()), 
                 server_default=sa.text("'{}'"), nullable=True,
                 comment='Additional audit metadata'),
        sa.Column('reason', sa.Text(), nullable=True,
                 comment='Human-readable reason for the action'),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                 server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False,
                 comment='When the audit event occurred'),
        sa.ForeignKeyConstraint(['license_id'], ['licenses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('current_hash')
    )
    
    # Create indexes for license_audit table
    op.create_index('idx_license_audit_license_id', 'license_audit', ['license_id'])
    op.create_index('idx_license_audit_user_id', 'license_audit', ['user_id'])
    op.create_index('idx_license_audit_event_type', 'license_audit', ['event_type'])
    op.create_index('idx_license_audit_created_at', 'license_audit', ['created_at'])
    op.create_index('idx_license_audit_license_event', 'license_audit', 
                   ['license_id', 'event_type'])
    op.create_index('idx_license_audit_previous_hash', 'license_audit', ['previous_hash'])
    
    # Composite index for audit trail queries
    op.create_index(
        'idx_license_audit_license_created',
        'license_audit',
        ['license_id', 'created_at'],
        postgresql_using='btree'
    )
    
    # Add comment to tables
    op.execute("COMMENT ON TABLE licenses IS 'Task 4.1: Ultra-enterprise license domain with state transitions'")
    op.execute("COMMENT ON TABLE license_audit IS 'Task 4.1: License audit trail with hash-chain integrity'")


def downgrade() -> None:
    """Drop license domain tables."""
    
    # Drop indexes first
    op.drop_index('idx_license_audit_license_created', table_name='license_audit')
    op.drop_index('idx_license_audit_previous_hash', table_name='license_audit')
    op.drop_index('idx_license_audit_license_event', table_name='license_audit')
    op.drop_index('idx_license_audit_created_at', table_name='license_audit')
    op.drop_index('idx_license_audit_event_type', table_name='license_audit')
    op.drop_index('idx_license_audit_user_id', table_name='license_audit')
    op.drop_index('idx_license_audit_license_id', table_name='license_audit')
    
    op.drop_index('idx_licenses_scope', table_name='licenses')
    op.drop_index('idx_licenses_active_expiring', table_name='licenses')
    op.drop_index('uq_licenses_one_active_per_user', table_name='licenses')
    op.drop_index('idx_licenses_user_status', table_name='licenses')
    op.drop_index('idx_licenses_status_ends_at', table_name='licenses')
    op.drop_index('idx_licenses_ends_at', table_name='licenses')
    op.drop_index('idx_licenses_status', table_name='licenses')
    op.drop_index('idx_licenses_user_id', table_name='licenses')
    
    # Drop tables
    op.drop_table('license_audit')
    op.drop_table('licenses')