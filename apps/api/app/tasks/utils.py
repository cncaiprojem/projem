"""
Task Utilities Module

Shared utility functions and data classes for Celery tasks.
Provides common functionality for job management, idempotency,
and task result handling across different task modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..core.database import SessionLocal
from ..core.logging import get_logger
from ..models.enums import JobStatus
from ..models.job import Job

logger = get_logger(__name__)


@dataclass
class TaskResult:
    """Standard task result structure for all model flow tasks."""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    artefacts: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    progress: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "artefacts": self.artefacts,
            "warnings": self.warnings,
            "progress": self.progress,
            "timestamp": self.timestamp
        }


def update_job_status(
    job_id: str,
    status: JobStatus,
    progress: int = 0,
    output_data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> Optional[Job]:
    """Update job status in database with error handling."""
    db = None
    try:
        db = SessionLocal()
        job = db.query(Job).filter(Job.id == job_id).first()

        if not job:
            logger.warning("Job not found for status update", job_id=job_id)
            return None

        job.status = status
        job.progress = progress

        if output_data:
            job.output_data = output_data

        if error_message:
            if not job.output_data:
                job.output_data = {}
            job.output_data["error"] = error_message

        job.modified_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(
            "Job status updated",
            job_id=job_id,
            status=status.value,
            progress=progress
        )

        return job

    except Exception as e:
        logger.error("Failed to update job status", job_id=job_id, error=str(e))
        if db:
            db.rollback()
        return None
    finally:
        if db:
            db.close()


def ensure_idempotency(job_id: str, request_id: str) -> bool:
    """Check job idempotency and prevent duplicate execution."""
    db = None
    try:
        db = SessionLocal()

        # Check if job already exists and is not in initial state
        job = db.query(Job).filter(Job.id == job_id).first()

        if job and job.status not in [JobStatus.PENDING, JobStatus.FAILED]:
            logger.info(
                "Job already processed - idempotency check",
                job_id=job_id,
                current_status=job.status.value,
                request_id=request_id
            )
            return False

        # Update or create job with running status
        if job:
            job.status = JobStatus.RUNNING
            job.progress = 0
            job.modified_at = datetime.now(timezone.utc)
        else:
            logger.warning(
                "Job not found during idempotency check",
                job_id=job_id,
                request_id=request_id
            )

        db.commit()
        return True

    except Exception as e:
        logger.error(
            "Idempotency check failed",
            job_id=job_id,
            request_id=request_id,
            error=str(e)
        )
        if db:
            db.rollback()
        return False
    finally:
        if db:
            db.close()


def get_turkish_term(key: str) -> str:
    """Get Turkish terminology for common CAD/FEM terms."""
    TURKISH_TERMS = {
        "flange": "flanş",
        "bearing": "yatak",
        "gear": "dişli",
        "shaft": "mil",
        "bracket": "konsol",
        "assembly": "montaj",
        "part": "parça",
        "drawing": "teknik resim",
        "analysis": "analiz",
        "simulation": "simülasyon",
        "mesh": "ağ",
        "constraint": "kısıt",
        "boundary_condition": "sınır koşulu",
        "load": "yük",
        "material": "malzeme",
        "stress": "gerilme",
        "strain": "şekil değiştirme",
        "displacement": "yer değiştirme",
        "frequency": "frekans",
        "mode": "mod",
        "modal": "modal/özdeğer",
        "buckling": "burkulma",
        "thermal": "ısıl",
        "static": "doğrusal statik",
        "coupled": "bağlama",
        "temperature": "sıcaklık",
        "heat_flux": "ısı akısı",
        "convection": "taşınım",
        "contact": "temas",
        "element": "eleman",
        "node": "düğüm",
        "solver": "çözücü",
        "result": "sonuç",
        "factor_of_safety": "emniyet katsayısı",
        "steel": "çelik",
        "aluminum": "alüminyum",
        "copper": "bakır",
        "plastic": "plastik"
    }
    return TURKISH_TERMS.get(key, key)