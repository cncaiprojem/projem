"""
Monitoring tasks for system metrics and health monitoring.
"""
from __future__ import annotations

import logging
import subprocess
import time
from typing import Dict, Any, List

from celery import shared_task
from kombu import Connection

from ..config import settings
from ..core.queue_constants import ALL_QUEUES, DLQ_PREFIX

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="app.tasks.monitoring.collect_queue_metrics")
def collect_queue_metrics(self) -> Dict[str, Any]:
    """
    Queue metriklerini toplama task'ı.
    RabbitMQ queue'larındaki mesaj sayıları ve worker durumlarını izler.
    """
    try:
        metrics = {
            "timestamp": time.time(),
            "queues": {},
            "workers": {},
            "total_active_tasks": 0,
            "total_pending_tasks": 0,
        }
        
        # RabbitMQ queue metrikleri
        try:
            with Connection(settings.rabbitmq_url) as conn:
                with conn.channel() as channel:
                    queue_names = ALL_QUEUES
                    
                    for queue_name in queue_names:
                        try:
                            queue_info = channel.queue_declare(queue_name, passive=True)
                            metrics["queues"][queue_name] = {
                                "message_count": queue_info.message_count,
                                "consumer_count": getattr(queue_info, "consumer_count", 0),
                            }
                            
                            if not queue_name.startswith(DLQ_PREFIX):
                                metrics["total_pending_tasks"] += queue_info.message_count
                                
                        except Exception as e:
                            logger.warning(f"Failed to get metrics for queue {queue_name}: {e}")
                            metrics["queues"][queue_name] = {"error": str(e)}
                            
        except Exception as e:
            logger.error(f"Failed to collect RabbitMQ metrics: {e}")
            metrics["rabbitmq_error"] = str(e)
        
        # Celery worker metrikleri
        try:
            from ..tasks.worker import celery_app
            
            inspect = celery_app.control.inspect()
            
            # Active tasks
            active_tasks = inspect.active()
            if active_tasks:
                for worker, tasks in active_tasks.items():
                    metrics["workers"][worker] = {
                        "active_tasks": len(tasks),
                        "status": "active"
                    }
                    metrics["total_active_tasks"] += len(tasks)
            
            # Worker stats
            stats = inspect.stats()
            if stats:
                for worker, worker_stats in stats.items():
                    if worker not in metrics["workers"]:
                        metrics["workers"][worker] = {}
                    
                    metrics["workers"][worker].update({
                        "pool_processes": worker_stats.get("pool", {}).get("processes", 0),
                        "total_tasks": worker_stats.get("total", 0),
                        "rusage": worker_stats.get("rusage", {}),
                    })
                    
        except Exception as e:
            logger.error(f"Failed to collect Celery metrics: {e}")
            metrics["celery_error"] = str(e)
        
        # Log metrics
        logger.info(
            f"Queue metrics - Pending: {metrics['total_pending_tasks']}, "
            f"Active: {metrics['total_active_tasks']}, "
            f"Workers: {len(metrics['workers'])}"
        )
        
        return metrics
        
    except Exception as e:
        logger.error(f"Queue metrics collection failed: {e}")
        raise self.retry(exc=e, countdown=120, max_retries=3)


@shared_task(bind=True, name="app.tasks.monitoring.freecad_health_check")
def freecad_health_check(self) -> Dict[str, Any]:
    """
    FreeCAD sağlık kontrolü task'ı.
    FreeCAD binary'sinin çalışabilirliğini ve sürümünü kontrol eder.
    """
    try:
        health_status = {
            "timestamp": time.time(),
            "freecad_available": False,
            "freecad_version": None,
            "python_modules": {},
            "test_execution": False,
        }
        
        # FreeCAD binary kontrolü
        try:
            freecad_cmd = settings.freecadcmd_path or "freecadcmd"
            
            # Version check
            result = subprocess.run(
                [freecad_cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                health_status["freecad_available"] = True
                health_status["freecad_version"] = result.stdout.strip()
                logger.debug(f"FreeCAD version: {health_status['freecad_version']}")
            else:
                logger.warning(f"FreeCAD version check failed: {result.stderr}")
                
        except Exception as e:
            logger.error(f"FreeCAD binary check failed: {e}")
            health_status["freecad_error"] = str(e)
        
        # Python modules check (in FreeCAD environment)
        if health_status["freecad_available"]:
            try:
                test_script = '''
import sys
modules = {}
try:
    import FreeCAD
    modules["FreeCAD"] = True
    modules["FreeCAD_version"] = FreeCAD.Version()
except ImportError as e:
    modules["FreeCAD"] = str(e)

try:
    import Part
    modules["Part"] = True
except ImportError as e:
    modules["Part"] = str(e)

try:
    import Mesh
    modules["Mesh"] = True
except ImportError as e:
    modules["Mesh"] = str(e)

try:
    import Draft
    modules["Draft"] = True
except ImportError as e:
    modules["Draft"] = str(e)

try:
    import Path
    modules["Path"] = True
except ImportError as e:
    modules["Path"] = str(e)

# ASM4 check if required
try:
    import Asm4_libs
    modules["Asm4"] = True
except ImportError as e:
    modules["Asm4"] = str(e)

for module, status in modules.items():
    print(f"{module}:{status}")
'''
                
                result = subprocess.run(
                    [freecad_cmd, "-c", test_script],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode == 0:
                    # Parse module status
                    for line in result.stdout.strip().split('\n'):
                        if ':' in line:
                            module, status = line.split(':', 1)
                            health_status["python_modules"][module] = status
                    
                    health_status["test_execution"] = True
                    logger.debug("FreeCAD Python modules check completed")
                else:
                    logger.warning(f"FreeCAD Python test failed: {result.stderr}")
                    health_status["test_error"] = result.stderr
                    
            except Exception as e:
                logger.error(f"FreeCAD Python modules check failed: {e}")
                health_status["modules_error"] = str(e)
        
        # Check ASM4 requirement if needed
        if settings.freecad_asm4_required:
            asm4_available = health_status["python_modules"].get("Asm4") == "True"
            if not asm4_available:
                logger.warning("ASM4 workbench not available but required")
                health_status["asm4_warning"] = True
        
        # Overall health assessment
        freecad_healthy = (
            health_status["freecad_available"] and
            health_status["test_execution"] and
            health_status["python_modules"].get("FreeCAD") == "True" and
            health_status["python_modules"].get("Part") == "True"
        )
        
        health_status["overall_health"] = freecad_healthy
        
        if freecad_healthy:
            logger.info("FreeCAD health check passed")
        else:
            logger.warning("FreeCAD health check failed", extra=health_status)
        
        return health_status
        
    except Exception as e:
        logger.error(f"FreeCAD health check task failed: {e}")
        raise self.retry(exc=e, countdown=300, max_retries=2)


@shared_task(bind=True, name="app.tasks.monitoring.system_resource_check")
def system_resource_check(self) -> Dict[str, Any]:
    """
    Sistem kaynak kullanımı kontrolü task'ı.
    CPU, memory, disk kullanımını izler.
    """
    try:
        import psutil
        
        resource_status = {
            "timestamp": time.time(),
            "cpu": {},
            "memory": {},
            "disk": {},
            "processes": [],
        }
        
        # CPU metrics
        resource_status["cpu"] = {
            "percent": psutil.cpu_percent(interval=1),
            "count": psutil.cpu_count(),
            "count_logical": psutil.cpu_count(logical=True),
        }
        
        # Memory metrics
        memory = psutil.virtual_memory()
        resource_status["memory"] = {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
            "free": memory.free,
        }
        
        # Disk metrics
        disk = psutil.disk_usage('/')
        resource_status["disk"] = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": (disk.used / disk.total) * 100,
        }
        
        # Process metrics (FreeCAD and Celery processes)
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                pinfo = proc.info
                if 'freecad' in pinfo['name'].lower() or 'celery' in pinfo['name'].lower():
                    resource_status["processes"].append(pinfo)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Resource warnings
        warnings = []
        if resource_status["cpu"]["percent"] > 80:
            warnings.append(f"High CPU usage: {resource_status['cpu']['percent']:.1f}%")
        
        if resource_status["memory"]["percent"] > 85:
            warnings.append(f"High memory usage: {resource_status['memory']['percent']:.1f}%")
        
        if resource_status["disk"]["percent"] > 90:
            warnings.append(f"High disk usage: {resource_status['disk']['percent']:.1f}%")
        
        resource_status["warnings"] = warnings
        
        if warnings:
            logger.warning(f"Resource warnings: {', '.join(warnings)}")
        else:
            logger.info("System resources within normal limits")
        
        return resource_status
        
    except Exception as e:
        logger.error(f"System resource check failed: {e}")
        raise self.retry(exc=e, countdown=180, max_retries=2)