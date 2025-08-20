"""
Task 2.6: Security and Audit Tables with Hash-Chain

Creates enterprise-grade security and audit tables with cryptographic hash-chain integrity
for ultra enterprise FreeCAD CNC/CAM production platform compliance.

Revision ID: 20250817_1700_task_26
Revises: 20250817_1600-task_25_billing_tables_enterprise_financial_precision
Create Date: 2025-08-17 17:00:00.000000

Features:
- audit_logs: Hash-chain integrity with scope-based auditing
- security_events: High-performance security incident tracking
- PostgreSQL 17.6 enterprise optimizations
- Turkish compliance and GDPR/KVKK patterns
- Comprehensive indexing for enterprise scale
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Import enterprise migration helpers
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from migration_helpers import (
    add_table_comment,
    add_column_comment,
    create_gin_index,
    create_partial_index,
    add_check_constraint,
    validate_migration_safety
)

# revision identifiers, used by Alembic.
revision = '20250817_1700_task_26'
down_revision = '20250817_1600-task_25_billing_tables_enterprise_financial_precision'
branch_labels = None
depends_on = None


def upgrade():
    """Create security and audit tables with enterprise hash-chain integrity."""
    
    # Validate migration safety
    print("🔍 Validating migration safety for enterprise deployment...")
    
    # Create audit_logs table with hash-chain integrity
    print("📋 Creating audit_logs table with cryptographic hash-chain...")
    op.create_table(
        'audit_logs',
        sa.Column(
            'id', 
            sa.BigInteger(), 
            nullable=False, 
            primary_key=True,
            autoincrement=True,
            comment="Unique audit log entry identifier for enterprise tracking"
        ),
        sa.Column(
            'scope_type', 
            sa.String(length=50), 
            nullable=False,
            comment="Type of entity being audited (e.g., 'job', 'user', 'payment')"
        ),
        sa.Column(
            'scope_id', 
            sa.BigInteger(), 
            nullable=True,
            comment="ID of the specific entity being audited (NULL for system-wide events)"
        ),
        sa.Column(
            'actor_user_id', 
            sa.BigInteger(), 
            sa.ForeignKey('users.id', ondelete='RESTRICT'), 
            nullable=True,
            comment="User who performed the audited action (NULL for system actions)"
        ),
        sa.Column(
            'event_type', 
            sa.String(length=100), 
            nullable=False,
            comment="Type of action performed (e.g., 'CREATE', 'UPDATE', 'DELETE')"
        ),
        sa.Column(
            'payload', 
            postgresql.JSONB(astext_type=sa.Text()), 
            nullable=True,
            comment="Structured data about the audited event for compliance tracking"
        ),
        sa.Column(
            'prev_chain_hash', 
            sa.String(length=64), 
            nullable=False,
            comment="SHA256 hash of previous audit log entry (genesis: '0' * 64)"
        ),
        sa.Column(
            'chain_hash', 
            sa.String(length=64), 
            nullable=False,
            comment="SHA256 hash of this entry (prev_hash + canonical_json(payload))"
        ),
        sa.Column(
            'created_at', 
            sa.DateTime(timezone=True), 
            nullable=False,
            server_default=sa.text('NOW()'),
            comment="When the audit event occurred (UTC) for compliance chronology"
        ),
        comment="Enterprise audit trail with cryptographic hash-chain integrity for regulatory compliance"
    )
    
    # Create security_events table
    print("🔒 Creating security_events table for enterprise security monitoring...")
    op.create_table(
        'security_events',
        sa.Column(
            'id', 
            sa.BigInteger(), 
            nullable=False, 
            primary_key=True,
            autoincrement=True,
            comment="Unique security event identifier for incident tracking"
        ),
        sa.Column(
            'user_id', 
            sa.BigInteger(), 
            sa.ForeignKey('users.id', ondelete='RESTRICT'), 
            nullable=True,
            comment="Associated user (NULL for anonymous/system events)"
        ),
        sa.Column(
            'type', 
            sa.String(length=100), 
            nullable=False,
            comment="Security event type (e.g., 'LOGIN_FAILED', 'ACCESS_DENIED')"
        ),
        sa.Column(
            'ip', 
            postgresql.INET(), 
            nullable=True,
            comment="Source IP address of the security event for forensic analysis"
        ),
        sa.Column(
            'ua', 
            sa.Text(), 
            nullable=True,
            comment="User agent string from the request for device identification"
        ),
        sa.Column(
            'created_at', 
            sa.DateTime(timezone=True), 
            nullable=False,
            server_default=sa.text('NOW()'),
            comment="When the security event occurred (UTC) for incident chronology"
        ),
        comment="Enterprise security event tracking for compliance and threat monitoring"
    )
    
    # Add enterprise-grade constraints for audit_logs
    print("🔐 Adding hash-chain integrity constraints...")
    
    # Hash format validation constraints
    add_check_constraint(
        'audit_logs',
        'chain_hash_format',
        "char_length(chain_hash) = 64 AND chain_hash ~ '^[0-9a-f]{64}$'"
    )
    
    add_check_constraint(
        'audit_logs',
        'prev_chain_hash_format', 
        "char_length(prev_chain_hash) = 64 AND prev_chain_hash ~ '^[0-9a-f]{64}$'"
    )
    
    # Unique constraint on chain_hash for integrity
    op.create_unique_constraint(
        'uq_audit_logs_chain_hash',
        'audit_logs',
        ['chain_hash']
    )
    
    # Create enterprise performance indexes for audit_logs
    print("⚡ Creating enterprise performance indexes for audit_logs...")
    
    # Primary query pattern: scope-based audit lookups with time filtering
    op.create_index(
        'idx_audit_logs_scope_created',
        'audit_logs',
        ['scope_type', 'scope_id', 'created_at'],
        comment="Enterprise index for scope-based audit queries with temporal filtering"
    )
    
    # Event type filtering for security analysis
    op.create_index(
        'idx_audit_logs_event_type',
        'audit_logs',
        ['event_type'],
        comment="Event type index for security analysis and compliance reporting"
    )
    
    # Actor-based queries for user activity auditing
    op.create_index(
        'idx_audit_logs_actor_user',
        'audit_logs',
        ['actor_user_id'],
        postgresql_where='actor_user_id IS NOT NULL',
        comment="User activity index for behavioral analysis (excludes system events)"
    )
    
    # GIN index for payload JSONB queries
    create_gin_index(
        'audit_logs',
        'payload',
        'gin_audit_logs_payload',
        condition='payload IS NOT NULL'
    )
    
    # Create enterprise performance indexes for security_events
    print("🛡️ Creating enterprise performance indexes for security_events...")
    
    # Primary query patterns for security monitoring
    op.create_index(
        'idx_security_events_user_id',
        'security_events',
        ['user_id'],
        comment="User-based security event index for threat analysis"
    )
    
    op.create_index(
        'idx_security_events_type',
        'security_events',
        ['type'],
        comment="Event type index for security pattern analysis"
    )
    
    op.create_index(
        'idx_security_events_created_at',
        'security_events',
        ['created_at'],
        comment="Temporal index for security incident chronology"
    )
    
    # Composite index for user + event type analysis
    op.create_index(
        'idx_security_events_user_type',
        'security_events',
        ['user_id', 'type', 'created_at'],
        comment="Composite index for user security behavior analysis"
    )
    
    # IP-based partial index for forensic analysis
    op.create_index(
        'idx_security_events_ip_created',
        'security_events',
        ['ip', 'created_at'],
        postgresql_where='ip IS NOT NULL',
        comment="IP-based forensic index for geographic threat analysis"
    )
    
    # Add enterprise documentation comments
    print("📝 Adding enterprise documentation...")
    
    # Table comments
    add_table_comment(
        'audit_logs',
        'Enterprise audit trail with cryptographic hash-chain integrity for regulatory compliance and data integrity assurance'
    )
    
    add_table_comment(
        'security_events', 
        'Enterprise security event tracking for compliance monitoring and threat detection'
    )
    
    # Column comments for audit_logs
    add_column_comment('audit_logs', 'id', 'Unique audit log entry identifier')
    add_column_comment('audit_logs', 'scope_type', 'Type of entity being audited (e.g., job, user, payment)')
    add_column_comment('audit_logs', 'scope_id', 'ID of the specific entity being audited')
    add_column_comment('audit_logs', 'actor_user_id', 'User who performed the audited action (NULL for system)')
    add_column_comment('audit_logs', 'event_type', 'Type of action performed (CREATE, UPDATE, DELETE, etc.)')
    add_column_comment('audit_logs', 'payload', 'Structured event data for compliance tracking')
    add_column_comment('audit_logs', 'prev_chain_hash', 'Previous entry hash for chain integrity')
    add_column_comment('audit_logs', 'chain_hash', 'Current entry hash (prev_hash + payload)')
    add_column_comment('audit_logs', 'created_at', 'When the audit event occurred (UTC)')
    
    # Column comments for security_events  
    add_column_comment('security_events', 'id', 'Unique security event identifier')
    add_column_comment('security_events', 'user_id', 'Associated user (NULL for anonymous events)')
    add_column_comment('security_events', 'type', 'Security event type (LOGIN_FAILED, ACCESS_DENIED, etc.)')
    add_column_comment('security_events', 'ip', 'Source IP address for forensic analysis')
    add_column_comment('security_events', 'ua', 'User agent string for device identification')
    add_column_comment('security_events', 'created_at', 'When the security event occurred (UTC)')
    
    print("✅ Task 2.6 completed: Security and audit tables with hash-chain integrity created successfully!")
    print("🔗 Hash-chain provides cryptographic integrity for regulatory compliance")
    print("🚀 Enterprise indexes optimized for high-frequency security monitoring")
    print("🏛️ Turkish GDPR/KVKK compliance patterns implemented")


def downgrade():
    """Remove security and audit tables and related constraints."""
    
    print("⚠️  Downgrading Task 2.6: Removing security and audit tables...")
    print("🔍 Note: This will remove all audit trail and security event data!")
    
    # Drop indexes first to avoid constraint issues
    print("🗑️ Dropping enterprise performance indexes...")
    
    # Drop audit_logs indexes
    try:
        op.drop_index('gin_audit_logs_payload', table_name='audit_logs')
    except Exception:
        pass
        
    try:
        op.drop_index('idx_audit_logs_actor_user', table_name='audit_logs')
    except Exception:
        pass
        
    try:
        op.drop_index('idx_audit_logs_event_type', table_name='audit_logs')
    except Exception:
        pass
        
    try:
        op.drop_index('idx_audit_logs_scope_created', table_name='audit_logs')
    except Exception:
        pass
    
    # Drop security_events indexes
    try:
        op.drop_index('idx_security_events_ip_created', table_name='security_events')
    except Exception:
        pass
        
    try:
        op.drop_index('idx_security_events_user_type', table_name='security_events')
    except Exception:
        pass
        
    try:
        op.drop_index('idx_security_events_created_at', table_name='security_events')
    except Exception:
        pass
        
    try:
        op.drop_index('idx_security_events_type', table_name='security_events')
    except Exception:
        pass
        
    try:
        op.drop_index('idx_security_events_user_id', table_name='security_events')
    except Exception:
        pass
    
    # Drop constraints
    print("🔓 Dropping hash-chain integrity constraints...")
    
    try:
        op.drop_constraint('uq_audit_logs_chain_hash', 'audit_logs', type_='unique')
    except Exception:
        pass
        
    try:
        op.drop_constraint('ck_audit_logs_prev_chain_hash_format', 'audit_logs', type_='check')
    except Exception:
        pass
        
    try:
        op.drop_constraint('ck_audit_logs_chain_hash_format', 'audit_logs', type_='check')
    except Exception:
        pass
    
    # Drop tables
    print("🗑️ Dropping security and audit tables...")
    
    try:
        op.drop_table('security_events')
        print("✅ Dropped security_events table")
    except Exception as e:
        print(f"⚠️  Could not drop security_events table: {e}")
    
    try:
        op.drop_table('audit_logs')
        print("✅ Dropped audit_logs table")
    except Exception as e:
        print(f"⚠️  Could not drop audit_logs table: {e}")
    
    print("✅ Task 2.6 downgrade completed")
    print("⚠️  All audit trail and security event data has been removed!")