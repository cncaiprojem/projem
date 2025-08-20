"""Task 3.1: Add enterprise authentication fields to users table

Revision ID: 20250817_2030_task_31_enterprise_auth_fields
Revises: 20250817_1530_init_basic_tables
Create Date: 2025-08-17 20:30

This migration adds ultra enterprise security fields for password authentication:
- Enhanced password security fields (salt, pepper usage, algorithm)
- Account lockout mechanism
- Failed login attempt tracking
- Full name and display preferences
- Authentication audit timestamps
- Password policy compliance fields
- Turkish KVKV compliance metadata
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
from typing import Union

revision: str = '20250817_2030_task_31'
down_revision: Union[str, None] = '20250817_2000_3d_printer'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """Add enterprise authentication security fields to users table."""
    
    # Add full name and display fields
    op.add_column('users', sa.Column('full_name', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('display_name', sa.String(100), nullable=True))
    
    # Enhanced password security fields
    op.add_column('users', sa.Column('password_salt', sa.String(64), nullable=True, comment='Per-user salt for Argon2'))
    op.add_column('users', sa.Column('password_algorithm', sa.String(20), nullable=False, server_default='argon2id', comment='Password hashing algorithm'))
    op.add_column('users', sa.Column('password_updated_at', sa.DateTime(timezone=True), nullable=True, comment='Last password change timestamp'))
    op.add_column('users', sa.Column('password_must_change', sa.Boolean, nullable=False, server_default='false', comment='Force password change on next login'))
    
    # Account lockout mechanism
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer, nullable=False, server_default='0', comment='Current failed login attempt count'))
    op.add_column('users', sa.Column('account_locked_until', sa.DateTime(timezone=True), nullable=True, comment='Account lockout expiration timestamp'))
    op.add_column('users', sa.Column('last_failed_login_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp of last failed login'))
    op.add_column('users', sa.Column('last_lockout_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp when account was last locked'))
    
    # Authentication audit fields
    op.add_column('users', sa.Column('last_successful_login_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp of last successful login'))
    op.add_column('users', sa.Column('last_login_ip', sa.String(45), nullable=True, comment='IP address of last login (IPv4/IPv6)'))
    op.add_column('users', sa.Column('last_login_user_agent', sa.Text, nullable=True, comment='User agent of last login'))
    op.add_column('users', sa.Column('total_login_count', sa.BigInteger, nullable=False, server_default='0', comment='Total successful login count'))
    
    # Email verification and security
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True, comment='Email verification timestamp'))
    op.add_column('users', sa.Column('email_verification_token', sa.String(128), nullable=True, comment='Current email verification token'))
    op.add_column('users', sa.Column('email_verification_expires_at', sa.DateTime(timezone=True), nullable=True, comment='Email verification token expiration'))
    
    # Password reset functionality
    op.add_column('users', sa.Column('password_reset_token', sa.String(128), nullable=True, comment='Current password reset token'))
    op.add_column('users', sa.Column('password_reset_expires_at', sa.DateTime(timezone=True), nullable=True, comment='Password reset token expiration'))
    op.add_column('users', sa.Column('password_reset_attempts', sa.Integer, nullable=False, server_default='0', comment='Password reset attempt count in current window'))
    
    # Account status and compliance
    op.add_column('users', sa.Column('account_status', sa.String(20), nullable=False, server_default='active', comment='Account status: active, suspended, locked, pending'))
    op.add_column('users', sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True, comment='Account deactivation timestamp'))
    op.add_column('users', sa.Column('deactivation_reason', sa.String(100), nullable=True, comment='Reason for account deactivation'))
    
    # Turkish KVKV compliance fields
    op.add_column('users', sa.Column('data_processing_consent', sa.Boolean, nullable=False, server_default='false', comment='KVKV data processing consent'))
    op.add_column('users', sa.Column('data_processing_consent_at', sa.DateTime(timezone=True), nullable=True, comment='KVKV consent timestamp'))
    op.add_column('users', sa.Column('marketing_consent', sa.Boolean, nullable=False, server_default='false', comment='Marketing communication consent'))
    op.add_column('users', sa.Column('marketing_consent_at', sa.DateTime(timezone=True), nullable=True, comment='Marketing consent timestamp'))
    
    # Security preferences and metadata
    op.add_column('users', sa.Column('security_preferences', JSONB, nullable=True, comment='User security preferences and settings'))
    op.add_column('users', sa.Column('auth_metadata', JSONB, nullable=True, comment='Authentication-related metadata'))
    
    # Create indexes for performance and security
    op.create_index('idx_users_account_status', 'users', ['account_status'])
    op.create_index('idx_users_account_locked_until', 'users', ['account_locked_until'], postgresql_where='account_locked_until IS NOT NULL')
    op.create_index('idx_users_failed_login_attempts', 'users', ['failed_login_attempts'], postgresql_where='failed_login_attempts > 0')
    op.create_index('idx_users_password_reset_token', 'users', ['password_reset_token'], unique=True, postgresql_where='password_reset_token IS NOT NULL')
    op.create_index('idx_users_email_verification_token', 'users', ['email_verification_token'], unique=True, postgresql_where='email_verification_token IS NOT NULL')
    op.create_index('idx_users_last_login_ip', 'users', ['last_login_ip'], postgresql_where='last_login_ip IS NOT NULL')
    op.create_index('idx_users_password_updated_at', 'users', ['password_updated_at'])
    op.create_index('idx_users_full_name', 'users', ['full_name'], postgresql_where='full_name IS NOT NULL')
    op.create_index('idx_users_data_processing_consent', 'users', ['data_processing_consent'])
    
    # Add check constraints for data integrity
    op.create_check_constraint(
        'ck_users_failed_login_attempts_non_negative',
        'users',
        'failed_login_attempts >= 0'
    )
    op.create_check_constraint(
        'ck_users_total_login_count_non_negative', 
        'users',
        'total_login_count >= 0'
    )
    op.create_check_constraint(
        'ck_users_password_reset_attempts_non_negative',
        'users', 
        'password_reset_attempts >= 0'
    )
    op.create_check_constraint(
        'ck_users_account_status_valid',
        'users',
        "account_status IN ('active', 'suspended', 'locked', 'pending', 'deactivated')"
    )
    op.create_check_constraint(
        'ck_users_password_algorithm_valid',
        'users',
        "password_algorithm IN ('argon2id', 'argon2i', 'argon2d', 'bcrypt')"
    )
    
    # Add constraint to ensure lockout expiration is in future if set
    op.create_check_constraint(
        'ck_users_account_locked_until_future',
        'users',
        'account_locked_until IS NULL OR account_locked_until > NOW()'
    )


def downgrade() -> None:
    """Remove enterprise authentication security fields from users table."""
    
    # Drop constraints first
    op.drop_constraint('ck_users_account_locked_until_future', 'users')
    op.drop_constraint('ck_users_password_algorithm_valid', 'users')
    op.drop_constraint('ck_users_account_status_valid', 'users')
    op.drop_constraint('ck_users_password_reset_attempts_non_negative', 'users')
    op.drop_constraint('ck_users_total_login_count_non_negative', 'users')
    op.drop_constraint('ck_users_failed_login_attempts_non_negative', 'users')
    
    # Drop indexes
    op.drop_index('idx_users_data_processing_consent', 'users')
    op.drop_index('idx_users_full_name', 'users')
    op.drop_index('idx_users_password_updated_at', 'users')
    op.drop_index('idx_users_last_login_ip', 'users')
    op.drop_index('idx_users_email_verification_token', 'users')
    op.drop_index('idx_users_password_reset_token', 'users')
    op.drop_index('idx_users_failed_login_attempts', 'users')
    op.drop_index('idx_users_account_locked_until', 'users')
    op.drop_index('idx_users_account_status', 'users')
    
    # Drop columns in reverse order
    op.drop_column('users', 'auth_metadata')
    op.drop_column('users', 'security_preferences')
    op.drop_column('users', 'marketing_consent_at')
    op.drop_column('users', 'marketing_consent')
    op.drop_column('users', 'data_processing_consent_at')
    op.drop_column('users', 'data_processing_consent')
    op.drop_column('users', 'deactivation_reason')
    op.drop_column('users', 'deactivated_at')
    op.drop_column('users', 'account_status')
    op.drop_column('users', 'password_reset_attempts')
    op.drop_column('users', 'password_reset_expires_at')
    op.drop_column('users', 'password_reset_token')
    op.drop_column('users', 'email_verification_expires_at')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'email_verified_at')
    op.drop_column('users', 'total_login_count')
    op.drop_column('users', 'last_login_user_agent')
    op.drop_column('users', 'last_login_ip')
    op.drop_column('users', 'last_successful_login_at')
    op.drop_column('users', 'last_lockout_at')
    op.drop_column('users', 'last_failed_login_at')
    op.drop_column('users', 'account_locked_until')
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'password_must_change')
    op.drop_column('users', 'password_updated_at')
    op.drop_column('users', 'password_algorithm')
    op.drop_column('users', 'password_salt')
    op.drop_column('users', 'display_name')
    op.drop_column('users', 'full_name')