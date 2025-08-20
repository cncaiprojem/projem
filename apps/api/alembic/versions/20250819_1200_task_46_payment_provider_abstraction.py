"""
Task 4.6: Payments provider abstraction and webhook handling with idempotency

Revision ID: task_46_payment_provider
Revises: task_44_invoice_model
Create Date: 2025-08-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '20250819_1200_task_46'
down_revision = '20250819_0000_task_47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Task 4.6: Create payment provider abstraction with webhook handling and idempotency.
    
    Features:
    - Provider-agnostic payment interface
    - Webhook idempotency with unique event tracking
    - Banking-grade audit logging
    - Status tracking with Task 4.6 specific enum values
    """
    
    # Create payment status enum with Task 4.6 specific values
    try:
        payment_status_enum = postgresql.ENUM(
            'requires_action', 'processing', 'succeeded', 'failed', 'canceled', 'refunded',
            name='payment_status_enum',
            create_type=False
        )
        payment_status_enum.create(op.get_bind(), checkfirst=True)
    except sa.exc.ProgrammingError as e:
        if "already exists" not in str(e):
            raise
    except sa.exc.OperationalError:
        raise
    
    # Create payments table with Task 4.6 specification
    op.create_table('payments',
        # Primary key
        sa.Column('id', sa.BigInteger(), nullable=False, comment='Payment primary key'),
        
        # Foreign key - Task 4.6 specification
        sa.Column('invoice_id', sa.BigInteger(), nullable=False, comment='Invoice this payment is for'),
        
        # Provider integration - Task 4.6 specification
        sa.Column('provider', sa.String(length=50), nullable=False, comment='Payment provider identifier (stripe, iyzico, etc.)'),
        sa.Column('provider_payment_id', sa.String(length=255), nullable=False, comment='Provider payment intent ID'),
        
        # Financial details with DECIMAL precision - Task 4.6 specification
        sa.Column('amount_cents', sa.BigInteger(), nullable=False, comment='Payment amount in smallest currency unit (cents)'),
        sa.Column('currency', sa.CHAR(length=3), server_default=sa.text("'TRY'"), nullable=False, comment='Payment currency'),
        
        # Status tracking - Task 4.6 specification
        sa.Column('status', payment_status_enum, server_default=sa.text("'requires_action'"), nullable=False, comment='Payment status'),
        
        # Provider request/response logging - Task 4.6 specification
        sa.Column('raw_request', postgresql.JSONB(), nullable=True, comment='Raw provider request data'),
        sa.Column('raw_response', postgresql.JSONB(), nullable=True, comment='Raw provider response data'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Primary key constraint
        sa.PrimaryKeyConstraint('id'),
        
        # Foreign key constraints
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='RESTRICT'),
        
        # Task 4.6 Ultra-enterprise constraints
        sa.CheckConstraint('amount_cents > 0', name='ck_payments_amount_positive'),
        sa.CheckConstraint("currency = 'TRY'", name='ck_payments_currency_try_only'),
        
        # Provider payment ID uniqueness per provider
        sa.UniqueConstraint('provider', 'provider_payment_id', name='uq_payments_provider_payment_id'),
    )
    
    # Create payment_webhook_events table for idempotency - Task 4.6 specification
    op.create_table('payment_webhook_events',
        # Primary key
        sa.Column('id', sa.BigInteger(), nullable=False, comment='Webhook event primary key'),
        
        # Event identification
        sa.Column('event_id', sa.String(length=255), nullable=False, comment='Unique provider event ID for idempotency'),
        sa.Column('provider', sa.String(length=50), nullable=False, comment='Payment provider identifier'),
        sa.Column('event_type', sa.String(length=100), nullable=False, comment='Event type (payment_intent.succeeded, etc.)'),
        
        # Associated payment
        sa.Column('payment_id', sa.BigInteger(), nullable=True, comment='Associated payment ID'),
        
        # Processing status
        sa.Column('processed', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Whether event was processed'),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True, comment='When event was processed'),
        
        # Raw event data
        sa.Column('raw_event', postgresql.JSONB(), nullable=False, comment='Raw webhook event data'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Primary key constraint
        sa.PrimaryKeyConstraint('id'),
        
        # Foreign key constraints
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='SET NULL'),
        
        # Idempotency constraint - unique event_id per provider
        sa.UniqueConstraint('provider', 'event_id', name='uq_webhook_events_provider_event_id'),
    )
    
    # Create payment_audit_logs table for compliance - Task 4.6 specification
    op.create_table('payment_audit_logs',
        # Primary key
        sa.Column('id', sa.BigInteger(), nullable=False, comment='Audit log primary key'),
        
        # Associated payment
        sa.Column('payment_id', sa.BigInteger(), nullable=True, comment='Associated payment ID'),
        sa.Column('invoice_id', sa.BigInteger(), nullable=True, comment='Associated invoice ID'),
        
        # Audit details
        sa.Column('action', sa.String(length=100), nullable=False, comment='Action performed (payment_succeeded, payment_failed, etc.)'),
        sa.Column('actor_type', sa.String(length=50), nullable=False, comment='Who performed action (system, webhook, user)'),
        sa.Column('actor_id', sa.String(length=255), nullable=True, comment='Actor identifier'),
        
        # Event context
        sa.Column('context', postgresql.JSONB(), nullable=True, comment='Additional context and metadata'),
        sa.Column('ip_address', sa.INET(), nullable=True, comment='IP address of request'),
        sa.Column('user_agent', sa.Text(), nullable=True, comment='User agent string'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Primary key constraint
        sa.PrimaryKeyConstraint('id'),
        
        # Foreign key constraints
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='SET NULL'),
    )
    
    # Create performance indexes
    op.create_index('idx_payments_invoice_status', 'payments', ['invoice_id', 'status'])
    op.create_index('idx_payments_provider_status', 'payments', ['provider', 'status'])
    op.create_index('idx_payments_created_at', 'payments', ['created_at'])
    
    op.create_index('idx_webhook_events_provider_processed', 'payment_webhook_events', ['provider', 'processed'])
    op.create_index('idx_webhook_events_created_at', 'payment_webhook_events', ['created_at'])
    
    op.create_index('idx_audit_logs_payment_action', 'payment_audit_logs', ['payment_id', 'action'])
    op.create_index('idx_audit_logs_created_at', 'payment_audit_logs', ['created_at'])
    
    # Partial indexes for active payments
    op.create_index(
        'idx_payments_active',
        'payments',
        ['provider', 'status', 'created_at'],
        postgresql_where=sa.text("status IN ('requires_action', 'processing')")
    )


def downgrade() -> None:
    """Remove payment provider abstraction tables and related constraints."""
    
    # Drop indexes
    index_names = [
        ('idx_payments_active', 'payments'),
        ('idx_audit_logs_created_at', 'payment_audit_logs'),
        ('idx_audit_logs_payment_action', 'payment_audit_logs'),
        ('idx_webhook_events_created_at', 'payment_webhook_events'),
        ('idx_webhook_events_provider_processed', 'payment_webhook_events'),
        ('idx_payments_created_at', 'payments'),
        ('idx_payments_provider_status', 'payments'),
        ('idx_payments_invoice_status', 'payments')
    ]
    
    for index_name, table_name in index_names:
        try:
            op.drop_index(index_name, table_name=table_name)
        except sa.exc.ProgrammingError as e:
            if "does not exist" not in str(e):
                raise
        except sa.exc.OperationalError:
            raise
    
    # Drop tables
    op.drop_table('payment_audit_logs')
    op.drop_table('payment_webhook_events')
    op.drop_table('payments')
    
    # Drop enum
    try:
        payment_status_enum = postgresql.ENUM(name='payment_status_enum')
        payment_status_enum.drop(op.get_bind(), checkfirst=True)
    except sa.exc.ProgrammingError as e:
        if "does not exist" not in str(e) and "cannot be dropped" not in str(e):
            raise
    except sa.exc.OperationalError:
        raise