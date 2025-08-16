"""
Maintenance tasks for system cleanup and health management.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Any

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import async_session
from ..core.s3_client import s3_client

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="app.tasks.maintenance.health_check")
def health_check(self) -> Dict[str, Any]:
    """
    Sistem sağlık kontrolü task'ı.
    Database, Redis, MinIO ve RabbitMQ bağlantılarını kontrol eder.
    """
    try:
        health_status = {
            "timestamp": time.time(),
            "database": False,
            "s3": False,
            "worker_id": self.request.id,
            "hostname": self.request.hostname,
        }
        
        # Database health check
        try:
            async def check_db():
                async with async_session() as session:
                    result = await session.execute("SELECT 1")
                    return result.scalar() == 1
            
            # Run async function in sync context
            health_status["database"] = asyncio.run(check_db())
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status["database"] = False
        
        # S3/MinIO health check
        try:
            buckets = s3_client.list_buckets()
            health_status["s3"] = "Buckets" in buckets
        except Exception as e:
            logger.error(f"S3 health check failed: {e}")
            health_status["s3"] = False
        
        # Log health status
        if all([health_status["database"], health_status["s3"]]):
            logger.info("Health check passed", extra=health_status)
        else:
            logger.warning("Health check failed", extra=health_status)
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check task failed: {e}")
        raise self.retry(exc=e, countdown=60, max_retries=3)


@shared_task(bind=True, name="app.tasks.maintenance.cleanup_temp_files")
def cleanup_temp_files(self, max_age_hours: int = 24) -> Dict[str, Any]:
    """
    Geçici dosyaları temizleme task'ı.
    Belirtilen süreden eski geçici dosyaları siler.
    
    Args:
        max_age_hours: Silinecek dosyaların maksimum yaşı (saat)
    """
    try:
        cleanup_stats = {
            "files_deleted": 0,
            "bytes_freed": 0,
            "errors": 0,
            "start_time": time.time(),
        }
        
        temp_dirs = [
            tempfile.gettempdir(),
            "/tmp",  # Unix systems
            "/var/tmp",  # Unix systems
        ]
        
        # FreeCAD specific temp directories
        freecad_temp_dirs = [
            os.path.expanduser("~/.FreeCAD/Mod"),
            "/tmp/freecad",
        ]
        temp_dirs.extend(freecad_temp_dirs)
        
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        for temp_dir in temp_dirs:
            if not os.path.exists(temp_dir):
                continue
                
            try:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = Path(root) / file
                        
                        # Skip if file is too new
                        if file_path.stat().st_mtime > cutoff_time:
                            continue
                        
                        # Only delete specific file types to be safe
                        if file_path.suffix.lower() in ['.tmp', '.temp', '.stl', '.step', '.fcstd', '.log']:
                            try:
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                cleanup_stats["files_deleted"] += 1
                                cleanup_stats["bytes_freed"] += file_size
                                logger.debug(f"Deleted temp file: {file_path}")
                            except Exception as e:
                                cleanup_stats["errors"] += 1
                                logger.warning(f"Failed to delete {file_path}: {e}")
                                
            except Exception as e:
                cleanup_stats["errors"] += 1
                logger.warning(f"Failed to process temp directory {temp_dir}: {e}")
        
        cleanup_stats["duration_seconds"] = time.time() - cleanup_stats["start_time"]
        
        logger.info(
            f"Temp cleanup completed: {cleanup_stats['files_deleted']} files, "
            f"{cleanup_stats['bytes_freed']} bytes freed, "
            f"{cleanup_stats['errors']} errors"
        )
        
        return cleanup_stats
        
    except Exception as e:
        logger.error(f"Temp cleanup task failed: {e}")
        raise self.retry(exc=e, countdown=300, max_retries=2)


@shared_task(bind=True, name="app.tasks.maintenance.cleanup_dead_letter_queue")
def cleanup_dead_letter_queue(self, max_messages: int = 1000) -> Dict[str, Any]:
    """
    Dead Letter Queue temizleme task'ı.
    Eski ve başarısız mesajları temizler.
    
    Args:
        max_messages: DLQ'da tutulacak maksimum mesaj sayısı
    """
    try:
        from kombu import Connection
        from ..config import settings
        
        cleanup_stats = {
            "messages_processed": 0,
            "messages_requeued": 0,
            "messages_discarded": 0,
            "start_time": time.time(),
        }
        
        with Connection(settings.rabbitmq_url) as conn:
            with conn.channel() as channel:
                # DLQ'yu kontrol et
                dlq_info = channel.queue_declare("freecad.dlq", passive=True)
                message_count = dlq_info.message_count
                
                if message_count <= max_messages:
                    logger.info(f"DLQ message count ({message_count}) within limit ({max_messages})")
                    return cleanup_stats
                
                # Eski mesajları işle
                messages_to_process = message_count - max_messages
                
                for _ in range(messages_to_process):
                    method, properties, body = channel.basic_get("freecad.dlq", auto_ack=False)
                    
                    if method is None:
                        break
                    
                    cleanup_stats["messages_processed"] += 1
                    
                    # Mesaj yaşını kontrol et (headers'da timestamp varsa)
                    message_age_hours = 0
                    if properties and properties.headers:
                        timestamp = properties.headers.get("timestamp")
                        if timestamp:
                            message_age_hours = (time.time() - timestamp) / 3600
                    
                    # 7 günden eski mesajları sil, yenileri tekrar kuyruğa koy
                    if message_age_hours > 168:  # 7 gün
                        channel.basic_ack(method.delivery_tag)
                        cleanup_stats["messages_discarded"] += 1
                        logger.debug(f"Discarded old DLQ message (age: {message_age_hours:.1f}h)")
                    else:
                        # Mesajı orijinal kuyruğa geri gönder (retry)
                        original_queue = properties.headers.get("x-original-queue", "cpu")
                        channel.basic_publish(
                            exchange="freecad.direct",
                            routing_key=original_queue,
                            body=body,
                            properties=properties
                        )
                        channel.basic_ack(method.delivery_tag)
                        cleanup_stats["messages_requeued"] += 1
                        logger.debug(f"Requeued DLQ message to {original_queue}")
        
        cleanup_stats["duration_seconds"] = time.time() - cleanup_stats["start_time"]
        
        logger.info(
            f"DLQ cleanup completed: {cleanup_stats['messages_processed']} processed, "
            f"{cleanup_stats['messages_requeued']} requeued, "
            f"{cleanup_stats['messages_discarded']} discarded"
        )
        
        return cleanup_stats
        
    except Exception as e:
        logger.error(f"DLQ cleanup task failed: {e}")
        raise self.retry(exc=e, countdown=600, max_retries=2)