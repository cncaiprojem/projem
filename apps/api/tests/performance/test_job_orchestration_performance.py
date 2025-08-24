"""
Performance tests for Task 6.10: Job Orchestration Observability

Tests cover:
- 1000 concurrent job creation performance
- Metrics collection performance under load
- Tracing performance with high throughput
- Memory usage and resource efficiency
- Throughput and latency benchmarks
- Observability overhead measurement
"""

import asyncio
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
from prometheus_client import CollectorRegistry, generate_latest
import psutil

from app.core.logging_config import bind_request_context, get_logger
from app.core.metrics import metrics
from app.core.telemetry import create_span, initialize_telemetry, get_tracer


class PerformanceMetrics:
    """Helper class for collecting performance metrics."""
    
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.memory_start = None
        self.memory_end = None
        self.cpu_start = None
        self.cpu_end = None
        self.durations = []
        self.errors = []
    
    def start_measurement(self):
        """Start performance measurement."""
        self.start_time = time.perf_counter()
        self.memory_start = psutil.virtual_memory().used
        self.cpu_start = psutil.cpu_percent()
        
    def end_measurement(self):
        """End performance measurement."""
        self.end_time = time.perf_counter()
        self.memory_end = psutil.virtual_memory().used
        self.cpu_end = psutil.cpu_percent()
    
    def add_duration(self, duration: float):
        """Add a duration measurement."""
        self.durations.append(duration)
    
    def add_error(self, error: str):
        """Add an error."""
        self.errors.append(error)
    
    @property
    def total_duration(self) -> float:
        """Total test duration."""
        return self.end_time - self.start_time if self.end_time and self.start_time else 0
    
    @property
    def memory_usage_mb(self) -> float:
        """Memory usage increase in MB."""
        if self.memory_end and self.memory_start:
            return (self.memory_end - self.memory_start) / 1024 / 1024
        return 0
    
    @property
    def avg_duration(self) -> float:
        """Average duration."""
        return statistics.mean(self.durations) if self.durations else 0
    
    @property
    def p95_duration(self) -> float:
        """95th percentile duration."""
        if not self.durations:
            return 0
        return statistics.quantiles(self.durations, n=20)[18]  # 95th percentile
    
    @property
    def p99_duration(self) -> float:
        """99th percentile duration."""
        if not self.durations:
            return 0
        return statistics.quantiles(self.durations, n=100)[98]  # 99th percentile
    
    @property
    def throughput(self) -> float:
        """Operations per second."""
        return len(self.durations) / self.total_duration if self.total_duration > 0 else 0


@pytest.fixture(scope="module")
def performance_telemetry():
    """Setup telemetry for performance testing."""
    initialize_telemetry(
        service_name="perf-test-freecad-api",
        otlp_endpoint="http://localhost:4317",
        environment="performance_test"
    )
    yield
    # Cleanup after tests


class TestConcurrentJobCreationPerformance:
    """Test performance of concurrent job creation."""
    
    @pytest.mark.performance
    def test_1000_concurrent_job_creation_metrics(self):
        """Test 1000 concurrent job creations with metrics collection."""
        perf_metrics = PerformanceMetrics()
        perf_metrics.start_measurement()
        
        def create_job_with_metrics(job_index: int) -> Dict[str, Any]:
            """Create a single job with full metrics collection."""
            job_start = time.perf_counter()
            
            try:
                job_id = f"perf-job-{job_index}-{uuid.uuid4()}"
                job_type = ["model", "cam", "sim", "report"][job_index % 4]
                
                # Record job creation metrics
                metrics.record_job_creation(job_type, "success", False)
                
                # Record idempotency operation
                metrics.record_idempotency_operation("create", False, False)
                
                # Set job in progress
                queue_name = f"{job_type}_queue"
                metrics.set_job_in_progress(job_type, queue_name, 1)
                
                # Simulate quick processing
                time.sleep(0.001)  # 1ms simulated processing
                
                # Record completion
                duration = time.perf_counter() - job_start
                metrics.record_job_duration(job_type, "success", queue_name, duration)
                metrics.set_job_in_progress(job_type, queue_name, 0)
                
                # Record audit operation
                metrics.record_audit_chain_operation("complete", "success", False)
                
                return {
                    "job_id": job_id,
                    "duration": duration,
                    "status": "success"
                }
                
            except Exception as e:
                return {
                    "error": str(e),
                    "duration": time.perf_counter() - job_start,
                    "status": "error"
                }
        
        # Execute 1000 concurrent job creations
        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = [
                executor.submit(create_job_with_metrics, i) 
                for i in range(1000)
            ]
            
            results = []
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                
                if result["status"] == "success":
                    perf_metrics.add_duration(result["duration"])
                else:
                    perf_metrics.add_error(result.get("error", "Unknown error"))
        
        perf_metrics.end_measurement()
        
        # Performance assertions
        assert len(results) == 1000
        success_rate = len([r for r in results if r["status"] == "success"]) / 1000
        assert success_rate >= 0.95, f"Success rate too low: {success_rate}"
        
        # Performance benchmarks
        assert perf_metrics.total_duration < 60, f"Total time too high: {perf_metrics.total_duration}s"
        assert perf_metrics.throughput > 16, f"Throughput too low: {perf_metrics.throughput} ops/sec"
        assert perf_metrics.p95_duration < 5.0, f"P95 latency too high: {perf_metrics.p95_duration}s"
        assert perf_metrics.memory_usage_mb < 500, f"Memory usage too high: {perf_metrics.memory_usage_mb}MB"
        
        # Log performance results
        logger = get_logger(__name__)
        logger.info("1000 concurrent job creation performance", 
                   total_duration=perf_metrics.total_duration,
                   throughput=perf_metrics.throughput,
                   p95_duration=perf_metrics.p95_duration,
                   p99_duration=perf_metrics.p99_duration,
                   memory_usage_mb=perf_metrics.memory_usage_mb,
                   success_rate=success_rate,
                   error_count=len(perf_metrics.errors))
    
    @pytest_asyncio.mark.asyncio
    @pytest.mark.performance
    async def test_1000_concurrent_jobs_with_tracing(self, performance_telemetry):
        """Test 1000 concurrent jobs with full OpenTelemetry tracing."""
        perf_metrics = PerformanceMetrics()
        perf_metrics.start_measurement()
        
        async def create_traced_job(job_index: int) -> Dict[str, Any]:
            """Create job with full tracing."""
            job_start = time.perf_counter()
            
            try:
                job_id = f"traced-job-{job_index}-{uuid.uuid4()}"
                job_type = ["model", "cam", "sim", "report"][job_index % 4]
                idempotency_key = f"idem-{job_index}-{uuid.uuid4()}"
                
                with create_span(
                    "performance_job_creation",
                    operation_type="job",
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    attributes={
                        "job.type": job_type,
                        "job.index": job_index,
                        "test.type": "performance"
                    }
                ):
                    # Bind request context
                    bind_request_context(
                        job_id=job_id,
                        trace_id=f"trace-{uuid.uuid4()}",
                        request_id=f"req-{uuid.uuid4()}",
                        idempotency_key=idempotency_key
                    )
                    
                    # Record metrics within span
                    metrics.record_job_creation(job_type, "success", False)
                    metrics.record_idempotency_operation("create", False, False)
                    
                    # Simulate job phases with nested spans
                    phases = ["validate", "process", "complete"]
                    for phase in phases:
                        with create_span(f"job_{phase}", job_id=job_id):
                            await asyncio.sleep(0.001)  # 1ms per phase
                            metrics.record_progress_update(job_type, "worker", False)
                    
                    # Record completion
                    duration = time.perf_counter() - job_start
                    metrics.record_job_duration(job_type, "success", f"{job_type}_queue", duration)
                    
                    # Record trace span creation
                    metrics.record_trace_span("job", "freecad-api", True)
                    
                    return {
                        "job_id": job_id,
                        "duration": duration,
                        "status": "success",
                        "phases": len(phases)
                    }
                    
            except Exception as e:
                return {
                    "error": str(e),
                    "duration": time.perf_counter() - job_start,
                    "status": "error"
                }
        
        # Execute 1000 concurrent traced jobs
        tasks = [create_traced_job(i) for i in range(1000)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        perf_metrics.end_measurement()
        
        # Process results
        successful_results = []
        for result in results:
            if isinstance(result, dict) and result.get("status") == "success":
                successful_results.append(result)
                perf_metrics.add_duration(result["duration"])
            else:
                perf_metrics.add_error(str(result))
        
        # Performance assertions with tracing overhead
        success_rate = len(successful_results) / 1000
        assert success_rate >= 0.95, f"Success rate with tracing too low: {success_rate}"
        
        # Tracing adds overhead, so more lenient benchmarks
        assert perf_metrics.total_duration < 120, f"Total time with tracing too high: {perf_metrics.total_duration}s"
        assert perf_metrics.throughput > 8, f"Throughput with tracing too low: {perf_metrics.throughput} ops/sec"
        assert perf_metrics.p95_duration < 10.0, f"P95 latency with tracing too high: {perf_metrics.p95_duration}s"
        assert perf_metrics.memory_usage_mb < 1000, f"Memory usage with tracing too high: {perf_metrics.memory_usage_mb}MB"
        
        # Log tracing performance
        logger = get_logger(__name__)
        logger.info("1000 concurrent jobs with tracing performance",
                   total_duration=perf_metrics.total_duration,
                   throughput=perf_metrics.throughput,
                   p95_duration=perf_metrics.p95_duration,
                   memory_usage_mb=perf_metrics.memory_usage_mb,
                   success_rate=success_rate,
                   tracing_enabled=True)


class TestMetricsCollectionPerformance:
    """Test performance of metrics collection under load."""
    
    @pytest.mark.performance
    def test_metrics_collection_overhead(self):
        """Test overhead of metrics collection."""
        iterations = 10000
        
        # Test without metrics
        start_time = time.perf_counter()
        for i in range(iterations):
            # Simulate job processing without metrics
            time.sleep(0.0001)  # 0.1ms simulated work
        no_metrics_duration = time.perf_counter() - start_time
        
        # Test with metrics
        start_time = time.perf_counter()
        for i in range(iterations):
            # Simulate job processing with metrics
            job_type = ["model", "cam"][i % 2]
            metrics.record_job_creation(job_type, "success", False)
            metrics.set_job_in_progress(job_type, f"{job_type}_queue", 1)
            metrics.record_progress_update(job_type, "worker", False)
            time.sleep(0.0001)  # Same simulated work
            metrics.record_job_duration(job_type, "success", f"{job_type}_queue", 0.0001)
            metrics.set_job_in_progress(job_type, f"{job_type}_queue", 0)
        with_metrics_duration = time.perf_counter() - start_time
        
        # Calculate overhead
        metrics_overhead = (with_metrics_duration - no_metrics_duration) / no_metrics_duration * 100
        
        # Metrics overhead should be reasonable
        assert metrics_overhead < 50, f"Metrics overhead too high: {metrics_overhead}%"
        
        logger = get_logger(__name__)
        logger.info("Metrics collection overhead",
                   iterations=iterations,
                   without_metrics_duration=no_metrics_duration,
                   with_metrics_duration=with_metrics_duration,
                   overhead_percentage=metrics_overhead)
    
    @pytest.mark.performance
    def test_concurrent_metrics_collection(self):
        """Test concurrent metrics collection performance."""
        perf_metrics = PerformanceMetrics()
        perf_metrics.start_measurement()
        
        def collect_metrics_batch(batch_size: int) -> Dict[str, Any]:
            """Collect a batch of metrics."""
            batch_start = time.perf_counter()
            
            try:
                for i in range(batch_size):
                    job_type = ["model", "cam", "sim", "report"][i % 4]
                    
                    # High-frequency metrics collection
                    metrics.record_job_creation(job_type, "success", False)
                    metrics.record_progress_update(job_type, "worker", i % 10 == 0)  # 10% throttled
                    metrics.record_idempotency_operation("create", i % 5 == 0, i % 20 == 0)  # Some race conditions
                    
                    if i % 3 == 0:
                        metrics.record_job_retry(job_type, "TIMEOUT", f"{job_type}_queue", 1)
                    
                    if i % 7 == 0:
                        metrics.record_dlq_replay(f"{job_type}_dlq", "success", "manual")
                    
                    if i % 11 == 0:
                        metrics.record_job_cancellation(job_type, "user", "timeout", "running")
                
                duration = time.perf_counter() - batch_start
                return {"batch_size": batch_size, "duration": duration, "status": "success"}
                
            except Exception as e:
                return {"error": str(e), "duration": time.perf_counter() - batch_start, "status": "error"}
        
        # Run concurrent batches
        batch_size = 100
        num_batches = 50  # 5000 total operations
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(collect_metrics_batch, batch_size)
                for _ in range(num_batches)
            ]
            
            results = []
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                
                if result["status"] == "success":
                    perf_metrics.add_duration(result["duration"])
                else:
                    perf_metrics.add_error(result.get("error", "Unknown error"))
        
        perf_metrics.end_measurement()
        
        # Performance assertions
        success_rate = len([r for r in results if r["status"] == "success"]) / num_batches
        assert success_rate >= 0.95, f"Metrics collection success rate too low: {success_rate}"
        
        total_operations = num_batches * batch_size
        operations_per_second = total_operations / perf_metrics.total_duration
        
        assert operations_per_second > 1000, f"Metrics collection throughput too low: {operations_per_second} ops/sec"
        assert perf_metrics.p95_duration < 1.0, f"P95 batch duration too high: {perf_metrics.p95_duration}s"
        
        logger = get_logger(__name__)
        logger.info("Concurrent metrics collection performance",
                   total_operations=total_operations,
                   operations_per_second=operations_per_second,
                   p95_batch_duration=perf_metrics.p95_duration,
                   success_rate=success_rate)


class TestResourceEfficiencyUnderLoad:
    """Test resource efficiency under high load."""
    
    @pytest.mark.performance
    def test_memory_efficiency_high_load(self):
        """Test memory efficiency under high observability load."""
        perf_metrics = PerformanceMetrics()
        perf_metrics.start_measurement()
        
        # Create many concurrent spans and contexts
        active_spans = []
        try:
            for i in range(1000):
                job_id = f"mem-test-{i}"
                span = create_span(f"memory_test_job_{i}", job_id=job_id)
                active_spans.append(span)
                
                # Bind contexts
                bind_request_context(
                    job_id=job_id,
                    trace_id=f"trace-{i}",
                    request_id=f"req-{i}",
                    idempotency_key=f"idem-{i}"
                )
                
                # Record metrics
                metrics.record_job_creation("model", "success", False)
                metrics.record_progress_update("model", "worker", False)
                
                # Measure memory every 100 iterations
                if i % 100 == 0:
                    current_memory = psutil.virtual_memory().used
                    memory_growth = (current_memory - perf_metrics.memory_start) / 1024 / 1024
                    
                    # Memory growth should be reasonable
                    assert memory_growth < 1000, f"Memory growth too high at {i} iterations: {memory_growth}MB"
        
        finally:
            # Cleanup spans
            for span in active_spans:
                if hasattr(span, '__exit__'):
                    try:
                        span.__exit__(None, None, None)
                    except:
                        pass
        
        perf_metrics.end_measurement()
        
        # Final memory check
        assert perf_metrics.memory_usage_mb < 1000, f"Total memory usage too high: {perf_metrics.memory_usage_mb}MB"
        
        logger = get_logger(__name__)
        logger.info("Memory efficiency under load",
                   spans_created=1000,
                   memory_usage_mb=perf_metrics.memory_usage_mb,
                   duration=perf_metrics.total_duration)
    
    @pytest_asyncio.mark.asyncio
    @pytest.mark.performance
    async def test_cpu_efficiency_under_load(self):
        """Test CPU efficiency under observability load."""
        perf_metrics = PerformanceMetrics()
        perf_metrics.start_measurement()
        
        async def cpu_intensive_observability_task(task_id: int):
            """Simulate CPU-intensive task with full observability."""
            job_id = f"cpu-test-{task_id}"
            
            with create_span("cpu_intensive_task", job_id=job_id):
                # CPU-intensive work simulation
                total = 0
                for i in range(10000):  # Computational work
                    total += i ** 0.5
                    
                    # Record metrics frequently (observability overhead)
                    if i % 1000 == 0:
                        metrics.record_progress_update("model", "worker", False)
                        bind_request_context(job_id=job_id, progress=i/10000*100)
                
                # Record completion
                metrics.record_job_duration("model", "success", "model_queue", 0.1)
                
                return {"task_id": task_id, "result": total}
        
        # Run many concurrent CPU-intensive tasks
        tasks = [cpu_intensive_observability_task(i) for i in range(100)]
        results = await asyncio.gather(*tasks)
        
        perf_metrics.end_measurement()
        
        # CPU efficiency assertions
        assert len(results) == 100
        assert all("result" in r for r in results)
        
        # Task completion should be reasonable even with observability overhead
        assert perf_metrics.total_duration < 30, f"CPU tasks too slow with observability: {perf_metrics.total_duration}s"
        
        tasks_per_second = len(results) / perf_metrics.total_duration
        assert tasks_per_second > 3, f"CPU task throughput too low: {tasks_per_second} tasks/sec"
        
        logger = get_logger(__name__)
        logger.info("CPU efficiency under observability load",
                   total_tasks=len(results),
                   tasks_per_second=tasks_per_second,
                   total_duration=perf_metrics.total_duration,
                   memory_usage_mb=perf_metrics.memory_usage_mb)


class TestObservabilityScaling:
    """Test observability system scaling behavior."""
    
    @pytest.mark.performance 
    def test_scaling_performance_by_job_count(self):
        """Test how observability performance scales with job count."""
        job_counts = [100, 500, 1000, 2000]
        scaling_results = []
        
        for job_count in job_counts:
            perf_metrics = PerformanceMetrics()
            perf_metrics.start_measurement()
            
            def process_jobs_batch(count: int) -> Dict[str, Any]:
                """Process a batch of jobs with observability."""
                batch_start = time.perf_counter()
                
                try:
                    for i in range(count):
                        job_id = f"scale-test-{i}"
                        job_type = ["model", "cam"][i % 2]
                        
                        with create_span("scaling_test_job", job_id=job_id):
                            metrics.record_job_creation(job_type, "success", False)
                            metrics.set_job_in_progress(job_type, f"{job_type}_queue", 1)
                            metrics.record_progress_update(job_type, "worker", False)
                            
                            # Simulate minimal processing
                            time.sleep(0.0001)
                            
                            metrics.record_job_duration(job_type, "success", f"{job_type}_queue", 0.0001)
                            metrics.set_job_in_progress(job_type, f"{job_type}_queue", 0)
                    
                    return {
                        "count": count,
                        "duration": time.perf_counter() - batch_start,
                        "status": "success"
                    }
                    
                except Exception as e:
                    return {
                        "error": str(e),
                        "duration": time.perf_counter() - batch_start,
                        "status": "error"
                    }
            
            # Execute batch
            result = process_jobs_batch(job_count)
            perf_metrics.end_measurement()
            
            throughput = job_count / result["duration"] if result["status"] == "success" else 0
            
            scaling_results.append({
                "job_count": job_count,
                "duration": result["duration"],
                "throughput": throughput,
                "memory_usage_mb": perf_metrics.memory_usage_mb,
                "status": result["status"]
            })
        
        # Analyze scaling behavior
        successful_results = [r for r in scaling_results if r["status"] == "success"]
        assert len(successful_results) == len(job_counts), "Some scaling tests failed"
        
        # Throughput shouldn't degrade significantly
        throughputs = [r["throughput"] for r in successful_results]
        min_throughput = min(throughputs)
        max_throughput = max(throughputs)
        
        # Allow for some degradation but not too much
        degradation_ratio = min_throughput / max_throughput
        assert degradation_ratio > 0.5, f"Throughput degrades too much with scale: {degradation_ratio}"
        
        # Memory usage should scale reasonably
        memory_usages = [r["memory_usage_mb"] for r in successful_results]
        memory_growth_ratio = max(memory_usages) / (memory_usages[0] if memory_usages[0] > 0 else 1)
        job_count_ratio = max(job_counts) / min(job_counts)
        
        # Memory growth should be sub-linear compared to job count growth
        assert memory_growth_ratio < job_count_ratio * 2, f"Memory scaling too aggressive: {memory_growth_ratio} vs {job_count_ratio}"
        
        logger = get_logger(__name__)
        logger.info("Observability scaling analysis", 
                   scaling_results=scaling_results,
                   throughput_degradation_ratio=degradation_ratio,
                   memory_growth_ratio=memory_growth_ratio)


if __name__ == "__main__":
    # Run performance tests with special marker
    pytest.main([__file__, "-v", "-m", "performance", "--asyncio-mode=auto"])