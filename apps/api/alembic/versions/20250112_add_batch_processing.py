"""Add batch processing tables

Revision ID: batch_processing_001
Revises: 
Create Date: 2025-01-12 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'batch_processing_001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create batch processing related tables."""
    
    # Create batch_jobs table
    op.create_table(
        'batch_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('operation_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('config', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('input_models', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('output_location', sa.String(length=500), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('results', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('errors', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('warnings', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('cpu_seconds', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('memory_mb_peak', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('retry_delay_seconds', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_batch_jobs_user_id', 'batch_jobs', ['user_id'])
    op.create_index('ix_batch_jobs_status', 'batch_jobs', ['status'])
    op.create_index('ix_batch_jobs_operation_type', 'batch_jobs', ['operation_type'])
    op.create_index('ix_batch_jobs_created_at', 'batch_jobs', ['created_at'])
    
    # Create quality_checks table
    op.create_table(
        'quality_checks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_job_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('check_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('passed', sa.Boolean(), nullable=True),
        sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('issues_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('issues_fixed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('findings', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('recommendations', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('auto_fix_available', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('auto_fix_applied', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('metrics', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['batch_job_id'], ['batch_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['models.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_job_id', 'model_id', 'check_type', name='uq_quality_check')
    )
    op.create_index('ix_quality_checks_batch_job_id', 'quality_checks', ['batch_job_id'])
    op.create_index('ix_quality_checks_model_id', 'quality_checks', ['model_id'])
    op.create_index('ix_quality_checks_check_type', 'quality_checks', ['check_type'])
    op.create_index('ix_quality_checks_status', 'quality_checks', ['status'])
    
    # Create workflow_executions table
    op.create_table(
        'workflow_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_job_id', sa.Integer(), nullable=False),
        sa.Column('workflow_name', sa.String(length=255), nullable=False),
        sa.Column('workflow_version', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('parameters', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('total_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_step', sa.String(length=255), nullable=True),
        sa.Column('steps', sa.JSON(), nullable=True, server_default='[]'),
        sa.Column('step_results', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_step', sa.String(length=255), nullable=True),
        sa.Column('error_details', sa.JSON(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('can_retry', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['batch_job_id'], ['batch_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_workflow_executions_batch_job_id', 'workflow_executions', ['batch_job_id'])
    op.create_index('ix_workflow_executions_status', 'workflow_executions', ['status'])
    op.create_index('ix_workflow_executions_workflow_name', 'workflow_executions', ['workflow_name'])
    
    # Create batch_operations_stats view for analytics
    op.execute("""
        CREATE OR REPLACE VIEW batch_operations_stats AS
        SELECT 
            bj.user_id,
            bj.operation_type,
            COUNT(DISTINCT bj.id) as total_jobs,
            COUNT(DISTINCT CASE WHEN bj.status = 'completed' THEN bj.id END) as completed_jobs,
            COUNT(DISTINCT CASE WHEN bj.status = 'failed' THEN bj.id END) as failed_jobs,
            AVG(bj.duration_seconds) as avg_duration_seconds,
            SUM(bj.processed_items) as total_processed_items,
            SUM(bj.failed_items) as total_failed_items,
            AVG(CASE WHEN bj.processed_items > 0 
                THEN (bj.processed_items - bj.failed_items)::float / bj.processed_items * 100 
                ELSE 0 END) as avg_success_rate
        FROM batch_jobs bj
        GROUP BY bj.user_id, bj.operation_type
    """)


def downgrade() -> None:
    """Drop batch processing related tables."""
    
    # Drop view
    op.execute("DROP VIEW IF EXISTS batch_operations_stats")
    
    # Drop indexes
    op.drop_index('ix_workflow_executions_workflow_name', table_name='workflow_executions')
    op.drop_index('ix_workflow_executions_status', table_name='workflow_executions')
    op.drop_index('ix_workflow_executions_batch_job_id', table_name='workflow_executions')
    
    op.drop_index('ix_quality_checks_status', table_name='quality_checks')
    op.drop_index('ix_quality_checks_check_type', table_name='quality_checks')
    op.drop_index('ix_quality_checks_model_id', table_name='quality_checks')
    op.drop_index('ix_quality_checks_batch_job_id', table_name='quality_checks')
    
    op.drop_index('ix_batch_jobs_created_at', table_name='batch_jobs')
    op.drop_index('ix_batch_jobs_operation_type', table_name='batch_jobs')
    op.drop_index('ix_batch_jobs_status', table_name='batch_jobs')
    op.drop_index('ix_batch_jobs_user_id', table_name='batch_jobs')
    
    # Drop tables
    op.drop_table('workflow_executions')
    op.drop_table('quality_checks')
    op.drop_table('batch_jobs')