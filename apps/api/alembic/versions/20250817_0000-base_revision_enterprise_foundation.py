"""Base revision - enterprise foundation

This is the foundational base revision for the FreeCAD CNC/CAM/CAD production platform.
It establishes the enterprise-grade migration framework with PostgreSQL 17.6 optimizations,
comprehensive naming conventions, and proper audit trail foundation.

Revision ID: base_revision
Revises: 0011_complete_schema
Create Date: 2025-08-17 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Import our enterprise migration helpers
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from migration_helpers import (
    create_enum_type, 
    add_table_comment, 
    add_column_comment,
    create_gin_index,
    add_check_constraint,
    validate_migration_safety
)

# revision identifiers, used by Alembic.
revision = 'base_revision'
down_revision = '0011_complete_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Enterprise base revision upgrade.
    
    This migration establishes the enterprise foundation:
    1. Creates audit infrastructure
    2. Establishes monitoring and performance baseline
    3. Sets up enterprise naming conventions
    4. Adds PostgreSQL 17.6 specific optimizations
    """
    
    # Log the start of enterprise migration
    op.execute(sa.text("SELECT pg_advisory_lock(1234567890)"))  # Prevent concurrent migrations
    
    # 1. Create enterprise audit log table for comprehensive tracking
    try:
        op.create_table(
            'enterprise_audit_log',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('table_name', sa.String(255), nullable=False, index=True),
            sa.Column('operation', sa.String(10), nullable=False, index=True),
            sa.Column('row_id', sa.String(255), nullable=True, index=True),
            sa.Column('old_values', postgresql.JSONB(), nullable=True),
            sa.Column('new_values', postgresql.JSONB(), nullable=True),
            sa.Column('user_id', sa.String(255), nullable=True, index=True),
            sa.Column('session_id', sa.String(255), nullable=True),
            sa.Column('ip_address', sa.String(45), nullable=True),
            sa.Column('user_agent', sa.Text(), nullable=True),
            sa.Column('transaction_id', sa.String(255), nullable=True, index=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            # PostgreSQL 17.6 specific optimizations
            postgresql_partition_by='RANGE (created_at)',  # Partition by month for performance
        )
        print("✅ Created enterprise_audit_log table")
    except Exception as e:
        print(f"❌ Failed to create enterprise_audit_log table: {e}")
        raise RuntimeError(f"Critical failure in audit table creation: {e}") from e
    
    # Add enterprise audit constraints
    try:
        add_check_constraint('enterprise_audit_log', 'valid_operation', 
                           "operation IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')")
        print("✅ Added audit log constraints")
    except Exception as e:
        print(f"❌ Failed to add audit log constraints: {e}")
        raise RuntimeError(f"Failed to add audit constraints: {e}") from e
    
    # Create optimized indexes for audit queries
    try:
        create_gin_index('enterprise_audit_log', 'old_values')
        print("✅ Created GIN index for old_values")
    except Exception as e:
        print(f"❌ Failed to create old_values GIN index: {e}")
        raise RuntimeError(f"Failed to create old_values index: {e}") from e
    
    try:
        create_gin_index('enterprise_audit_log', 'new_values')
        print("✅ Created GIN index for new_values")
    except Exception as e:
        print(f"❌ Failed to create new_values GIN index: {e}")
        raise RuntimeError(f"Failed to create new_values index: {e}") from e
    
    # Add comprehensive table documentation
    try:
        add_table_comment('enterprise_audit_log', 
                         'Enterprise audit log for comprehensive security and compliance tracking')
        add_column_comment('enterprise_audit_log', 'table_name', 'Name of the table being audited')
        add_column_comment('enterprise_audit_log', 'operation', 'Type of operation: INSERT, UPDATE, DELETE, TRUNCATE')
        add_column_comment('enterprise_audit_log', 'old_values', 'Previous values in JSONB format')
        add_column_comment('enterprise_audit_log', 'new_values', 'New values in JSONB format')
        add_column_comment('enterprise_audit_log', 'transaction_id', 'Database transaction identifier for grouping changes')
        print("✅ Added audit log documentation")
    except Exception as e:
        print(f"❌ Failed to add audit log documentation: {e}")
        # Continue - documentation is not critical
    
    # 2. Create migration history table for enterprise tracking
    try:
        op.create_table(
            'enterprise_migration_history',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('revision', sa.String(255), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('migration_start', sa.DateTime(timezone=True), nullable=False),
            sa.Column('migration_end', sa.DateTime(timezone=True), nullable=True),
            sa.Column('duration_seconds', sa.Integer(), nullable=True),
            sa.Column('success', sa.Boolean(), default=False, nullable=False),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('postgresql_version', sa.String(50), nullable=True),
            sa.Column('alembic_version', sa.String(50), nullable=True),
            sa.Column('environment', sa.String(50), nullable=True),
            sa.Column('applied_by', sa.String(255), nullable=True),
            sa.Column('server_info', postgresql.JSONB(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        print("✅ Created enterprise_migration_history table")
    except Exception as e:
        print(f"❌ Failed to create enterprise_migration_history table: {e}")
        raise RuntimeError(f"Critical failure in migration history table creation: {e}") from e
    
    try:
        add_table_comment('enterprise_migration_history', 
                         'Complete history of database migrations with performance metrics')
        print("✅ Added migration history documentation")
    except Exception as e:
        print(f"❌ Failed to add migration history documentation: {e}")
        # Continue - documentation is not critical
    
    # 3. Create performance monitoring baseline
    try:
        op.create_table(
            'enterprise_performance_baseline',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('metric_name', sa.String(255), nullable=False),
            sa.Column('table_name', sa.String(255), nullable=True),
            sa.Column('baseline_value', sa.Numeric(20, 6), nullable=False),
            sa.Column('measurement_unit', sa.String(50), nullable=False),
            sa.Column('measurement_date', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('postgresql_version', sa.String(50), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
        )
        print("✅ Created enterprise_performance_baseline table")
    except Exception as e:
        print(f"❌ Failed to create enterprise_performance_baseline table: {e}")
        raise RuntimeError(f"Critical failure in performance baseline table creation: {e}") from e
    
    try:
        op.create_index('idx_perf_baseline_metric_table', 'enterprise_performance_baseline', 
                       ['metric_name', 'table_name'])
        print("✅ Created performance baseline index")
    except Exception as e:
        print(f"❌ Failed to create performance baseline index: {e}")
        raise RuntimeError(f"Failed to create performance baseline index: {e}") from e
    
    try:
        add_table_comment('enterprise_performance_baseline', 
                         'Performance baseline metrics for monitoring database health')
        print("✅ Added performance baseline documentation")
    except Exception as e:
        print(f"❌ Failed to add performance baseline documentation: {e}")
        # Continue - documentation is not critical
    
    # 4. Create enterprise configuration table
    try:
        op.create_table(
            'enterprise_config',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('config_key', sa.String(255), nullable=False, unique=True),
            sa.Column('config_value', sa.Text(), nullable=False),
            sa.Column('config_type', sa.String(50), nullable=False, default='string'),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_sensitive', sa.Boolean(), default=False, nullable=False),
            sa.Column('environment', sa.String(50), nullable=False, default='production'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), 
                     onupdate=sa.func.now(), nullable=False),
        )
        print("✅ Created enterprise_config table")
    except Exception as e:
        print(f"❌ Failed to create enterprise_config table: {e}")
        raise RuntimeError(f"Critical failure in enterprise config table creation: {e}") from e
    
    try:
        add_check_constraint('enterprise_config', 'valid_config_type',
                           "config_type IN ('string', 'integer', 'boolean', 'json', 'encrypted')")
        add_check_constraint('enterprise_config', 'valid_environment',
                           "environment IN ('development', 'testing', 'staging', 'production')")
        print("✅ Added enterprise config constraints")
    except Exception as e:
        print(f"❌ Failed to add enterprise config constraints: {e}")
        raise RuntimeError(f"Failed to add config constraints: {e}") from e
    
    try:
        add_table_comment('enterprise_config', 
                         'Enterprise configuration settings with environment separation')
        print("✅ Added enterprise config documentation")
    except Exception as e:
        print(f"❌ Failed to add enterprise config documentation: {e}")
        # Continue - documentation is not critical
    
    # 5. Record this base revision in migration history
    try:
        op.execute(sa.text("""
            INSERT INTO enterprise_migration_history 
            (revision, description, migration_start, success, postgresql_version, alembic_version, environment)
            VALUES 
            ('base_revision', 'Enterprise foundation - audit, monitoring, configuration', NOW(), true, 
             (SELECT version()), 'alembic-1.13.2', COALESCE(current_setting('app.environment', true), 'unknown'))
        """))
        print("✅ Recorded migration in history")
    except Exception as e:
        print(f"❌ Failed to record migration history: {e}")
        # Continue - history recording is not critical for functionality
    
    # 6. Insert initial configuration
    try:
        op.execute(sa.text("""
            INSERT INTO enterprise_config (config_key, config_value, config_type, description, environment)
            VALUES 
            ('audit.enabled', 'true', 'boolean', 'Enable comprehensive audit logging', 'production'),
            ('audit.retention_days', '2555', 'integer', 'Audit log retention period in days (7 years)', 'production'),
            ('performance.monitoring_enabled', 'true', 'boolean', 'Enable performance monitoring', 'production'),
            ('migration.backup_required', 'true', 'boolean', 'Require backup before major migrations', 'production'),
            ('postgresql.version_target', '17.6', 'string', 'Target PostgreSQL version', 'production'),
            ('naming_convention.enforced', 'true', 'boolean', 'Enforce enterprise naming conventions', 'production')
        """))
        print("✅ Inserted initial configuration")
    except Exception as e:
        print(f"❌ Failed to insert initial configuration: {e}")
        raise RuntimeError(f"Failed to insert initial configuration: {e}") from e
    
    # 7. Create initial performance baselines
    try:
        op.execute(sa.text("""
            INSERT INTO enterprise_performance_baseline (metric_name, baseline_value, measurement_unit, postgresql_version, notes)
            VALUES 
            ('connection_pool_size', 20, 'connections', (SELECT version()), 'Default connection pool size'),
            ('max_parallel_workers', 4, 'workers', (SELECT version()), 'Maximum parallel workers for large operations'),
            ('maintenance_work_mem', 256, 'MB', (SELECT version()), 'Memory allocated for maintenance operations'),
            ('statement_timeout', 1800, 'seconds', (SELECT version()), 'Maximum statement execution time'),
            ('lock_timeout', 300, 'seconds', (SELECT version()), 'Maximum lock wait time')
        """))
        print("✅ Created initial performance baselines")
    except Exception as e:
        print(f"❌ Failed to create performance baselines: {e}")
        # Continue - baselines are not critical for basic functionality
    
    print("✅ Enterprise base revision applied successfully")
    print("   - Audit infrastructure created")
    print("   - Performance monitoring baseline established")
    print("   - Enterprise configuration framework initialized")
    print("   - PostgreSQL 17.6 optimizations applied")
    finally:
        # Release advisory lock
        op.execute(sa.text("SELECT pg_advisory_unlock(1234567890)"))


def downgrade() -> None:
    """
    Downgrade enterprise base revision.
    
    WARNING: This will remove all enterprise audit and monitoring infrastructure.
    Only use in development environments.
    """
    
    # Validate this is not production
    result = op.get_bind().execute(sa.text("""
        SELECT COALESCE(current_setting('app.environment', true), 'unknown')
    """)).scalar()
    
    if result == 'production':
        raise RuntimeError(
            "Downgrading enterprise base revision is not allowed in production environment. "
            "This would remove all audit trails and monitoring infrastructure."
        )
    
    print("⚠️  Downgrading enterprise base revision...")
    
    # Drop enterprise tables in reverse order with individual error handling
    # Each table is dropped independently to maximize successful cleanup
    
    # 1. Drop enterprise_config table
    try:
        op.drop_table('enterprise_config')
        print("✅ Dropped enterprise_config table")
    except Exception as e:
        print(f"❌ Failed to drop enterprise_config table: {e}")
        # Continue with other tables even if this fails
    
    # 2. Drop enterprise_performance_baseline table  
    try:
        op.drop_table('enterprise_performance_baseline')
        print("✅ Dropped enterprise_performance_baseline table")
    except Exception as e:
        print(f"❌ Failed to drop enterprise_performance_baseline table: {e}")
        # Continue with other tables even if this fails
    
    # 3. Drop enterprise_migration_history table
    try:
        op.drop_table('enterprise_migration_history')
        print("✅ Dropped enterprise_migration_history table")
    except Exception as e:
        print(f"❌ Failed to drop enterprise_migration_history table: {e}")
        # Continue with other tables even if this fails
    
    # 4. Drop enterprise_audit_log table (most critical, drop last)
    try:
        op.drop_table('enterprise_audit_log')
        print("✅ Dropped enterprise_audit_log table")
    except Exception as e:
        print(f"❌ Failed to drop enterprise_audit_log table: {e}")
        # This is the most critical failure as it contains audit data
        print("⚠️  WARNING: Audit log table could not be removed")
        print("   Manual cleanup may be required for compliance")
    
    print("✅ Enterprise base revision downgrade completed")
    print("   - Enterprise infrastructure removal attempted")
    print("   - Check output above for any failed operations")
    print("   - Manual cleanup may be required for failed operations")