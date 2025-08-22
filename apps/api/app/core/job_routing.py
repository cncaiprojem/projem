"""
Job type routing and queue mapping for Task 6.3.
İş türü yönlendirmesi ve kuyruk eşlemesi.

Task 6.3: Job type routing, payload contracts, and validation
- Job types: ai (routes to default), model, cam, sim, report, erp
- Routing map: type → routing_key (jobs.<type>) → queue
- Canonical task payload schema with validation
- Max payload size 256KB enforcement
"""

from enum import Enum
from typing import Dict, Optional

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


class JobType(str, Enum):
    """
    İş türleri enumerasyonu - Task 6.3 spesifikasyonu.
    Job types per Task 6.3 specification.
    """
    
    AI = "ai"  # AI/ML işleri - routes to default queue
    MODEL = "model"  # 3D model oluşturma - routes to model queue
    CAM = "cam"  # CAM yolu oluşturma - routes to cam queue
    SIM = "sim"  # Simülasyon işleri - routes to sim queue
    REPORT = "report"  # Rapor oluşturma - routes to report queue
    ERP = "erp"  # ERP entegrasyonu - routes to erp queue


# Job type to queue mapping - Task 6.3 routing rules
JOB_TYPE_TO_QUEUE: Dict[JobType, str] = {
    JobType.AI: QUEUE_DEFAULT,  # AI tasks route to default queue
    JobType.MODEL: QUEUE_MODEL,
    JobType.CAM: QUEUE_CAM,
    JobType.SIM: QUEUE_SIM,
    JobType.REPORT: QUEUE_REPORT,
    JobType.ERP: QUEUE_ERP,
}


# Job type to routing key mapping - Task 6.3 specification
JOB_TYPE_TO_ROUTING_KEY: Dict[JobType, str] = {
    JobType.AI: "jobs.ai",
    JobType.MODEL: "jobs.model",
    JobType.CAM: "jobs.cam",
    JobType.SIM: "jobs.sim",
    JobType.REPORT: "jobs.report",
    JobType.ERP: "jobs.erp",
}


def get_queue_for_job_type(job_type: JobType) -> str:
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
    if job_type not in JOB_TYPE_TO_QUEUE:
        raise ValueError(f"Unknown job type: {job_type}")
    
    return JOB_TYPE_TO_QUEUE[job_type]


def get_routing_key_for_job_type(job_type: JobType) -> str:
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
    if job_type not in JOB_TYPE_TO_ROUTING_KEY:
        raise ValueError(f"Unknown job type: {job_type}")
    
    return JOB_TYPE_TO_ROUTING_KEY[job_type]


def get_routing_config_for_job_type(job_type: JobType) -> Dict[str, str]:
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