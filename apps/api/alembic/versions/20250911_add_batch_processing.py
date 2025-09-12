"""Add batch processing tables for Task 7.23

Revision ID: batch_processing_7_23
Revises: 20250120_add_file_metadata_tables
Create Date: 2025-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'batch_processing_7_23'
down_revision: Union[str, None] = '20250120_add_file_metadata_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create batch processing tables."""
    
    # Create batch_jobs table
    op.create_table(
        'batch_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('operation', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('total_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('successful_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('strategy', sa.String(50), nullable=False, server_default='adaptive'),
        sa.Column('max_workers', sa.Integer(), nullable=True),
        sa.Column('chunk_size', sa.Integer(), nullable=True, server_default='10'),
        sa.Column('max_retries', sa.Integer(), nullable=True, server_default='3'),
        sa.Column('continue_on_error', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='[]'),
        sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('statistics', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        comment='Batch processing jobs and execution history'
    )
    
    # Create indexes for batch_jobs
    op.create_index('ix_batch_jobs_batch_id', 'batch_jobs', ['batch_id'], unique=True)
    op.create_index('ix_batch_jobs_operation', 'batch_jobs', ['operation'])
    op.create_index('ix_batch_jobs_status', 'batch_jobs', ['status'])
    op.create_index('ix_batch_jobs_status_created', 'batch_jobs', ['status', 'created_at'])
    op.create_index('ix_batch_jobs_user_status', 'batch_jobs', ['user_id', 'status'])
    
    # Create batch_job_items table
    op.create_table(
        'batch_job_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_job_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('retries', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('processing_time_ms', sa.Float(), nullable=True),
        sa.Column('input_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('output_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['batch_job_id'], ['batch_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Individual items in batch processing jobs'
    )
    
    # Create indexes for batch_job_items
    op.create_index('ix_batch_job_items_batch_status', 'batch_job_items', ['batch_job_id', 'status'])
    op.create_index('ix_batch_job_items_status', 'batch_job_items', ['status'])
    
    # Create workflow_definitions table
    op.create_table(
        'workflow_definitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('entry_point', sa.String(64), nullable=True),
        sa.Column('global_timeout', sa.Integer(), nullable=True),
        sa.Column('on_success', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('on_failure', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('messages', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'version', name='uq_workflow_name_version'),
        comment='Workflow definitions and configurations'
    )
    
    # Create indexes for workflow_definitions
    op.create_index('ix_workflow_definitions_workflow_id', 'workflow_definitions', ['workflow_id'], unique=True)
    op.create_index('ix_workflow_definitions_name', 'workflow_definitions', ['name'])
    op.create_index('ix_workflow_definitions_active', 'workflow_definitions', ['is_active'])
    
    # Create workflow_executions table
    op.create_table(
        'workflow_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('execution_id', sa.String(64), nullable=False),
        sa.Column('workflow_definition_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='created'),
        sa.Column('current_step', sa.String(64), nullable=True),
        sa.Column('input_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('step_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('start_time', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workflow_definition_id'], ['workflow_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        comment='Workflow execution instances and history'
    )
    
    # Create indexes for workflow_executions
    op.create_index('ix_workflow_executions_execution_id', 'workflow_executions', ['execution_id'], unique=True)
    op.create_index('ix_workflow_executions_status', 'workflow_executions', ['status'])
    op.create_index('ix_workflow_executions_status_started', 'workflow_executions', ['status', 'start_time'])
    op.create_index('ix_workflow_executions_definition_status', 'workflow_executions', ['workflow_definition_id', 'status'])
    
    # Create scheduled_jobs table
    op.create_table(
        'scheduled_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('function', sa.String(255), nullable=False),
        sa.Column('trigger_type', sa.String(50), nullable=False),
        sa.Column('trigger_args', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='[]'),
        sa.Column('kwargs', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('max_instances', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('misfire_grace_time', sa.Integer(), nullable=True, server_default='60'),
        sa.Column('coalesce', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('next_run_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id', name='uq_scheduled_job_id'),
        comment='Scheduled job configurations'
    )
    
    # Create indexes for scheduled_jobs
    op.create_index('ix_scheduled_jobs_job_id', 'scheduled_jobs', ['job_id'])
    op.create_index('ix_scheduled_jobs_enabled', 'scheduled_jobs', ['enabled'])
    op.create_index('ix_scheduled_jobs_enabled_next_run', 'scheduled_jobs', ['enabled', 'next_run_time'])
    op.create_index('ix_scheduled_jobs_next_run_time', 'scheduled_jobs', ['next_run_time'])
    
    # Create scheduled_job_executions table
    op.create_table(
        'scheduled_job_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('execution_id', sa.String(64), nullable=False),
        sa.Column('scheduled_job_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('scheduled_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['scheduled_job_id'], ['scheduled_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Scheduled job execution history'
    )
    
    # Create indexes for scheduled_job_executions
    op.create_index('ix_scheduled_job_executions_execution_id', 'scheduled_job_executions', ['execution_id'], unique=True)
    op.create_index('ix_scheduled_job_executions_status', 'scheduled_job_executions', ['status'])
    op.create_index('ix_scheduled_job_executions_job_started', 'scheduled_job_executions', ['scheduled_job_id', 'start_time'])


def downgrade() -> None:
    """Drop batch processing tables."""
    
    # Drop scheduled_job_executions
    op.drop_index('ix_scheduled_job_executions_job_started', table_name='scheduled_job_executions')
    op.drop_index('ix_scheduled_job_executions_status', table_name='scheduled_job_executions')
    op.drop_index('ix_scheduled_job_executions_execution_id', table_name='scheduled_job_executions')
    op.drop_table('scheduled_job_executions')
    
    # Drop scheduled_jobs
    op.drop_index('ix_scheduled_jobs_next_run_time', table_name='scheduled_jobs')
    op.drop_index('ix_scheduled_jobs_enabled_next_run', table_name='scheduled_jobs')
    op.drop_index('ix_scheduled_jobs_enabled', table_name='scheduled_jobs')
    op.drop_index('ix_scheduled_jobs_job_id', table_name='scheduled_jobs')
    op.drop_table('scheduled_jobs')
    
    # Drop workflow_executions
    op.drop_index('ix_workflow_executions_definition_status', table_name='workflow_executions')
    op.drop_index('ix_workflow_executions_status_started', table_name='workflow_executions')
    op.drop_index('ix_workflow_executions_status', table_name='workflow_executions')
    op.drop_index('ix_workflow_executions_execution_id', table_name='workflow_executions')
    op.drop_table('workflow_executions')
    
    # Drop workflow_definitions
    op.drop_index('ix_workflow_definitions_active', table_name='workflow_definitions')
    op.drop_index('ix_workflow_definitions_name', table_name='workflow_definitions')
    op.drop_index('ix_workflow_definitions_workflow_id', table_name='workflow_definitions')
    op.drop_table('workflow_definitions')
    
    # Drop batch_job_items
    op.drop_index('ix_batch_job_items_status', table_name='batch_job_items')
    op.drop_index('ix_batch_job_items_batch_status', table_name='batch_job_items')
    op.drop_table('batch_job_items')
    
    # Drop batch_jobs
    op.drop_index('ix_batch_jobs_user_status', table_name='batch_jobs')
    op.drop_index('ix_batch_jobs_status_created', table_name='batch_jobs')
    op.drop_index('ix_batch_jobs_status', table_name='batch_jobs')
    op.drop_index('ix_batch_jobs_operation', table_name='batch_jobs')
    op.drop_index('ix_batch_jobs_batch_id', table_name='batch_jobs')
    op.drop_table('batch_jobs')