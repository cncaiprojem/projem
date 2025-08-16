"""
Celery task logging integration with structlog.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

from celery import Task, current_task
from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_success,
    task_revoked,
    before_task_publish,
    after_task_publish,
)

from .logging import get_logger, task_id_ctx


logger = get_logger(__name__)

# Type variable for decorators
F = TypeVar("F", bound=Callable[..., Any])

# Store task start times for duration calculation
task_start_times: Dict[str, float] = {}


@before_task_publish.connect
def before_task_publish_handler(
    sender: Optional[str] = None,
    headers: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
    **kwargs: Any
) -> None:
    """Log when a task is published to the queue."""
    task_id = headers.get("id") if headers else None
    task_name = headers.get("task") if headers else sender
    
    logger.info(
        "celery_task_published",
        task_id=task_id,
        task_name=task_name,
        routing_key=kwargs.get("routing_key"),
        exchange=kwargs.get("exchange"),
        queue=kwargs.get("queue"),
    )


@after_task_publish.connect
def after_task_publish_handler(
    sender: Optional[str] = None,
    headers: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
    **kwargs: Any
) -> None:
    """Log after a task is successfully published."""
    task_id = headers.get("id") if headers else None
    task_name = headers.get("task") if headers else sender
    
    logger.debug(
        "celery_task_publish_confirmed",
        task_id=task_id,
        task_name=task_name,
    )


@task_prerun.connect
def task_prerun_handler(
    sender: Optional[Task] = None,
    task_id: Optional[str] = None,
    task: Optional[Task] = None,
    args: Optional[tuple] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    **kw: Any
) -> None:
    """Log task start and set context."""
    # Set task ID context
    if task_id:
        task_id_ctx.set(task_id)
    
    # Store start time
    task_start_times[task_id] = time.perf_counter()
    
    # Log task start
    log_data = {
        "event": "task_started",
        "task_id": task_id,
        "task_name": task.name if task else None,
        "hostname": kw.get("hostname"),
        "args_count": len(args) if args else 0,
        "kwargs_keys": list(kwargs.keys()) if kwargs else [],
    }
    
    # Add queue name if available
    if task and hasattr(task.request, "delivery_info"):
        delivery_info = task.request.delivery_info
        if delivery_info and "routing_key" in delivery_info:
            log_data["queue"] = delivery_info["routing_key"]
    
    logger.info("celery_task_start", **log_data)


@task_postrun.connect
def task_postrun_handler(
    sender: Optional[Task] = None,
    task_id: Optional[str] = None,
    task: Optional[Task] = None,
    args: Optional[tuple] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    retval: Optional[Any] = None,
    state: Optional[str] = None,
    **kw: Any
) -> None:
    """Log task completion and clear context."""
    # Calculate duration
    duration_ms = None
    if task_id in task_start_times:
        start_time = task_start_times.pop(task_id)
        duration_ms = int((time.perf_counter() - start_time) * 1000)
    
    # Log task completion
    log_data = {
        "event": "task_completed",
        "task_id": task_id,
        "task_name": task.name if task else None,
        "state": state,
        "duration_ms": duration_ms,
        "hostname": kw.get("hostname"),
    }
    
    # Log slow tasks as warnings
    if duration_ms and duration_ms > 30000:  # 30 seconds
        logger.warning("celery_slow_task", **log_data)
    else:
        logger.info("celery_task_complete", **log_data)
    
    # Clear task ID context
    task_id_ctx.set(None)


@task_success.connect
def task_success_handler(
    sender: Optional[Task] = None,
    result: Optional[Any] = None,
    **kwargs: Any
) -> None:
    """Log successful task completion."""
    task_id = sender.request.id if sender and sender.request else None
    
    logger.info(
        "celery_task_success",
        task_id=task_id,
        task_name=sender.name if sender else None,
        result_type=type(result).__name__ if result else None,
    )


@task_failure.connect
def task_failure_handler(
    sender: Optional[Task] = None,
    task_id: Optional[str] = None,
    exception: Optional[Exception] = None,
    args: Optional[tuple] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    traceback: Optional[Any] = None,
    einfo: Optional[Any] = None,
    **kw: Any
) -> None:
    """Log task failure with exception details."""
    # Calculate duration if available
    duration_ms = None
    if task_id in task_start_times:
        start_time = task_start_times.pop(task_id)
        duration_ms = int((time.perf_counter() - start_time) * 1000)
    
    logger.error(
        "celery_task_failure",
        task_id=task_id,
        task_name=sender.name if sender else None,
        error=str(exception) if exception else None,
        error_type=type(exception).__name__ if exception else None,
        duration_ms=duration_ms,
        hostname=kw.get("hostname"),
        exc_info=einfo.exc_info if einfo and hasattr(einfo, "exc_info") else None,
    )


@task_retry.connect
def task_retry_handler(
    sender: Optional[Task] = None,
    task_id: Optional[str] = None,
    reason: Optional[Any] = None,
    einfo: Optional[Any] = None,
    **kwargs: Any
) -> None:
    """Log task retry attempts."""
    request = sender.request if sender else None
    
    logger.warning(
        "celery_task_retry",
        task_id=task_id,
        task_name=sender.name if sender else None,
        reason=str(reason) if reason else None,
        retry_count=request.retries if request else None,
        max_retries=sender.max_retries if sender else None,
        exc_info=einfo.exc_info if einfo and hasattr(einfo, "exc_info") else None,
    )


@task_revoked.connect
def task_revoked_handler(
    sender: Optional[Task] = None,
    request: Optional[Any] = None,
    terminated: bool = False,
    signum: Optional[int] = None,
    expired: bool = False,
    **kwargs: Any
) -> None:
    """Log task revocation."""
    task_id = request.id if request else None
    
    logger.warning(
        "celery_task_revoked",
        task_id=task_id,
        task_name=request.task if request else None,
        terminated=terminated,
        expired=expired,
        signal=signum,
    )


def log_task_execution(
    include_args: bool = False,
    include_result: bool = False,
    max_length: int = 200,
) -> Callable[[F], F]:
    """
    Decorator for Celery tasks to add structured logging.
    
    Args:
        include_args: Whether to log task arguments
        include_result: Whether to log task result
        max_length: Maximum length for logged values
    
    Example:
        @celery_app.task
        @log_task_execution(include_result=True)
        def process_data(user_id: str, data: dict) -> dict:
            ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            task = current_task
            task_id = task.request.id if task else None
            task_name = task.name if task else func.__name__
            
            # Set task context
            if task_id:
                task_id_ctx.set(task_id)
            
            logger = get_logger(func.__module__)
            start_time = time.perf_counter()
            
            # Log task execution start
            log_data = {
                "event": "task_execution_start",
                "task_id": task_id,
                "task_name": task_name,
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
            
            logger.info("task_execution_start", **log_data)
            
            try:
                result = func(*args, **kwargs)
                
                # Log task execution end
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                exit_data = {
                    "event": "task_execution_complete",
                    "task_id": task_id,
                    "task_name": task_name,
                    "elapsed_ms": elapsed_ms,
                    "status": "success",
                }
                
                if include_result:
                    exit_data["result"] = str(result)[:max_length]
                
                logger.info("task_execution_complete", **exit_data)
                
                return result
                
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                logger.error(
                    "task_execution_error",
                    task_id=task_id,
                    task_name=task_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    elapsed_ms=elapsed_ms,
                    exc_info=True,
                )
                raise
            finally:
                # Clear task context
                task_id_ctx.set(None)
        
        return wrapper  # type: ignore
    
    return decorator


class LoggingTask(Task):
    """
    Custom Celery Task class with built-in structured logging.
    
    Usage:
        @celery_app.task(base=LoggingTask)
        def my_task():
            ...
    """
    
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute task with logging."""
        task_id = self.request.id
        task_id_ctx.set(task_id)
        
        logger = get_logger(self.__module__)
        
        try:
            logger.debug(
                "task_call",
                task_id=task_id,
                task_name=self.name,
                args_count=len(args),
                kwargs_keys=list(kwargs.keys()),
            )
            
            result = super().__call__(*args, **kwargs)
            
            logger.debug(
                "task_call_complete",
                task_id=task_id,
                task_name=self.name,
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "task_call_error",
                task_id=task_id,
                task_name=self.name,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            raise
        finally:
            task_id_ctx.set(None)
    
    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        """Handle task failure."""
        logger = get_logger(self.__module__)
        
        logger.error(
            "task_failure_handler",
            task_id=task_id,
            task_name=self.name,
            error=str(exc),
            error_type=type(exc).__name__,
            args_count=len(args),
            kwargs_keys=list(kwargs.keys()),
            exc_info=einfo.exc_info if hasattr(einfo, "exc_info") else None,
        )
        
        super().on_failure(exc, task_id, args, kwargs, einfo)
    
    def on_retry(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        """Handle task retry."""
        logger = get_logger(self.__module__)
        
        logger.warning(
            "task_retry_handler",
            task_id=task_id,
            task_name=self.name,
            error=str(exc),
            error_type=type(exc).__name__,
            retry_count=self.request.retries,
            max_retries=self.max_retries,
            exc_info=einfo.exc_info if hasattr(einfo, "exc_info") else None,
        )
        
        super().on_retry(exc, task_id, args, kwargs, einfo)
    
    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        """Handle task success."""
        logger = get_logger(self.__module__)
        
        logger.info(
            "task_success_handler",
            task_id=task_id,
            task_name=self.name,
            result_type=type(retval).__name__,
        )
        
        super().on_success(retval, task_id, args, kwargs)