"""
Enterprise Alembic Environment Configuration for PostgreSQL 17.6
FreeCAD CNC/CAM/CAD Production Platform

This module configures Alembic for enterprise-grade database migrations with:
- PostgreSQL 17.6 specific optimizations
- Comprehensive naming conventions for constraints and indexes
- Security and audit controls
- Error handling and rollback safety
- Performance optimizations for large schemas
"""

from __future__ import annotations

import logging
import os
from logging.config import fileConfig
from typing import Any

from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import Connection
from alembic import context

# Import all model metadata for comprehensive schema detection
from app.models import Base, metadata

# All models are now in the main models package - no additional imports needed
# All Task Master ERD models are registered via app.models import above
logging.info("All Task Master ERD models loaded from main models package")

# Configure Alembic context
config = context.config


# Enterprise Security Controls
def validate_database_connection(db_url: str) -> str:
    """
    Validate and sanitize database connection string for security.

    Security Controls:
    - Prevents SQL injection in connection strings
    - Validates SSL requirements for production
    - Logs connection attempts for audit trail

    Args:
        db_url: Database connection URL

    Returns:
        Validated and sanitized connection URL

    Raises:
        RuntimeError: If URL validation fails or security requirements not met
    """
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is empty. "
            "Please configure database connection in .env file."
        )

    # Security: Ensure SSL is enabled for production environments
    if "PRODUCTION" in os.environ and "sslmode" not in db_url:
        logging.warning("Production environment detected without SSL mode specification")
        if "?" in db_url:
            db_url += "&sslmode=require"
        else:
            db_url += "?sslmode=require"

    # Security: Sanitize potential injection attempts
    dangerous_chars = [";", "--", "/*", "*/", "xp_", "sp_"]
    for char in dangerous_chars:
        if char in db_url.lower():
            raise RuntimeError(
                f"Potentially dangerous character sequence '{char}' detected in DATABASE_URL"
            )

    # Log connection attempt for audit trail (without credentials)
    sanitized_url = db_url.split("@")[1] if "@" in db_url else db_url
    logging.info(f"Validating database connection to: {sanitized_url}")

    return db_url


# Database Connection Configuration
section = config.get_section(config.config_ini_section) or {}
db_url = validate_database_connection(os.getenv("DATABASE_URL", ""))
config.set_main_option("sqlalchemy.url", db_url)

# Logging Configuration
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata with all models included
target_metadata = metadata


def get_postgresql_version(connection: Connection) -> tuple[int, int]:
    """
    Get PostgreSQL version for version-specific optimizations.

    Returns:
        Tuple of (major_version, minor_version)
    """
    try:
        result = connection.execute(text("SELECT version()"))
        version_string = result.scalar()
        # Extract version from string like "PostgreSQL 17.6 on ..."
        if version_string and "PostgreSQL" in version_string:
            version_part = version_string.split()[1]
            major, minor = map(int, version_part.split(".")[:2])
            return major, minor
        return 13, 0  # Default fallback
    except Exception as e:
        logging.warning(f"Could not determine PostgreSQL version: {e}")
        return 13, 0  # Default fallback


def configure_postgresql_session(connection: Connection) -> None:
    """
    Configure PostgreSQL session for optimal migration performance.

    Enterprise-grade PostgreSQL session optimization for large schema migrations:
    - Enhanced memory settings for complex DDL operations
    - Optimized checkpoint and WAL settings
    - Lock timeout configuration for production safety
    - Query planner optimization for migration efficiency

    Args:
        connection: Active database connection
    """
    try:
        major, minor = get_postgresql_version(connection)
        logging.info(f"Detected PostgreSQL version: {major}.{minor}")

        # Enterprise PostgreSQL optimization settings for large schema migrations
        optimization_settings = [
            # Memory optimization for large migrations
            ("SET work_mem = '256MB'", "Increase working memory for complex operations"),
            ("SET maintenance_work_mem = '1GB'", "Optimize memory for DDL operations"),
            # Lock and timeout management for production safety
            ("SET lock_timeout = '30s'", "Prevent indefinite lock waits"),
            ("SET statement_timeout = '600s'", "Set reasonable statement timeout"),
            # Query planner optimization
            ("SET random_page_cost = 1.1", "Optimize for SSD storage"),
            ("SET effective_cache_size = '2GB'", "Optimize query planning"),
            # WAL and checkpoint optimization for migration stability
            ("SET wal_buffers = '16MB'", "Optimize WAL buffer size"),
            ("SET checkpoint_completion_target = 0.9", "Spread checkpoint I/O"),
            # Connection and constraint optimization
            ("SET constraint_exclusion = 'on'", "Enable constraint exclusion"),
            ("SET default_statistics_target = 100", "Improve query planning statistics"),
        ]

        # Apply optimization settings with error handling
        for setting, description in optimization_settings:
            try:
                connection.execute(text(setting))
                logging.debug(f"Applied: {setting} - {description}")
            except Exception as setting_error:
                logging.warning(f"Could not apply setting '{setting}': {setting_error}")

        # Version-specific optimizations
        if major >= 14:
            try:
                connection.execute(text("SET enable_incremental_sort = on"))
                logging.debug("Applied PostgreSQL 14+ incremental sort optimization")
            except Exception as version_error:
                logging.warning(f"Could not apply version-specific optimization: {version_error}")

        if major >= 15:
            try:
                connection.execute(text("SET enable_memoize = on"))
                logging.debug("Applied PostgreSQL 15+ memoization optimization")
            except Exception as version_error:
                logging.warning(f"Could not apply PostgreSQL 15+ optimization: {version_error}")

        logging.info("Enterprise PostgreSQL session optimizations applied successfully")

    except Exception as e:
        logging.warning(f"Could not configure PostgreSQL session optimizations: {e}")
        logging.info("Continuing with default PostgreSQL settings")


def include_object(object, name, type_, reflected, compare_to):
    """
    Filter objects for migration generation.

    Exclude temporary objects and system tables from migrations.
    """
    # Exclude temporary objects
    if type_ == "table" and name.startswith("temp_"):
        return False

    # Exclude PostgreSQL system objects
    if name.startswith("pg_"):
        return False

    # Exclude Alembic version table
    if name == "alembic_version":
        return False

    return True


def render_item(type_, obj, autogen_context):
    """
    Render migration items with enterprise formatting and documentation.
    """
    # Add documentation comments for major schema changes
    if type_ == "table":
        return f"# Creating table: {obj.name}\n    " + repr(obj)

    return repr(obj)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode for SQL script generation.

    This configures the context with URL only and not an Engine,
    though an Engine is also acceptable here. By skipping the Engine creation
    we don't even need a database available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        render_item=render_item,
        # PostgreSQL-specific dialect options
        dialect_opts={
            "paramstyle": "named",
            "postgresql_insert_on_duplicate": True,
        },
    )

    with context.begin_transaction():
        logging.info("Running migration in offline mode")
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode with live database connection.

    In this scenario we need to create an Engine and associate a connection
    with the context. This is the standard way to run migrations.

    Includes enterprise-grade error handling, performance optimization,
    and security controls.
    """
    # Create engine with PostgreSQL-specific optimizations
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # PostgreSQL-specific engine options
        pool_pre_ping=True,  # Validate connections before use
        pool_recycle=3600,  # Recycle connections every hour
        echo=False,  # Set to True for SQL debugging
        future=True,  # Use SQLAlchemy 2.0 style
    )

    try:
        with connectable.connect() as connection:
            # Configure PostgreSQL session for optimal performance
            configure_postgresql_session(connection)

            # Configure Alembic context with simplified settings for debugging
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
                include_object=include_object,
                render_item=render_item,
                # Simplified PostgreSQL configuration for debugging
                transaction_per_migration=False,  # Use single transaction
                transactional_ddl=True,  # PostgreSQL supports DDL in transactions
                # Version table configuration
                version_table_schema=None,  # Use default schema
            )

            # Execute migrations with detailed debugging
            logging.info("Starting online migration execution")
            logging.info(f"Connection info: {connection.info}")

            # Test direct DDL execution before migration
            try:
                logging.info("Testing direct DDL execution...")
                connection.execute(text("CREATE TABLE alembic_test (id SERIAL PRIMARY KEY)"))
                connection.commit()
                logging.info("Direct DDL test successful")
                connection.execute(text("DROP TABLE alembic_test"))
                connection.commit()
                logging.info("Table cleanup successful")
            except Exception as e:
                logging.error(f"Direct DDL test failed: {e}")

            with context.begin_transaction():
                logging.info("Inside transaction - starting migrations")
                context.run_migrations()
                logging.info("Inside transaction - migration execution completed")
                # Note: context.begin_transaction() handles commit automatically
                # Removing redundant connection.commit() to prevent nested transaction issues
                logging.info("Transaction will be committed automatically by context manager")

    except Exception as e:
        logging.error(f"Migration failed with error: {e}")
        raise RuntimeError(f"Database migration failed: {e}") from e
    finally:
        # Ensure connection cleanup
        try:
            connectable.dispose()
        except Exception as e:
            logging.warning(f"Error during connection cleanup: {e}")


# Main execution logic
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
