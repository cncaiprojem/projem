# Enterprise Migration Best Practices
## FreeCAD CNC/CAM/CAD Production Platform - PostgreSQL 17.6

This document outlines enterprise-grade best practices for database migrations using Alembic with PostgreSQL 17.6.

## Table of Contents

1. [Migration Safety Guidelines](#migration-safety-guidelines)
2. [Naming Conventions](#naming-conventions)
3. [Performance Optimization](#performance-optimization)
4. [Security and Audit](#security-and-audit)
5. [PostgreSQL 17.6 Specific Features](#postgresql-176-specific-features)
6. [Common Patterns](#common-patterns)
7. [Troubleshooting](#troubleshooting)
8. [Emergency Procedures](#emergency-procedures)

## Migration Safety Guidelines

### Pre-Migration Checklist

- [ ] **Database Backup**: Always create a full backup before major migrations
- [ ] **Lock Analysis**: Check for long-running transactions that might block migration
- [ ] **Downtime Window**: Schedule migrations during low-traffic periods
- [ ] **Rollback Plan**: Ensure downgrade functions are tested and functional
- [ ] **Resource Monitoring**: Monitor CPU, memory, and disk I/O during migration
- [ ] **Connection Limits**: Verify sufficient connection pool capacity

### Migration Validation

```python
from alembic import op
from migration_helpers import validate_migration_safety

def upgrade():
    # Always validate before major operations
    if not validate_migration_safety('target_table'):
        raise RuntimeError("Migration safety check failed")
    
    # Proceed with migration...
```

### Production Environment Controls

- **Advisory Locks**: Use PostgreSQL advisory locks to prevent concurrent migrations
- **Transaction Scope**: Keep migrations atomic within single transactions where possible
- **Timeout Settings**: Configure appropriate timeouts for long-running operations
- **Progress Monitoring**: Log progress for large data migrations

## Naming Conventions

Our enterprise naming conventions ensure consistency and maintainability:

### Tables
- Use lowercase with underscores: `user_sessions`, `audit_logs`
- Plural form for entity tables: `users`, `projects`, `tools`
- Avoid reserved words and PostgreSQL keywords

### Constraints
- **Primary Keys**: `pk_tablename` (e.g., `pk_users`)
- **Foreign Keys**: `fk_tablename_column_reftable` (e.g., `fk_projects_user_id_users`)
- **Unique Constraints**: `uq_tablename_column` (e.g., `uq_users_email`)
- **Check Constraints**: `ck_tablename_description` (e.g., `ck_users_valid_email`)

### Indexes
- **Standard Index**: `ix_tablename_column` (e.g., `ix_users_email`)
- **Composite Index**: `ix_tablename_column1_column2` (e.g., `ix_jobs_status_created_at`)
- **Partial Index**: `pix_tablename_column` (e.g., `pix_jobs_status_active`)
- **GIN Index**: `gin_tablename_column` (e.g., `gin_projects_metadata`)

### Example Migration with Proper Naming

```python
def upgrade():
    # Create table with proper naming
    op.create_table(
        'manufacturing_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id')),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('metadata', postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    
    # Add constraints with naming convention
    add_check_constraint('manufacturing_jobs', 'valid_status',
                        "status IN ('pending', 'running', 'completed', 'failed')")
    
    # Create optimized indexes
    op.create_index('ix_manufacturing_jobs_status', 'manufacturing_jobs', ['status'])
    op.create_index('ix_manufacturing_jobs_project_id', 'manufacturing_jobs', ['project_id'])
    create_gin_index('manufacturing_jobs', 'metadata')
    
    # Add partial index for active jobs
    create_partial_index('manufacturing_jobs', ['created_at'], 
                        "status IN ('pending', 'running')", 
                        'pix_manufacturing_jobs_active')
```

## Performance Optimization

### PostgreSQL 17.6 Optimizations

```python
def configure_session_for_migration(connection):
    """Configure PostgreSQL session for optimal migration performance."""
    
    # Increase memory for large operations
    connection.execute(text("SET maintenance_work_mem = '512MB'"))
    
    # Optimize checkpoint behavior
    connection.execute(text("SET checkpoint_completion_target = 0.9"))
    
    # Enable WAL compression for large migrations
    connection.execute(text("SET wal_compression = on"))
    
    # Use parallel processing for PostgreSQL 17+
    connection.execute(text("SET max_parallel_workers_per_gather = 4"))
    connection.execute(text("SET parallel_setup_cost = 100"))
```

### Large Table Migration Patterns

```python
def upgrade_large_table():
    """Pattern for migrating large tables safely."""
    
    # 1. Create new table structure
    op.create_table('users_new', ...)
    
    # 2. Copy data in batches to avoid long locks
    op.execute(text("""
        WITH batch AS (
            SELECT * FROM users 
            WHERE id BETWEEN 1 AND 10000
        )
        INSERT INTO users_new SELECT * FROM batch
    """))
    
    # 3. Repeat for all batches...
    
    # 4. Swap tables atomically
    op.execute(text("BEGIN"))
    op.execute(text("ALTER TABLE users RENAME TO users_old"))
    op.execute(text("ALTER TABLE users_new RENAME TO users"))
    op.execute(text("COMMIT"))
```

### Index Creation Strategy

```python
def create_indexes_concurrently():
    """Create indexes without blocking writes."""
    
    # Use CONCURRENTLY for production
    op.execute(text("""
        CREATE INDEX CONCURRENTLY ix_jobs_status_created_at 
        ON jobs (status, created_at)
        WHERE status IN ('pending', 'running')
    """))
```

## Security and Audit

### Audit Trail Integration

```python
def upgrade_with_audit():
    """Migration with comprehensive audit trail."""
    
    # Record migration start
    op.execute(text("""
        INSERT INTO enterprise_migration_history 
        (revision, description, migration_start, applied_by)
        VALUES ('rev_001', 'Add user preferences', NOW(), current_user)
    """))
    
    try:
        # Perform migration
        op.add_column('users', sa.Column('preferences', postgresql.JSONB()))
        
        # Record success
        op.execute(text("""
            UPDATE enterprise_migration_history 
            SET migration_end = NOW(), success = true,
                duration_seconds = EXTRACT(EPOCH FROM (NOW() - migration_start))
            WHERE revision = 'rev_001'
        """))
        
    except Exception as e:
        # Record failure
        op.execute(text(f"""
            UPDATE enterprise_migration_history 
            SET migration_end = NOW(), success = false,
                error_message = '{str(e)}'
            WHERE revision = 'rev_001'
        """))
        raise
```

### Row Level Security Integration

```python
def enable_rls_for_table():
    """Enable Row Level Security for sensitive tables."""
    
    # Enable RLS
    enable_row_level_security('sensitive_data')
    
    # Create policies
    create_rls_policy(
        'user_access_policy', 
        'sensitive_data',
        'ALL',
        'authenticated_users',
        'user_id = current_user_id()'
    )
```

## PostgreSQL 17.6 Specific Features

### Enhanced Parallel Processing

```python
def use_parallel_features():
    """Leverage PostgreSQL 17.6 parallel processing."""
    
    # Configure parallel execution
    op.execute(text("SET max_parallel_workers_per_gather = 8"))
    op.execute(text("SET parallel_tuple_cost = 0.01"))
    
    # Use parallel-aware operations
    op.execute(text("""
        CREATE INDEX CONCURRENTLY ix_large_table_computed 
        ON large_table ((expensive_function(data)))
        WITH (parallel_workers = 4)
    """))
```

### Advanced JSONB Operations

```python
def optimize_jsonb_operations():
    """Optimize JSONB operations for PostgreSQL 17.6."""
    
    # Create expression indexes for JSONB paths
    op.execute(text("""
        CREATE INDEX ix_projects_metadata_status 
        ON projects ((metadata->>'status'))
        WHERE metadata ? 'status'
    """))
    
    # Use advanced GIN options
    create_gin_index('projects', 'metadata', postgresql_with={
        'fastupdate': 'on',
        'gin_pending_list_limit': 4096
    })
```

## Common Patterns

### ENUM Type Management

```python
def upgrade_enum():
    """Safely add values to existing ENUM."""
    
    # PostgreSQL 17.6 allows adding enum values in transactions
    op.execute(text("""
        ALTER TYPE job_status_enum 
        ADD VALUE IF NOT EXISTS 'paused' 
        AFTER 'running'
    """))
```

### Materialized View Management

```python
def create_performance_view():
    """Create materialized view for performance."""
    
    create_materialized_view('job_summary_mv', """
        SELECT 
            status,
            count(*) as job_count,
            avg(duration_minutes) as avg_duration,
            max(created_at) as last_job
        FROM jobs 
        WHERE created_at >= NOW() - INTERVAL '30 days'
        GROUP BY status
    """)
    
    # Create refresh schedule
    op.execute(text("""
        CREATE OR REPLACE FUNCTION refresh_job_summary()
        RETURNS void AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY job_summary_mv;
        END;
        $$ LANGUAGE plpgsql
    """))
```

## Troubleshooting

### Common Issues

1. **Lock Timeouts**
   ```sql
   -- Check for blocking queries
   SELECT pid, query, state, waiting 
   FROM pg_stat_activity 
   WHERE state != 'idle';
   ```

2. **Memory Issues**
   ```sql
   -- Monitor memory usage
   SELECT * FROM pg_stat_database 
   WHERE datname = current_database();
   ```

3. **Performance Problems**
   ```sql
   -- Check slow queries during migration
   SELECT query, mean_exec_time, calls
   FROM pg_stat_statements 
   ORDER BY mean_exec_time DESC 
   LIMIT 10;
   ```

### Diagnostic Queries

```sql
-- Check migration progress
SELECT schemaname, tablename, n_tup_ins, n_tup_upd, n_tup_del
FROM pg_stat_user_tables 
WHERE schemaname = 'public'
ORDER BY n_tup_ins + n_tup_upd + n_tup_del DESC;

-- Monitor index usage
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes 
WHERE idx_scan = 0;
```

## Emergency Procedures

### Rollback Procedures

1. **Immediate Rollback**
   ```bash
   # Emergency rollback to previous version
   alembic downgrade -1
   ```

2. **Point-in-Time Recovery**
   ```bash
   # Restore from backup if migration corrupted data
   pg_restore -d database_name backup_file
   ```

3. **Partial Rollback**
   ```python
   def emergency_cleanup():
       """Emergency cleanup for failed migration."""
       try:
           op.drop_table('partially_created_table')
           op.execute(text("ROLLBACK TO SAVEPOINT migration_start"))
       except:
           pass  # Best effort cleanup
   ```

### Monitoring and Alerts

```python
def setup_migration_monitoring():
    """Set up monitoring for migration operations."""
    
    # Log migration metrics
    op.execute(text("""
        INSERT INTO enterprise_performance_baseline 
        (metric_name, baseline_value, measurement_unit, notes)
        VALUES 
        ('migration_duration_seconds', %s, 'seconds', 'Current migration duration'),
        ('tables_affected', %s, 'count', 'Number of tables modified'),
        ('rows_migrated', %s, 'count', 'Total rows affected')
    """), [duration, table_count, row_count])
```

## Best Practices Summary

1. **Always backup before major migrations**
2. **Use advisory locks to prevent concurrent migrations**
3. **Follow enterprise naming conventions consistently**
4. **Monitor performance and resource usage**
5. **Implement comprehensive audit trails**
6. **Test rollback procedures thoroughly**
7. **Use PostgreSQL 17.6 features for optimal performance**
8. **Document all migration decisions and rationale**
9. **Validate data integrity after migrations**
10. **Plan for zero-downtime deployments where possible**

## Contact and Support

For migration issues or questions:
- Database Team: db-team@company.com
- On-call DBA: +1-555-DB-ADMIN
- Escalation: CTO office

Remember: When in doubt, prioritize data safety over migration speed.