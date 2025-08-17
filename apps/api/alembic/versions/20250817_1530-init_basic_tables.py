"""Initial basic tables for Task 1-2

Revision ID: 20250817_1530-init_basic_tables
Revises: 
Create Date: 2025-08-17 15:30

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
import uuid

# revision identifiers, used by Alembic.
revision = '20250817_1530_init_basic_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table with basic fields
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('role', sa.String(50), nullable=False, server_default='engineer'),
        sa.Column('locale', sa.String(10), nullable=False, server_default='tr'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_role', 'users', ['role'])
    
    # Create jobs table with basic fields
    op.create_table(
        'jobs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(255), nullable=True),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metrics', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_jobs_user_id', 'jobs', ['user_id'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_type', 'jobs', ['type'])
    op.create_index('ix_jobs_idempotency_key', 'jobs', ['idempotency_key'])
    
    # Create artefacts table
    op.create_table(
        'artefacts',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.Integer, sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('s3_key', sa.String(1024), nullable=False),
        sa.Column('size', sa.Integer, nullable=False, server_default='0'),
        sa.Column('sha256', sa.String(64), nullable=True),
        sa.Column('extra', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_artefacts_job_id', 'artefacts', ['job_id'])
    op.create_index('ix_artefacts_type', 'artefacts', ['type'])
    
    # Create models table
    op.create_table(
        'models',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('parameters', JSONB, nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_models_user_id', 'models', ['user_id'])
    op.create_index('ix_models_status', 'models', ['status'])
    op.create_index('ix_models_name', 'models', ['name'])
    
    # Create sessions table for authentication
    op.create_table(
        'sessions',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('session_token', sa.String(255), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])
    op.create_index('ix_sessions_session_token', 'sessions', ['session_token'], unique=True)
    op.create_index('ix_sessions_expires_at', 'sessions', ['expires_at'])


def downgrade() -> None:
    op.drop_table('sessions')
    op.drop_table('models')
    op.drop_table('artefacts')
    op.drop_table('jobs')
    op.drop_table('users')