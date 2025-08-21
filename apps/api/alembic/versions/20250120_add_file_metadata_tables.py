"""Add file metadata and upload session tables for Task 5.3

Revision ID: 20250120_file_metadata
Revises: latest
Create Date: 2025-01-20

Task 5.3: Upload/download APIs with presigned URLs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '20250120_file_metadata'
down_revision = '20250819_task_411'  # Latest revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create file metadata and upload session tables."""
    
    # Create file status enum
    op.execute("""
        CREATE TYPE file_status AS ENUM (
            'pending', 'uploading', 'verifying', 'scanning', 
            'completed', 'failed', 'deleted'
        )
    """)
    
    # Create file type enum
    op.execute("""
        CREATE TYPE file_type AS ENUM (
            'model', 'gcode', 'report', 'invoice', 'log', 'temp'
        )
    """)
    
    # Create file_metadata table
    op.create_table(
        'file_metadata',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column('object_key', sa.String(1024), nullable=False, unique=True, index=True),
        sa.Column('bucket', sa.String(63), nullable=False, index=True),
        sa.Column('filename', sa.String(255), nullable=True),
        sa.Column('file_type', postgresql.ENUM('model', 'gcode', 'report', 'invoice', 'log', 'temp', name='file_type'), nullable=False, index=True),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False, index=True),
        sa.Column('etag', sa.String(100), nullable=True),
        sa.Column('version_id', sa.String(100), nullable=True),
        sa.Column('status', postgresql.ENUM('pending', 'uploading', 'verifying', 'scanning', 'completed', 'failed', 'deleted', name='file_status'), nullable=False, index=True),
        sa.Column('job_id', sa.String(100), nullable=False, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column('machine_id', sa.String(50), nullable=True, index=True),
        sa.Column('post_processor', sa.String(50), nullable=True),
        sa.Column('tags', postgresql.JSON(), nullable=True, default={}),
        sa.Column('metadata', postgresql.JSON(), nullable=True, default={}),
        sa.Column('client_ip', sa.String(45), nullable=True),
        sa.Column('malware_scan_result', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('job_id', 'filename', name='uq_job_filename'),
        sa.CheckConstraint('size > 0', name='ck_positive_size'),
        sa.CheckConstraint('length(sha256) = 64', name='ck_sha256_length'),
        sa.CheckConstraint('length(object_key) > 0', name='ck_object_key_not_empty'),
        comment='File metadata for upload tracking and verification'
    )
    
    # Create composite indexes
    op.create_index('ix_file_metadata_job_status', 'file_metadata', ['job_id', 'status'])
    op.create_index('ix_file_metadata_type_created', 'file_metadata', ['file_type', 'created_at'])
    op.create_index('ix_file_metadata_user_created', 'file_metadata', ['user_id', 'created_at'])
    
    # Create upload_sessions table
    op.create_table(
        'upload_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column('upload_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('object_key', sa.String(1024), nullable=False),
        sa.Column('expected_size', sa.BigInteger(), nullable=False),
        sa.Column('expected_sha256', sa.String(64), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('job_id', sa.String(100), nullable=False, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('client_ip', sa.String(45), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSON(), nullable=True, default={}),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.CheckConstraint('expected_size > 0', name='ck_session_positive_size'),
        comment='Upload session tracking for validation'
    )
    
    # Create indexes for upload_sessions
    op.create_index('ix_upload_sessions_expires', 'upload_sessions', ['expires_at'])
    op.create_index('ix_upload_sessions_user_created', 'upload_sessions', ['user_id', 'created_at'])


def downgrade() -> None:
    """Drop file metadata and upload session tables."""
    
    # Drop tables
    op.drop_table('upload_sessions')
    op.drop_table('file_metadata')
    
    # Drop enums
    op.execute('DROP TYPE IF EXISTS file_status')
    op.execute('DROP TYPE IF EXISTS file_type')