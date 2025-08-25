"""
Job queue position service for Task 6.5.

Provides queue position calculation for jobs.
"""

from __future__ import annotations

from typing import Optional, Dict, List, Mapping
from types import MappingProxyType
from sqlalchemy import select, func, and_, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
import structlog

from ..models import Job
from ..models.enums import JobStatus, JobType
from ..core.job_routing import get_routing_config_for_job_type

logger = structlog.get_logger(__name__)


# Pre-compute reverse mapping from queue names to job types at module load time
# This avoids expensive iteration over all JobType enums on every request
# Using MappingProxyType to make it immutable for thread safety
def _compute_queue_to_job_types() -> Mapping[str, List[JobType]]:
    """Compute the reverse mapping from queues to job types."""
    temp_mapping: Dict[str, List[JobType]] = {}
    
    for job_type in JobType:
        try:
            config = get_routing_config_for_job_type(job_type)
            queue_name = config.get("queue", "default")
            
            if queue_name not in temp_mapping:
                temp_mapping[queue_name] = []
            temp_mapping[queue_name].append(job_type)
        except ValueError:
            # Skip job types without routing config
            continue
    
    return MappingProxyType(temp_mapping)

_QUEUE_TO_JOB_TYPES: Mapping[str, List[JobType]] = _compute_queue_to_job_types()

logger.info(
    "Initialized queue to job type mappings",
    mappings=dict(_QUEUE_TO_JOB_TYPES)  # Convert to dict for logging
)

# Default processing time estimates in seconds for each job type
# Used when no historical data is available for wait time calculation
DEFAULT_JOB_TIME_ESTIMATES: Mapping[JobType, int] = MappingProxyType({
    JobType.MODEL: 120,      # 2 minutes - FreeCAD model generation
    JobType.CAM: 180,        # 3 minutes - CAM path generation
    JobType.SIM: 300,        # 5 minutes - Simulation processing
    JobType.AI: 30,          # 30 seconds - AI tasks
    JobType.REPORT: 60,      # 1 minute - Report generation
    JobType.ERP: 45,         # 45 seconds - ERP integration
    JobType.CAD_IMPORT: 90,  # 1.5 minutes - CAD file import/processing
    JobType.ASSEMBLY: 150,   # 2.5 minutes - Assembly4 operations
})


class JobQueueService:
    """Service for calculating job queue positions."""
    
    @staticmethod
    def get_queue_position(db: Session, job: Job) -> Optional[int]:
        """
        Calculate the queue position for a job.
        
        Returns:
            - None if job is completed, failed, cancelled, or if position cannot be determined due to errors
            - 0 if job is currently running
            - Position (1+) if job is pending or queued
        """
        
        # No queue position for terminal states
        if job.is_complete:
            return None
        
        # Currently running = position 0
        if job.status == JobStatus.RUNNING:
            return 0
        
        # For pending/queued jobs, calculate position
        if job.status in [JobStatus.PENDING, JobStatus.QUEUED]:
            try:
                # Get the queue name for this job type
                routing_config = get_routing_config_for_job_type(job.type)
                queue_name = routing_config.get("queue", "default")
                
                # Use pre-computed mapping for O(1) lookup
                same_queue_types = _QUEUE_TO_JOB_TYPES.get(queue_name, [])
                
                # Count jobs ahead in the same queue
                # Jobs are ahead if they have:
                # 1. Same queue (job type)
                # 2. Status is PENDING or QUEUED
                # 3. Higher priority OR (same priority AND created earlier)
                position_query = select(func.count(Job.id)).where(
                    and_(
                        Job.type.in_(same_queue_types),
                        Job.status.in_([JobStatus.PENDING, JobStatus.QUEUED]),
                        Job.id != job.id,  # Exclude current job
                        # Higher priority OR (same priority and created earlier)
                        or_(
                            Job.priority > job.priority,
                            and_(
                                Job.priority == job.priority,
                                Job.created_at < job.created_at
                            )
                        )
                    )
                )
                
                ahead_count = db.scalar(position_query) or 0
                
                # Add currently running jobs in the same queue
                running_query = select(func.count(Job.id)).where(
                    and_(
                        Job.type.in_(same_queue_types),
                        Job.status == JobStatus.RUNNING
                    )
                )
                
                running_count = db.scalar(running_query) or 0
                
                # Position is number of jobs ahead + running jobs + 1
                position = ahead_count + running_count + 1
                
                logger.debug(
                    "Calculated queue position",
                    job_id=job.id,
                    job_type=job.type.value,
                    queue=queue_name,
                    ahead_count=ahead_count,
                    running_count=running_count,
                    position=position
                )
                
                return position
                
            except SQLAlchemyError as e:
                logger.error(
                    "Failed to calculate queue position",
                    job_id=job.id,
                    error=str(e)
                )
                # Return None to indicate position could not be determined
                return None
        
        # Default for any other status
        return None
    
    @staticmethod
    def get_estimated_wait_time(db: Session, job: Job) -> Optional[int]:
        """
        Estimate wait time in seconds based on queue position and average processing time.
        
        This is a rough estimate based on historical data.
        """
        position = JobQueueService.get_queue_position(db, job)
        
        if position is None or position == 0:
            return None
        
        try:
            # Get average processing time for this job type (last 100 completed jobs)
            # Use subquery to first get the last 100 jobs, then calculate average
            avg_time_query = select(
                func.avg(
                    func.extract('epoch', Job.finished_at - Job.started_at)
                )
            ).where(
                Job.id.in_(
                    select(Job.id).where(
                        and_(
                            Job.type == job.type,
                            Job.status == JobStatus.COMPLETED,
                            Job.started_at.isnot(None),
                            Job.finished_at.isnot(None)
                        )
                    ).order_by(Job.finished_at.desc()).limit(100)
                )
            )
            
            avg_seconds = db.scalar(avg_time_query)
            
            if avg_seconds:
                # Rough estimate: position * average time
                # Add some buffer for variability
                estimated_seconds = int(position * avg_seconds * 1.2)
                return estimated_seconds
            else:
                # No historical data, use a default estimate based on job type
                default_time = DEFAULT_JOB_TIME_ESTIMATES.get(job.type, 60)
                return position * default_time
                
        except SQLAlchemyError as e:
            logger.error(
                "Failed to estimate wait time",
                job_id=job.id,
                error=str(e)
            )
            return None