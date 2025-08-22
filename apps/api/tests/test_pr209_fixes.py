"""
Test PR #209 fixes
Verifies all 4 issues raised in PR #209 review feedback are resolved.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from app.core.retry_config import (
    create_task_headers_with_retry_info,
    get_retry_kwargs_by_task_name,
    TASK_ROUTING_MAP,
    AI_TASK_RETRY_KWARGS,
    MODEL_TASK_RETRY_KWARGS,
    CAM_TASK_RETRY_KWARGS,
)
from app.core.dlq_handler import DLQHandler
from app.core.queue_constants import QUEUE_DEFAULT, DLQ_SUFFIX


class TestPR209Fixes:
    """Test all fixes applied for PR #209 review feedback."""
    
    def test_retry_timestamp_is_set(self):
        """
        Test Issue 1: Verify retry_timestamp is actually set when headers are created.
        Previous issue: Comment said "Will be set when task is retried" but it was None.
        """
        # Create headers with retry info
        task_id = "test-task-123"
        attempt_count = 2
        
        headers = create_task_headers_with_retry_info(
            task_id=task_id,
            attempt_count=attempt_count
        )
        
        # Verify retry_timestamp is set and not None
        assert headers['retry_timestamp'] is not None
        assert isinstance(headers['retry_timestamp'], str)
        
        # Verify it's a valid ISO format timestamp
        timestamp = datetime.fromisoformat(headers['retry_timestamp'])
        assert timestamp.tzinfo is not None  # Should have timezone info
        
        # Verify it's recent (within last minute)
        now = datetime.now(timezone.utc)
        time_diff = (now - timestamp).total_seconds()
        assert time_diff < 60  # Should be within last minute
    
    def test_dlq_routing_key_exact_match(self):
        """
        Test Issue 2: Verify DLQ uses exact routing key for direct exchange.
        Previous issue: Using '#' as routing key with direct exchange won't work.
        """
        # Mock Celery app with proper context manager
        mock_app = Mock()
        mock_producer = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_producer
        mock_app.producer_pool.acquire.return_value = mock_context
        
        # Create DLQ handler
        handler = DLQHandler(mock_app)
        
        # Test sending to DLQ
        queue_name = "model"
        dlq_name = f"{queue_name}{DLQ_SUFFIX}"
        
        with patch('app.core.dlq_handler.Exchange') as mock_exchange:
            handler.send_task_to_dlq(
                task_id="test-123",
                task_name="test.task",
                queue_name=queue_name,
                args=(),
                kwargs={},
                exc=Exception("Test error"),
                attempt_count=3,
                failure_reason="max_retries_exceeded"
            )
            
            # Verify publish was called with correct routing key
            mock_producer.publish.assert_called_once()
            call_kwargs = mock_producer.publish.call_args[1]
            
            # Should use dlq_name as routing key for direct exchange
            assert call_kwargs['routing_key'] == dlq_name
            assert call_kwargs['routing_key'] != '#'  # Not using wildcard
    
    def test_queue_default_constant_usage(self):
        """
        Test Issue 3: Verify QUEUE_DEFAULT constant is used instead of hardcoded 'default'.
        Previous issue: Line 219 used hardcoded 'default' instead of QUEUE_DEFAULT constant.
        """
        from app.core.dlq_handler import handle_task_failure
        
        # Mock task with no queue info
        mock_task = Mock()
        mock_task.name = "test.task"
        mock_task.request = Mock()
        mock_task.request.queue = None  # No queue attribute
        mock_task.request.delivery_info = {}  # No routing_key
        mock_task.request.retries = 0
        mock_task.max_retries = None
        mock_task.app = Mock()
        
        with patch('app.core.dlq_handler.DLQHandler') as mock_handler_class:
            mock_handler = Mock()
            mock_handler.should_send_to_dlq.return_value = (False, 'retryable')
            mock_handler_class.return_value = mock_handler
            
            with patch('app.core.dlq_handler.get_queue_retry_config') as mock_get_config:
                mock_get_config.return_value = {'max_retries': 3}
                
                # Call handle_task_failure
                handle_task_failure(
                    mock_task,
                    Exception("Test"),
                    "task-123",
                    (),
                    {},
                    None
                )
                
                # Verify get_queue_retry_config was called with QUEUE_DEFAULT
                mock_get_config.assert_called_with(QUEUE_DEFAULT)
    
    def test_data_driven_task_routing(self):
        """
        Test Issue 4: Verify task routing uses data-driven mapping instead of if/elif chain.
        Previous issue: Long if/elif chain was not maintainable.
        """
        # Verify TASK_ROUTING_MAP exists and is a dictionary
        assert isinstance(TASK_ROUTING_MAP, dict)
        assert len(TASK_ROUTING_MAP) > 0
        
        # Test various task name patterns using the data-driven approach
        test_cases = [
            ('app.tasks.maintenance.cleanup', AI_TASK_RETRY_KWARGS),
            ('app.tasks.cad.generate_model', MODEL_TASK_RETRY_KWARGS),
            ('app.tasks.cam.process_path', CAM_TASK_RETRY_KWARGS),
            ('app.tasks.monitoring.check_health', AI_TASK_RETRY_KWARGS),
            ('app.tasks.freecad.build', MODEL_TASK_RETRY_KWARGS),
        ]
        
        for task_name, expected_kwargs in test_cases:
            result = get_retry_kwargs_by_task_name(task_name)
            assert result == expected_kwargs, f"Failed for task: {task_name}"
        
        # Verify the mapping structure has expected keys
        for queue_type, config in TASK_ROUTING_MAP.items():
            assert 'patterns' in config
            assert 'retry_kwargs' in config
            assert isinstance(config['patterns'], list)
            assert isinstance(config['retry_kwargs'], dict)
        
        # Test extensibility - adding new pattern should be easy
        # This demonstrates the maintainability improvement
        new_queue_config = {
            'patterns': ['new_service', 'custom_task'],
            'retry_kwargs': {'max_retries': 10}
        }
        # Just showing structure is extensible, not actually modifying
        assert 'patterns' in new_queue_config
        assert 'retry_kwargs' in new_queue_config


if __name__ == "__main__":
    pytest.main([__file__, "-v"])