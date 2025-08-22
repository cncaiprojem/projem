"""
Dead Letter Queue (DLQ) Handler for Task 6.2
Handles routing of failed tasks to appropriate DLQ based on error classification.

This module provides:
- DLQ routing for tasks that exceed retry limits
- Error metadata preservation for observability
- Dead letter exchange integration
- Failed task analysis and recovery utilities
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from celery.exceptions import Retry, Reject
from kombu import Exchange, Queue

from .error_taxonomy import (
    classify_error, 
    format_error_for_dlq,
    get_error_metadata,
    FATAL_EXCEPTIONS,
    CANCELLATION_EXCEPTIONS
)
from .queue_constants import DLX_SUFFIX, DLQ_SUFFIX


logger = logging.getLogger(__name__)


class DLQHandler:
    """Handler for Dead Letter Queue operations."""
    
    def __init__(self, celery_app):
        self.celery_app = celery_app
    
    def should_send_to_dlq(
        self, 
        exc: Exception, 
        attempt_count: int, 
        max_retries: int
    ) -> tuple[bool, str]:
        """
        Determine if a task should be sent to DLQ and why.
        
        Args:
            exc: Exception that occurred
            attempt_count: Current attempt number
            max_retries: Maximum retries allowed
            
        Returns:
            tuple: (should_send_to_dlq, reason)
        """
        error_classification = classify_error(exc)
        
        # Task 6.2: Fatal errors go directly to DLQ
        if error_classification == 'fatal':
            return True, 'fatal_error'
        
        # Task 6.2: Cancellation errors don't retry, but also don't go to DLQ
        if error_classification == 'cancellation':
            return False, 'cancelled'
        
        # Task 6.2: Non-retryable errors go directly to DLQ
        if error_classification == 'non_retryable':
            return True, 'non_retryable_error'
        
        # Task 6.2: Retryable errors go to DLQ only after exceeding max retries
        if error_classification == 'retryable' and attempt_count >= max_retries:
            return True, 'max_retries_exceeded'
        
        return False, 'retryable'
    
    def send_task_to_dlq(
        self,
        task_id: str,
        task_name: str,
        queue_name: str,
        args: tuple,
        kwargs: dict,
        exc: Exception,
        attempt_count: int,
        headers: Optional[Dict] = None
    ) -> bool:
        """
        Send a failed task to the appropriate Dead Letter Queue.
        
        Task 6.2: On exceeding retries, nack with requeue=False to send to DLQ
        
        Args:
            task_id: Unique task identifier
            task_name: Name of the failed task
            queue_name: Original queue name
            args: Task arguments
            kwargs: Task keyword arguments
            exc: Exception that caused the failure
            attempt_count: Number of attempts made
            headers: Original task headers
            
        Returns:
            bool: True if successfully sent to DLQ
        """
        try:
            # Format DLQ message with all metadata
            dlq_message = self._create_dlq_message(
                task_id, task_name, queue_name, args, kwargs, 
                exc, attempt_count, headers
            )
            
            # Get DLQ name for the original queue
            dlq_name = f"{queue_name}{DLQ_SUFFIX}"
            dlx_name = f"{queue_name}{DLX_SUFFIX}"
            
            # Send to DLX, which will route to DLQ
            dlx_exchange = Exchange(dlx_name, type='direct', durable=True)
            
            # Publish to DLX with routing key that matches DLQ binding
            with self.celery_app.producer_pool.acquire(block=True) as producer:
                producer.publish(
                    dlq_message,
                    exchange=dlx_exchange,
                    routing_key='#',  # Matches DLQ binding
                    declare=[dlx_exchange],
                    serializer='json',
                    compression='gzip',
                    headers={
                        'x-failed-queue': queue_name,
                        'x-failed-task': task_name,
                        'x-failed-at': datetime.now(timezone.utc).isoformat(),
                        'x-attempt-count': attempt_count,
                    }
                )
            
            logger.warning(
                f"Task {task_id} ({task_name}) sent to DLQ {dlq_name} "
                f"after {attempt_count} attempts. Error: {exc}"
            )
            return True
            
        except Exception as dlq_error:
            logger.error(
                f"Failed to send task {task_id} to DLQ: {dlq_error}", 
                exc_info=True
            )
            return False
    
    def _create_dlq_message(
        self,
        task_id: str,
        task_name: str,
        queue_name: str,
        args: tuple,
        kwargs: dict,
        exc: Exception,
        attempt_count: int,
        headers: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Create a comprehensive DLQ message with all metadata."""
        
        error_metadata = get_error_metadata(exc)
        
        return {
            # Original task information
            'task_id': task_id,
            'task_name': task_name,
            'original_queue': queue_name,
            'args': args,
            'kwargs': kwargs,
            'headers': headers or {},
            
            # Failure information
            'attempt_count': attempt_count,
            'failed_at': datetime.now(timezone.utc).isoformat(),
            'error_metadata': error_metadata,
            
            # Classification
            'failure_reason': 'max_retries_exceeded' if error_metadata['is_retryable'] else 'non_retryable_error',
            'error_classification': error_metadata['error_classification'],
            
            # Recovery information
            'recoverable': error_metadata['is_retryable'],
            'dlq_version': '1.0',  # For future DLQ message format evolution
        }


def handle_task_failure(
    task_self, 
    exc: Exception, 
    task_id: str, 
    args: tuple, 
    kwargs: dict, 
    einfo
):
    """
    Handle task failure with retry strategy and DLQ routing.
    
    Task 6.2: This function should be called from task on_failure handlers
    or as part of the retry logic to properly route failed tasks.
    
    Args:
        task_self: The task instance (when using bind=True)
        exc: Exception that caused the failure
        task_id: Unique task identifier
        args: Task arguments
        kwargs: Task keyword arguments
        einfo: Exception info from Celery
    """
    from .retry_config import get_queue_retry_config
    
    # Get task metadata
    task_name = task_self.name
    queue_name = getattr(task_self.request, 'delivery_info', {}).get('routing_key', 'default')
    attempt_count = getattr(task_self.request, 'retries', 0) + 1
    
    # Get retry configuration for this queue
    retry_config = get_queue_retry_config(queue_name)
    max_retries = retry_config['max_retries']
    
    # Create DLQ handler
    dlq_handler = DLQHandler(task_self.app)
    
    # Check if should send to DLQ
    should_dlq, reason = dlq_handler.should_send_to_dlq(exc, attempt_count, max_retries)
    
    if should_dlq:
        # Send to DLQ
        success = dlq_handler.send_task_to_dlq(
            task_id=task_id,
            task_name=task_name,
            queue_name=queue_name,
            args=args,
            kwargs=kwargs,
            exc=exc,
            attempt_count=attempt_count,
            headers=getattr(task_self.request, 'headers', {})
        )
        
        if success:
            # Task 6.2: Reject without requeue to prevent infinite loops
            raise Reject(exc, requeue=False)
        else:
            logger.error(f"Failed to send task {task_id} to DLQ, rejecting without requeue")
            raise Reject(exc, requeue=False)
    
    # For retryable errors that haven't exceeded max retries,
    # let the normal retry mechanism handle it
    elif reason == 'retryable':
        # The autoretry mechanism will handle this
        pass
    
    # For cancellation, just reject without requeue
    elif reason == 'cancelled':
        raise Reject(exc, requeue=False)


def create_dlq_recovery_task():
    """
    Create a task for recovering messages from DLQ.
    This is a utility function for DLQ management.
    """
    from celery import current_app
    
    @current_app.task(bind=True, name='dlq.recover_message')
    def recover_dlq_message(self, dlq_message: dict, requeue_to: str = None):
        """
        Recover a message from DLQ by re-queueing it.
        
        Args:
            dlq_message: The DLQ message to recover
            requeue_to: Optional queue to send to (defaults to original)
        """
        try:
            original_queue = requeue_to or dlq_message['original_queue']
            task_name = dlq_message['task_name']
            
            # Re-create the original task call
            task = current_app.tasks.get(task_name)
            if not task:
                raise ValueError(f"Task {task_name} not found")
            
            # Send with reset retry count
            result = task.apply_async(
                args=dlq_message['args'],
                kwargs=dlq_message['kwargs'],
                queue=original_queue,
                headers={'x-recovered-from-dlq': True}
            )
            
            logger.info(
                f"Recovered task {dlq_message['task_id']} from DLQ "
                f"as new task {result.id}"
            )
            
            return {
                'status': 'recovered',
                'original_task_id': dlq_message['task_id'],
                'new_task_id': result.id,
                'queue': original_queue
            }
            
        except Exception as e:
            logger.error(f"Failed to recover DLQ message: {e}", exc_info=True)
            raise
    
    return recover_dlq_message