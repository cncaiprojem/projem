"""
Scheduled Operations Service for Task 7.23

Provides scheduled and recurring operations with:
- APScheduler integration
- SQLAlchemy job store for persistence
- Cron and interval triggers
- Job management and monitoring
- Nightly optimization tasks
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import (
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED,
    JobExecutionEvent
)
from pydantic import BaseModel, Field

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.metrics import scheduled_job_counter, scheduled_job_duration_histogram
from ..core.telemetry import create_span
from .freecad_document_manager import FreeCADDocumentManager
from .batch_import_export import BatchProcessor

logger = get_logger(__name__)


class JobTriggerType(str, Enum):
    """Types of job triggers."""
    CRON = "cron"
    INTERVAL = "interval"
    DATE = "date"


class JobStatus(str, Enum):
    """Job execution status."""
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MISSED = "missed"
    PAUSED = "paused"


class OptimizationType(str, Enum):
    """Types of optimization operations."""
    MESH = "mesh"  # Mesh optimization
    FEATURES = "features"  # Feature cleanup
    STORAGE = "storage"  # Storage compression
    CACHE = "cache"  # Cache cleanup
    INDEX = "index"  # Index optimization
    ALL = "all"  # All optimizations


class ScheduledJobConfig(BaseModel):
    """Configuration for scheduled job."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="İş adı")
    description: Optional[str] = Field(default=None, description="Açıklama")
    trigger_type: JobTriggerType = Field(description="Tetikleyici tipi")
    trigger_args: Dict[str, Any] = Field(description="Tetikleyici parametreleri")
    function: str = Field(description="Çalıştırılacak fonksiyon")
    args: List[Any] = Field(default_factory=list, description="Fonksiyon argümanları")
    kwargs: Dict[str, Any] = Field(default_factory=dict, description="Fonksiyon keyword argümanları")
    max_instances: int = Field(default=1, ge=1, le=10, description="Maksimum eşzamanlı örnek")
    misfire_grace_time: int = Field(default=60, ge=1, le=3600, description="Kaçırma tolerans süresi (saniye)")
    coalesce: bool = Field(default=True, description="Kaçırılan işleri birleştir")
    replace_existing: bool = Field(default=True, description="Mevcut işi değiştir")
    enabled: bool = Field(default=True, description="İş etkin mi")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = {"json_schema_extra": {"examples": [
        {
            "name": "Gece Optimizasyonu",
            "trigger_type": "cron",
            "trigger_args": {"hour": 2, "minute": 0},
            "function": "optimize_all_models",
            "max_instances": 1,
            "enabled": True
        }
    ]}}


class JobExecutionHistory(BaseModel):
    """Job execution history record."""
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str = Field(description="İş ID")
    job_name: str = Field(description="İş adı")
    status: JobStatus = Field(description="Durum")
    start_time: datetime = Field(description="Başlangıç zamanı")
    end_time: Optional[datetime] = Field(default=None, description="Bitiş zamanı")
    duration_ms: Optional[float] = Field(default=None, description="Süre (ms)")
    result: Optional[Any] = Field(default=None, description="Sonuç")
    error: Optional[str] = Field(default=None, description="Hata mesajı")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelOptimizer:
    """Optimize FreeCAD models for storage and performance."""
    
    def __init__(self, document_manager: Optional[FreeCADDocumentManager] = None):
        """Initialize model optimizer."""
        self.document_manager = document_manager or FreeCADDocumentManager()
    
    async def optimize_mesh(self, model_path: Path) -> Dict[str, Any]:
        """Optimize model mesh."""
        try:
            # Load model
            doc = await self.document_manager.open_document(str(model_path))
            
            # Mesh optimization logic
            optimization_stats = {
                "original_vertices": 0,
                "optimized_vertices": 0,
                "reduction_percent": 0,
                "time_ms": 0
            }
            
            # TODO: Implement actual mesh optimization
            # This would involve:
            # 1. Analyzing mesh complexity
            # 2. Reducing vertices while preserving quality
            # 3. Optimizing face normals
            # 4. Removing duplicate vertices
            
            # Save optimized model
            await self.document_manager.save_document(doc.id)
            
            return {
                "success": True,
                "model": str(model_path),
                "optimization": "mesh",
                "stats": optimization_stats
            }
            
        except Exception as e:
            logger.error(f"Mesh optimizasyon hatası {model_path}: {e}")
            return {
                "success": False,
                "model": str(model_path),
                "optimization": "mesh",
                "error": str(e)
            }
    
    async def cleanup_features(self, model_path: Path) -> Dict[str, Any]:
        """Remove unused features from model."""
        try:
            # Load model
            doc = await self.document_manager.open_document(str(model_path))
            
            cleanup_stats = {
                "removed_features": 0,
                "cleaned_constraints": 0,
                "space_saved_kb": 0
            }
            
            # TODO: Implement feature cleanup
            # This would involve:
            # 1. Identifying unused features
            # 2. Removing orphaned constraints
            # 3. Cleaning up construction geometry
            # 4. Optimizing feature tree
            
            # Save cleaned model
            await self.document_manager.save_document(doc.id)
            
            return {
                "success": True,
                "model": str(model_path),
                "optimization": "features",
                "stats": cleanup_stats
            }
            
        except Exception as e:
            logger.error(f"Özellik temizleme hatası {model_path}: {e}")
            return {
                "success": False,
                "model": str(model_path),
                "optimization": "features",
                "error": str(e)
            }
    
    async def compress_model(self, model_path: Path) -> Dict[str, Any]:
        """Compress model for storage."""
        try:
            import gzip
            import shutil
            
            original_size = model_path.stat().st_size
            compressed_path = model_path.with_suffix(model_path.suffix + ".gz")
            
            # Compress file
            with open(model_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb', compresslevel=9) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            compressed_size = compressed_path.stat().st_size
            compression_ratio = (1 - compressed_size / original_size) * 100
            
            return {
                "success": True,
                "model": str(model_path),
                "optimization": "storage",
                "stats": {
                    "original_size_kb": original_size / 1024,
                    "compressed_size_kb": compressed_size / 1024,
                    "compression_ratio": compression_ratio
                }
            }
            
        except Exception as e:
            logger.error(f"Model sıkıştırma hatası {model_path}: {e}")
            return {
                "success": False,
                "model": str(model_path),
                "optimization": "storage",
                "error": str(e)
            }


class ScheduledOperations:
    """Manage scheduled and recurring operations."""
    
    def __init__(self):
        """Initialize scheduled operations."""
        # Configure job store
        database_url = getattr(settings, "DATABASE_URL", "sqlite:///scheduled_jobs.db")
        # Convert async URL to sync for APScheduler
        if database_url.startswith("postgresql+asyncpg"):
            database_url = database_url.replace("postgresql+asyncpg", "postgresql")
        
        self.jobstore = SQLAlchemyJobStore(url=database_url)
        
        # Initialize scheduler
        self.scheduler = AsyncIOScheduler(
            jobstores={'default': self.jobstore},
            job_defaults={
                'coalesce': True,
                'max_instances': 3,
                'misfire_grace_time': 60
            },
            timezone='UTC'
        )
        
        # Job history
        self.execution_history: List[JobExecutionHistory] = []
        
        # Register event listeners
        self.scheduler.add_listener(
            self._job_executed,
            EVENT_JOB_EXECUTED
        )
        self.scheduler.add_listener(
            self._job_error,
            EVENT_JOB_ERROR
        )
        self.scheduler.add_listener(
            self._job_missed,
            EVENT_JOB_MISSED
        )
        
        # Registered job functions
        self.job_functions: Dict[str, Callable] = {}
        
        # Model optimizer
        self.model_optimizer = ModelOptimizer()
        
        # Batch processor
        self.batch_processor = BatchProcessor()
        
        # Register default jobs
        self._register_default_jobs()
    
    def _register_default_jobs(self) -> None:
        """Register default job functions."""
        self.register_job_function("optimize_all_models", self.optimize_all_models)
        self.register_job_function("cleanup_old_files", self.cleanup_old_files)
        self.register_job_function("generate_daily_report", self.generate_daily_report)
        self.register_job_function("backup_database", self.backup_database)
        self.register_job_function("refresh_cache", self.refresh_cache)
    
    def register_job_function(self, name: str, function: Callable) -> None:
        """Register a job function."""
        self.job_functions[name] = function
    
    def start(self) -> None:
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Zamanlayıcı başlatıldı")
    
    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("Zamanlayıcı kapatıldı")
    
    def schedule_job(self, config: ScheduledJobConfig) -> str:
        """
        Schedule a new job.
        
        Args:
            config: Job configuration
            
        Returns:
            Job ID
        """
        with create_span("schedule_job") as span:
            span.set_attribute("job_name", config.name)
            span.set_attribute("trigger_type", config.trigger_type.value)
            
            # Get function
            func = self.job_functions.get(config.function)
            if not func:
                raise ValueError(f"İş fonksiyonu bulunamadı: {config.function}")
            
            # Create trigger
            if config.trigger_type == JobTriggerType.CRON:
                trigger = CronTrigger(**config.trigger_args)
            elif config.trigger_type == JobTriggerType.INTERVAL:
                trigger = IntervalTrigger(**config.trigger_args)
            elif config.trigger_type == JobTriggerType.DATE:
                trigger = DateTrigger(**config.trigger_args)
            else:
                raise ValueError(f"Geçersiz tetikleyici tipi: {config.trigger_type}")
            
            # Add job
            job = self.scheduler.add_job(
                func=func,
                trigger=trigger,
                args=config.args,
                kwargs=config.kwargs,
                id=config.job_id,
                name=config.name,
                max_instances=config.max_instances,
                misfire_grace_time=config.misfire_grace_time,
                coalesce=config.coalesce,
                replace_existing=config.replace_existing
            )
            
            logger.info(f"İş zamanlandı: {config.name} ({config.job_id})")
            
            scheduled_job_counter.labels(
                operation="schedule",
                job_type=config.trigger_type.value
            ).inc()
            
            return job.id
    
    def schedule_nightly_optimization(self) -> str:
        """Schedule nightly model optimization."""
        config = ScheduledJobConfig(
            job_id="nightly_optimization",
            name="Gece Model Optimizasyonu",
            description="Tüm modelleri optimize et",
            trigger_type=JobTriggerType.CRON,
            trigger_args={"hour": 2, "minute": 0},
            function="optimize_all_models",
            max_instances=1,
            enabled=True
        )
        
        return self.schedule_job(config)
    
    def schedule_hourly_cleanup(self) -> str:
        """Schedule hourly cleanup."""
        config = ScheduledJobConfig(
            job_id="hourly_cleanup",
            name="Saatlik Temizlik",
            description="Geçici dosyaları temizle",
            trigger_type=JobTriggerType.INTERVAL,
            trigger_args={"hours": 1},
            function="cleanup_old_files",
            max_instances=1,
            enabled=True
        )
        
        return self.schedule_job(config)
    
    def schedule_daily_report(self) -> str:
        """Schedule daily report generation."""
        config = ScheduledJobConfig(
            job_id="daily_report",
            name="Günlük Rapor",
            description="Günlük özet raporu oluştur",
            trigger_type=JobTriggerType.CRON,
            trigger_args={"hour": 6, "minute": 0},
            function="generate_daily_report",
            max_instances=1,
            enabled=True
        )
        
        return self.schedule_job(config)
    
    async def optimize_all_models(self, optimization_type: OptimizationType = OptimizationType.ALL) -> Dict[str, Any]:
        """Optimize all models in repository."""
        with create_span("optimize_all_models") as span:
            span.set_attribute("optimization_type", optimization_type.value)
            
            start_time = datetime.now(UTC)
            results = {
                "total_models": 0,
                "optimized": 0,
                "failed": 0,
                "skipped": 0,
                "optimizations": []
            }
            
            try:
                # Get all model files from database or storage
                model_paths = await self.get_all_models()
                
                results["total_models"] = len(model_paths)
                
                for model_path in model_paths:
                    try:
                        if optimization_type in [OptimizationType.MESH, OptimizationType.ALL]:
                            result = await self.model_optimizer.optimize_mesh(model_path)
                            results["optimizations"].append(result)
                        
                        if optimization_type in [OptimizationType.FEATURES, OptimizationType.ALL]:
                            result = await self.model_optimizer.cleanup_features(model_path)
                            results["optimizations"].append(result)
                        
                        if optimization_type in [OptimizationType.STORAGE, OptimizationType.ALL]:
                            result = await self.model_optimizer.compress_model(model_path)
                            results["optimizations"].append(result)
                        
                        results["optimized"] += 1
                        
                    except Exception as e:
                        logger.error(f"Model optimizasyon hatası {model_path}: {e}")
                        results["failed"] += 1
                
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                scheduled_job_duration_histogram.labels(
                    job_type="optimization"
                ).observe(duration_ms)
                
                logger.info(
                    f"Model optimizasyonu tamamlandı: "
                    f"{results['optimized']}/{results['total_models']} başarılı, "
                    f"Süre: {duration_ms:.2f}ms"
                )
                
                return results
                
            except Exception as e:
                logger.error(f"Toplu optimizasyon hatası: {e}")
                raise
    
    async def cleanup_old_files(self, days_old: int = 7) -> Dict[str, Any]:
        """Clean up old temporary files."""
        with create_span("cleanup_old_files") as span:
            span.set_attribute("days_old", days_old)
            
            results = {
                "files_checked": 0,
                "files_deleted": 0,
                "space_freed_mb": 0
            }
            
            try:
                # Define temp directories
                temp_dirs = [
                    Path("/tmp/freecad"),
                    Path("/tmp/batch_processing"),
                    Path("/tmp/exports")
                ]
                
                cutoff_date = datetime.now(UTC) - timedelta(days=days_old)
                
                for temp_dir in temp_dirs:
                    if not temp_dir.exists():
                        continue
                    
                    for file_path in temp_dir.rglob("*"):
                        if file_path.is_file():
                            results["files_checked"] += 1
                            
                            # Check file age
                            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime, UTC)
                            if file_mtime < cutoff_date:
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                results["files_deleted"] += 1
                                results["space_freed_mb"] += file_size / (1024 * 1024)
                
                logger.info(
                    f"Temizlik tamamlandı: {results['files_deleted']} dosya silindi, "
                    f"{results['space_freed_mb']:.2f}MB alan boşaltıldı"
                )
                
                return results
                
            except Exception as e:
                logger.error(f"Dosya temizleme hatası: {e}")
                raise
    
    async def generate_daily_report(self) -> Dict[str, Any]:
        """Generate daily operations report."""
        with create_span("generate_daily_report"):
            report = {
                "date": datetime.now(UTC).date().isoformat(),
                "jobs_executed": 0,
                "jobs_failed": 0,
                "models_processed": 0,
                "errors": []
            }
            
            # Analyze execution history for the last 24 hours
            cutoff_time = datetime.now(UTC) - timedelta(days=1)
            
            for execution in self.execution_history:
                if execution.start_time >= cutoff_time:
                    if execution.status == JobStatus.COMPLETED:
                        report["jobs_executed"] += 1
                    elif execution.status == JobStatus.FAILED:
                        report["jobs_failed"] += 1
                        report["errors"].append({
                            "job": execution.job_name,
                            "error": execution.error,
                            "time": execution.start_time.isoformat()
                        })
            
            logger.info(f"Günlük rapor oluşturuldu: {report['date']}")
            
            # TODO: Save report to database or send via email
            
            return report
    
    async def backup_database(self) -> Dict[str, Any]:
        """Backup database."""
        # Placeholder for database backup logic
        logger.info("Veritabanı yedekleme başlatıldı")
        
        result = {
            "backup_file": f"backup_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.sql",
            "size_mb": 0,
            "duration_ms": 0
        }
        
        # TODO: Implement actual database backup
        
        return result
    
    async def refresh_cache(self) -> Dict[str, Any]:
        """Refresh application cache."""
        # Placeholder for cache refresh logic
        logger.info("Önbellek yenileme başlatıldı")
        
        result = {
            "cache_keys_refreshed": 0,
            "duration_ms": 0
        }
        
        # TODO: Implement actual cache refresh
        
        return result
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        job = self.scheduler.get_job(job_id)
        if job:
            job.pause()
            logger.info(f"İş duraklatıldı: {job_id}")
            return True
        return False
    
    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        job = self.scheduler.get_job(job_id)
        if job:
            job.resume()
            logger.info(f"İş devam ettirildi: {job_id}")
            return True
        return False
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"İş kaldırıldı: {job_id}")
            return True
        except Exception as e:
            logger.error(f"İş kaldırma hatası {job_id}: {e}")
            return False
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
                "pending": job.pending
            })
        return jobs
    
    def get_job_history(self, job_id: Optional[str] = None, limit: int = 100) -> List[JobExecutionHistory]:
        """Get job execution history."""
        if job_id:
            history = [h for h in self.execution_history if h.job_id == job_id]
        else:
            history = self.execution_history
        
        # Return most recent first
        return sorted(history, key=lambda x: x.start_time, reverse=True)[:limit]
    
    async def get_all_models(self) -> List[str]:
        """
        Get all model file paths from database or storage.
        
        Returns:
            List of model file paths
        """
        try:
            # Import here to avoid circular dependencies
            from ..models import Model
            from ..core.dependencies import get_db
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession
            
            model_paths = []
            
            # Get database session
            async for db_session in get_db():
                try:
                    # Query all active models from database
                    query = select(Model).where(
                        Model.status.in_(["completed", "optimized", "active"])
                    )
                    result = await db_session.execute(query)
                    models = result.scalars().all()
                    
                    # Extract file paths from models
                    for model in models:
                        if model.file_path:
                            model_paths.append(model.file_path)
                        elif model.s3_key:
                            # For S3-stored models, use the S3 key as path
                            model_paths.append(f"s3://{model.s3_bucket}/{model.s3_key}")
                    
                    logger.info(f"Toplam {len(model_paths)} model bulundu")
                    
                finally:
                    await db_session.close()
            
            return model_paths
            
        except Exception as e:
            logger.error(f"Model listesi alma hatası: {e}")
            # Return empty list on error to allow operation to continue
            return []
    
    def _job_executed(self, event: JobExecutionEvent) -> None:
        """Handle successful job execution."""
        execution = JobExecutionHistory(
            job_id=event.job_id,
            job_name=event.job_id,  # Could be enhanced to get actual name
            status=JobStatus.COMPLETED,
            start_time=event.scheduled_run_time,
            end_time=datetime.now(UTC),
            result=event.retval
        )
        
        self.execution_history.append(execution)
        
        scheduled_job_counter.labels(
            operation="execute",
            job_type="scheduled"
        ).inc()
        
        logger.info(f"İş başarıyla tamamlandı: {event.job_id}")
    
    def _job_error(self, event: JobExecutionEvent) -> None:
        """Handle job execution error."""
        execution = JobExecutionHistory(
            job_id=event.job_id,
            job_name=event.job_id,
            status=JobStatus.FAILED,
            start_time=event.scheduled_run_time,
            end_time=datetime.now(UTC),
            error=str(event.exception) if event.exception else "Unknown error"
        )
        
        self.execution_history.append(execution)
        
        scheduled_job_counter.labels(
            operation="error",
            job_type="scheduled"
        ).inc()
        
        logger.error(f"İş hatası: {event.job_id}, Hata: {event.exception}")
    
    def _job_missed(self, event: JobExecutionEvent) -> None:
        """Handle missed job execution."""
        execution = JobExecutionHistory(
            job_id=event.job_id,
            job_name=event.job_id,
            status=JobStatus.MISSED,
            start_time=event.scheduled_run_time,
            end_time=datetime.now(UTC)
        )
        
        self.execution_history.append(execution)
        
        scheduled_job_counter.labels(
            operation="missed",
            job_type="scheduled"
        ).inc()
        
        logger.warning(f"İş kaçırıldı: {event.job_id}")


# Global scheduler instance
_scheduler_instance: Optional[ScheduledOperations] = None


def get_scheduler() -> ScheduledOperations:
    """Get or create global scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ScheduledOperations()
        _scheduler_instance.start()
    return _scheduler_instance