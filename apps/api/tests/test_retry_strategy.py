"""
Tests for Task 6.2 - Retry Strategy Implementation
Comprehensive tests for exponential backoff, jitter, error taxonomy, and DLQ handling.
"""

import pytest
import random
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from app.core.error_taxonomy import (
    TransientExternalError,
    RateLimitedError,
    NetworkError,
    ValidationError,
    UnauthorizedError,
    QuotaExceededError,
    JobCancelledError,
    IntegrityError,
    classify_error,
    should_retry_error,
    get_error_metadata
)

from app.core.retry_config import (
    calculate_retry_delay,
    get_queue_retry_config,
    get_task_time_limits,
    create_retry_decorator_kwargs,
    get_retry_kwargs_by_task_name,
    QUEUE_RETRY_CONFIG
)

from app.core.dlq_handler import (
    DLQHandler,
    handle_task_failure
)

from app.core.queue_constants import (
    QUEUE_DEFAULT,
    QUEUE_MODEL,
    QUEUE_CAM,
    QUEUE_SIM,
    QUEUE_REPORT,
    QUEUE_ERP
)


class TestErrorTaxonomy:
    """Test error classification and taxonomy."""
    
    def test_retryable_errors(self):
        """Test that retryable errors are classified correctly."""
        retryable_errors = [
            TransientExternalError("Service unavailable"),
            RateLimitedError("Rate limited", retry_after=60),
            NetworkError("Connection timeout"),
            ConnectionError("Network error"),
            TimeoutError("Request timeout"),
            OSError("I/O error")
        ]
        
        for error in retryable_errors:
            assert classify_error(error) == 'retryable'
            assert should_retry_error(error) is True
    
    def test_non_retryable_errors(self):
        """Test that non-retryable errors are classified correctly."""
        non_retryable_errors = [
            ValidationError("Invalid input"),
            UnauthorizedError("Access denied"),
            QuotaExceededError("Quota exceeded"),
            ValueError("Invalid value"),
            TypeError("Wrong type"),
            KeyError("Missing key")
        ]
        
        for error in non_retryable_errors:
            assert classify_error(error) == 'non_retryable'
            assert should_retry_error(error) is False
    
    def test_cancellation_errors(self):
        """Test that cancellation errors are classified correctly."""
        cancellation_errors = [
            JobCancelledError("Job cancelled by user"),
            KeyboardInterrupt()
        ]
        
        for error in cancellation_errors:
            assert classify_error(error) == 'cancellation'
            assert should_retry_error(error) is False
    
    def test_fatal_errors(self):
        """Test that fatal errors are classified correctly."""
        fatal_errors = [
            IntegrityError("Data integrity violation"),
            MemoryError("Out of memory"),
            SystemExit(1)
        ]
        
        for error in fatal_errors:
            assert classify_error(error) == 'fatal'
            assert should_retry_error(error) is False
    
    def test_unknown_error_defaults_to_non_retryable(self):
        """Test that unknown errors default to non-retryable."""
        class UnknownError(Exception):
            pass
        
        error = UnknownError("Unknown error")
        assert classify_error(error) == 'non_retryable'
        assert should_retry_error(error) is False
    
    def test_error_metadata_extraction(self):
        """Test error metadata extraction."""
        error = RateLimitedError(
            "Rate limited", 
            retry_after=120, 
            retry_count=2, 
            max_retries=5
        )
        
        metadata = get_error_metadata(error)
        
        assert metadata['error_type'] == 'RateLimitedError'
        assert metadata['error_message'] == 'Rate limited'
        assert metadata['error_classification'] == 'retryable'
        assert metadata['is_retryable'] is True
        assert metadata['retry_after'] == 120
        assert metadata['retry_count'] == 2
        assert metadata['max_retries'] == 5
    


class TestRetryConfiguration:
    """Test retry configuration and backoff calculations."""
    
    def test_exponential_backoff_without_jitter(self):
        """Test exponential backoff calculation without jitter."""
        base_delay = 2.0
        cap = 60.0
        
        # Test exponential growth
        assert calculate_retry_delay(0, base_delay, cap, jitter=False) == 2.0
        assert calculate_retry_delay(1, base_delay, cap, jitter=False) == 4.0
        assert calculate_retry_delay(2, base_delay, cap, jitter=False) == 8.0
        assert calculate_retry_delay(3, base_delay, cap, jitter=False) == 16.0
        assert calculate_retry_delay(4, base_delay, cap, jitter=False) == 32.0
        assert calculate_retry_delay(5, base_delay, cap, jitter=False) == 60.0  # Capped
        assert calculate_retry_delay(6, base_delay, cap, jitter=False) == 60.0  # Still capped
    
    def test_exponential_backoff_with_jitter(self):
        """Test exponential backoff with jitter."""
        base_delay = 2.0
        cap = 60.0
        
        # Test that jitter produces values in expected range
        for attempt in range(6):
            delay = calculate_retry_delay(attempt, base_delay, cap, jitter=True)
            expected_base = min(cap, base_delay * (2 ** attempt))
            min_delay = expected_base * 0.5
            max_delay = expected_base * 1.5
            
            assert min_delay <= delay <= max_delay
    
    def test_jitter_randomness(self):
        """Test that jitter produces different values."""
        delays = []
        for _ in range(10):
            delay = calculate_retry_delay(3, 2.0, 60.0, jitter=True)
            delays.append(delay)
        
        # Should have some variance due to jitter
        assert len(set(delays)) > 1
    
    def test_queue_retry_configurations(self):
        """Test that each queue has proper retry configuration."""
        # Task 6.2: Test specified retry counts and caps
        
        # AI queue: 3 retries, 20s cap
        ai_config = get_queue_retry_config(QUEUE_DEFAULT)
        assert ai_config['max_retries'] == 3
        assert ai_config['backoff_cap'] == 20
        
        # Model queue: 5 retries, 60s cap
        model_config = get_queue_retry_config(QUEUE_MODEL)
        assert model_config['max_retries'] == 5
        assert model_config['backoff_cap'] == 60
        
        # CAM queue: 5 retries, 60s cap
        cam_config = get_queue_retry_config(QUEUE_CAM)
        assert cam_config['max_retries'] == 5
        assert cam_config['backoff_cap'] == 60
        
        # Sim queue: 5 retries, 60s cap
        sim_config = get_queue_retry_config(QUEUE_SIM)
        assert sim_config['max_retries'] == 5
        assert sim_config['backoff_cap'] == 60
        
        # Report queue: 5 retries, 45s cap
        report_config = get_queue_retry_config(QUEUE_REPORT)
        assert report_config['max_retries'] == 5
        assert report_config['backoff_cap'] == 45
        
        # ERP queue: 5 retries, 45s cap
        erp_config = get_queue_retry_config(QUEUE_ERP)
        assert erp_config['max_retries'] == 5
        assert erp_config['backoff_cap'] == 45
    
    def test_time_limits_per_queue(self):
        """Test time limits configuration per queue."""
        # Task 6.2: Test time limits per task type (e.g., model 900/840s)
        
        # Model tasks: 15 min hard / 14 min soft
        soft_limit, hard_limit = get_task_time_limits(QUEUE_MODEL)
        assert soft_limit == 840  # 14 minutes
        assert hard_limit == 900  # 15 minutes
        
        # AI tasks: 10 min hard / 9 min soft
        soft_limit, hard_limit = get_task_time_limits(QUEUE_DEFAULT)
        assert soft_limit == 540  # 9 minutes
        assert hard_limit == 600  # 10 minutes
    
    def test_retry_decorator_kwargs_generation(self):
        """Test generation of Celery task decorator kwargs."""
        kwargs = create_retry_decorator_kwargs(QUEUE_MODEL)
        
        # Task 6.2: Should include all required configurations
        assert 'autoretry_for' in kwargs
        assert kwargs['max_retries'] == 5
        assert kwargs['retry_backoff'] is True
        assert kwargs['retry_backoff_max'] == 60
        assert kwargs['retry_jitter'] is True
        assert kwargs['acks_late'] is True
        assert kwargs['reject_on_worker_lost'] is True
        assert kwargs['time_limit'] == 900
        assert kwargs['soft_time_limit'] == 840
        assert kwargs['track_started'] is True
    
    def test_task_name_to_retry_kwargs_mapping(self):
        """Test mapping task names to appropriate retry configurations."""
        # Test different task name patterns
        test_cases = [
            ('app.tasks.cad.generate_model', 5),  # Model queue
            ('app.tasks.cam.process_toolpath', 5),  # CAM queue
            ('app.tasks.sim.run_simulation', 5),  # Sim queue
            ('app.tasks.reports.generate_pdf', 5),  # Report queue
            ('app.tasks.maintenance.cleanup', 3),  # AI queue
            ('app.tasks.unknown.task', 3),  # Default to AI queue
        ]
        
        for task_name, expected_retries in test_cases:
            kwargs = get_retry_kwargs_by_task_name(task_name)
            assert kwargs['max_retries'] == expected_retries


class TestDLQHandler:
    """Test Dead Letter Queue handling."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_celery_app = Mock()
        self.mock_producer_pool = Mock()
        self.mock_celery_app.producer_pool = self.mock_producer_pool
        self.dlq_handler = DLQHandler(self.mock_celery_app)
    
    def test_should_send_to_dlq_fatal_error(self):
        """Test that fatal errors immediately go to DLQ."""
        error = IntegrityError("Data corruption")
        should_dlq, reason = self.dlq_handler.should_send_to_dlq(error, 1, 5)
        
        assert should_dlq is True
        assert reason == 'fatal_error'
    
    def test_should_send_to_dlq_non_retryable(self):
        """Test that non-retryable errors go to DLQ."""
        error = ValidationError("Invalid input")
        should_dlq, reason = self.dlq_handler.should_send_to_dlq(error, 1, 5)
        
        assert should_dlq is True
        assert reason == 'non_retryable_error'
    
    def test_should_send_to_dlq_cancellation(self):
        """Test that cancellation errors don't go to DLQ."""
        error = JobCancelledError("User cancelled")
        should_dlq, reason = self.dlq_handler.should_send_to_dlq(error, 1, 5)
        
        assert should_dlq is False
        assert reason == 'cancelled'
    
    def test_should_send_to_dlq_retryable_under_limit(self):
        """Test that retryable errors under limit don't go to DLQ."""
        error = NetworkError("Connection failed")
        should_dlq, reason = self.dlq_handler.should_send_to_dlq(error, 3, 5)
        
        assert should_dlq is False
        assert reason == 'retryable'
    
    def test_should_send_to_dlq_retryable_exceeded_limit(self):
        """Test that retryable errors exceeding limit go to DLQ."""
        error = NetworkError("Connection failed")
        should_dlq, reason = self.dlq_handler.should_send_to_dlq(error, 5, 5)
        
        assert should_dlq is True
        assert reason == 'max_retries_exceeded'