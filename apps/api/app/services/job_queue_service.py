"""
Job queue position service for Task 6.5.

Provides queue position calculation for jobs.
"""

from __future__ import annotations

from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
import structlog

from ..models import Job
from ..models.enums import JobStatus, JobType
from ..core.job_routing import get_routing_config_for_job_type

logger = structlog.get_logger(__name__)


class JobQueueService:
    """Service for calculating job queue positions."""
    
    @staticmethod
    def get_queue_position(db: Session, job: Job) -> Optional[int]:
        """
        Calculate the queue position for a job.
        
        Returns:
            - None if job is completed, failed, or cancelled
            - 0 if job is currently running
            - Position (1+) if job is pending or queued
        """
        
        # No queue position for terminal states
        if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, 
                          JobStatus.CANCELLED, JobStatus.TIMEOUT]:
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
                
                # Find job types that use the same queue
                same_queue_types = []
                for job_type in JobType:
                    try:
                        config = get_routing_config_for_job_type(job_type)
                        if config.get("queue") == queue_name:
                            same_queue_types.append(job_type)
                    except ValueError:
                        continue
                
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
                        (
                            (Job.priority > job.priority) |
                            (
                                (Job.priority == job.priority) &
                                (Job.created_at < job.created_at)
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
                
            except Exception as e:
                logger.error(
                    "Failed to calculate queue position",
                    job_id=job.id,
                    error=str(e)
                )
                # Return a default position on error
                return 1
        
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
            avg_time_query = select(
                func.avg(
                    func.extract('epoch', Job.finished_at - Job.started_at)
                )
            ).where(
                and_(
                    Job.type == job.type,
                    Job.status == JobStatus.COMPLETED,
                    Job.started_at.isnot(None),
                    Job.finished_at.isnot(None)
                )
            ).order_by(
                Job.finished_at.desc()
            ).limit(100)
            
            avg_seconds = db.scalar(avg_time_query)
            
            if avg_seconds:
                # Rough estimate: position * average time
                # Add some buffer for variability
                estimated_seconds = int(position * avg_seconds * 1.2)
                return estimated_seconds
            else:
                # No historical data, use a default estimate based on job type
                default_estimates = {
                    JobType.FREECAD_MODEL: 120,  # 2 minutes
                    JobType.FREECAD_CAM: 180,    # 3 minutes
                    JobType.FREECAD_SIMULATION: 300,  # 5 minutes
                    JobType.AI_CHAT: 30,          # 30 seconds
                    JobType.REPORT_GENERATION: 60,  # 1 minute
                }
                
                default_time = default_estimates.get(job.type, 60)
                return position * default_time
                
        except Exception as e:
            logger.error(
                "Failed to estimate wait time",
                job_id=job.id,
                error=str(e)
            )
            return None