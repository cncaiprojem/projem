"""Add idempotency_records table for Task 4.2

Revision ID: add_idempotency_records
Revises: add_license_and_audit_tables
Create Date: 2025-08-18 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_idempotency_records'
down_revision = 'add_license_and_audit_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create idempotency_records table for API operation deduplication."""
    
    # Create idempotency_records table
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False, index=True,
                  comment='User who made the request'),
        sa.Column('idempotency_key', sa.String(255), nullable=False, index=True,
                  comment='Unique key from Idempotency-Key header'),
        sa.Column('endpoint', sa.String(255), nullable=False,
                  comment='API endpoint path'),
        sa.Column('method', sa.String(10), nullable=False,
                  comment='HTTP method (POST, PUT, etc.)'),
        sa.Column('response_status', sa.Integer(), nullable=False,
                  comment='HTTP response status code'),
        sa.Column('response_data', postgresql.JSON(astext_type=sa.Text()), nullable=False,
                  comment='Stored response data for replay'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(),
                  comment='When the request was first processed'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False,
                  comment='When this idempotency record expires (24 hours by default)'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_user_idempotency_key'),
        comment='Idempotency tracking for API operations with Turkish KVKV compliance'
    )
    
    # Create index for efficient expiry cleanup
    op.create_index(
        'ix_idempotency_expires',
        'idempotency_records',
        ['expires_at'],
        postgresql_where=sa.text('expires_at > NOW()')
    )
    
    # Add comment to the table
    op.execute("""
        COMMENT ON TABLE idempotency_records IS 
        'Tracks API request idempotency to prevent duplicate operations. Ultra-enterprise banking grade with Turkish KVKV compliance.';
    """)
    
    # Add comments to columns for documentation
    op.execute("""
        COMMENT ON COLUMN idempotency_records.id IS 'Primary key';
        COMMENT ON COLUMN idempotency_records.user_id IS 'UUID of the user making the request';
        COMMENT ON COLUMN idempotency_records.idempotency_key IS 'Unique key from Idempotency-Key header for deduplication';
        COMMENT ON COLUMN idempotency_records.endpoint IS 'API endpoint path for validation';
        COMMENT ON COLUMN idempotency_records.method IS 'HTTP method used (POST, PUT, DELETE, etc.)';
        COMMENT ON COLUMN idempotency_records.response_status IS 'HTTP status code of the original response';
        COMMENT ON COLUMN idempotency_records.response_data IS 'JSON response data for replay';
        COMMENT ON COLUMN idempotency_records.created_at IS 'Timestamp when request was first processed';
        COMMENT ON COLUMN idempotency_records.expires_at IS 'TTL expiration timestamp for automatic cleanup';
    """)


def downgrade() -> None:
    """Drop idempotency_records table."""
    
    # Drop indexes first
    op.drop_index('ix_idempotency_expires', table_name='idempotency_records')
    
    # Drop the table
    op.drop_table('idempotency_records')