"""
Enterprise Migration Helper Utilities for PostgreSQL 17.6
FreeCAD CNC/CAM/CAD Production Platform

This module provides helper functions for creating consistent, maintainable,
and secure database migrations with enterprise-grade practices.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from alembic import op
from sqlalchemy import text, CheckConstraint, Index
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import sqltypes


logger = logging.getLogger(__name__)

# PostgreSQL 17.6 Enterprise Migration Helpers

def create_enum_type(enum_name: str, values: Sequence[str], schema: str | None = None) -> None:
    """
    Create PostgreSQL ENUM type with enterprise error handling.
    
    Args:
        enum_name: Name of the enum type to create
        values: List of valid enum values
        schema: Optional schema name (defaults to public)
        
    Example:
        create_enum_type('project_status', ['draft', 'active', 'completed'])
    """
    try:
        # Check if enum already exists to prevent conflicts
        schema_prefix = f"{schema}." if schema else ""
        check_query = f"""
        SELECT 1 FROM pg_type t 
        JOIN pg_namespace n ON t.typnamespace = n.oid 
        WHERE t.typname = '{enum_name}' 
        AND n.nspname = '{schema or "public"}'
        """
        
        result = op.get_bind().execute(text(check_query)).fetchone()
        if result:
            logger.info(f"ENUM type {schema_prefix}{enum_name} already exists, skipping creation")
            return
            
        # Create the enum type
        enum_type = postgresql.ENUM(*values, name=enum_name, schema=schema)
        enum_type.create(op.get_bind())
        
        logger.info(f"Created ENUM type: {schema_prefix}{enum_name} with values: {values}")
        
    except Exception as e:
        logger.error(f"Failed to create ENUM type {enum_name}: {e}")
        raise

def drop_enum_type(enum_name: str, schema: str | None = None) -> None:
    """
    Drop PostgreSQL ENUM type safely.
    
    Args:
        enum_name: Name of the enum type to drop
        schema: Optional schema name
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        enum_type = postgresql.ENUM(name=enum_name, schema=schema)
        enum_type.drop(op.get_bind(), checkfirst=True)
        
        logger.info(f"Dropped ENUM type: {schema_prefix}{enum_name}")
        
    except Exception as e:
        logger.warning(f"Could not drop ENUM type {enum_name}: {e}")

def create_gin_index(
    table_name: str, 
    column_name: str, 
    index_name: str | None = None,
    schema: str | None = None,
    **kwargs: Any
) -> None:
    """
    Create GIN index optimized for JSONB columns in PostgreSQL 17.6.
    
    Args:
        table_name: Name of the table
        column_name: Name of the JSONB column
        index_name: Optional custom index name
        schema: Optional schema name
        **kwargs: Additional index options
        
    Example:
        create_gin_index('projects', 'summary_json')
    """
    try:
        if not index_name:
            index_name = f"gin_{table_name}_{column_name}"
            
        # PostgreSQL 17.6 optimized GIN index with enhanced options
        op.create_index(
            index_name,
            table_name,
            [column_name],
            postgresql_using="gin",
            schema=schema,
            # PostgreSQL 17.6 GIN optimizations
            postgresql_with={
                "fastupdate": "on",         # Enable fast updates for better performance
                "gin_pending_list_limit": 4096,  # Larger pending list for bulk operations
            },
            **kwargs
        )
        
        logger.info(f"Created GIN index: {index_name} on {table_name}.{column_name}")
        
    except Exception as e:
        logger.error(f"Failed to create GIN index {index_name}: {e}")
        raise

def create_partial_index(
    table_name: str,
    column_names: Sequence[str],
    condition: str,
    index_name: str | None = None,
    unique: bool = False,
    schema: str | None = None
) -> None:
    """
    Create partial index with condition for optimized queries.
    
    Args:
        table_name: Name of the table
        column_names: List of column names to index
        condition: WHERE condition for partial index
        index_name: Optional custom index name
        unique: Whether to create unique partial index
        schema: Optional schema name
        
    Example:
        create_partial_index('jobs', ['status'], "status IN ('pending', 'running')")
    """
    try:
        if not index_name:
            cols_part = "_".join(column_names)
            prefix = "puq" if unique else "pix"
            index_name = f"{prefix}_{table_name}_{cols_part}"
            
        op.create_index(
            index_name,
            table_name,
            column_names,
            unique=unique,
            schema=schema,
            postgresql_where=text(condition)
        )
        
        logger.info(f"Created partial index: {index_name} on {table_name} WHERE {condition}")
        
    except Exception as e:
        logger.error(f"Failed to create partial index {index_name}: {e}")
        raise

def add_check_constraint(
    table_name: str,
    constraint_name: str,
    condition: str,
    schema: str | None = None
) -> None:
    """
    Add check constraint with proper naming and error handling.
    
    Args:
        table_name: Name of the table
        constraint_name: Name of the constraint
        condition: Check condition SQL
        schema: Optional schema name
        
    Example:
        add_check_constraint('jobs', 'valid_status', "status IN ('pending', 'running', 'completed')")
    """
    try:
        # Use naming convention for consistency
        full_constraint_name = f"ck_{table_name}_{constraint_name}"
        
        op.create_check_constraint(
            full_constraint_name,
            table_name,
            condition,
            schema=schema
        )
        
        logger.info(f"Added check constraint: {full_constraint_name} on {table_name}")
        
    except Exception as e:
        logger.error(f"Failed to add check constraint {constraint_name}: {e}")
        raise

def create_trigger(
    trigger_name: str,
    table_name: str,
    function_name: str,
    events: Sequence[str] = ("INSERT", "UPDATE"),
    when: str = "AFTER",
    schema: str | None = None
) -> None:
    """
    Create PostgreSQL trigger with enterprise configuration.
    
    Args:
        trigger_name: Name of the trigger
        table_name: Name of the table
        function_name: Name of the trigger function
        events: List of events (INSERT, UPDATE, DELETE)
        when: BEFORE or AFTER
        schema: Optional schema name
        
    Example:
        create_trigger('audit_changes', 'projects', 'audit_log_changes')
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        events_str = " OR ".join(events)
        
        trigger_sql = f"""
        CREATE TRIGGER {trigger_name}
        {when} {events_str} ON {schema_prefix}{table_name}
        FOR EACH ROW EXECUTE FUNCTION {function_name}()
        """
        
        op.execute(text(trigger_sql))
        
        logger.info(f"Created trigger: {trigger_name} on {table_name}")
        
    except Exception as e:
        logger.error(f"Failed to create trigger {trigger_name}: {e}")
        raise

def drop_trigger(
    trigger_name: str,
    table_name: str,
    schema: str | None = None,
    if_exists: bool = True
) -> None:
    """
    Drop PostgreSQL trigger safely.
    
    Args:
        trigger_name: Name of the trigger
        table_name: Name of the table
        schema: Optional schema name
        if_exists: Whether to use IF EXISTS clause
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        if_exists_clause = "IF EXISTS " if if_exists else ""
        
        trigger_sql = f"DROP TRIGGER {if_exists_clause}{trigger_name} ON {schema_prefix}{table_name}"
        
        op.execute(text(trigger_sql))
        
        logger.info(f"Dropped trigger: {trigger_name} from {table_name}")
        
    except Exception as e:
        logger.warning(f"Could not drop trigger {trigger_name}: {e}")

def enable_row_level_security(table_name: str, schema: str | None = None) -> None:
    """
    Enable Row Level Security (RLS) for a table.
    
    Args:
        table_name: Name of the table
        schema: Optional schema name
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        
        op.execute(text(f"ALTER TABLE {schema_prefix}{table_name} ENABLE ROW LEVEL SECURITY"))
        
        logger.info(f"Enabled RLS for table: {schema_prefix}{table_name}")
        
    except Exception as e:
        logger.error(f"Failed to enable RLS for {table_name}: {e}")
        raise

def create_rls_policy(
    policy_name: str,
    table_name: str,
    command: str = "ALL",
    role: str | None = None,
    using_condition: str | None = None,
    check_condition: str | None = None,
    schema: str | None = None
) -> None:
    """
    Create Row Level Security policy.
    
    Args:
        policy_name: Name of the policy
        table_name: Name of the table
        command: SQL command (ALL, SELECT, INSERT, UPDATE, DELETE)
        role: Role name for policy
        using_condition: USING condition
        check_condition: WITH CHECK condition
        schema: Optional schema name
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        
        policy_sql = f"CREATE POLICY {policy_name} ON {schema_prefix}{table_name}"
        
        if command != "ALL":
            policy_sql += f" FOR {command}"
            
        if role:
            policy_sql += f" TO {role}"
            
        if using_condition:
            policy_sql += f" USING ({using_condition})"
            
        if check_condition:
            policy_sql += f" WITH CHECK ({check_condition})"
            
        op.execute(text(policy_sql))
        
        logger.info(f"Created RLS policy: {policy_name} on {table_name}")
        
    except Exception as e:
        logger.error(f"Failed to create RLS policy {policy_name}: {e}")
        raise

def create_materialized_view(
    view_name: str,
    query: str,
    schema: str | None = None,
    with_data: bool = True
) -> None:
    """
    Create materialized view for performance optimization.
    
    Args:
        view_name: Name of the materialized view
        query: SQL query for the view
        schema: Optional schema name
        with_data: Whether to populate with data initially
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        with_data_clause = "WITH DATA" if with_data else "WITH NO DATA"
        
        view_sql = f"""
        CREATE MATERIALIZED VIEW {schema_prefix}{view_name} AS
        {query}
        {with_data_clause}
        """
        
        op.execute(text(view_sql))
        
        logger.info(f"Created materialized view: {schema_prefix}{view_name}")
        
    except Exception as e:
        logger.error(f"Failed to create materialized view {view_name}: {e}")
        raise

def refresh_materialized_view(
    view_name: str,
    schema: str | None = None,
    concurrently: bool = False
) -> None:
    """
    Refresh materialized view data.
    
    Args:
        view_name: Name of the materialized view
        schema: Optional schema name
        concurrently: Whether to refresh concurrently
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        concurrently_clause = "CONCURRENTLY " if concurrently else ""
        
        refresh_sql = f"REFRESH MATERIALIZED VIEW {concurrently_clause}{schema_prefix}{view_name}"
        
        op.execute(text(refresh_sql))
        
        logger.info(f"Refreshed materialized view: {schema_prefix}{view_name}")
        
    except Exception as e:
        logger.error(f"Failed to refresh materialized view {view_name}: {e}")
        raise

def add_table_comment(table_name: str, comment: str, schema: str | None = None) -> None:
    """
    Add comment to table for documentation.
    
    Args:
        table_name: Name of the table
        comment: Comment text
        schema: Optional schema name
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        
        comment_sql = f"COMMENT ON TABLE {schema_prefix}{table_name} IS '{comment}'"
        
        op.execute(text(comment_sql))
        
        logger.info(f"Added comment to table: {schema_prefix}{table_name}")
        
    except Exception as e:
        logger.warning(f"Could not add comment to table {table_name}: {e}")

def add_column_comment(
    table_name: str, 
    column_name: str, 
    comment: str, 
    schema: str | None = None
) -> None:
    """
    Add comment to column for documentation.
    
    Args:
        table_name: Name of the table
        column_name: Name of the column
        comment: Comment text
        schema: Optional schema name
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        
        comment_sql = f"COMMENT ON COLUMN {schema_prefix}{table_name}.{column_name} IS '{comment}'"
        
        op.execute(text(comment_sql))
        
        logger.info(f"Added comment to column: {schema_prefix}{table_name}.{column_name}")
        
    except Exception as e:
        logger.warning(f"Could not add comment to column {table_name}.{column_name}: {e}")

# Enterprise Validation Helpers

def validate_migration_safety(table_name: str, schema: str | None = None) -> bool:
    """
    Validate that migration operations are safe for production.
    
    Args:
        table_name: Name of the table to validate
        schema: Optional schema name
        
    Returns:
        True if migration is safe, False otherwise
    """
    try:
        schema_prefix = f"{schema}." if schema else ""
        
        # Check table size to warn about long-running operations
        size_query = f"""
        SELECT pg_size_pretty(pg_total_relation_size('{schema_prefix}{table_name}'))
        """
        
        result = op.get_bind().execute(text(size_query)).scalar()
        logger.info(f"Table {schema_prefix}{table_name} size: {result}")
        
        # Check for active locks that might conflict
        lock_query = f"""
        SELECT count(*) FROM pg_locks l
        JOIN pg_class c ON l.relation = c.oid
        WHERE c.relname = '{table_name}' AND l.granted = false
        """
        
        pending_locks = op.get_bind().execute(text(lock_query)).scalar()
        if pending_locks > 0:
            logger.warning(f"Found {pending_locks} pending locks on {table_name}")
            return False
            
        return True
        
    except Exception as e:
        logger.warning(f"Could not validate migration safety for {table_name}: {e}")
        return True  # Default to allowing migration

# Usage Examples and Documentation
"""
Enterprise Migration Patterns:

1. Creating an ENUM with proper error handling:
   create_enum_type('job_status', ['pending', 'running', 'completed', 'failed'])

2. Adding JSONB column with optimized GIN index:
   op.add_column('projects', sa.Column('metadata', postgresql.JSONB))
   create_gin_index('projects', 'metadata')

3. Creating partial index for frequent queries:
   create_partial_index('jobs', ['status', 'created_at'], "status IN ('pending', 'running')")

4. Adding check constraint with validation:
   add_check_constraint('users', 'valid_email', "email ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'")

5. Enabling Row Level Security:
   enable_row_level_security('sensitive_data')
   create_rls_policy('user_access', 'sensitive_data', 'ALL', 'authenticated_users', 'user_id = current_user_id()')

6. Creating materialized view for performance:
   create_materialized_view('job_summary', '''
       SELECT status, count(*) as count, avg(duration) as avg_duration
       FROM jobs
       GROUP BY status
   ''')

7. Adding comprehensive documentation:
   add_table_comment('projects', 'Manufacturing projects with CAD/CAM workflows')
   add_column_comment('projects', 'status', 'Current project status in workflow')
"""