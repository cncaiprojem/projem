"""
Job type routing and queue mapping for Task 6.3.
İş türü yönlendirmesi ve kuyruk eşlemesi.

Task 6.3: Job type routing, payload contracts, and validation
- Job types: ai (routes to default), model, cam, sim, report, erp
- Routing map: type → routing_key (jobs.<type>) → queue
- Canonical task payload schema with validation
- Max payload size 256KB enforcement
"""

from typing import Dict, Optional, Union

from ..models.enums import JobType
from ..core.queue_constants import (
    QUEUE_DEFAULT,
    QUEUE_MODEL,
    QUEUE_CAM,
    QUEUE_SIM,
    QUEUE_REPORT,
    QUEUE_ERP,
    JOBS_EXCHANGE,
    JOBS_EXCHANGE_TYPE,
)


# Job type to queue mapping - Task 6.3 routing rules
JOB_TYPE_TO_QUEUE: Dict[JobType, str] = {
    JobType.AI: QUEUE_DEFAULT,  # AI tasks route to default queue
    JobType.MODEL: QUEUE_MODEL,
    JobType.ASSEMBLY: QUEUE_MODEL,  # Assembly uses model queue
    JobType.CAM: QUEUE_CAM,
    JobType.SIM: QUEUE_SIM,
    JobType.REPORT: QUEUE_REPORT,
    JobType.ERP: QUEUE_ERP,
    # Legacy job types for backward compatibility
    JobType.CAD_GENERATE: QUEUE_MODEL,
    JobType.CAD_IMPORT: QUEUE_MODEL,
    JobType.CAD_EXPORT: QUEUE_MODEL,
    JobType.CAM_PROCESS: QUEUE_CAM,
    JobType.CAM_OPTIMIZE: QUEUE_CAM,
    JobType.SIM_RUN: QUEUE_SIM,
    JobType.SIM_COLLISION: QUEUE_SIM,
    JobType.GCODE_POST: QUEUE_CAM,
    JobType.GCODE_VERIFY: QUEUE_CAM,
    JobType.REPORT_GENERATE: QUEUE_REPORT,
    JobType.MODEL_REPAIR: QUEUE_MODEL,
}


# Job type to routing key mapping - Task 6.3 specification
JOB_TYPE_TO_ROUTING_KEY: Dict[JobType, str] = {
    JobType.AI: "jobs.ai",
    JobType.MODEL: "jobs.model",
    JobType.ASSEMBLY: "jobs.model",  # Assembly uses model routing key
    JobType.CAM: "jobs.cam",
    JobType.SIM: "jobs.sim",
    JobType.REPORT: "jobs.report",
    JobType.ERP: "jobs.erp",
    # Legacy job types for backward compatibility
    JobType.CAD_GENERATE: "jobs.model",
    JobType.CAD_IMPORT: "jobs.model",
    JobType.CAD_EXPORT: "jobs.model",
    JobType.CAM_PROCESS: "jobs.cam",
    JobType.CAM_OPTIMIZE: "jobs.cam",
    JobType.SIM_RUN: "jobs.sim",
    JobType.SIM_COLLISION: "jobs.sim",
    JobType.GCODE_POST: "jobs.cam",
    JobType.GCODE_VERIFY: "jobs.cam",
    JobType.REPORT_GENERATE: "jobs.report",
    JobType.MODEL_REPAIR: "jobs.model",
}


def _normalize_job_type(job_type: Union[JobType, str]) -> JobType:
    """
    Normalize job type from string or enum.
    
    Args:
        job_type: Job type as string or JobType enum
        
    Returns:
        JobType enum value
        
    Raises:
        ValueError: If job type is not recognized
    """
    if isinstance(job_type, str):
        try:
            return JobType(job_type)
        except ValueError:
            raise ValueError(f"Unknown job type: {job_type}")
    return job_type


def get_queue_for_job_type(job_type: Union[JobType, str]) -> str:
    """
    İş türü için hedef kuyruğu döndürür.
    Returns the target queue for a given job type.
    
    Args:
        job_type: The job type enum value
        
    Returns:
        Queue name for the job type
        
    Raises:
        ValueError: If job type is not recognized
    """
    job_type = _normalize_job_type(job_type)
    queue = JOB_TYPE_TO_QUEUE.get(job_type)
    if queue is None:
        raise ValueError(f"Unknown job type: {job_type}")
    
    return queue


def get_routing_key_for_job_type(job_type: Union[JobType, str]) -> str:
    """
    İş türü için routing key döndürür.
    Returns the routing key for a given job type.
    
    Args:
        job_type: The job type enum value
        
    Returns:
        Routing key for the job type (jobs.<type>)
        
    Raises:
        ValueError: If job type is not recognized
    """
    job_type = _normalize_job_type(job_type)
    routing_key = JOB_TYPE_TO_ROUTING_KEY.get(job_type)
    if routing_key is None:
        raise ValueError(f"Unknown job type: {job_type}")
    
    return routing_key


def get_routing_config_for_job_type(job_type: Union[JobType, str]) -> Dict[str, str]:
    """
    İş türü için tam routing konfigürasyonunu döndürür.
    Returns complete routing configuration for a job type.
    
    Args:
        job_type: The job type enum value
        
    Returns:
        Dictionary with queue, exchange, exchange_type, and routing_key
        
    Raises:
        ValueError: If job type is not recognized
    """
    return {
        "queue": get_queue_for_job_type(job_type),
        "exchange": JOBS_EXCHANGE,
        "exchange_type": JOBS_EXCHANGE_TYPE,
        "routing_key": get_routing_key_for_job_type(job_type),
    }


def validate_job_type(job_type_str: str) -> Optional[JobType]:
    """
    String değerden JobType enum'a dönüşüm ve validasyon.
    Validates and converts string to JobType enum.
    
    Args:
        job_type_str: String representation of job type
        
    Returns:
        JobType enum value if valid, None if invalid
    """
    try:
        return JobType(job_type_str.lower())
    except (ValueError, AttributeError):
        return None


# Export all public symbols
__all__ = [
    "JobType",
    "JOB_TYPE_TO_QUEUE",
    "JOB_TYPE_TO_ROUTING_KEY",
    "get_queue_for_job_type",
    "get_routing_key_for_job_type",
    "get_routing_config_for_job_type",
    "validate_job_type",
]