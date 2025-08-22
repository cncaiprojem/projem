"""
Retry Configuration for Task 6.2 - Exponential Backoff with Jitter
Per-queue retry policies with exponential backoff and full jitter implementation.

This module provides:
- Per-queue retry configurations as per Task 6.2 requirements
- Exponential backoff with full jitter algorithm
- Time limit configurations per task type
- Retry strategy functions for Celery tasks
"""

from __future__ import annotations

import random
from typing import Dict, Tuple, Optional
from .queue_constants import (
    QUEUE_DEFAULT, QUEUE_MODEL, QUEUE_CAM, 
    QUEUE_SIM, QUEUE_REPORT, QUEUE_ERP
)
from .error_taxonomy import RETRYABLE_EXCEPTIONS, get_error_metadata


# Task 6.2: Per-queue retry configuration
# Max retries: AI 3, model 5, cam 5, sim 5, erp 5, report 5
QUEUE_RETRY_CONFIG: Dict[str, Dict] = {
    QUEUE_DEFAULT: {  # AI queue
        'max_retries': 3,
        'backoff_cap': 20,  # 20 seconds cap
        'time_limit': 600,  # 10 minutes hard limit
        'soft_time_limit': 540,  # 9 minutes soft limit
    },
    QUEUE_MODEL: {  # Model generation
        'max_retries': 5,
        'backoff_cap': 60,  # 60 seconds cap
        'time_limit': 900,  # 15 minutes hard limit
        'soft_time_limit': 840,  # 14 minutes soft limit
    },
    QUEUE_CAM: {  # CAM processing
        'max_retries': 5,
        'backoff_cap': 60,  # 60 seconds cap
        'time_limit': 900,  # 15 minutes hard limit
        'soft_time_limit': 840,  # 14 minutes soft limit
    },
    QUEUE_SIM: {  # Simulation
        'max_retries': 5,
        'backoff_cap': 60,  # 60 seconds cap
        'time_limit': 900,  # 15 minutes hard limit
        'soft_time_limit': 840,  # 14 minutes soft limit
    },
    QUEUE_REPORT: {  # Report generation
        'max_retries': 5,
        'backoff_cap': 45,  # 45 seconds cap
        'time_limit': 600,  # 10 minutes hard limit
        'soft_time_limit': 540,  # 9 minutes soft limit
    },
    QUEUE_ERP: {  # ERP integration
        'max_retries': 5,
        'backoff_cap': 45,  # 45 seconds cap
        'time_limit': 600,  # 10 minutes hard limit
        'soft_time_limit': 540,  # 9 minutes soft limit
    },
}


def calculate_retry_delay(
    attempt: int, 
    base_delay: float = 2.0, 
    cap: float = 60.0,
    jitter: bool = True
) -> float:
    """
    Calculate retry delay using exponential backoff with full jitter.
    
    Task 6.2 Algorithm: delay_n = min(cap, base * 2^n) * random.uniform(0.5, 1.5)
    
    Args:
        attempt: Retry attempt number (0-based)
        base_delay: Base delay in seconds (default: 2.0)
        cap: Maximum delay cap in seconds
        jitter: Whether to apply jitter (default: True)
        
    Returns:
        float: Calculated delay in seconds
    """
    # Exponential backoff: base * 2^attempt
    exponential_delay = base_delay * (2 ** attempt)
    
    # Apply cap
    capped_delay = min(cap, exponential_delay)
    
    # Apply full jitter if enabled
    if jitter:
        # Task 6.2: Full jitter with random.uniform(0.5, 1.5)
        jitter_factor = random.uniform(0.5, 1.5)
        final_delay = capped_delay * jitter_factor
    else:
        final_delay = capped_delay
    
    return final_delay


def get_queue_retry_config(queue_name: str) -> Dict:
    """
    Get retry configuration for a specific queue.
    
    Args:
        queue_name: Name of the queue
        
    Returns:
        dict: Retry configuration for the queue
    """
    return QUEUE_RETRY_CONFIG.get(queue_name, QUEUE_RETRY_CONFIG[QUEUE_DEFAULT])


def get_task_time_limits(queue_name: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Get time limits for tasks in a specific queue.
    
    Args:
        queue_name: Name of the queue
        
    Returns:
        tuple: (soft_time_limit, time_limit) in seconds
    """
    config = get_queue_retry_config(queue_name)
    return config['soft_time_limit'], config['time_limit']


def create_retry_decorator_kwargs(queue_name: str) -> Dict:
    """
    Create comprehensive kwargs for Celery task decorator with retry configuration.
    
    Args:
        queue_name: Name of the queue this task will run on
        
    Returns:
        dict: Complete kwargs for @app.task decorator
    """
    config = get_queue_retry_config(queue_name)
    soft_limit, hard_limit = get_task_time_limits(queue_name)
    
    return {
        # Task 6.2: Autoretry configuration
        'autoretry_for': RETRYABLE_EXCEPTIONS,
        'max_retries': config['max_retries'],
        'retry_backoff': True,
        'retry_backoff_max': config['backoff_cap'],
        'retry_jitter': True,
        
        # Task 6.2: Acknowledgment and worker configuration
        'acks_late': True,
        'reject_on_worker_lost': True,
        
        # Task 6.2: Time limits per task type
        'soft_time_limit': soft_limit,
        'time_limit': hard_limit,
        
        # Observability
        'track_started': True,
        'store_errors_even_if_ignored': True,
    }


# Task 6.2: Pre-configured retry kwargs for each queue type
AI_TASK_RETRY_KWARGS = create_retry_decorator_kwargs(QUEUE_DEFAULT)
MODEL_TASK_RETRY_KWARGS = create_retry_decorator_kwargs(QUEUE_MODEL)
CAM_TASK_RETRY_KWARGS = create_retry_decorator_kwargs(QUEUE_CAM)
SIM_TASK_RETRY_KWARGS = create_retry_decorator_kwargs(QUEUE_SIM)
REPORT_TASK_RETRY_KWARGS = create_retry_decorator_kwargs(QUEUE_REPORT)
ERP_TASK_RETRY_KWARGS = create_retry_decorator_kwargs(QUEUE_ERP)


# Task 6.2: Data-driven task routing configuration
# Maps task name patterns to their corresponding retry kwargs
TASK_ROUTING_MAP = {
    'ai': {
        'patterns': ['maintenance', 'monitoring', 'license_notifications'],
        'retry_kwargs': AI_TASK_RETRY_KWARGS
    },
    'model': {
        'patterns': ['cad', 'assembly', 'design', 'freecad'],
        'retry_kwargs': MODEL_TASK_RETRY_KWARGS
    },
    'cam': {
        'patterns': ['cam', 'cam_build', 'm18_cam'],
        'retry_kwargs': CAM_TASK_RETRY_KWARGS
    },
    'sim': {
        'patterns': ['sim', 'm18_sim'],
        'retry_kwargs': SIM_TASK_RETRY_KWARGS
    },
    'report': {
        'patterns': ['reports', 'm18_post'],
        'retry_kwargs': REPORT_TASK_RETRY_KWARGS
    },
    'erp': {
        'patterns': ['erp'],
        'retry_kwargs': ERP_TASK_RETRY_KWARGS
    }
}


def get_retry_kwargs_by_task_name(task_name: str) -> Dict:
    """
    Get retry kwargs based on task name routing using data-driven mapping.
    
    Args:
        task_name: Full task name (e.g., 'app.tasks.cad.generate_model')
        
    Returns:
        dict: Retry kwargs for the task
    """
    # Iterate through the routing map to find matching patterns
    for queue_type, config in TASK_ROUTING_MAP.items():
        if any(pattern in task_name for pattern in config['patterns']):
            return config['retry_kwargs']
    
    # Default to AI queue configuration if no pattern matches
    return AI_TASK_RETRY_KWARGS


def create_task_headers_with_retry_info(
    task_id: str, 
    attempt_count: int, 
    last_exception: Optional[Exception] = None
) -> Dict:
    """
    Create task headers with retry information for observability.
    
    Task 6.2: Include attempt count and last_exception in task headers
    
    Args:
        task_id: Unique task identifier
        attempt_count: Current attempt number
        last_exception: Exception from previous attempt (if any)
        
    Returns:
        dict: Headers to include with task message
    """
    from datetime import datetime, timezone
    
    headers = {
        'task_id': task_id,
        'attempt_count': attempt_count,
        'retry_timestamp': datetime.now(timezone.utc).isoformat(),  # Set timestamp when headers are created
    }
    
    if last_exception:
        headers['last_exception'] = get_error_metadata(last_exception)
    
    return headers