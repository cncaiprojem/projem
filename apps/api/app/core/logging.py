"""
Comprehensive structlog configuration for production-ready logging.
Supports both development (colorful console) and production (JSON) modes.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Protocol, TypeVar

import structlog
from structlog.processors import CallsiteParameter
from structlog.types import EventDict, Processor

# Context variables for request tracking
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
task_id_ctx: ContextVar[Optional[str]] = ContextVar("task_id", default=None)


class LogLevel(str, Enum):
    """Log levels with Turkish descriptions."""
    
    DEBUG = "DEBUG"  # Hata ayıklama
    INFO = "INFO"  # Bilgi
    WARNING = "WARNING"  # Uyarı
    ERROR = "ERROR"  # Hata
    CRITICAL = "CRITICAL"  # Kritik


class LoggerProtocol(Protocol):
    """Protocol for logger interface."""
    
    def debug(self, event: str, **kwargs: Any) -> None: ...
    def info(self, event: str, **kwargs: Any) -> None: ...
    def warning(self, event: str, **kwargs: Any) -> None: ...
    def error(self, event: str, **kwargs: Any) -> None: ...
    def critical(self, event: str, **kwargs: Any) -> None: ...
    def bind(self, **kwargs: Any) -> LoggerProtocol: ...


# Type variables for decorators
F = TypeVar("F", bound=Callable[..., Any])


def add_timestamp(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add ISO-8601 timestamp to log entry."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_app_context(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add application context (request_id, user_id, task_id) to log entry."""
    if request_id := request_id_ctx.get():
        event_dict["request_id"] = request_id
    if user_id := user_id_ctx.get():
        event_dict["user_id"] = user_id
    if task_id := task_id_ctx.get():
        event_dict["task_id"] = task_id
    
    # Add hostname and process info
    event_dict["hostname"] = os.environ.get("HOSTNAME", "unknown")
    event_dict["pid"] = os.getpid()
    
    return event_dict


def add_turkish_messages(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add Turkish translations for common log messages."""
    turkish_map = {
        "request_started": "İstek başlatıldı",
        "request_completed": "İstek tamamlandı",
        "request_failed": "İstek başarısız oldu",
        "authentication_failed": "Kimlik doğrulama başarısız",
        "authorization_failed": "Yetkilendirme başarısız",
        "database_error": "Veritabanı hatası",
        "validation_error": "Doğrulama hatası",
        "task_started": "Görev başlatıldı",
        "task_completed": "Görev tamamlandı",
        "task_failed": "Görev başarısız oldu",
        "slow_request": "Yavaş istek tespit edildi",
        "rate_limit_exceeded": "Hız limiti aşıldı",
        "file_upload_started": "Dosya yükleme başladı",
        "file_upload_completed": "Dosya yükleme tamamlandı",
        "cache_hit": "Önbellek bulundu",
        "cache_miss": "Önbellekte bulunamadı",
    }
    
    # Add Turkish message if available
    if event := event_dict.get("event"):
        if turkish := turkish_map.get(event):
            event_dict["message_tr"] = turkish
    
    return event_dict


def mask_sensitive_data(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Mask sensitive data in log entries."""
    sensitive_keys = {
        "password", "token", "secret", "api_key", "authorization",
        "şifre", "parola", "gizli", "anahtar", "kredi_kartı", "credit_card"
    }
    
    def mask_value(value: Any) -> Any:
        if isinstance(value, str) and len(value) > 4:
            # Keep first and last 2 chars, mask middle
            return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"
        return "***"
    
    def mask_dict(d: Dict[str, Any]) -> Dict[str, Any]:
        masked = {}
        for key, value in d.items():
            if any(s in key.lower() for s in sensitive_keys):
                masked[key] = mask_value(value)
            elif isinstance(value, dict):
                masked[key] = mask_dict(value)
            elif isinstance(value, list):
                masked[key] = [mask_dict(item) if isinstance(item, dict) else item for item in value]
            else:
                masked[key] = value
        return masked
    
    return mask_dict(event_dict)


def extract_from_http_request(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Extract useful information from HTTP request objects if present."""
    if "request" in event_dict:
        request = event_dict.pop("request")
        if hasattr(request, "method"):
            event_dict["http_method"] = request.method
        if hasattr(request, "url"):
            event_dict["http_path"] = str(request.url.path)
            event_dict["http_query"] = str(request.url.query) if request.url.query else None
        if hasattr(request, "headers"):
            # Extract useful headers
            headers = dict(request.headers)
            event_dict["http_user_agent"] = headers.get("user-agent")
            event_dict["http_referer"] = headers.get("referer")
            event_dict["http_host"] = headers.get("host")
    
    return event_dict


def drop_null_values(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Remove null values from log entries to reduce size."""
    return {k: v for k, v in event_dict.items() if v is not None}


def get_environment() -> str:
    """Get current environment (development/production)."""
    return os.environ.get("ENVIRONMENT", "development").lower()


def get_log_level() -> str:
    """Get configured log level from environment."""
    default_level = "DEBUG" if get_environment() == "development" else "INFO"
    return os.environ.get("LOG_LEVEL", default_level).upper()


def configure_structlog() -> None:
    """Configure structlog based on environment."""
    environment = get_environment()
    log_level = get_log_level()
    
    # Common processors for all environments
    common_processors: List[Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        add_timestamp,
        add_app_context,
        add_turkish_messages,
        extract_from_http_request,
        mask_sensitive_data,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if environment == "development":
        # Development: Colorful console output
        processors = common_processors + [
            structlog.processors.add_log_level,
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    CallsiteParameter.FILENAME,
                    CallsiteParameter.LINENO,
                    CallsiteParameter.FUNC_NAME,
                ]
            ),
            drop_null_values,
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.RichTracebackFormatter(
                    show_locals=True,
                    max_frames=5,
                ),
            ),
        ]
    else:
        # Production: JSON output
        processors = common_processors + [
            structlog.processors.format_exc_info,
            drop_null_values,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level),
    )
    
    # Suppress noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None, **kwargs: Any) -> LoggerProtocol:
    """
    Get a configured structlog logger.
    
    Args:
        name: Logger name (defaults to module name)
        **kwargs: Additional context to bind to logger
    
    Returns:
        Configured structlog logger
    """
    logger = structlog.get_logger(name)
    if kwargs:
        logger = logger.bind(**kwargs)
    return logger


def log_execution(
    level: str = "INFO",
    include_args: bool = True,
    include_result: bool = False,
    max_length: int = 200,
    sanitize_params: bool = True,
) -> Callable[[F], F]:
    """
    Decorator to log function execution with timing.
    
    Args:
        level: Log level for entry/exit messages
        include_args: Whether to log function arguments
        include_result: Whether to log function result
        max_length: Maximum length for logged values
        sanitize_params: Whether to mask sensitive parameters
    
    Example:
        @log_execution(level="DEBUG", include_result=True)
        async def process_data(user_id: str, data: dict) -> dict:
            ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger(func.__module__)
            start_time = datetime.now(timezone.utc)
            
            # Log function entry
            log_data = {
                "function": func.__name__,
                "execution_type": "async",
            }
            
            if include_args:
                # Truncate long values
                def truncate(value: Any) -> Any:
                    str_val = str(value)
                    if len(str_val) > max_length:
                        return f"{str_val[:max_length]}..."
                    return value
                
                if args:
                    log_data["args"] = [truncate(arg) for arg in args]
                if kwargs:
                    log_data["kwargs"] = {k: truncate(v) for k, v in kwargs.items()}
            
            logger.log(level.lower(), "function_entry", **log_data)
            
            try:
                result = await func(*args, **kwargs)
                
                # Log function exit
                elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                exit_data = {
                    "function": func.__name__,
                    "elapsed_ms": elapsed_ms,
                    "status": "success",
                }
                
                if include_result:
                    exit_data["result"] = str(result)[:max_length]
                
                # Log as warning if slow
                if elapsed_ms > 1000:
                    logger.warning("slow_function_execution", **exit_data)
                else:
                    logger.log(level.lower(), "function_exit", **exit_data)
                
                return result
                
            except Exception as e:
                elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                logger.error(
                    "function_error",
                    function=func.__name__,
                    error=str(e),
                    error_type=type(e).__name__,
                    elapsed_ms=elapsed_ms,
                    exc_info=True,
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger(func.__module__)
            start_time = datetime.now(timezone.utc)
            
            # Log function entry
            log_data = {
                "function": func.__name__,
                "execution_type": "sync",
            }
            
            if include_args:
                # Truncate long values
                def truncate(value: Any) -> Any:
                    str_val = str(value)
                    if len(str_val) > max_length:
                        return f"{str_val[:max_length]}..."
                    return value
                
                if args:
                    log_data["args"] = [truncate(arg) for arg in args]
                if kwargs:
                    log_data["kwargs"] = {k: truncate(v) for k, v in kwargs.items()}
            
            logger.log(level.lower(), "function_entry", **log_data)
            
            try:
                result = func(*args, **kwargs)
                
                # Log function exit
                elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                exit_data = {
                    "function": func.__name__,
                    "elapsed_ms": elapsed_ms,
                    "status": "success",
                }
                
                if include_result:
                    exit_data["result"] = str(result)[:max_length]
                
                # Log as warning if slow
                if elapsed_ms > 1000:
                    logger.warning("slow_function_execution", **exit_data)
                else:
                    logger.log(level.lower(), "function_exit", **exit_data)
                
                return result
                
            except Exception as e:
                elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                logger.error(
                    "function_error",
                    function=func.__name__,
                    error=str(e),
                    error_type=type(e).__name__,
                    elapsed_ms=elapsed_ms,
                    exc_info=True,
                )
                raise
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore
    
    return decorator


def log_database_query(query: str, params: Optional[Dict[str, Any]] = None, duration_ms: Optional[int] = None) -> None:
    """
    Log database query with optional parameters and duration.
    
    Args:
        query: SQL query string
        params: Query parameters
        duration_ms: Query execution time in milliseconds
    """
    logger = get_logger("database")
    
    # Truncate long queries
    truncated_query = query[:500] if len(query) > 500 else query
    
    log_data = {
        "query": truncated_query,
        "query_length": len(query),
    }
    
    if params:
        log_data["params"] = params
    
    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms
        
        # Log slow queries as warnings
        if duration_ms > 1000:
            logger.warning("slow_database_query", **log_data)
        else:
            logger.debug("database_query", **log_data)
    else:
        logger.debug("database_query", **log_data)


def log_external_api_call(
    service: str,
    method: str,
    url: str,
    status_code: Optional[int] = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """
    Log external API call with details.
    
    Args:
        service: Name of the external service
        method: HTTP method
        url: Request URL
        status_code: Response status code
        duration_ms: Request duration in milliseconds
        error: Error message if request failed
    """
    logger = get_logger("external_api")
    
    log_data = {
        "service": service,
        "method": method,
        "url": url,
    }
    
    if status_code is not None:
        log_data["status_code"] = status_code
    
    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms
    
    if error:
        log_data["error"] = error
        logger.error("external_api_error", **log_data)
    elif status_code and status_code >= 400:
        logger.warning("external_api_client_error", **log_data)
    elif duration_ms and duration_ms > 5000:
        logger.warning("slow_external_api_call", **log_data)
    else:
        logger.info("external_api_call", **log_data)


def log_security_event(
    event_type: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log security-related events.
    
    Args:
        event_type: Type of security event (e.g., "failed_login", "unauthorized_access")
        user_id: User ID if available
        ip_address: Client IP address
        details: Additional event details
    """
    logger = get_logger("security")
    
    log_data = {
        "security_event": event_type,
    }
    
    if user_id:
        log_data["user_id"] = user_id
    
    if ip_address:
        log_data["ip_address"] = ip_address
    
    if details:
        log_data["details"] = details
    
    # Security events are always logged at WARNING or higher
    if event_type in {"intrusion_attempt", "data_breach", "privilege_escalation"}:
        logger.critical("critical_security_event", **log_data)
    else:
        logger.warning("security_event", **log_data)


# Initialize logging on module import
configure_structlog()