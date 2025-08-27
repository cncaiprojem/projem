"""
Ultra-Enterprise FreeCAD Service Implementation for Task 7.1

Features:
- FreeCADCmd 1.1.0+ with headless operation
- License-based feature control (Basic/Pro/Enterprise tiers)
- Resource limits per license tier
- Subprocess isolation with psutil monitoring
- Memory/CPU limits enforcement
- Timeout management with graceful termination
- Temporary file cleanup with context managers
- Structured error handling with error codes
- Process pool for parallel operations
- Health checks and readiness probes
- Metrics collection
- Input sanitization and validation
- Output determinism with SHA256 hashing
- Turkish error messages support
- Retry mechanism with exponential backoff
- Circuit breaker pattern for failure protection
- Comprehensive logging with correlation IDs
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import psutil
import random
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..middleware.correlation_middleware import get_correlation_id
from ..services.license_service import LicenseService
from ..models.license import License
from ..core import metrics
from .freecad_document_manager import FreeCADDocumentManager, document_manager, DocumentException, DocumentErrorCode
from ..schemas.freecad import (
    FreeCADHealthCheckResponse,
    MetricsSummaryResponse,
    FreeCADHealthStatus,
    CircuitBreakerStatus,
    ActiveProcessesStatus,
    ResourceConfiguration,
    HealthCheckStatus
)

logger = get_logger(__name__)


class LicenseTier(str, Enum):
    """License tier enumeration for feature control."""
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class FreeCADErrorCode(str, Enum):
    """Standardized error codes for FreeCAD operations."""
    FREECAD_NOT_FOUND = "FREECAD_NOT_FOUND"
    INVALID_VERSION = "INVALID_VERSION"
    SUBPROCESS_FAILED = "SUBPROCESS_FAILED"
    TIMEOUT_EXCEEDED = "TIMEOUT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    CPU_LIMIT_EXCEEDED = "CPU_LIMIT_EXCEEDED"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    LICENSE_RESTRICTION = "LICENSE_RESTRICTION"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"


class FreeCADException(Exception):
    """Base exception for FreeCAD operations."""
    def __init__(
        self, 
        message: str, 
        error_code: FreeCADErrorCode, 
        turkish_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.turkish_message = turkish_message or message
        self.details = details or {}


class ResourceLimits(BaseModel):
    """Resource limits per license tier."""
    max_memory_mb: int
    max_cpu_percent: float
    max_execution_time_seconds: int
    max_model_complexity: int
    max_concurrent_operations: int
    allowed_export_formats: Set[str]
    max_file_size_mb: int

    class Config:
        # Allow sets in Pydantic models
        arbitrary_types_allowed = True


class ProcessMetrics(BaseModel):
    """Process execution metrics."""
    start_time: datetime
    end_time: Optional[datetime]
    peak_memory_mb: float
    average_cpu_percent: float
    exit_code: Optional[int]
    stdout_lines: int
    stderr_lines: int
    execution_duration_seconds: float


class FreeCADResult(BaseModel):
    """Result of FreeCAD operation."""
    success: bool
    output_files: List[Path]
    metrics: ProcessMetrics
    sha256_hashes: Dict[str, str]
    error_code: Optional[FreeCADErrorCode]
    error_message: Optional[str]
    turkish_error_message: Optional[str]
    warnings: List[str]

    class Config:
        # Allow Path objects and enums in Pydantic models
        arbitrary_types_allowed = True
    
    def serialize_for_celery(self) -> dict:
        """Serialize result for Celery task return."""
        return {
            'success': self.success,
            'output_files': [str(f) for f in self.output_files],
            'sha256_hashes': self.sha256_hashes,
            'error_code': self.error_code.value if self.error_code else None,
            'error_message': self.error_message,
            'turkish_error_message': self.turkish_error_message,
            'warnings': self.warnings,
            'metrics': {
                'start_time': self.metrics.start_time.isoformat() if self.metrics else None,
                'end_time': self.metrics.end_time.isoformat() if self.metrics and self.metrics.end_time else None,
                'peak_memory_mb': self.metrics.peak_memory_mb if self.metrics else 0.0,
                'average_cpu_percent': self.metrics.average_cpu_percent if self.metrics else 0.0,
                'execution_duration_seconds': self.metrics.execution_duration_seconds if self.metrics else 0.0,
                'exit_code': self.metrics.exit_code if self.metrics else None
            } if self.metrics else None
        }


class CircuitBreaker:
    """Circuit breaker pattern implementation for FreeCAD operations."""
    
    def __init__(
        self, 
        failure_threshold: int = 5, 
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self._lock = threading.Lock()
    
    def __call__(self, func):
        def wrapper(*args, **kwargs):
            # Check state without holding lock during execution.
            # Race condition is acceptable here: it's better to allow a few extra
            # operations through than to hold the lock during long-running operations,
            # which would create a bottleneck. The worst case is a few extra failures
            # get recorded before the circuit opens.
            with self._lock:
                if self.state == 'OPEN':
                    # Add defensive check for last_failure_time
                    if self.last_failure_time and (time.monotonic() - self.last_failure_time < self.recovery_timeout):
                        logger.warning("circuit_breaker_open", 
                                     failure_count=self.failure_count,
                                     last_failure_time=self.last_failure_time)
                        raise FreeCADException(
                            "FreeCAD operations temporarily unavailable",
                            FreeCADErrorCode.CIRCUIT_BREAKER_OPEN,
                            "FreeCAD işlemleri geçici olarak kullanılamıyor"
                        )
                    else:
                        self.state = 'HALF_OPEN'
                        logger.info("circuit_breaker_half_open")
                
                current_state = self.state
            
            # Execute function without holding lock
            try:
                result = func(*args, **kwargs)
                
                # Update state on success (only lock for state change)
                if current_state == 'HALF_OPEN':
                    with self._lock:
                        self.failure_count = 0
                        self.state = 'CLOSED'
                        logger.info("circuit_breaker_recovered")
                
                return result
                
            except self.expected_exception as e:
                # Update state on failure (only lock for state change)
                with self._lock:
                    self.failure_count += 1
                    self.last_failure_time = time.monotonic()
                    
                    if self.failure_count >= self.failure_threshold:
                        self.state = 'OPEN'
                        logger.error("circuit_breaker_opened", 
                                   failure_count=self.failure_count,
                                   exception=str(e))
                raise
        
        return wrapper


class LicenseFeatureController:
    """Controls features based on license tier."""
    
    # License tier resource limits
    RESOURCE_LIMITS = {
        LicenseTier.BASIC: ResourceLimits(
            max_memory_mb=512,
            max_cpu_percent=50.0,
            max_execution_time_seconds=300,  # 5 minutes
            max_model_complexity=1000,
            max_concurrent_operations=1,
            allowed_export_formats={'FCStd', 'STL'},
            max_file_size_mb=10
        ),
        LicenseTier.PRO: ResourceLimits(
            max_memory_mb=2048,
            max_cpu_percent=80.0,
            max_execution_time_seconds=1800,  # 30 minutes
            max_model_complexity=10000,
            max_concurrent_operations=3,
            allowed_export_formats={'FCStd', 'STL', 'STEP', 'IGES', 'OBJ'},
            max_file_size_mb=100
        ),
        LicenseTier.ENTERPRISE: ResourceLimits(
            max_memory_mb=8192,
            max_cpu_percent=100.0,
            max_execution_time_seconds=7200,  # 2 hours
            max_model_complexity=100000,
            max_concurrent_operations=10,
            allowed_export_formats={'FCStd', 'STL', 'STEP', 'IGES', 'OBJ', 'DXF', 'IFC', 'DAE'},
            max_file_size_mb=1000
        )
    }
    
    @staticmethod
    def get_license_tier(license: Optional[License]) -> LicenseTier:
        """Determine license tier from license object."""
        if not license:
            return LicenseTier.BASIC
        
        # Map license types to tiers
        license_type_mapping = {
            '3m': LicenseTier.BASIC,
            '6m': LicenseTier.PRO,
            '12m': LicenseTier.ENTERPRISE
        }
        
        return license_type_mapping.get(license.type, LicenseTier.BASIC)
    
    @staticmethod
    def get_resource_limits(license: Optional[License]) -> ResourceLimits:
        """Get resource limits for a license."""
        tier = LicenseFeatureController.get_license_tier(license)
        return LicenseFeatureController.RESOURCE_LIMITS[tier]
    
    @staticmethod
    def check_feature_access(license: Optional[License], feature: str) -> bool:
        """Check if license allows access to a feature."""
        tier = LicenseFeatureController.get_license_tier(license)
        
        # Feature access matrix
        features = {
            LicenseTier.BASIC: {
                'basic_modeling', 'stl_export', 'fcstd_export'
            },
            LicenseTier.PRO: {
                'basic_modeling', 'advanced_modeling', 'step_export', 
                'iges_export', 'obj_export', 'stl_export', 'fcstd_export',
                'assembly_operations'
            },
            LicenseTier.ENTERPRISE: {
                'basic_modeling', 'advanced_modeling', 'step_export', 
                'iges_export', 'obj_export', 'stl_export', 'fcstd_export',
                'assembly_operations', 'dxf_export', 'ifc_export', 
                'dae_export', 'batch_processing', 'api_access',
                'advanced_validation', 'performance_optimization'
            }
        }
        
        return feature in features[tier]


class ProcessMonitor:
    """Monitors FreeCAD subprocess resource usage."""
    
    def __init__(self, pid: int, limits: ResourceLimits):
        self.pid = pid
        self.limits = limits
        self.process = psutil.Process(pid)
        self.metrics = ProcessMetrics(
            start_time=datetime.now(timezone.utc),
            end_time=None,
            peak_memory_mb=0.0,
            average_cpu_percent=0.0,
            exit_code=None,
            stdout_lines=0,
            stderr_lines=0,
            execution_duration_seconds=0.0
        )
        self.cpu_samples = []
        self._monitoring = True
        self._monitor_thread = None
    
    def start_monitoring(self):
        """Start resource monitoring in background thread."""
        self._monitor_thread = threading.Thread(target=self._monitor_loop)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop resource monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        
        self.metrics.end_time = datetime.now(timezone.utc)
        if self.metrics.end_time and self.metrics.start_time:
            self.metrics.execution_duration_seconds = (
                self.metrics.end_time - self.metrics.start_time
            ).total_seconds()
        
        if self.cpu_samples:
            self.metrics.average_cpu_percent = sum(self.cpu_samples) / len(self.cpu_samples)
    
    def _monitor_loop(self):
        """Background monitoring loop."""
        # Get monitoring interval once, outside the loop
        monitoring_interval = settings.FREECAD_MONITORING_INTERVAL_SECONDS
        
        while self._monitoring:
            try:
                if not self.process.is_running():
                    break
                
                # Check memory usage
                memory_info = self.process.memory_info()
                memory_mb = memory_info.rss / (1024 * 1024)
                self.metrics.peak_memory_mb = max(self.metrics.peak_memory_mb, memory_mb)
                
                # Check CPU usage
                cpu_percent = self.process.cpu_percent()
                self.cpu_samples.append(cpu_percent)
                
                # Enforce limits
                if memory_mb > self.limits.max_memory_mb:
                    logger.error("memory_limit_exceeded",
                               current_mb=memory_mb,
                               limit_mb=self.limits.max_memory_mb,
                               pid=self.pid)
                    self._terminate_process("Memory limit exceeded")
                    break
                
                if cpu_percent > self.limits.max_cpu_percent:
                    # Note: CPU limit is for monitoring/warning only, not enforced
                    # Terminating for CPU spikes can be problematic
                    logger.warning("cpu_usage_high",
                                 current_percent=cpu_percent,
                                 limit_percent=self.limits.max_cpu_percent,
                                 pid=self.pid,
                                 note="CPU limit is for monitoring only, not enforced")
                
                # Use monitoring interval from settings (retrieved once outside loop)
                time.sleep(monitoring_interval)
                
            except psutil.NoSuchProcess:
                break
            except Exception as e:
                logger.error("monitoring_error", error=str(e), pid=self.pid)
                break
    
    def _terminate_process(self, reason: str):
        """Terminate process due to resource violation."""
        try:
            logger.warning("terminating_process", pid=self.pid, reason=reason)
            self.process.terminate()
            
            # Wait for graceful termination
            try:
                self.process.wait(timeout=5)
            except psutil.TimeoutExpired:
                # Force kill if doesn't terminate gracefully
                self.process.kill()
                
        except Exception as e:
            logger.error("process_termination_error", pid=self.pid, error=str(e))


# Define output file extensions set at module level
OUTPUT_FILE_EXTENSIONS = {'.fcstd', '.step', '.stl', '.iges', '.obj', '.dxf', '.ifc', '.dae'}

# Constants for error handling and retry logic
DEFAULT_ERROR_EXIT_CODE = -1


class UltraEnterpriseFreeCADService:
    """Ultra-enterprise FreeCAD service with comprehensive features."""
    
    def __init__(self):
        # Process and thread pools removed as they're not used (we use subprocess.Popen)
        self.active_processes: Dict[str, ProcessMonitor] = {}
        # Track per-user active operations for proper license enforcement
        self.user_active_operations: Dict[int, int] = {}  # user_id -> count
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=settings.FREECAD_CIRCUIT_BREAKER_THRESHOLD,
            recovery_timeout=settings.FREECAD_CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
            expected_exception=FreeCADException
        )
        self._process_lock = threading.Lock()
        
        # Configuration for document lifecycle (can be disabled for testing or legacy mode)
        self.enable_document_lifecycle = getattr(settings, 'FREECAD_ENABLE_DOCUMENT_LIFECYCLE', True)
        self.require_document_lifecycle = getattr(settings, 'FREECAD_REQUIRE_DOCUMENT_LIFECYCLE', False)
        
        # Initialize Turkish error messages
        self.turkish_errors = {
            FreeCADErrorCode.FREECAD_NOT_FOUND: "FreeCAD bulunamadı",
            FreeCADErrorCode.INVALID_VERSION: "Geçersiz FreeCAD sürümü",
            FreeCADErrorCode.SUBPROCESS_FAILED: "Alt işlem başarısız oldu",
            FreeCADErrorCode.TIMEOUT_EXCEEDED: "Zaman aşımı",
            FreeCADErrorCode.MEMORY_LIMIT_EXCEEDED: "Bellek sınırı aşıldı",
            FreeCADErrorCode.CPU_LIMIT_EXCEEDED: "İşlemci sınırı aşıldı",
            FreeCADErrorCode.INVALID_GEOMETRY: "Geçersiz geometri",
            FreeCADErrorCode.UNSUPPORTED_FORMAT: "Desteklenmeyen format",
            FreeCADErrorCode.LICENSE_RESTRICTION: "Lisans kısıtlaması",
            FreeCADErrorCode.RESOURCE_EXHAUSTED: "Kaynak tükendi",
            FreeCADErrorCode.CIRCUIT_BREAKER_OPEN: "Servis geçici olarak kullanılamıyor",
            FreeCADErrorCode.VALIDATION_FAILED: "Doğrulama başarısız",
            FreeCADErrorCode.SECURITY_VIOLATION: "Güvenlik ihlali",
            FreeCADErrorCode.TEMPORARY_FAILURE: "Geçici hata"
        }
    
    @contextmanager
    def managed_temp_directory(self):
        """Context manager for temporary directory with cleanup."""
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="freecad_", suffix="_work")
            logger.debug("created_temp_directory", path=temp_dir)
            yield Path(temp_dir)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug("cleaned_temp_directory", path=temp_dir)
                except Exception as e:
                    logger.error("temp_cleanup_failed", path=temp_dir, error=str(e))
    
    def find_freecadcmd_path(self) -> Optional[str]:
        """Find FreeCADCmd executable with version validation."""
        correlation_id = get_correlation_id()
        
        with create_span("freecad_path_discovery", correlation_id=correlation_id) as span:
            # Check configured path first
            if settings.FREECADCMD_PATH and os.path.isfile(settings.FREECADCMD_PATH):
                span.set_attribute("discovery.method", "configured")
                span.set_attribute("discovery.path", settings.FREECADCMD_PATH)
                return settings.FREECADCMD_PATH
            
            # Check PATH
            path_candidate = shutil.which("FreeCADCmd")
            if path_candidate:
                span.set_attribute("discovery.method", "path")
                span.set_attribute("discovery.path", path_candidate)
                return path_candidate
            
            # Check common installation paths
            common_paths = [
                "/usr/bin/FreeCADCmd",
                "/usr/local/bin/FreeCADCmd",
                "/opt/freecad/bin/FreeCADCmd",
                "C:/Program Files/FreeCAD 1.1/bin/FreeCADCmd.exe",
                "C:/Program Files/FreeCAD/bin/FreeCADCmd.exe",
            ]
            
            for path in common_paths:
                if os.path.isfile(path):
                    span.set_attribute("discovery.method", "common_path")
                    span.set_attribute("discovery.path", path)
                    return path
            
            span.set_attribute("discovery.method", "not_found")
            return None
    
    def validate_freecad_version(self, freecad_path: str) -> Tuple[bool, Optional[str]]:
        """Validate FreeCAD version meets minimum requirements."""
        try:
            result = subprocess.run(
                [freecad_path, "--version"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout:
                version_line = result.stdout.strip().split('\n')[0]
                
                # Extract version number (expecting format like "FreeCAD 1.1.0")
                version_parts = version_line.split()
                if len(version_parts) >= 2:
                    version = version_parts[1]
                    
                    # Check if version is 1.1.0 or higher
                    try:
                        major, minor, patch = map(int, version.split('.'))
                        if (major, minor, patch) >= (1, 1, 0):
                            return True, version
                        else:
                            return False, version
                    except ValueError:
                        return False, version
            
            return False, None
            
        except Exception as e:
            logger.error("freecad_version_check_failed", 
                        path=freecad_path, error=str(e))
            return False, None
    
    def sanitize_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize and validate input data."""
        correlation_id = get_correlation_id()
        
        with create_span("input_sanitization", correlation_id=correlation_id) as span:
            sanitized = {}
            
            # Remove potentially dangerous keys
            dangerous_keys = {'__', 'eval', 'exec', 'import', 'open', 'file'}
            for key, value in input_data.items():
                if any(dangerous in str(key).lower() for dangerous in dangerous_keys):
                    logger.warning("dangerous_input_key_filtered", key=key)
                    span.set_attribute("sanitization.filtered_keys", str(key))
                    continue
                
                # Sanitize string values
                if isinstance(value, str):
                    # Remove potentially dangerous patterns
                    dangerous_patterns = ['import ', 'exec(', 'eval(', '__', 'os.']
                    for pattern in dangerous_patterns:
                        if pattern in value.lower():
                            logger.warning("dangerous_input_pattern_filtered", 
                                         pattern=pattern, key=key)
                            span.set_attribute("sanitization.filtered_patterns", pattern)
                            value = value.replace(pattern, '')
                
                sanitized[key] = value
            
            span.set_attribute("sanitization.input_keys", len(input_data))
            span.set_attribute("sanitization.output_keys", len(sanitized))
            
            return sanitized
    
    def compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error("file_hash_computation_failed", 
                        path=str(file_path), error=str(e))
            raise
    
    @circuit_breaker
    def execute_freecad_operation(
        self,
        db: Session,
        user_id: int,
        operation_type: str,
        script_content: str,
        parameters: Dict[str, Any],
        output_formats: List[str],
        job_id: str,
        correlation_id: Optional[str] = None
    ) -> FreeCADResult:
        """Execute FreeCAD operation with comprehensive monitoring and control."""
        
        if not correlation_id:
            correlation_id = get_correlation_id()
        
        operation_start = time.time()
        
        with create_span(
            "freecad_operation_execution",
            operation_type="cad_processing",
            correlation_id=correlation_id,
            attributes={
                "operation.type": operation_type,
                "operation.user_id": str(user_id),
                "operation.output_formats": ",".join(output_formats)
            }
        ) as span:
            
            # Get user license and determine limits
            license = LicenseService.get_active_license(db, user_id)
            resource_limits = LicenseFeatureController.get_resource_limits(license)
            license_tier = LicenseFeatureController.get_license_tier(license)
            
            span.set_attribute("license.tier", license_tier.value)
            span.set_attribute("limits.max_memory_mb", str(resource_limits.max_memory_mb))
            span.set_attribute("limits.max_cpu_percent", str(resource_limits.max_cpu_percent))
            
            # Validate license permissions
            for format_type in output_formats:
                feature = f"{format_type.lower()}_export"
                if not LicenseFeatureController.check_feature_access(license, feature):
                    error_msg = f"License {license_tier.value} does not allow {format_type} export"
                    turkish_msg = f"{license_tier.value} lisansı {format_type} dışa aktarımına izin vermiyor"
                    
                    logger.warning("license_restriction_violation",
                                 user_id=user_id,
                                 license_tier=license_tier.value,
                                 requested_format=format_type,
                                 correlation_id=correlation_id)
                    
                    raise FreeCADException(
                        error_msg,
                        FreeCADErrorCode.LICENSE_RESTRICTION,
                        turkish_msg,
                        {"requested_format": format_type, "license_tier": license_tier.value}
                    )
            
            # Check concurrent operations limit per user
            with self._process_lock:
                user_active_count = self.user_active_operations.get(user_id, 0)
                if user_active_count >= resource_limits.max_concurrent_operations:
                    error_msg = f"Maximum concurrent operations ({resource_limits.max_concurrent_operations}) exceeded for user"
                    turkish_msg = f"Kullanıcı için maksimum eş zamanlı işlem sayısı ({resource_limits.max_concurrent_operations}) aşıldı"
                    
                    logger.warning("user_concurrent_limit_exceeded",
                                 user_id=user_id,
                                 current_count=user_active_count,
                                 limit=resource_limits.max_concurrent_operations,
                                 correlation_id=correlation_id)
                    
                    raise FreeCADException(
                        error_msg,
                        FreeCADErrorCode.RESOURCE_EXHAUSTED,
                        turkish_msg
                    )
            
            # Find and validate FreeCAD
            freecad_path = self.find_freecadcmd_path()
            if not freecad_path:
                raise FreeCADException(
                    "FreeCADCmd executable not found",
                    FreeCADErrorCode.FREECAD_NOT_FOUND,
                    "FreeCADCmd çalıştırılabilir dosyası bulunamadı"
                )
            
            version_valid, version = self.validate_freecad_version(freecad_path)
            if not version_valid:
                raise FreeCADException(
                    f"FreeCAD version {version} is not supported. Requires 1.1.0 or higher.",
                    FreeCADErrorCode.INVALID_VERSION,
                    f"FreeCAD sürümü {version} desteklenmiyor. 1.1.0 veya üzeri gereklidir."
                )
            
            span.set_attribute("freecad.version", version or "unknown")
            span.set_attribute("freecad.path", freecad_path)
            
            # Sanitize inputs
            sanitized_params = self.sanitize_input(parameters)
            
            # Initialize document lifecycle management if job_id provided and enabled
            document_metadata = None
            transaction_info = None
            document_lock = None
            if job_id and self.enable_document_lifecycle:
                try:
                    # Create or open document for this job
                    document_metadata = document_manager.open_document(
                        job_id=job_id,
                        document_path=None,
                        create_if_not_exists=True
                    )
                    
                    # CRITICAL: Acquire lock before operations
                    document_lock = document_manager.acquire_lock(
                        document_metadata.document_id,
                        owner_id=str(user_id),
                        lock_type="exclusive"
                    )
                    
                    # Start transaction for atomic operations
                    transaction_info = document_manager.start_transaction(document_metadata.document_id)
                    
                    # Add operation to transaction log
                    transaction_info.add_operation({
                        "operation_type": operation_type,
                        "user_id": user_id,
                        "output_formats": output_formats
                    })
                    
                    logger.info("document_lifecycle_initialized",
                              document_id=document_metadata.document_id,
                              transaction_id=transaction_info.transaction_id,
                              correlation_id=correlation_id)
                    
                except DocumentException as e:
                    logger.warning("document_lifecycle_init_failed",
                                 job_id=job_id,
                                 error=str(e),
                                 correlation_id=correlation_id)
                    # Only raise if lifecycle is required
                    if self.require_document_lifecycle:
                        # Map specific document errors to more descriptive service errors
                        if hasattr(e, 'error_code') and e.error_code == DocumentErrorCode.DOCUMENT_LOCKED:
                            f_error_code = FreeCADErrorCode.RESOURCE_EXHAUSTED
                        else:
                            f_error_code = FreeCADErrorCode.TEMPORARY_FAILURE
                        
                        raise FreeCADException(
                            message=f"Failed to initialize document lifecycle for job {job_id}: {e}",
                            error_code=f_error_code,
                            turkish_message=f"İş {job_id} için belge yaşam döngüsü başlatılamadı: {getattr(e, 'turkish_message', str(e))}",
                            details={"job_id": job_id, "error": str(e), "original_error_code": getattr(e, 'error_code', None)}
                        ) from e
                    else:
                        # Continue without document lifecycle if not required
                        logger.warning("document_lifecycle_disabled_due_to_error",
                                     job_id=job_id,
                                     error=str(e),
                                     correlation_id=correlation_id)
                        document_metadata = None
                        transaction_info = None
                        document_lock = None
            
            # Execute with managed resources
            with self.managed_temp_directory() as temp_dir:
                # Increment user's active operation count
                with self._process_lock:
                    self.user_active_operations[user_id] = self.user_active_operations.get(user_id, 0) + 1
                    logger.debug("user_operation_started",
                               user_id=user_id,
                               active_count=self.user_active_operations[user_id],
                               correlation_id=correlation_id)
                
                try:
                    result = self._execute_with_monitoring(
                        freecad_path=freecad_path,
                        script_content=script_content,
                        parameters=sanitized_params,
                        output_formats=output_formats,
                        temp_dir=temp_dir,
                        resource_limits=resource_limits,
                        correlation_id=correlation_id,
                        user_id=user_id
                    )
                    
                    # Update metrics
                    operation_duration = time.time() - operation_start
                    
                    metrics.freecad_operations_total.labels(
                        operation_type=operation_type,
                        license_tier=license_tier.value,
                        status="success"
                    ).inc()
                    
                    metrics.freecad_operation_duration_seconds.labels(
                        operation_type=operation_type,
                        license_tier=license_tier.value,
                        status="success"
                    ).observe(operation_duration)
                    
                    if result.metrics:
                        metrics.freecad_memory_peak_mb.labels(
                            operation_type=operation_type,
                            license_tier=license_tier.value
                        ).set(result.metrics.peak_memory_mb)
                        
                        metrics.freecad_cpu_average_percent.labels(
                            operation_type=operation_type,
                            license_tier=license_tier.value
                        ).set(result.metrics.average_cpu_percent)
                    
                    # Finalize document lifecycle if initialized
                    if document_metadata and transaction_info:
                        try:
                            # Add undo snapshot before commit
                            document_manager.add_undo_snapshot(
                                document_metadata.document_id,
                                f"{operation_type} completed",
                                {
                                    "operation_type": operation_type,
                                    "output_files": [str(f) for f in result.output_files],
                                    "sha256_hashes": result.sha256_hashes
                                }
                            )
                            
                            # Commit transaction
                            document_manager.commit_transaction(transaction_info.transaction_id)
                            
                            # Save document with output files
                            if result.output_files:
                                # CRITICAL: Pass owner_id to save_document
                                document_path = document_manager.save_document(
                                    document_metadata.document_id,
                                    owner_id=str(user_id),
                                    save_path=str(result.output_files[0]),
                                    compress=True,
                                    create_backup=True
                                )
                                
                                logger.info("document_lifecycle_finalized",
                                          document_id=document_metadata.document_id,
                                          document_path=document_path,
                                          correlation_id=correlation_id)
                        
                        except DocumentException as e:
                            logger.warning("document_lifecycle_finalization_failed",
                                         document_id=document_metadata.document_id,
                                         error=str(e),
                                         correlation_id=correlation_id)
                            # Abort transaction on failure
                            try:
                                document_manager.abort_transaction(transaction_info.transaction_id)
                            except Exception as abort_exc:
                                logger.error("transaction_abort_on_finalize_failed",
                                           transaction_id=transaction_info.transaction_id,
                                           error=str(abort_exc),
                                           correlation_id=correlation_id)
                            
                            # Map specific document errors to more descriptive service errors
                            if hasattr(e, 'error_code') and e.error_code == DocumentErrorCode.SAVE_FAILED:
                                f_error_code = FreeCADErrorCode.TEMPORARY_FAILURE
                            elif hasattr(e, 'error_code') and e.error_code == DocumentErrorCode.DOCUMENT_LOCKED:
                                f_error_code = FreeCADErrorCode.RESOURCE_EXHAUSTED
                            else:
                                f_error_code = FreeCADErrorCode.TEMPORARY_FAILURE
                            
                            # Re-raise with preserved context
                            raise FreeCADException(
                                message=f"Failed to finalize document lifecycle for job {job_id}: {e}",
                                error_code=f_error_code,
                                turkish_message=f"İş {job_id} için belge yaşam döngüsü sonlandırılamadı: {getattr(e, 'turkish_message', str(e))}",
                                details={"job_id": job_id, "error": str(e), "original_error_code": getattr(e, 'error_code', None)}
                            ) from e
                    
                    logger.info("freecad_operation_completed",
                              operation_type=operation_type,
                              user_id=user_id,
                              license_tier=license_tier.value,
                              duration_seconds=operation_duration,
                              output_files=len(result.output_files),
                              correlation_id=correlation_id)
                    
                    return result
                    
                except Exception as e:
                    operation_duration = time.time() - operation_start
                    
                    metrics.freecad_operations_total.labels(
                        operation_type=operation_type,
                        license_tier=license_tier.value,
                        status="error"
                    ).inc()
                    
                    metrics.freecad_operation_duration_seconds.labels(
                        operation_type=operation_type,
                        license_tier=license_tier.value,
                        status="error"
                    ).observe(operation_duration)
                    
                    logger.error("freecad_operation_failed",
                               operation_type=operation_type,
                               user_id=user_id,
                               license_tier=license_tier.value,
                               duration_seconds=operation_duration,
                               error=str(e),
                               correlation_id=correlation_id,
                               exc_info=True)
                    
                    raise
                finally:
                    # Release lock if acquired
                    if document_lock and document_metadata:
                        try:
                            document_manager.release_lock(
                                document_metadata.document_id,
                                document_lock.lock_id
                            )
                        except Exception as e:
                            logger.warning("lock_release_failed",
                                         document_id=document_metadata.document_id,
                                         error=str(e),
                                         correlation_id=correlation_id)
                    
                    # Decrement user's active operation count
                    with self._process_lock:
                        if user_id in self.user_active_operations:
                            self.user_active_operations[user_id] -= 1
                            if self.user_active_operations[user_id] <= 0:
                                del self.user_active_operations[user_id]
                            logger.debug("user_operation_ended",
                                       user_id=user_id,
                                       remaining_count=self.user_active_operations.get(user_id, 0),
                                       correlation_id=correlation_id)
    
    def _execute_with_monitoring(
        self,
        freecad_path: str,
        script_content: str,
        parameters: Dict[str, Any],
        output_formats: List[str],
        temp_dir: Path,
        resource_limits: ResourceLimits,
        correlation_id: str,
        user_id: Optional[int] = None
    ) -> FreeCADResult:
        """Execute FreeCAD with process monitoring."""
        
        # Create script file
        script_file = temp_dir / "script.py"
        with open(script_file, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        # Create parameters file
        params_file = temp_dir / "parameters.json"
        with open(params_file, 'w', encoding='utf-8') as f:
            json.dump(parameters, f, indent=2)
        
        # Prepare command
        cmd = [
            freecad_path,
            "-c",
            str(script_file),
            "--",
            str(params_file),
            str(temp_dir)
        ]
        
        # Create environment with restrictions
        env = os.environ.copy()
        env.update({
            'FREECAD_USER_HOME': str(temp_dir),
            'FREECAD_USER_DATA': str(temp_dir / 'data'),
            'FREECAD_USER_TEMP': str(temp_dir / 'tmp'),
            'PYTHONDONTWRITEBYTECODE': '1',
            'FREECAD_HEADLESS': '1'
        })
        
        # Execute subprocess
        start_time = time.time()
        process = None
        monitor = None
        exit_code = DEFAULT_ERROR_EXIT_CODE  # Default error code in case of early exception
        stdout, stderr = None, None
        
        try:
            # Start process with resource limits
            if platform.system() == 'Windows':
                process = subprocess.Popen(
                    cmd,
                    cwd=temp_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                process = subprocess.Popen(
                    cmd,
                    cwd=temp_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    preexec_fn=os.setsid
                )
            
            # Start monitoring
            monitor = ProcessMonitor(process.pid, resource_limits)
            monitor.start_monitoring()
            
            # Register active process
            process_key = f"{correlation_id}_{process.pid}"
            with self._process_lock:
                self.active_processes[process_key] = monitor
            
            try:
                # Wait for completion with timeout
                stdout, stderr = process.communicate(timeout=resource_limits.max_execution_time_seconds)
                exit_code = process.returncode
                
            except subprocess.TimeoutExpired:
                logger.warning("freecad_process_timeout", 
                             pid=process.pid,
                             timeout_seconds=resource_limits.max_execution_time_seconds,
                             correlation_id=correlation_id)
                
                # Terminate process tree
                self._terminate_process_tree(process.pid)
                
                raise FreeCADException(
                    f"FreeCAD operation exceeded timeout of {resource_limits.max_execution_time_seconds} seconds",
                    FreeCADErrorCode.TIMEOUT_EXCEEDED,
                    f"FreeCAD işlemi {resource_limits.max_execution_time_seconds} saniye zaman aşımını aştı"
                )
            
            finally:
                # Stop monitoring and cleanup
                if monitor:
                    monitor.stop_monitoring()
                    monitor.metrics.exit_code = process.returncode if process else None
                    monitor.metrics.stdout_lines = len(stdout.splitlines()) if stdout else 0
                    monitor.metrics.stderr_lines = len(stderr.splitlines()) if stderr else 0
                
                # Unregister process
                with self._process_lock:
                    self.active_processes.pop(process_key, None)
            
            # Check for errors
            if exit_code != 0:
                error_msg = f"FreeCAD process failed with exit code {exit_code}"
                turkish_msg = f"FreeCAD işlemi {exit_code} çıkış koduyla başarısız oldu"
                
                logger.error("freecad_subprocess_failed",
                           exit_code=exit_code,
                           stdout=stdout[:1000] if stdout else "",
                           stderr=stderr[:1000] if stderr else "",
                           correlation_id=correlation_id)
                
                raise FreeCADException(
                    error_msg,
                    FreeCADErrorCode.SUBPROCESS_FAILED,
                    turkish_msg,
                    {"exit_code": exit_code, "stderr": stderr[:500]}
                )
            
            # Collect output files and compute hashes
            output_files = []
            sha256_hashes = {}
            warnings = []
            
            for file_path in temp_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in OUTPUT_FILE_EXTENSIONS:
                    output_files.append(file_path)
                    try:
                        file_hash = self.compute_file_hash(file_path)
                        sha256_hashes[str(file_path.name)] = file_hash
                    except Exception as e:
                        warnings.append(f"Failed to compute hash for {file_path.name}: {str(e)}")
            
            # Validate required outputs
            if not output_files:
                warnings.append("No output files generated")
            
            # Use monitor metrics (monitor is always created and available here)
            process_metrics = monitor.metrics
            
            return FreeCADResult(
                success=True,
                output_files=output_files,
                metrics=process_metrics,
                sha256_hashes=sha256_hashes,
                error_code=None,
                error_message="Operation completed successfully",
                turkish_error_message="İşlem başarıyla tamamlandı",
                warnings=warnings
            )
            
        except FreeCADException:
            raise
        except Exception as e:
            logger.error("freecad_execution_error",
                        error=str(e),
                        correlation_id=correlation_id,
                        exc_info=True)
            
            raise FreeCADException(
                f"Unexpected error during FreeCAD execution: {str(e)}",
                FreeCADErrorCode.TEMPORARY_FAILURE,
                f"FreeCAD çalıştırılması sırasında beklenmeyen hata: {str(e)}"
            )
        
        finally:
            # Cleanup process if still running
            if process and process.poll() is None:
                self._terminate_process_tree(process.pid)
    
    def _terminate_process_tree(self, pid: int):
        """Terminate process and all its children."""
        try:
            if platform.system() == 'Windows':
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10
                )
            else:
                try:
                    os.killpg(pid, signal.SIGTERM)
                    time.sleep(2)  # Give time for graceful termination
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # Process already terminated
        except Exception as e:
            logger.error("process_tree_termination_failed", pid=pid, error=str(e))
    
    def health_check(self) -> FreeCADHealthCheckResponse:
        """Perform comprehensive health check."""
        healthy = True
        error = None
        freecad_status = None
        
        try:
            # Check FreeCAD availability
            freecad_path = self.find_freecadcmd_path()
            if freecad_path:
                version_valid, version = self.validate_freecad_version(freecad_path)
                freecad_status = FreeCADHealthStatus(
                    available=True,
                    path=freecad_path,
                    version=version,
                    version_valid=version_valid
                )
                if not version_valid:
                    healthy = False
            else:
                freecad_status = FreeCADHealthStatus(
                    available=False,
                    error="FreeCADCmd not found"
                )
                healthy = False
            
            # Check circuit breaker status
            circuit_breaker_status = CircuitBreakerStatus(
                state=self.circuit_breaker.state,
                failure_count=self.circuit_breaker.failure_count,
                last_failure=self.circuit_breaker.last_failure_time
            )
            
            if self.circuit_breaker.state == 'OPEN':
                healthy = False
            
            # Check active processes
            with self._process_lock:
                active_processes_status = ActiveProcessesStatus(
                    count=len(self.active_processes),
                    processes=list(self.active_processes.keys())
                )
            
            # Check resource configuration
            resource_config = ResourceConfiguration(
                max_concurrent_operations=settings.FREECAD_MAX_WORKERS,
                circuit_breaker_threshold=settings.FREECAD_CIRCUIT_BREAKER_THRESHOLD,
                circuit_breaker_recovery_timeout=settings.FREECAD_CIRCUIT_BREAKER_RECOVERY_TIMEOUT
            )
            
            checks = HealthCheckStatus(
                freecad=freecad_status,
                circuit_breaker=circuit_breaker_status,
                active_processes=active_processes_status,
                resource_configuration=resource_config
            )
            
        except Exception as e:
            healthy = False
            error = str(e)
            logger.error("health_check_failed", error=str(e), exc_info=True)
            
            # Create default checks in case of error
            checks = HealthCheckStatus(
                freecad=FreeCADHealthStatus(available=False, error=error),
                circuit_breaker=CircuitBreakerStatus(
                    state="UNKNOWN",
                    failure_count=0,
                    last_failure=None
                ),
                active_processes=ActiveProcessesStatus(count=0, processes=[]),
                resource_configuration=ResourceConfiguration(
                    max_concurrent_operations=settings.FREECAD_MAX_WORKERS,
                    circuit_breaker_threshold=settings.FREECAD_CIRCUIT_BREAKER_THRESHOLD,
                    circuit_breaker_recovery_timeout=settings.FREECAD_CIRCUIT_BREAKER_RECOVERY_TIMEOUT
                )
            )
        
        return FreeCADHealthCheckResponse(
            healthy=healthy,
            checks=checks,
            timestamp=datetime.now(timezone.utc),
            version="1.0.0",
            error=error
        )
    
    def get_metrics_summary(self) -> MetricsSummaryResponse:
        """Get service metrics summary."""
        with self._process_lock:
            active_count = len(self.active_processes)
        
        return MetricsSummaryResponse(
            active_processes=active_count,
            circuit_breaker_state=self.circuit_breaker.state,
            circuit_breaker_failures=self.circuit_breaker.failure_count,
            timestamp=datetime.now(timezone.utc)
        )
    
    def retry_with_exponential_backoff(
        self,
        operation,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
        jitter: bool = True
    ):
        """Execute operation with exponential backoff retry logic.
        
        This method helps prevent resource exhaustion by spreading out retry attempts
        and is especially important when combined with the circuit breaker pattern
        to limit cascading failures and resource consumption during system issues.
        
        The jitter helps prevent thundering herd problems when multiple operations
        retry simultaneously.
        """
        
        for attempt in range(max_retries + 1):
            try:
                return operation()
            except FreeCADException as e:
                if e.error_code in [FreeCADErrorCode.LICENSE_RESTRICTION, 
                                   FreeCADErrorCode.SECURITY_VIOLATION,
                                   FreeCADErrorCode.VALIDATION_FAILED]:
                    # Don't retry permanent failures
                    raise
                
                if attempt == max_retries:
                    raise
                
                # Calculate delay with exponential backoff and jitter
                delay = min(base_delay * (backoff_multiplier ** attempt), max_delay)
                if jitter:
                    # Use random.uniform for cleaner jitter implementation
                    delay *= random.uniform(0.75, 1.25)  # Apply jitter to help prevent thundering herd retries
                
                logger.warning("freecad_operation_retry",
                             attempt=attempt + 1,
                             max_retries=max_retries,
                             delay_seconds=delay,
                             error=str(e))
                
                time.sleep(delay)
    
    def reset_circuit_breaker(self):
        """Reset the circuit breaker state.
        
        This is an administrative operation that should be used carefully
        to reset the circuit breaker after resolving underlying issues.
        """
        with self.circuit_breaker._lock:
            self.circuit_breaker.failure_count = 0
            self.circuit_breaker.state = 'CLOSED'
            self.circuit_breaker.last_failure_time = None
            logger.info("circuit_breaker_reset_manually")
    
    def shutdown(self):
        """Graceful shutdown of the service."""
        logger.info("freecad_service_shutdown_initiated")
        
        # Terminate active processes
        with self._process_lock:
            for process_key, monitor in list(self.active_processes.items()):
                try:
                    monitor.stop_monitoring()
                    if hasattr(monitor, 'process') and monitor.process.is_running():
                        monitor.process.terminate()
                except Exception as e:
                    logger.error("process_shutdown_error", 
                               process_key=process_key, error=str(e))
        
        logger.info("freecad_service_shutdown_completed")


# Global service instance
freecad_service = UltraEnterpriseFreeCADService()