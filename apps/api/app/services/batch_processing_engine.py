"""
Enterprise-grade Batch Processing Engine for Task 7.23

Provides parallel batch processing with:
- ProcessPoolExecutor for CPU-intensive operations
- AsyncIO for I/O-bound operations
- Progress tracking with Redis
- Result aggregation and reporting
- Error recovery and retry logic
- Resource management and throttling
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic

import redis.asyncio as aioredis
from pydantic import BaseModel, Field, field_validator

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.metrics import batch_counter, batch_duration_histogram
from ..core.telemetry import create_span

logger = get_logger(__name__)

T = TypeVar('T')
R = TypeVar('R')


class BatchItemStatus(str, Enum):
    """Status of individual batch items."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class BatchStatus(str, Enum):
    """Overall batch status."""
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingStrategy(str, Enum):
    """Batch processing strategies."""
    PARALLEL = "parallel"  # Maximum parallelism
    SEQUENTIAL = "sequential"  # One at a time
    ADAPTIVE = "adaptive"  # Adjust based on resources
    CHUNKED = "chunked"  # Process in chunks
    PRIORITY = "priority"  # Process by priority


class BatchItem(BaseModel, Generic[T]):
    """Individual item in a batch."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    data: T = Field(description="İşlenecek veri")
    priority: int = Field(default=0, ge=0, le=10, description="Öncelik (0-10)")
    status: BatchItemStatus = Field(default=BatchItemStatus.PENDING)
    retries: int = Field(default=0, ge=0, description="Tekrar deneme sayısı")
    error: Optional[str] = Field(default=None, description="Hata mesajı")
    result: Optional[Any] = Field(default=None, description="İşlem sonucu")
    processing_time_ms: Optional[float] = Field(default=None, description="İşlem süresi (ms)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Ek bilgiler")


class BatchOptions(BaseModel):
    """Options for batch processing."""
    strategy: ProcessingStrategy = Field(default=ProcessingStrategy.ADAPTIVE)
    max_workers: Optional[int] = Field(default=None, ge=1, le=64, description="Maksimum işçi sayısı")
    chunk_size: int = Field(default=10, ge=1, le=1000, description="Chunk boyutu")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maksimum tekrar sayısı")
    retry_delay_ms: int = Field(default=1000, ge=100, le=60000, description="Tekrar gecikme süresi (ms)")
    timeout_per_item_s: int = Field(default=300, ge=1, le=3600, description="Öğe başına timeout (saniye)")
    continue_on_error: bool = Field(default=True, description="Hata durumunda devam et")
    save_results: bool = Field(default=True, description="Sonuçları kaydet")
    track_progress: bool = Field(default=True, description="İlerlemeyi takip et")
    use_process_pool: bool = Field(default=False, description="CPU-intensive işler için process pool kullan")
    memory_limit_mb: Optional[int] = Field(default=None, ge=128, le=32768, description="Bellek limiti (MB)")
    priority_queue: bool = Field(default=False, description="Öncelik kuyruğu kullan")
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "strategy": "adaptive",
            "max_workers": 4,
            "chunk_size": 20,
            "max_retries": 3,
            "continue_on_error": True
        }
    ]}}


class BatchResult(BaseModel, Generic[R]):
    """Result of batch processing."""
    batch_id: str = Field(description="Toplu işlem ID")
    status: BatchStatus = Field(description="Durum")
    total_items: int = Field(description="Toplam öğe sayısı")
    processed_items: int = Field(description="İşlenen öğe sayısı")
    successful_items: int = Field(description="Başarılı öğe sayısı")
    failed_items: int = Field(description="Başarısız öğe sayısı")
    skipped_items: int = Field(description="Atlanan öğe sayısı")
    results: List[R] = Field(default_factory=list, description="Sonuçlar")
    errors: Dict[str, str] = Field(default_factory=dict, description="Hatalar")
    start_time: datetime = Field(description="Başlangıç zamanı")
    end_time: Optional[datetime] = Field(default=None, description="Bitiş zamanı")
    duration_ms: Optional[float] = Field(default=None, description="Toplam süre (ms)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Ek bilgiler")
    
    # Turkish messages
    messages: Dict[str, str] = Field(default_factory=lambda: {
        "batch_created": "Toplu işlem oluşturuldu",
        "batch_started": "Toplu işlem başladı",
        "batch_completed": "Toplu işlem tamamlandı",
        "batch_failed": "Toplu işlem başarısız",
        "item_processing": "Öğe işleniyor",
        "item_completed": "Öğe tamamlandı",
        "item_failed": "Öğe başarısız"
    })


class ProgressTracker:
    """Track batch processing progress in Redis."""
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialize progress tracker."""
        self.redis = redis_client
        self._local_progress: Dict[str, Dict[str, Any]] = {}
    
    async def init_batch(self, batch_id: str, total_items: int) -> None:
        """Initialize batch progress."""
        progress_data = {
            "batch_id": batch_id,
            "total": total_items,
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "current_item": None,
            "start_time": datetime.now(UTC).isoformat(),
            "status": BatchStatus.CREATED.value
        }
        
        if self.redis:
            try:
                await self.redis.hset(
                    f"batch:progress:{batch_id}",
                    mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) 
                            for k, v in progress_data.items()}
                )
                await self.redis.expire(f"batch:progress:{batch_id}", 86400)  # 24 hours
            except Exception as e:
                logger.warning(f"Redis bağlantı hatası, yerel takip kullanılıyor: {e}")
                self._local_progress[batch_id] = progress_data
        else:
            self._local_progress[batch_id] = progress_data
    
    async def update_progress(
        self,
        batch_id: str,
        processed: int = 0,
        successful: int = 0,
        failed: int = 0,
        skipped: int = 0,
        current_item: Optional[str] = None,
        status: Optional[BatchStatus] = None
    ) -> None:
        """Update batch progress."""
        if self.redis:
            try:
                updates = {}
                if processed > 0:
                    await self.redis.hincrby(f"batch:progress:{batch_id}", "processed", processed)
                if successful > 0:
                    await self.redis.hincrby(f"batch:progress:{batch_id}", "successful", successful)
                if failed > 0:
                    await self.redis.hincrby(f"batch:progress:{batch_id}", "failed", failed)
                if skipped > 0:
                    await self.redis.hincrby(f"batch:progress:{batch_id}", "skipped", skipped)
                if current_item is not None:
                    updates["current_item"] = current_item
                if status is not None:
                    updates["status"] = status.value
                
                if updates:
                    await self.redis.hset(
                        f"batch:progress:{batch_id}",
                        mapping=updates
                    )
            except Exception as e:
                logger.warning(f"Redis güncelleme hatası: {e}")
                self._update_local_progress(
                    batch_id, processed, successful, failed, skipped, current_item, status
                )
        else:
            self._update_local_progress(
                batch_id, processed, successful, failed, skipped, current_item, status
            )
    
    def _update_local_progress(
        self,
        batch_id: str,
        processed: int,
        successful: int,
        failed: int,
        skipped: int,
        current_item: Optional[str],
        status: Optional[BatchStatus]
    ) -> None:
        """Update local progress tracking."""
        if batch_id in self._local_progress:
            progress = self._local_progress[batch_id]
            progress["processed"] += processed
            progress["successful"] += successful
            progress["failed"] += failed
            progress["skipped"] += skipped
            if current_item is not None:
                progress["current_item"] = current_item
            if status is not None:
                progress["status"] = status.value
    
    async def get_progress(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get current batch progress."""
        if self.redis:
            try:
                data = await self.redis.hgetall(f"batch:progress:{batch_id}")
                if data:
                    return {
                        k.decode() if isinstance(k, bytes) else k: 
                        json.loads(v.decode()) if isinstance(v, bytes) and v.decode().startswith(('[', '{')) 
                        else v.decode() if isinstance(v, bytes) else v
                        for k, v in data.items()
                    }
            except Exception as e:
                logger.warning(f"Redis okuma hatası: {e}")
                return self._local_progress.get(batch_id)
        return self._local_progress.get(batch_id)


class ResultAggregator:
    """Aggregate batch processing results."""
    
    def aggregate(
        self,
        results: List[Any],
        batch_id: str,
        options: BatchOptions
    ) -> BatchResult:
        """Aggregate individual results into batch result."""
        successful = []
        failed = []
        errors = {}
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed.append(i)
                errors[str(i)] = str(result)
            elif isinstance(result, dict) and "error" in result:
                failed.append(i)
                errors[str(i)] = result["error"]
            else:
                successful.append(result)
        
        return BatchResult(
            batch_id=batch_id,
            status=BatchStatus.COMPLETED if len(successful) > 0 else BatchStatus.FAILED,
            total_items=len(results),
            processed_items=len(results),
            successful_items=len(successful),
            failed_items=len(failed),
            skipped_items=0,
            results=successful if options.save_results else [],
            errors=errors,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC)
        )


class ResourceMonitor:
    """Monitor system resources for adaptive processing."""
    
    @classmethod
    def get_optimal_workers(cls, item_count: int, cpu_intensive: bool = False) -> int:
        """Calculate optimal number of workers."""
        cpu_count = os.cpu_count() or 4
        
        if cpu_intensive:
            # For CPU-intensive tasks, use fewer workers
            optimal = min(cpu_count, item_count)
        else:
            # For I/O-bound tasks, can use more workers
            optimal = min(cpu_count * 2, item_count, 16)
        
        return max(1, optimal)
    
    @classmethod
    async def check_memory_usage(cls) -> float:
        """Check current memory usage percentage."""
        try:
            import psutil
            memory = psutil.virtual_memory()
            return memory.percent
        except ImportError:
            # If psutil not available, assume 50% usage
            return 50.0


class BatchProcessingEngine:
    """Enterprise-grade batch processing engine."""
    
    def __init__(
        self,
        redis_client: Optional[aioredis.Redis] = None,
        max_workers: Optional[int] = None
    ):
        """
        Initialize batch processing engine.
        
        Args:
            redis_client: Redis client for progress tracking
            max_workers: Maximum number of workers
        """
        self.redis = redis_client
        self.progress_tracker = ProgressTracker(redis_client)
        self.result_aggregator = ResultAggregator()
        self.max_workers = max_workers or os.cpu_count() or 4
        self._process_pool: Optional[ProcessPoolExecutor] = None
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
    
    async def process_batch(
        self,
        items: List[BatchItem[T]],
        operation: Callable[[T], R],
        options: Optional[BatchOptions] = None
    ) -> BatchResult[R]:
        """
        Process batch of items with specified operation.
        
        Args:
            items: List of batch items to process
            operation: Function to apply to each item
            options: Batch processing options
            
        Returns:
            Batch processing result
        """
        with create_span("batch_process") as span:
            batch_id = str(uuid.uuid4())
            options = options or BatchOptions()
            
            span.set_attribute("batch_id", batch_id)
            span.set_attribute("item_count", len(items))
            span.set_attribute("strategy", options.strategy.value)
            
            # Initialize tracking
            if options.track_progress:
                await self.progress_tracker.init_batch(batch_id, len(items))
                await self.progress_tracker.update_progress(
                    batch_id, status=BatchStatus.RUNNING
                )
            
            start_time = time.perf_counter()
            
            try:
                # Determine processing strategy
                if options.strategy == ProcessingStrategy.ADAPTIVE:
                    max_workers = ResourceMonitor.get_optimal_workers(
                        len(items), options.use_process_pool
                    )
                else:
                    max_workers = options.max_workers or self.max_workers
                
                # Sort items by priority if needed
                if options.priority_queue:
                    items = sorted(items, key=lambda x: x.priority, reverse=True)
                
                # Process items based on strategy
                if options.strategy == ProcessingStrategy.SEQUENTIAL:
                    results = await self._process_sequential(
                        batch_id, items, operation, options
                    )
                elif options.strategy == ProcessingStrategy.CHUNKED:
                    results = await self._process_chunked(
                        batch_id, items, operation, options, max_workers
                    )
                else:  # PARALLEL, ADAPTIVE, PRIORITY
                    results = await self._process_parallel(
                        batch_id, items, operation, options, max_workers
                    )
                
                # Aggregate results
                batch_result = self.result_aggregator.aggregate(
                    results, batch_id, options
                )
                
                # Update final metrics
                duration_ms = (time.perf_counter() - start_time) * 1000
                batch_result.duration_ms = duration_ms
                
                if options.track_progress:
                    await self.progress_tracker.update_progress(
                        batch_id, status=BatchStatus.COMPLETED
                    )
                
                # Record metrics
                batch_counter.labels(
                    operation="batch_process",
                    status="success" if batch_result.successful_items > 0 else "error"
                ).inc()
                
                batch_duration_histogram.labels(
                    operation="batch_process"
                ).observe(duration_ms)
                
                logger.info(
                    f"Toplu işlem tamamlandı: {batch_id}, "
                    f"Başarılı: {batch_result.successful_items}/{batch_result.total_items}, "
                    f"Süre: {duration_ms:.2f}ms"
                )
                
                return batch_result
                
            except Exception as e:
                logger.error(f"Toplu işlem hatası {batch_id}: {e}")
                
                if options.track_progress:
                    await self.progress_tracker.update_progress(
                        batch_id, status=BatchStatus.FAILED
                    )
                
                batch_counter.labels(
                    operation="batch_process",
                    status="error"
                ).inc()
                
                # Return error result
                return BatchResult(
                    batch_id=batch_id,
                    status=BatchStatus.FAILED,
                    total_items=len(items),
                    processed_items=0,
                    successful_items=0,
                    failed_items=len(items),
                    skipped_items=0,
                    errors={"batch_error": str(e)},
                    start_time=datetime.now(UTC),
                    end_time=datetime.now(UTC),
                    duration_ms=(time.perf_counter() - start_time) * 1000
                )
    
    async def _process_sequential(
        self,
        batch_id: str,
        items: List[BatchItem[T]],
        operation: Callable[[T], R],
        options: BatchOptions
    ) -> List[R]:
        """Process items sequentially."""
        results = []
        
        for i, item in enumerate(items):
            try:
                if options.track_progress:
                    await self.progress_tracker.update_progress(
                        batch_id, current_item=item.id
                    )
                
                # Process with timeout
                result = await asyncio.wait_for(
                    self._process_single_item(item, operation, options),
                    timeout=options.timeout_per_item_s
                )
                
                results.append(result)
                
                if options.track_progress:
                    await self.progress_tracker.update_progress(
                        batch_id, processed=1, successful=1
                    )
                
            except asyncio.TimeoutError:
                error_msg = f"Zaman aşımı: {item.id}"
                logger.error(error_msg)
                results.append(Exception(error_msg))
                
                if options.track_progress:
                    await self.progress_tracker.update_progress(
                        batch_id, processed=1, failed=1
                    )
                
                if not options.continue_on_error:
                    break
                    
            except Exception as e:
                logger.error(f"İşlem hatası {item.id}: {e}")
                results.append(e)
                
                if options.track_progress:
                    await self.progress_tracker.update_progress(
                        batch_id, processed=1, failed=1
                    )
                
                if not options.continue_on_error:
                    break
        
        return results
    
    async def _process_parallel(
        self,
        batch_id: str,
        items: List[BatchItem[T]],
        operation: Callable[[T], R],
        options: BatchOptions,
        max_workers: int
    ) -> List[R]:
        """Process items in parallel."""
        # Create semaphore for this batch
        if batch_id not in self._semaphores:
            self._semaphores[batch_id] = asyncio.Semaphore(max_workers)
        
        semaphore = self._semaphores[batch_id]
        
        async def process_with_semaphore(item: BatchItem[T]) -> R:
            async with semaphore:
                try:
                    if options.track_progress:
                        await self.progress_tracker.update_progress(
                            batch_id, current_item=item.id
                        )
                    
                    result = await asyncio.wait_for(
                        self._process_single_item(item, operation, options),
                        timeout=options.timeout_per_item_s
                    )
                    
                    if options.track_progress:
                        await self.progress_tracker.update_progress(
                            batch_id, processed=1, successful=1
                        )
                    
                    return result
                    
                except asyncio.TimeoutError:
                    error_msg = f"Zaman aşımı: {item.id}"
                    logger.error(error_msg)
                    
                    if options.track_progress:
                        await self.progress_tracker.update_progress(
                            batch_id, processed=1, failed=1
                        )
                    
                    if options.continue_on_error:
                        return Exception(error_msg)
                    raise
                    
                except Exception as e:
                    logger.error(f"İşlem hatası {item.id}: {e}")
                    
                    if options.track_progress:
                        await self.progress_tracker.update_progress(
                            batch_id, processed=1, failed=1
                        )
                    
                    if options.continue_on_error:
                        return e
                    raise
        
        # Process all items in parallel
        tasks = [process_with_semaphore(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=options.continue_on_error)
        
        # Clean up semaphore
        del self._semaphores[batch_id]
        
        return results
    
    async def _process_chunked(
        self,
        batch_id: str,
        items: List[BatchItem[T]],
        operation: Callable[[T], R],
        options: BatchOptions,
        max_workers: int
    ) -> List[R]:
        """Process items in chunks."""
        results = []
        chunk_size = options.chunk_size
        
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            chunk_results = await self._process_parallel(
                batch_id, chunk, operation, options, max_workers
            )
            results.extend(chunk_results)
            
            # Brief pause between chunks to avoid overwhelming the system
            if i + chunk_size < len(items):
                await asyncio.sleep(0.1)
        
        return results
    
    async def _process_single_item(
        self,
        item: BatchItem[T],
        operation: Callable[[T], R],
        options: BatchOptions
    ) -> R:
        """Process single item with retry logic."""
        last_error = None
        
        for attempt in range(options.max_retries + 1):
            try:
                item.status = BatchItemStatus.PROCESSING
                start_time = time.perf_counter()
                
                # Execute operation
                if asyncio.iscoroutinefunction(operation):
                    result = await operation(item.data)
                else:
                    # Run sync operation in thread pool
                    loop = asyncio.get_event_loop()
                    if options.use_process_pool:
                        # For CPU-intensive tasks
                        if not self._process_pool:
                            self._process_pool = ProcessPoolExecutor(max_workers=self.max_workers)
                        result = await loop.run_in_executor(self._process_pool, operation, item.data)
                    else:
                        # For I/O-bound tasks
                        if not self._thread_pool:
                            self._thread_pool = ThreadPoolExecutor(max_workers=self.max_workers * 2)
                        result = await loop.run_in_executor(self._thread_pool, operation, item.data)
                
                # Update item status
                item.status = BatchItemStatus.COMPLETED
                item.result = result
                item.processing_time_ms = (time.perf_counter() - start_time) * 1000
                
                return result
                
            except Exception as e:
                last_error = e
                item.retries = attempt + 1
                item.error = str(e)
                
                if attempt < options.max_retries:
                    item.status = BatchItemStatus.RETRYING
                    # Exponential backoff with jitter
                    delay = (options.retry_delay_ms / 1000) * (2 ** attempt) + (0.1 * attempt)
                    await asyncio.sleep(delay)
                else:
                    item.status = BatchItemStatus.FAILED
                    raise last_error
        
        raise last_error or Exception("İşlem başarısız")
    
    def partition_items(
        self,
        items: List[BatchItem[T]],
        partition_count: int
    ) -> List[List[BatchItem[T]]]:
        """Partition items for distributed processing."""
        if partition_count <= 1:
            return [items]
        
        partitions = [[] for _ in range(partition_count)]
        
        # Distribute items round-robin
        for i, item in enumerate(items):
            partition_idx = i % partition_count
            partitions[partition_idx].append(item)
        
        return partitions
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        if self._process_pool:
            self._process_pool.shutdown(wait=False)
            self._process_pool = None
        
        if self._thread_pool:
            self._thread_pool.shutdown(wait=False)
            self._thread_pool = None
        
        self._semaphores.clear()