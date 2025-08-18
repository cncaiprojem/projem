"""Task 3.7: Add MFA TOTP fields to users table and create MFA backup codes table

Revision ID: task_37_mfa_totp_tables  
Revises: task_311_audit_correlation_pii_fields
Create Date: 2025-08-18 00:00:00.000000

Ultra-enterprise MFA implementation with:
- AES-256-GCM encrypted TOTP secret storage
- SHA-256 hashed backup codes with usage tracking
- Turkish KVKV compliance for personal data protection
- Banking-level security with audit trails
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'task_37_mfa_totp_tables'
down_revision = 'task_311_audit_correlation_pii_fields'
branch_labels = None
depends_on = None


def upgrade():
    """Add MFA TOTP fields and backup codes table for Task 3.7."""
    
    # Add MFA fields to users table
    op.add_column('users', sa.Column(
        'mfa_enabled', 
        sa.Boolean(), 
        nullable=False, 
        server_default='false',
        comment='MFA activation status'
    ))
    op.add_column('users', sa.Column(
        'mfa_secret_encrypted', 
        sa.String(512), 
        nullable=True,
        comment='Encrypted MFA TOTP secret (AES-256-GCM)'
    ))
    op.add_column('users', sa.Column(
        'mfa_enabled_at', 
        sa.DateTime(timezone=True), 
        nullable=True,
        comment='MFA activation timestamp'
    ))
    op.add_column('users', sa.Column(
        'mfa_backup_codes_count', 
        sa.Integer(), 
        nullable=False, 
        server_default='0',
        comment='Number of unused backup codes remaining'
    ))
    
    # Create MFA backup codes table
    op.create_table('mfa_backup_codes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='Primary key'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='User ID (foreign key)'),
        sa.Column('code_hash', sa.String(64), nullable=False, comment='SHA-256 hash of backup code'),
        sa.Column('code_hint', sa.String(8), nullable=False, comment='First 4 and last 4 characters of code for identification'),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default='false', comment='Whether this backup code has been used'),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True, comment='When this code was used (if used)'),
        sa.Column('used_from_ip', sa.String(45), nullable=True, comment='IP address where code was used (IPv4/IPv6)'),
        sa.Column('used_user_agent', sa.Text(), nullable=True, comment='User agent when code was used'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, comment='Backup code expiration timestamp (90 days from creation)'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Record creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Record last update timestamp'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='MFA backup codes for recovery access with ultra-enterprise security'
    )
    
    # Create indexes for users MFA fields
    op.create_index('idx_users_mfa_enabled', 'users', ['mfa_enabled'])
    op.create_index('idx_users_mfa_enabled_at', 'users', ['mfa_enabled_at'], 
                    postgresql_where=sa.text('mfa_enabled_at IS NOT NULL'))
    
    # Create indexes for mfa_backup_codes table
    op.create_index('idx_mfa_backup_codes_user_id', 'mfa_backup_codes', ['user_id'])
    op.create_index('idx_mfa_backup_codes_code_hash', 'mfa_backup_codes', ['code_hash'])
    op.create_index('idx_mfa_backup_codes_is_used', 'mfa_backup_codes', ['is_used'])
    op.create_index('idx_mfa_backup_codes_expires_at', 'mfa_backup_codes', ['expires_at'])
    op.create_index('idx_mfa_backup_codes_used_at', 'mfa_backup_codes', ['used_at'],
                    postgresql_where=sa.text('used_at IS NOT NULL'))
    op.create_index('idx_mfa_backup_codes_active', 'mfa_backup_codes', ['user_id', 'is_used', 'expires_at'],
                    postgresql_where=sa.text('is_used = false AND expires_at > NOW()'))
    
    # Add check constraints for data integrity
    op.create_check_constraint(
        'ck_mfa_backup_codes_expires_after_creation',
        'mfa_backup_codes',
        'expires_at > created_at'
    )
    op.create_check_constraint(
        'ck_mfa_backup_codes_usage_consistency',
        'mfa_backup_codes',
        '(is_used = false AND used_at IS NULL) OR (is_used = true AND used_at IS NOT NULL)'
    )
    op.create_check_constraint(
        'ck_users_mfa_backup_codes_count_non_negative',
        'users',
        'mfa_backup_codes_count >= 0'
    )


def downgrade():
    """Remove MFA TOTP fields and backup codes table."""
    
    # Drop check constraints
    op.drop_constraint('ck_users_mfa_backup_codes_count_non_negative', 'users', type_='check')
    op.drop_constraint('ck_mfa_backup_codes_usage_consistency', 'mfa_backup_codes', type_='check')
    op.drop_constraint('ck_mfa_backup_codes_expires_after_creation', 'mfa_backup_codes', type_='check')
    
    # Drop indexes for mfa_backup_codes table
    op.drop_index('idx_mfa_backup_codes_active', 'mfa_backup_codes')
    op.drop_index('idx_mfa_backup_codes_used_at', 'mfa_backup_codes')
    op.drop_index('idx_mfa_backup_codes_expires_at', 'mfa_backup_codes')
    op.drop_index('idx_mfa_backup_codes_is_used', 'mfa_backup_codes')
    op.drop_index('idx_mfa_backup_codes_code_hash', 'mfa_backup_codes')
    op.drop_index('idx_mfa_backup_codes_user_id', 'mfa_backup_codes')
    
    # Drop indexes for users MFA fields
    op.drop_index('idx_users_mfa_enabled_at', 'users')
    op.drop_index('idx_users_mfa_enabled', 'users')
    
    # Drop mfa_backup_codes table
    op.drop_table('mfa_backup_codes')
    
    # Remove MFA columns from users table
    op.drop_column('users', 'mfa_backup_codes_count')
    op.drop_column('users', 'mfa_enabled_at')
    op.drop_column('users', 'mfa_secret_encrypted')
    op.drop_column('users', 'mfa_enabled')