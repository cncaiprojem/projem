"""
GPU Performance Monitor for Task 7.25 (Optional)

This module provides GPU monitoring capabilities for:
- NVIDIA GPU monitoring via pynvml
- AMD GPU monitoring (if available)
- OpenCL device monitoring
- CUDA operations tracking
- GPU memory usage and utilization
- Multi-GPU support
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid

from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id

logger = get_logger(__name__)

# Try to import GPU libraries
try:
    import pynvml
    NVIDIA_AVAILABLE = True
    pynvml.nvmlInit()
except (ImportError, Exception) as e:
    NVIDIA_AVAILABLE = False
    logger.debug(f"NVIDIA GPU monitoring not available: {e}")

try:
    import pyopencl as cl
    OPENCL_AVAILABLE = True
except ImportError:
    OPENCL_AVAILABLE = False
    logger.debug("OpenCL not available")

try:
    import pycuda.driver as cuda
    import pycuda.autoinit
    CUDA_AVAILABLE = True
except ImportError:
    CUDA_AVAILABLE = False
    logger.debug("CUDA not available")


class GPUVendor(str, Enum):
    """GPU vendor types."""
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    UNKNOWN = "unknown"


@dataclass
class GPUDevice:
    """GPU device information."""
    device_id: int
    name: str
    vendor: GPUVendor
    memory_total_mb: float
    compute_capability: Optional[Tuple[int, int]] = None  # CUDA compute capability
    driver_version: Optional[str] = None
    temperature_c: Optional[float] = None
    power_draw_w: Optional[float] = None
    max_power_w: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "vendor": self.vendor.value,
            "memory_total_mb": self.memory_total_mb,
            "compute_capability": self.compute_capability,
            "driver_version": self.driver_version,
            "temperature_c": self.temperature_c,
            "power_draw_w": self.power_draw_w,
            "max_power_w": self.max_power_w
        }


@dataclass
class GPUMetrics:
    """GPU performance metrics."""
    timestamp: datetime
    device_id: int
    utilization_percent: float
    memory_used_mb: float
    memory_free_mb: float
    memory_utilization_percent: float
    temperature_c: Optional[float] = None
    power_draw_w: Optional[float] = None
    fan_speed_percent: Optional[float] = None
    processes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "device_id": self.device_id,
            "utilization_percent": self.utilization_percent,
            "memory_used_mb": self.memory_used_mb,
            "memory_free_mb": self.memory_free_mb,
            "memory_utilization_percent": self.memory_utilization_percent,
            "temperature_c": self.temperature_c,
            "power_draw_w": self.power_draw_w,
            "fan_speed_percent": self.fan_speed_percent,
            "processes": self.processes
        }


class GPUMonitor:
    """
    GPU performance monitor for tracking GPU utilization and memory.

    Supports NVIDIA GPUs via pynvml and OpenCL devices.
    """

    def __init__(self, enable_monitoring: bool = True, sample_interval_seconds: float = 1.0):
        """
        Initialize GPU monitor.

        Args:
            enable_monitoring: Enable GPU monitoring
            sample_interval_seconds: Sampling interval for metrics
        """
        self.enable_monitoring = enable_monitoring
        self.sample_interval_seconds = sample_interval_seconds

        # Device information
        self.gpu_devices: List[GPUDevice] = []
        self.opencl_devices: List[Dict[str, Any]] = []

        # Metrics storage
        self.metrics_history: Dict[int, List[GPUMetrics]] = {}  # device_id -> metrics
        self.max_history_size = 1000

        # Monitoring state
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()

        # Initialize devices
        if self.enable_monitoring:
            self._discover_devices()
            self.start_monitoring()

        logger.info("GPUMonitor initialized",
                   nvidia_available=NVIDIA_AVAILABLE,
                   opencl_available=OPENCL_AVAILABLE,
                   cuda_available=CUDA_AVAILABLE,
                   device_count=len(self.gpu_devices))

    def _discover_devices(self):
        """Discover available GPU devices."""
        # Discover NVIDIA GPUs
        if NVIDIA_AVAILABLE:
            try:
                device_count = pynvml.nvmlDeviceGetCount()
                for i in range(device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle).decode('utf-8')
                    memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)

                    # Get additional info
                    try:
                        major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                        compute_cap = (major, minor)
                    except:
                        compute_cap = None

                    try:
                        driver_version = pynvml.nvmlSystemGetDriverVersion().decode('utf-8')
                    except:
                        driver_version = None

                    try:
                        temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    except:
                        temperature = None

                    try:
                        power_draw = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # Convert to watts
                        max_power = pynvml.nvmlDeviceGetPowerManagementLimitConstraints(handle)[1] / 1000.0
                    except:
                        power_draw = None
                        max_power = None

                    device = GPUDevice(
                        device_id=i,
                        name=name,
                        vendor=GPUVendor.NVIDIA,
                        memory_total_mb=memory_info.total / (1024 * 1024),
                        compute_capability=compute_cap,
                        driver_version=driver_version,
                        temperature_c=temperature,
                        power_draw_w=power_draw,
                        max_power_w=max_power
                    )

                    self.gpu_devices.append(device)
                    self.metrics_history[i] = []

                    logger.info(f"Discovered NVIDIA GPU: {name}",
                              device_id=i,
                              memory_mb=device.memory_total_mb)

            except Exception as e:
                logger.error(f"Failed to discover NVIDIA GPUs: {e}")

        # Discover OpenCL devices
        if OPENCL_AVAILABLE:
            try:
                platforms = cl.get_platforms()
                for platform in platforms:
                    devices = platform.get_devices()
                    for device in devices:
                        if device.type == cl.device_type.GPU:
                            device_info = {
                                "name": device.name,
                                "vendor": device.vendor,
                                "type": "GPU",
                                "global_memory_mb": device.global_mem_size / (1024 * 1024),
                                "compute_units": device.max_compute_units,
                                "max_work_group_size": device.max_work_group_size
                            }
                            self.opencl_devices.append(device_info)

                            logger.info(f"Discovered OpenCL GPU: {device.name}",
                                      vendor=device.vendor,
                                      memory_mb=device_info["global_memory_mb"])

            except Exception as e:
                logger.error(f"Failed to discover OpenCL devices: {e}")

    def get_current_metrics(self, device_id: int = 0) -> Optional[GPUMetrics]:
        """
        Get current GPU metrics for a device.

        Args:
            device_id: GPU device ID

        Returns:
            Current GPU metrics or None if unavailable
        """
        if not NVIDIA_AVAILABLE or device_id >= len(self.gpu_devices):
            return None

        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(device_id)

            # Get utilization
            utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)

            # Get memory info
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            memory_used_mb = memory_info.used / (1024 * 1024)
            memory_free_mb = memory_info.free / (1024 * 1024)
            memory_utilization = (memory_info.used / memory_info.total * 100) if memory_info.total > 0 else 0

            # Get temperature
            try:
                temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except:
                temperature = None

            # Get power
            try:
                power_draw = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # Convert to watts
            except:
                power_draw = None

            # Get fan speed
            try:
                fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
            except:
                fan_speed = None

            # Get processes
            processes = []
            try:
                procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                for proc in procs:
                    processes.append({
                        "pid": proc.pid,
                        "memory_mb": proc.usedGpuMemory / (1024 * 1024) if hasattr(proc, 'usedGpuMemory') else 0
                    })
            except:
                pass

            metrics = GPUMetrics(
                timestamp=datetime.now(timezone.utc),
                device_id=device_id,
                utilization_percent=utilization.gpu,
                memory_used_mb=memory_used_mb,
                memory_free_mb=memory_free_mb,
                memory_utilization_percent=memory_utilization,
                temperature_c=temperature,
                power_draw_w=power_draw,
                fan_speed_percent=fan_speed,
                processes=processes
            )

            return metrics

        except Exception as e:
            logger.error(f"Failed to get GPU metrics: {e}")
            return None

    def start_monitoring(self):
        """Start continuous GPU monitoring."""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            logger.warning("GPU monitoring already running")
            return

        if not self.gpu_devices:
            logger.warning("No GPU devices found for monitoring")
            return

        def monitor_loop():
            while not self._stop_monitoring.wait(self.sample_interval_seconds):
                for device_id in range(len(self.gpu_devices)):
                    current_metrics = self.get_current_metrics(device_id)
                    if current_metrics:
                        # Store metrics
                        if device_id not in self.metrics_history:
                            self.metrics_history[device_id] = []

                        self.metrics_history[device_id].append(current_metrics)

                        # Limit history size
                        if len(self.metrics_history[device_id]) > self.max_history_size:
                            self.metrics_history[device_id].pop(0)

                        # Update Prometheus metrics
                        metrics.gpu_utilization_percent.labels(
                            device_id=str(device_id),
                            device_name=self.gpu_devices[device_id].name
                        ).set(current_metrics.utilization_percent)

                        metrics.gpu_memory_used_mb.labels(
                            device_id=str(device_id),
                            device_name=self.gpu_devices[device_id].name
                        ).set(current_metrics.memory_used_mb)

        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitoring_thread.start()

        logger.info("GPU monitoring started",
                   sample_interval=self.sample_interval_seconds)

    def stop_monitoring(self):
        """Stop GPU monitoring."""
        if self._monitoring_thread:
            self._stop_monitoring.set()
            self._monitoring_thread.join(timeout=5.0)
            self._monitoring_thread = None
            logger.info("GPU monitoring stopped")

    def get_gpu_summary(self, device_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get GPU performance summary.

        Args:
            device_id: Specific device or None for all

        Returns:
            GPU performance summary
        """
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "devices": []
        }

        device_ids = [device_id] if device_id is not None else range(len(self.gpu_devices))

        for dev_id in device_ids:
            if dev_id >= len(self.gpu_devices):
                continue

            device = self.gpu_devices[dev_id]
            current_metrics = self.get_current_metrics(dev_id)

            # Calculate statistics from history
            history = self.metrics_history.get(dev_id, [])
            if history:
                recent_history = history[-100:]  # Last 100 samples

                avg_utilization = sum(m.utilization_percent for m in recent_history) / len(recent_history)
                max_utilization = max(m.utilization_percent for m in recent_history)
                avg_memory = sum(m.memory_used_mb for m in recent_history) / len(recent_history)
                max_memory = max(m.memory_used_mb for m in recent_history)
            else:
                avg_utilization = current_metrics.utilization_percent if current_metrics else 0
                max_utilization = avg_utilization
                avg_memory = current_metrics.memory_used_mb if current_metrics else 0
                max_memory = avg_memory

            device_summary = {
                "device": device.to_dict(),
                "current_metrics": current_metrics.to_dict() if current_metrics else None,
                "statistics": {
                    "avg_utilization_percent": avg_utilization,
                    "max_utilization_percent": max_utilization,
                    "avg_memory_mb": avg_memory,
                    "max_memory_mb": max_memory,
                    "sample_count": len(history)
                }
            }

            summary["devices"].append(device_summary)

        return summary

    def check_gpu_health(self) -> List[Dict[str, Any]]:
        """
        Check GPU health and report issues.

        Returns:
            List of health issues
        """
        issues = []

        for device_id, device in enumerate(self.gpu_devices):
            current_metrics = self.get_current_metrics(device_id)

            if not current_metrics:
                issues.append({
                    "device_id": device_id,
                    "device_name": device.name,
                    "issue": "Cannot retrieve metrics",
                    "severity": "warning"
                })
                continue

            # Check temperature
            if current_metrics.temperature_c and current_metrics.temperature_c > 85:
                issues.append({
                    "device_id": device_id,
                    "device_name": device.name,
                    "issue": f"High temperature: {current_metrics.temperature_c}°C",
                    "issue_tr": f"Yüksek sıcaklık: {current_metrics.temperature_c}°C",
                    "severity": "critical" if current_metrics.temperature_c > 90 else "warning"
                })

            # Check memory usage
            if current_metrics.memory_utilization_percent > 90:
                issues.append({
                    "device_id": device_id,
                    "device_name": device.name,
                    "issue": f"High memory usage: {current_metrics.memory_utilization_percent:.1f}%",
                    "issue_tr": f"Yüksek bellek kullanımı: {current_metrics.memory_utilization_percent:.1f}%",
                    "severity": "warning"
                })

            # Check power draw
            if device.max_power_w and current_metrics.power_draw_w:
                power_percent = (current_metrics.power_draw_w / device.max_power_w * 100)
                if power_percent > 95:
                    issues.append({
                        "device_id": device_id,
                        "device_name": device.name,
                        "issue": f"Near power limit: {current_metrics.power_draw_w:.1f}W / {device.max_power_w:.1f}W",
                        "issue_tr": f"Güç sınırına yakın: {current_metrics.power_draw_w:.1f}W / {device.max_power_w:.1f}W",
                        "severity": "warning"
                    })

        return issues

    def estimate_cuda_memory_required(self,
                                     tensor_shape: Tuple[int, ...],
                                     dtype_bytes: int = 4) -> Dict[str, Any]:
        """
        Estimate CUDA memory required for a tensor operation.

        Args:
            tensor_shape: Shape of the tensor
            dtype_bytes: Bytes per element (4 for float32, 8 for float64)

        Returns:
            Memory estimation
        """
        import functools
        import operator

        total_elements = functools.reduce(operator.mul, tensor_shape, 1)
        memory_bytes = total_elements * dtype_bytes
        memory_mb = memory_bytes / (1024 * 1024)

        # Check if any GPU has enough memory
        suitable_devices = []
        for device_id, device in enumerate(self.gpu_devices):
            current_metrics = self.get_current_metrics(device_id)
            if current_metrics and current_metrics.memory_free_mb > memory_mb:
                suitable_devices.append({
                    "device_id": device_id,
                    "device_name": device.name,
                    "free_memory_mb": current_metrics.memory_free_mb
                })

        return {
            "tensor_shape": tensor_shape,
            "dtype_bytes": dtype_bytes,
            "required_memory_mb": memory_mb,
            "suitable_devices": suitable_devices,
            "recommendation": "GPU available" if suitable_devices else "Insufficient GPU memory"
        }

    def get_optimization_recommendations(self) -> List[Dict[str, Any]]:
        """
        Get GPU optimization recommendations.

        Returns:
            List of recommendations
        """
        recommendations = []

        for device_id, device in enumerate(self.gpu_devices):
            history = self.metrics_history.get(device_id, [])

            if not history:
                continue

            recent_history = history[-100:]  # Last 100 samples

            # Check for underutilization
            avg_utilization = sum(m.utilization_percent for m in recent_history) / len(recent_history)
            if avg_utilization < 20:
                recommendations.append({
                    "device_id": device_id,
                    "device_name": device.name,
                    "issue": "GPU underutilization",
                    "issue_tr": "GPU yetersiz kullanım",
                    "recommendation": "Consider batching operations or increasing workload",
                    "recommendation_tr": "İşlemleri toplu hale getirmeyi veya iş yükünü artırmayı düşünün",
                    "metric": f"Average utilization: {avg_utilization:.1f}%"
                })

            # Check for memory fragmentation
            memory_fluctuation = max(m.memory_used_mb for m in recent_history) - min(m.memory_used_mb for m in recent_history)
            if memory_fluctuation > device.memory_total_mb * 0.5:
                recommendations.append({
                    "device_id": device_id,
                    "device_name": device.name,
                    "issue": "High memory fluctuation",
                    "issue_tr": "Yüksek bellek dalgalanması",
                    "recommendation": "Consider using memory pools or preallocating buffers",
                    "recommendation_tr": "Bellek havuzları kullanmayı veya önceden tampon ayırmayı düşünün",
                    "metric": f"Memory fluctuation: {memory_fluctuation:.1f}MB"
                })

        return recommendations

    def shutdown(self):
        """Cleanup and shutdown GPU monitor."""
        self.stop_monitoring()
        if NVIDIA_AVAILABLE:
            try:
                pynvml.nvmlShutdown()
            except:
                pass
        logger.info("GPUMonitor shutdown complete")


# Global GPU monitor instance (disabled by default)
gpu_monitor = GPUMonitor(enable_monitoring=False)