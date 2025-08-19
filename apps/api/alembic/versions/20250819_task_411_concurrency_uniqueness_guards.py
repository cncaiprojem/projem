"""Task 4.11: Add concurrency and uniqueness guards

Revision ID: task_411_concurrency_guards
Revises: 20250819_1245-task_49_job_cancellation_on_license_expiry
Create Date: 2025-08-19 14:00:00.000000

Task 4.11: Implements concurrency and uniqueness guards for:
- Invoice numbering with PostgreSQL sequences and advisory locks
- API idempotency with request/response caching
- Webhook event deduplication
- Unique active license per user constraint
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'task_411_concurrency_guards'
down_revision = '20250819_1245-task_49_job_cancellation_on_license_expiry'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add concurrency and uniqueness guard tables and constraints."""
    
    # Create idempotency_keys table for API request deduplication
    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False, comment='User who made the request'),
        sa.Column('key', sa.String(length=255), nullable=False, comment='Idempotency-Key header value'),
        sa.Column('request_path', sa.String(length=500), nullable=False, comment='API endpoint path'),
        sa.Column('request_method', sa.String(length=10), nullable=False, comment='HTTP method'),
        sa.Column('request_hash', sa.String(length=64), nullable=False, comment='SHA256 hash of request body'),
        sa.Column('response_status', sa.Integer(), nullable=False, comment='HTTP response status code'),
        sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Cached response body'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, comment='When this idempotency key expires'),
        sa.Column('is_processing', sa.Boolean(), nullable=False, server_default='false', comment='Whether request is currently being processed'),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True, comment='When processing started (for timeout detection)'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Store idempotency keys to prevent duplicate API operations'
    )
    
    # Create indexes for idempotency_keys
    op.create_index('idx_idempotency_keys_user_id', 'idempotency_keys', ['user_id'])
    op.create_index('idx_idempotency_keys_expires_at', 'idempotency_keys', ['expires_at'])
    op.create_index(
        'idx_idempotency_keys_processing',
        'idempotency_keys',
        ['is_processing', 'processing_started_at'],
        postgresql_where=sa.text('is_processing = true')
    )
    
    # Create unique constraint on user_id + key
    op.create_unique_constraint(
        'uq_idempotency_keys_user_key',
        'idempotency_keys',
        ['user_id', 'key']
    )
    
    # Create webhook_events table for webhook deduplication
    op.create_table(
        'webhook_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False, comment='Unique event identifier for deduplication'),
        sa.Column('event_type', sa.String(length=100), nullable=False, comment='Type of webhook event (e.g., license.expired, payment.completed)'),
        sa.Column('entity_type', sa.String(length=50), nullable=False, comment='Type of entity (e.g., license, invoice, payment)'),
        sa.Column('entity_id', sa.BigInteger(), nullable=False, comment='ID of the related entity'),
        sa.Column('user_id', sa.BigInteger(), nullable=True, comment='Associated user (if applicable)'),
        sa.Column('webhook_url', sa.String(length=500), nullable=False, comment='Target webhook URL'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='Webhook payload data'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending', comment='Delivery status: pending, processing, delivered, failed'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0', comment='Number of delivery attempts'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='5', comment='Maximum number of retry attempts'),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True, comment='When to attempt next delivery'),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True, comment='When webhook was successfully delivered'),
        sa.Column('last_response_status', sa.Integer(), nullable=True, comment='HTTP status code of last delivery attempt'),
        sa.Column('last_response_body', sa.Text(), nullable=True, comment='Response body from last delivery attempt'),
        sa.Column('last_error', sa.Text(), nullable=True, comment='Error message from last failed attempt'),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True, comment='When event was locked for processing'),
        sa.Column('locked_by', sa.String(length=100), nullable=True, comment='Worker ID that locked this event'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        comment='Track webhook events for deduplication and retry management'
    )
    
    # Create indexes for webhook_events
    op.create_index('idx_webhook_events_event_id', 'webhook_events', ['event_id'], unique=True)
    op.create_index('idx_webhook_events_event_type', 'webhook_events', ['event_type'])
    op.create_index('idx_webhook_events_entity_id', 'webhook_events', ['entity_id'])
    op.create_index('idx_webhook_events_user_id', 'webhook_events', ['user_id'])
    op.create_index('idx_webhook_events_status', 'webhook_events', ['status'])
    op.create_index('idx_webhook_events_next_retry_at', 'webhook_events', ['next_retry_at'])
    op.create_index(
        'idx_webhook_events_pending',
        'webhook_events',
        ['status', 'next_retry_at'],
        postgresql_where=sa.text("status IN ('pending', 'failed') AND retry_count < max_retries")
    )
    op.create_index(
        'idx_webhook_events_entity',
        'webhook_events',
        ['entity_type', 'entity_id']
    )
    op.create_index(
        'idx_webhook_events_locked',
        'webhook_events',
        ['locked_at', 'locked_by'],
        postgresql_where=sa.text('locked_at IS NOT NULL')
    )
    
    # Create unique constraint on event_id for deduplication
    op.create_unique_constraint(
        'uq_webhook_events_event_id',
        'webhook_events',
        ['event_id']
    )
    
    # Add unique constraint for one active license per user
    op.create_index(
        'uq_licenses_one_active_per_user',
        'licenses',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'")
    )
    
    # Create PostgreSQL sequence for invoice numbering (for current month)
    # Note: Monthly sequences will be created dynamically by the application
    op.execute("""
        CREATE SEQUENCE IF NOT EXISTS invoice_seq_202501
        START WITH 1
        INCREMENT BY 1
        NO MAXVALUE
        NO CYCLE
    """)
    
    # Add comment to invoices.number column about the new format
    op.execute("""
        COMMENT ON COLUMN invoices.number IS 
        'Unique invoice number in format YYYYMM-NNNNN-CNCAI with atomic sequence generation'
    """)
    
    print("✅ Task 4.11: Concurrency and uniqueness guards migration completed successfully")


def downgrade() -> None:
    """Remove concurrency and uniqueness guard tables and constraints."""
    
    # Drop unique constraint for one active license per user
    op.drop_index('uq_licenses_one_active_per_user', 'licenses')
    
    # Drop webhook_events table and its indexes
    op.drop_index('idx_webhook_events_locked', 'webhook_events')
    op.drop_index('idx_webhook_events_entity', 'webhook_events')
    op.drop_index('idx_webhook_events_pending', 'webhook_events')
    op.drop_index('idx_webhook_events_next_retry_at', 'webhook_events')
    op.drop_index('idx_webhook_events_status', 'webhook_events')
    op.drop_index('idx_webhook_events_user_id', 'webhook_events')
    op.drop_index('idx_webhook_events_entity_id', 'webhook_events')
    op.drop_index('idx_webhook_events_event_type', 'webhook_events')
    op.drop_index('idx_webhook_events_event_id', 'webhook_events')
    op.drop_constraint('uq_webhook_events_event_id', 'webhook_events', type_='unique')
    op.drop_table('webhook_events')
    
    # Drop idempotency_keys table and its indexes
    op.drop_index('idx_idempotency_keys_processing', 'idempotency_keys')
    op.drop_index('idx_idempotency_keys_expires_at', 'idempotency_keys')
    op.drop_index('idx_idempotency_keys_user_id', 'idempotency_keys')
    op.drop_constraint('uq_idempotency_keys_user_key', 'idempotency_keys', type_='unique')
    op.drop_table('idempotency_keys')
    
    # Drop invoice sequences (only the example one, others are created dynamically)
    op.execute("DROP SEQUENCE IF EXISTS invoice_seq_202501")
    
    # Remove comment update
    op.execute("""
        COMMENT ON COLUMN invoices.number IS 
        'Unique invoice number for business identification'
    """)
    
    print("✅ Task 4.11: Concurrency and uniqueness guards migration rolled back successfully")