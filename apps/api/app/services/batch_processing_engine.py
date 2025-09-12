"""
Batch Processing Engine with Advanced Retry Logic and Error Recovery

This module provides the core batch processing engine with features including:
- Exponential backoff with jitter for retries
- Circuit breaker pattern for failure protection
- Parallel processing with configurable concurrency
- Dead letter queue integration
- Comprehensive error tracking and recovery
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from celery import Task
from sqlalchemy.orm import Session

from ..core.celery_app import celery_app
from ..core.logging import get_logger
from ..core.metrics import (
    job_creation_counter,
    job_duration_histogram,
    job_progress_gauge,
    queue_depth_gauge,
)
from ..core.telemetry import create_span
from ..models.batch_processing import (
    BatchJob,
    BatchJobStatus,
    BatchOperationType,
    WorkflowExecution,
    WorkflowStepStatus,
)
from ..models.user import User
from .batch_operations import BatchOperationsService

logger = get_logger(__name__)


class RetryStrategy(str, Enum):
    """Retry strategies for batch processing."""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"
    FIBONACCI_BACKOFF = "fibonacci_backoff"


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker for batch processing operations."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitBreakerState.HALF_OPEN
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e
    
    async def async_call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute async function with circuit breaker protection."""
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitBreakerState.HALF_OPEN
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should attempt reset."""
        return (
            self.last_failure_time and
            datetime.now(timezone.utc) - self.last_failure_time > timedelta(seconds=self.recovery_timeout)
        )
    
    def _on_success(self):
        """Handle successful operation."""
        self.failure_count = 0
        self.state = CircuitBreakerState.CLOSED
    
    def _on_failure(self):
        """Handle failed operation."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


class BatchProcessingEngine:
    """Core engine for batch processing with advanced features."""
    
    def __init__(self, db: Session):
        self.db = db
        self.batch_operations = BatchOperationsService(db)
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._init_circuit_breakers()
    
    def _init_circuit_breakers(self):
        """Initialize circuit breakers for different operations."""
        self.circuit_breakers = {
            BatchOperationType.QUALITY_CHECK: CircuitBreaker(failure_threshold=3, recovery_timeout=30),
            BatchOperationType.MESH_OPTIMIZATION: CircuitBreaker(failure_threshold=5, recovery_timeout=60),
            BatchOperationType.FEATURE_CLEANUP: CircuitBreaker(failure_threshold=5, recovery_timeout=60),
            BatchOperationType.MODEL_COMPRESSION: CircuitBreaker(failure_threshold=5, recovery_timeout=60),
            BatchOperationType.FORMAT_CONVERSION: CircuitBreaker(failure_threshold=3, recovery_timeout=30),
        }
    
    async def execute_batch_job(
        self,
        batch_job: BatchJob,
        user: User,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a batch processing job with retry logic and error recovery."""
        with create_span("batch_job_execution", {"job_id": batch_job.id, "user_id": user.id}):
            config = config or {}
            
            try:
                # Update job metrics
                job_creation_counter.labels(
                    job_type="batch",
                    source="api",
                    priority="normal"
                ).inc()
                
                # Get circuit breaker for operation
                circuit_breaker = self.circuit_breakers.get(
                    batch_job.operation_type,
                    CircuitBreaker()
                )
                
                # Execute with circuit breaker protection
                result = await circuit_breaker.async_call(
                    self._execute_with_retry,
                    batch_job,
                    user,
                    config
                )
                
                # Update metrics
                if batch_job.duration_seconds:
                    job_duration_histogram.labels(
                        job_type="batch",
                        status="success"
                    ).observe(float(batch_job.duration_seconds))
                
                return result
                
            except Exception as e:
                logger.error(f"Batch job {batch_job.id} failed: {str(e)}")
                
                # Update metrics
                job_duration_histogram.labels(
                    job_type="batch",
                    status="failed"
                ).observe(0)
                
                # Update job status
                batch_job.status = BatchJobStatus.FAILED
                batch_job.end_time = datetime.now(timezone.utc)
                batch_job.errors.append({
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                self.db.commit()
                
                raise
    
    async def _execute_with_retry(
        self,
        batch_job: BatchJob,
        user: User,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute batch job with retry logic."""
        retry_strategy = config.get("retry_strategy", RetryStrategy.EXPONENTIAL_BACKOFF)
        max_retries = batch_job.max_retries
        
        for attempt in range(max_retries + 1):
            try:
                # Update retry count
                batch_job.retry_count = attempt
                self.db.commit()
                
                # Execute the batch operation
                result = await self.batch_operations.execute_batch_operation(
                    batch_job,
                    BatchOperationType(batch_job.operation_type),
                    batch_job.input_models,
                    config
                )
                
                return result
                
            except Exception as e:
                if attempt == max_retries:
                    raise
                
                # Calculate delay with jitter
                delay = self._calculate_retry_delay(
                    attempt,
                    retry_strategy,
                    batch_job.retry_delay_seconds
                )
                
                logger.warning(
                    f"Batch job {batch_job.id} attempt {attempt + 1} failed, "
                    f"retrying in {delay} seconds: {str(e)}"
                )
                
                await asyncio.sleep(delay)
    
    def _calculate_retry_delay(
        self,
        attempt: int,
        strategy: RetryStrategy,
        base_delay: int
    ) -> float:
        """Calculate retry delay with jitter based on strategy."""
        if strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            # Exponential backoff: base * 2^attempt
            delay = base_delay * (2 ** attempt)
        elif strategy == RetryStrategy.LINEAR_BACKOFF:
            # Linear backoff: base * (attempt + 1)
            delay = base_delay * (attempt + 1)
        elif strategy == RetryStrategy.FIBONACCI_BACKOFF:
            # Fibonacci backoff
            delay = base_delay * self._fibonacci(attempt + 1)
        else:  # FIXED_DELAY
            delay = base_delay
        
        # Add jitter (±25% randomization)
        jitter = random.uniform(0.75, 1.25)
        return delay * jitter
    
    def _fibonacci(self, n: int) -> int:
        """Calculate nth Fibonacci number."""
        if n <= 1:
            return n
        return self._fibonacci(n - 1) + self._fibonacci(n - 2)
    
    async def execute_parallel_batch(
        self,
        batch_jobs: List[BatchJob],
        user: User,
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """Execute multiple batch jobs in parallel with concurrency control."""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_with_semaphore(job):
            async with semaphore:
                try:
                    return await self.execute_batch_job(job, user)
                except Exception as e:
                    logger.error(f"Parallel batch job {job.id} failed: {str(e)}")
                    return {"job_id": job.id, "status": "failed", "error": str(e)}
        
        # Execute all jobs concurrently
        results = await asyncio.gather(
            *[execute_with_semaphore(job) for job in batch_jobs],
            return_exceptions=False
        )
        
        return results
    
    def schedule_batch_job(
        self,
        batch_job: BatchJob,
        user: User,
        delay_seconds: Optional[int] = None,
        eta: Optional[datetime] = None
    ) -> str:
        """Schedule a batch job for async execution via Celery."""
        task_kwargs = {
            "batch_job_id": batch_job.id,
            "user_id": user.id
        }
        
        if eta:
            # Schedule for specific time
            task = process_batch_job.apply_async(
                kwargs=task_kwargs,
                eta=eta,
                queue="default",
                routing_key="jobs.batch"
            )
        elif delay_seconds:
            # Schedule with delay
            task = process_batch_job.apply_async(
                kwargs=task_kwargs,
                countdown=delay_seconds,
                queue="default",
                routing_key="jobs.batch"
            )
        else:
            # Execute immediately
            task = process_batch_job.apply_async(
                kwargs=task_kwargs,
                queue="default",
                routing_key="jobs.batch"
            )
        
        # Store task ID in batch job
        batch_job.config["celery_task_id"] = task.id
        self.db.commit()
        
        logger.info(f"Scheduled batch job {batch_job.id} with task ID {task.id}")
        return task.id
    
    def cancel_batch_job(self, batch_job: BatchJob) -> bool:
        """Cancel a running or scheduled batch job."""
        try:
            # Get Celery task ID
            task_id = batch_job.config.get("celery_task_id")
            if not task_id:
                logger.warning(f"No task ID found for batch job {batch_job.id}")
                return False
            
            # Revoke the task
            celery_app.control.revoke(task_id, terminate=True)
            
            # Update job status
            batch_job.status = BatchJobStatus.CANCELLED
            batch_job.end_time = datetime.now(timezone.utc)
            self.db.commit()
            
            logger.info(f"Cancelled batch job {batch_job.id} (task {task_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel batch job {batch_job.id}: {str(e)}")
            return False
    
    def pause_batch_job(self, batch_job: BatchJob) -> bool:
        """Pause a running batch job."""
        try:
            if batch_job.status != BatchJobStatus.RUNNING:
                logger.warning(f"Cannot pause batch job {batch_job.id} with status {batch_job.status}")
                return False
            
            # Update status
            batch_job.status = BatchJobStatus.PAUSED
            batch_job.config["paused_at"] = datetime.now(timezone.utc).isoformat()
            self.db.commit()
            
            logger.info(f"Paused batch job {batch_job.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to pause batch job {batch_job.id}: {str(e)}")
            return False
    
    def resume_batch_job(self, batch_job: BatchJob, user: User) -> str:
        """Resume a paused batch job."""
        try:
            if batch_job.status != BatchJobStatus.PAUSED:
                logger.warning(f"Cannot resume batch job {batch_job.id} with status {batch_job.status}")
                return None
            
            # Update status
            batch_job.status = BatchJobStatus.PENDING
            paused_duration = 0
            
            if "paused_at" in batch_job.config:
                paused_at = datetime.fromisoformat(batch_job.config["paused_at"])
                paused_duration = (datetime.now(timezone.utc) - paused_at).total_seconds()
                del batch_job.config["paused_at"]
            
            # Adjust for paused time
            batch_job.config["paused_duration"] = batch_job.config.get("paused_duration", 0) + paused_duration
            self.db.commit()
            
            # Reschedule the job
            task_id = self.schedule_batch_job(batch_job, user)
            
            logger.info(f"Resumed batch job {batch_job.id} with new task {task_id}")
            return task_id
            
        except Exception as e:
            logger.error(f"Failed to resume batch job {batch_job.id}: {str(e)}")
            return None
    
    async def recover_failed_jobs(
        self,
        time_window_hours: int = 24,
        max_jobs: int = 10
    ) -> List[BatchJob]:
        """Recover and retry failed batch jobs within time window."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
        
        # Find failed jobs that can be retried
        failed_jobs = self.db.query(BatchJob).filter(
            BatchJob.status == BatchJobStatus.FAILED,
            BatchJob.created_at >= cutoff_time,
            BatchJob.retry_count < BatchJob.max_retries
        ).limit(max_jobs).all()
        
        recovered = []
        for job in failed_jobs:
            try:
                # Reset job for retry
                job.status = BatchJobStatus.PENDING
                job.processed_items = 0
                job.failed_items = 0
                job.skipped_items = 0
                job.errors = []
                job.warnings = []
                self.db.commit()
                
                # Get user
                user = job.user
                
                # Reschedule with exponential backoff
                delay = self._calculate_retry_delay(
                    job.retry_count,
                    RetryStrategy.EXPONENTIAL_BACKOFF,
                    60  # Base delay of 60 seconds
                )
                
                self.schedule_batch_job(job, user, delay_seconds=int(delay))
                recovered.append(job)
                
                logger.info(f"Recovered failed batch job {job.id} for retry")
                
            except Exception as e:
                logger.error(f"Failed to recover batch job {job.id}: {str(e)}")
        
        return recovered


# Celery tasks
@celery_app.task(name="process_batch_job", bind=True)
def process_batch_job(self: Task, batch_job_id: int, user_id: int) -> Dict[str, Any]:
    """Celery task to process a batch job asynchronously."""
    from ..core.database import SessionLocal
    from ..crud.user import get_user_by_id
    
    with SessionLocal() as db:
        try:
            # Get batch job
            batch_job = db.query(BatchJob).filter(BatchJob.id == batch_job_id).first()
            if not batch_job:
                raise ValueError(f"Batch job {batch_job_id} not found")
            
            # Get user
            user = get_user_by_id(db, user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Create engine and execute
            engine = BatchProcessingEngine(db)
            
            # Run async function in sync context
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    engine.execute_batch_job(batch_job, user)
                )
                return result
            finally:
                loop.close()
            
        except Exception as e:
            logger.error(f"Batch job {batch_job_id} processing failed: {str(e)}")
            
            # Update job status
            if batch_job:
                batch_job.status = BatchJobStatus.FAILED
                batch_job.end_time = datetime.now(timezone.utc)
                batch_job.errors.append({
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                db.commit()
            
            # Re-raise for Celery retry mechanism
            raise self.retry(exc=e, countdown=60, max_retries=3)