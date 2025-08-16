"""
Database query logging with SQLAlchemy integration.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import Pool

from .logging import get_logger, log_database_query


logger = get_logger(__name__)


def setup_database_logging(engine: Engine, log_queries: bool = True, slow_query_threshold_ms: int = 1000) -> None:
    """
    Set up database logging for SQLAlchemy engine.
    
    Args:
        engine: SQLAlchemy engine
        log_queries: Whether to log all queries (can be noisy in production)
        slow_query_threshold_ms: Threshold for slow query warnings
    """
    
    # Track query execution time
    query_start_times: Dict[Any, float] = {}
    
    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """Log before query execution."""
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())
        
        if log_queries:
            logger.debug(
                "database_query_start",
                query=statement[:500],  # Truncate long queries
                params_count=len(parameters) if parameters else 0,
                executemany=executemany,
            )
    
    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """Log after query execution."""
        total_time = None
        if hasattr(conn.info, "query_start_time") and conn.info["query_start_time"]:
            start_time = conn.info["query_start_time"].pop(-1)
            total_time = int((time.perf_counter() - start_time) * 1000)
        
        # Log the query with timing
        if log_queries or (total_time and total_time > slow_query_threshold_ms):
            log_database_query(
                query=statement,
                params=parameters if len(str(parameters)) < 1000 else None,  # Don't log huge param lists
                duration_ms=total_time,
            )
    
    @event.listens_for(engine, "handle_error")
    def handle_error(exception_context):
        """Log database errors."""
        logger.error(
            "database_error",
            error=str(exception_context.original_exception),
            error_type=type(exception_context.original_exception).__name__,
            statement=exception_context.statement[:500] if exception_context.statement else None,
            params=exception_context.parameters if exception_context.parameters and len(str(exception_context.parameters)) < 1000 else None,
            exc_info=True,
        )
    
    # Connection pool events
    @event.listens_for(Pool, "connect")
    def pool_connect(dbapi_conn, connection_record):
        """Log new database connection."""
        logger.info(
            "database_connection_created",
            connection_id=id(dbapi_conn),
        )
    
    @event.listens_for(Pool, "checkout")
    def pool_checkout(dbapi_conn, connection_record, connection_proxy):
        """Log connection checkout from pool."""
        logger.debug(
            "database_connection_checkout",
            connection_id=id(dbapi_conn),
            pool_size=connection_proxy._pool.size() if hasattr(connection_proxy, "_pool") else None,
        )
    
    @event.listens_for(Pool, "checkin")
    def pool_checkin(dbapi_conn, connection_record):
        """Log connection checkin to pool."""
        logger.debug(
            "database_connection_checkin",
            connection_id=id(dbapi_conn),
        )
    
    @event.listens_for(Pool, "reset")
    def pool_reset(dbapi_conn, connection_record):
        """Log connection reset."""
        logger.debug(
            "database_connection_reset",
            connection_id=id(dbapi_conn),
        )
    
    @event.listens_for(Pool, "invalidate")
    def pool_invalidate(dbapi_conn, connection_record, exception):
        """Log connection invalidation."""
        logger.warning(
            "database_connection_invalidated",
            connection_id=id(dbapi_conn),
            error=str(exception) if exception else None,
        )


class QueryLogger:
    """
    Context manager for logging specific database operations.
    
    Usage:
        with QueryLogger("user_fetch") as qlog:
            users = session.query(User).all()
            qlog.log_info(user_count=len(users))
    """
    
    def __init__(self, operation_name: str, **context: Any):
        """
        Initialize query logger.
        
        Args:
            operation_name: Name of the database operation
            **context: Additional context to log
        """
        self.operation_name = operation_name
        self.context = context
        self.start_time: Optional[float] = None
        self.logger = get_logger(__name__)
    
    def __enter__(self) -> "QueryLogger":
        """Start timing the operation."""
        self.start_time = time.perf_counter()
        self.logger.debug(
            "database_operation_start",
            operation=self.operation_name,
            **self.context,
        )
        return self
    
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Log operation completion or failure."""
        if self.start_time:
            elapsed_ms = int((time.perf_counter() - self.start_time) * 1000)
            
            if exc_type:
                self.logger.error(
                    "database_operation_error",
                    operation=self.operation_name,
                    error=str(exc_val),
                    error_type=exc_type.__name__,
                    elapsed_ms=elapsed_ms,
                    **self.context,
                )
            else:
                self.logger.info(
                    "database_operation_complete",
                    operation=self.operation_name,
                    elapsed_ms=elapsed_ms,
                    **self.context,
                )
    
    def log_info(self, **kwargs: Any) -> None:
        """Log additional information during the operation."""
        self.logger.info(
            "database_operation_info",
            operation=self.operation_name,
            **self.context,
            **kwargs,
        )
    
    def log_warning(self, **kwargs: Any) -> None:
        """Log a warning during the operation."""
        self.logger.warning(
            "database_operation_warning",
            operation=self.operation_name,
            **self.context,
            **kwargs,
        )


def log_transaction(name: str = "transaction"):
    """
    Decorator to log database transactions.
    
    Usage:
        @log_transaction("user_creation")
        def create_user(session, user_data):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            start_time = time.perf_counter()
            
            logger.debug(
                "database_transaction_start",
                transaction=name,
                function=func.__name__,
            )
            
            try:
                result = func(*args, **kwargs)
                
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                logger.info(
                    "database_transaction_complete",
                    transaction=name,
                    function=func.__name__,
                    elapsed_ms=elapsed_ms,
                )
                
                return result
                
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                logger.error(
                    "database_transaction_error",
                    transaction=name,
                    function=func.__name__,
                    error=str(e),
                    error_type=type(e).__name__,
                    elapsed_ms=elapsed_ms,
                    exc_info=True,
                )
                raise
        
        return wrapper
    
    return decorator