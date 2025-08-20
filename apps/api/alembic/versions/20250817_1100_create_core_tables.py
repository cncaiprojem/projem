"""Create core application tables

This migration creates the fundamental tables required for the FreeCAD CNC/CAM platform.
These tables must exist before optimization migrations can be applied.

Revision ID: 20250817_1100_core_tables
Revises: base_revision
Create Date: 2025-08-17 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '20250817_1100_core_tables'
down_revision = 'base_revision'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create core application tables."""
    
    # Create enum types with error handling
    from psycopg2 import errors
    
    def create_enum_safe(enum_name, values):
        try:
            op.execute(f"CREATE TYPE {enum_name} AS ENUM ({values})")
            print(f"✅ Created enum type: {enum_name}")
        except Exception as e:
            if 'already exists' in str(e):
                print(f"ℹ️ Enum type {enum_name} already exists, skipping")
            else:
                raise
    
    create_enum_safe('user_role', "'admin', 'engineer', 'operator', 'viewer'")
    create_enum_safe('user_status', "'active', 'inactive', 'suspended', 'deleted'")
    create_enum_safe('job_status', "'pending', 'queued', 'running', 'completed', 'failed', 'cancelled', 'timeout'")
    create_enum_safe('job_type', "'cad_generate', 'cad_import', 'cad_export', 'cam_process', 'cam_optimize', 'sim_run', 'sim_collision', 'gcode_post', 'gcode_verify', 'report_generate', 'model_repair'")
    create_enum_safe('model_type', "'part', 'assembly', 'drawing', 'sketch', 'mesh'")
    create_enum_safe('model_status', "'draft', 'review', 'approved', 'archived', 'deleted'")
    create_enum_safe('artefact_type', "'model', 'gcode', 'report', 'simulation', 'drawing', 'toolpath'")
    
    # 1. Create users table
    op.create_table('users',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('username', sa.String(100), nullable=True),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('hashed_password', sa.String(255), nullable=True),
        sa.Column('role', postgresql.ENUM('admin', 'engineer', 'operator', 'viewer', name='user_role', create_type=False), 
                  server_default='viewer', nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'suspended', 'deleted', name='user_status', create_type=False),
                  server_default='active', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_verified', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('login_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('failed_login_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('preferences', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('metadata_', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), 
                  onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username')
    )
    
    # Create indexes for users
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_status', 'users', ['status'])
    op.create_index('ix_users_role', 'users', ['role'])
    op.create_index('ix_users_created_at', 'users', ['created_at'])
    
    # 2. Create jobs table
    op.create_table('jobs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('job_type', postgresql.ENUM('cad_generate', 'cad_import', 'cad_export', 'cam_process', 
                                              'cam_optimize', 'sim_run', 'sim_collision', 'gcode_post', 
                                              'gcode_verify', 'report_generate', 'model_repair', 
                                              name='job_type', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'queued', 'running', 'completed', 'failed', 
                                           'cancelled', 'timeout', name='job_status', create_type=False), 
                  server_default='pending', nullable=False),
        sa.Column('priority', sa.Integer(), server_default='5', nullable=False),
        sa.Column('queue_name', sa.String(100), server_default='default', nullable=False),
        sa.Column('task_id', sa.String(255), nullable=True),
        sa.Column('params', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('progress', sa.Integer(), server_default='0', nullable=False),
        sa.Column('metrics', postgresql.JSONB(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_retries', sa.Integer(), server_default='3', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), 
                  onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('priority >= 1 AND priority <= 10', name='ck_jobs_priority_range'),
        sa.CheckConstraint('progress >= 0 AND progress <= 100', name='ck_jobs_progress_range')
    )
    
    # Create indexes for jobs
    op.create_index('ix_jobs_user_id', 'jobs', ['user_id'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_job_type', 'jobs', ['job_type'])
    op.create_index('ix_jobs_task_id', 'jobs', ['task_id'])
    op.create_index('ix_jobs_created_at', 'jobs', ['created_at'])
    op.create_index('ix_jobs_priority_status', 'jobs', ['priority', 'status'])
    
    # 3. Create models table
    op.create_table('models',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('job_id', sa.BigInteger(), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('model_type', postgresql.ENUM('part', 'assembly', 'drawing', 'sketch', 'mesh', 
                                                name='model_type', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('draft', 'review', 'approved', 'archived', 'deleted',
                                           name='model_status', create_type=False), server_default='draft', nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('parent_id', sa.BigInteger(), nullable=True),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('s3_key', sa.String(500), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('params', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('metadata_', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('properties', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), 
                  onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['parent_id'], ['models.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for models
    op.create_index('ix_models_user_id', 'models', ['user_id'])
    op.create_index('ix_models_job_id', 'models', ['job_id'])
    op.create_index('ix_models_name', 'models', ['name'])
    op.create_index('ix_models_status', 'models', ['status'])
    op.create_index('ix_models_model_type', 'models', ['model_type'])
    op.create_index('ix_models_parent_id', 'models', ['parent_id'])
    op.create_index('ix_models_created_at', 'models', ['created_at'])
    op.create_index('ix_models_file_hash', 'models', ['file_hash'])
    
    # 4. Create artefacts table
    op.create_table('artefacts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('job_id', sa.BigInteger(), nullable=True),
        sa.Column('model_id', sa.BigInteger(), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('artefact_type', postgresql.ENUM('model', 'gcode', 'report', 'simulation', 
                                                    'drawing', 'toolpath', name='artefact_type', create_type=False), 
                  nullable=False),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('s3_key', sa.String(500), nullable=True),
        sa.Column('s3_bucket', sa.String(100), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('metadata_', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('properties', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String()), server_default='{}', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), 
                  onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['model_id'], ['models.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for artefacts
    op.create_index('ix_artefacts_user_id', 'artefacts', ['user_id'])
    op.create_index('ix_artefacts_job_id', 'artefacts', ['job_id'])
    op.create_index('ix_artefacts_model_id', 'artefacts', ['model_id'])
    op.create_index('ix_artefacts_artefact_type', 'artefacts', ['artefact_type'])
    op.create_index('ix_artefacts_s3_key', 'artefacts', ['s3_key'])
    op.create_index('ix_artefacts_file_hash', 'artefacts', ['file_hash'])
    op.create_index('ix_artefacts_created_at', 'artefacts', ['created_at'])
    
    # 5. Create sessions table (basic version, will be enhanced in Task 3.2)
    op.create_table('sessions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('session_token', sa.String(255), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), 
                  onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_token')
    )
    
    # Create indexes for sessions
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])
    op.create_index('ix_sessions_session_token', 'sessions', ['session_token'])
    op.create_index('ix_sessions_expires_at', 'sessions', ['expires_at'])
    
    # 6. Create licenses table (basic version, will be enhanced in Task 4.1)
    op.create_table('licenses',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('license_key', sa.String(255), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), server_default='active', nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scope', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('metadata_', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), 
                  onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('license_key')
    )
    
    # Create indexes for licenses
    op.create_index('ix_licenses_user_id', 'licenses', ['user_id'])
    op.create_index('ix_licenses_license_key', 'licenses', ['license_key'])
    op.create_index('ix_licenses_status', 'licenses', ['status'])
    op.create_index('ix_licenses_expires_at', 'licenses', ['expires_at'])
    
    print("✅ Created all core tables successfully")
    
    # Record migration
    try:
        op.execute(sa.text("""
            INSERT INTO enterprise_migration_history 
            (revision, description, migration_start, success, postgresql_version, alembic_version, environment)
            VALUES 
            ('20250817_1100_core_tables', 'Created core application tables', NOW(), true, 
             (SELECT version()), 'alembic-1.13.2', COALESCE(current_setting('app.environment', true), 'unknown'))
        """))
        print("✅ Recorded migration in history")
    except Exception as e:
        print(f"⚠️ Failed to record migration history: {e}")


def downgrade() -> None:
    """Drop core application tables."""
    
    # Drop tables in reverse order
    op.drop_table('licenses')
    op.drop_table('sessions')
    op.drop_table('artefacts')
    op.drop_table('models')
    op.drop_table('jobs')
    op.drop_table('users')
    
    # Drop enum types
    op.execute("DROP TYPE IF EXISTS artefact_type CASCADE")
    op.execute("DROP TYPE IF EXISTS model_status CASCADE")
    op.execute("DROP TYPE IF EXISTS model_type CASCADE")
    op.execute("DROP TYPE IF EXISTS job_type CASCADE")
    op.execute("DROP TYPE IF EXISTS job_status CASCADE")
    op.execute("DROP TYPE IF EXISTS user_status CASCADE")
    op.execute("DROP TYPE IF EXISTS user_role CASCADE")
    
    print("✅ Dropped all core tables successfully")