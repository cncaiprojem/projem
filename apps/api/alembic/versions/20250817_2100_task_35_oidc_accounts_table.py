"""Task 3.5: Add OIDC accounts table for Google OAuth2/OIDC integration

Revision ID: 20250817_2100
Revises: 20250817_2045
Create Date: 2025-08-17 21:00:00.000000

This migration creates the oidc_accounts table to link local User accounts
with external OIDC providers (primarily Google) following ultra enterprise 
security standards with proper indexing and constraints.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250817_2100_task_35'
down_revision = '20250817_2045_task_32'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Create oidc_accounts table with enterprise security features."""
    
    # Create oidc_accounts table
    op.create_table(
        'oidc_accounts',
        
        # Primary key (UUID for enhanced security)
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True, 
                 comment='OIDC account UUID'),
        
        # Foreign key to users table
        sa.Column('user_id', sa.Integer(), nullable=False, 
                 comment='Reference to local user account'),
        
        # OIDC provider information
        sa.Column('provider', sa.String(50), nullable=False,
                 comment='OIDC provider name (e.g., google)'),
        
        # OIDC subject identifier (unique per provider)
        sa.Column('sub', sa.String(255), nullable=False,
                 comment='OIDC subject identifier from provider'),
        
        # User profile information from OIDC provider
        sa.Column('email', sa.String(255), nullable=False,
                 comment='Email address from OIDC provider'),
        
        sa.Column('email_verified', sa.Boolean(), nullable=False, default=False,
                 comment='Whether email is verified by OIDC provider'),
        
        sa.Column('picture', sa.String(500), nullable=True,
                 comment='Profile picture URL from OIDC provider'),
        
        # Provider-specific metadata
        sa.Column('provider_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                 comment='Additional provider-specific data (JSON)'),
        
        # Security tracking
        sa.Column('first_login_at', sa.DateTime(timezone=True), nullable=True,
                 comment='First login timestamp for this OIDC account'),
        
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True,
                 comment='Last login timestamp for this OIDC account'),
        
        sa.Column('login_count', sa.Integer(), nullable=False, default=0,
                 comment='Total number of logins via this OIDC account'),
        
        # Account status
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True,
                 comment='Whether this OIDC account is active'),
        
        # Timestamps (TimestampMixin)
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                 server_default=sa.text('NOW()')),
        
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                 server_default=sa.text('NOW()')),
        
        # Foreign key constraint
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    
    # Create indexes for optimal performance
    
    # Unique constraint: One OIDC account per provider per subject
    op.create_index(
        'ix_oidc_accounts_provider_sub',
        'oidc_accounts',
        ['provider', 'sub'],
        unique=True
    )
    
    # Index for efficient user lookups
    op.create_index(
        'ix_oidc_accounts_user_id',
        'oidc_accounts',
        ['user_id']
    )
    
    # Index for email lookups
    op.create_index(
        'ix_oidc_accounts_email',
        'oidc_accounts',
        ['email']
    )
    
    # Index for provider lookups
    op.create_index(
        'ix_oidc_accounts_provider',
        'oidc_accounts',
        ['provider']
    )
    
    # Index for active account queries
    op.create_index(
        'ix_oidc_accounts_is_active',
        'oidc_accounts',
        ['is_active']
    )
    
    # Performance index for audit queries
    op.create_index(
        'ix_oidc_accounts_last_login',
        'oidc_accounts',
        ['last_login_at']
    )
    
    # Composite index for active accounts by provider
    op.create_index(
        'ix_oidc_accounts_provider_active',
        'oidc_accounts',
        ['provider', 'is_active']
    )
    
    # Add check constraints for data integrity
    
    # Ensure login_count is non-negative
    op.create_check_constraint(
        'ck_oidc_accounts_login_count_non_negative',
        'oidc_accounts',
        'login_count >= 0'
    )
    
    # Ensure provider is not empty
    op.create_check_constraint(
        'ck_oidc_accounts_provider_not_empty',
        'oidc_accounts',
        "provider != ''"
    )
    
    # Ensure sub is not empty
    op.create_check_constraint(
        'ck_oidc_accounts_sub_not_empty',
        'oidc_accounts',
        "sub != ''"
    )
    
    # Ensure email is not empty
    op.create_check_constraint(
        'ck_oidc_accounts_email_not_empty',
        'oidc_accounts',
        "email != ''"
    )
    
    # Ensure first_login_at is before or equal to last_login_at
    op.create_check_constraint(
        'ck_oidc_accounts_login_timestamps_logical',
        'oidc_accounts',
        'first_login_at IS NULL OR last_login_at IS NULL OR first_login_at <= last_login_at'
    )

def downgrade() -> None:
    """Drop oidc_accounts table and all associated indexes/constraints."""
    
    # Drop the table (this will automatically drop all indexes and constraints)
    op.drop_table('oidc_accounts')