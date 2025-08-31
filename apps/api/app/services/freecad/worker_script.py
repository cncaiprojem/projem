#!/usr/bin/env python3
# ==============================================================================
# FREECAD WORKER HARNESS - Enterprise FreeCAD Workflow Execution Engine
# ==============================================================================
# A comprehensive, production-ready FreeCAD worker harness providing:
#
# Core Capabilities:
# - Health check HTTP server with FreeCAD validation and cgroup awareness
# - Resource monitoring with psutil (CPU, memory, I/O) and limits enforcement
# - Headless TechDraw technical drawing generation with multi-format export
# - Multi-workflow support: prompt-based, parametric, upload normalization, Assembly4
#
# Security & Reliability:
# - Path traversal protection with secure validation
# - AST-based safe script execution (via a4_assembly.py integration)
# - Deterministic exports with SHA256 hashing for reproducible builds
# - Graceful cancellation and comprehensive error handling
# - Resource limits enforcement with CPU time and memory constraints
#
# Manufacturing & CAD Features:
# - GLB export support via trimesh for web visualization
# - Turkish parameter normalization for local market support
# - Material-machine compatibility validation for manufacturing
# - Support for STEP, STL, FCStd, and GLB formats
# - Assembly4 workflow integration for complex assemblies
#
# Operational Features:
# - Structured JSON logging with Turkish terminology support
# - Standalone execution mode with --standalone flag
# - Configurable resource monitoring intervals
# - Docker-optimized with cgroup v1/v2 detection
# ==============================================================================

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import textwrap
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

# Import the DeterministicExporter to avoid code duplication
try:
    from .exporter import DeterministicExporter
except ImportError:
    # Fallback for when running as standalone script
    from exporter import DeterministicExporter

# Enforce deterministic environment (Task 7.6)
os.environ["PYTHONHASHSEED"] = "0"
if "SOURCE_DATE_EPOCH" not in os.environ:
    os.environ["SOURCE_DATE_EPOCH"] = "946684800"  # 2000-01-01 00:00:00 UTC


# ==============================================================================
# GLOBALS AND CONFIGURATION
# ==============================================================================

# Version and metadata
WORKER_VERSION = "2.0.0"  # Merged version
FREECAD_EXPECTED_VERSION = "1.1.0"

# Resource monitoring
RESOURCE_MONITOR_INTERVAL = 2.0  # seconds
RESOURCE_LOG_INTERVAL_SECONDS = 30  # Log resource stats every 30 seconds
RESOURCE_MONITOR_MIN_INTERVAL = 0.001  # Minimum allowed monitoring interval
RESOURCE_MONITOR_MAX_SAMPLES = 1000  # Maximum samples to keep in memory
MAX_INPUT_FILE_SIZE_MB = 10  # Maximum allowed input file size in MB

# Cancellation handling
CANCELLED = threading.Event()
EXIT_CODES = {
    'SUCCESS': 0,
    'ERROR': 1,
    'CANCELLED': 143,
    'TIMEOUT': 124,
    'OOM': 125,
    'VALIDATION_ERROR': 2
}

# TechDraw view directions
TECHDRAW_VIEWS = {
    'Front': [0, 0, 1],
    'Right': [1, 0, 0], 
    'Top': [0, 1, 0],
    'Isometric': [1, 1, 1],
    'Left': [-1, 0, 0],
    'Bottom': [0, -1, 0],
    'Back': [0, 0, -1]
}

# TechDraw layout constants
TECHDRAW_VIEW_GRID = {
    'start_x': 50,           # Starting X position for views
    'start_y_row1': 150,     # Y position for first row
    'start_y_row2': 75,      # Y position for second row
    'spacing_x': 80,         # Horizontal spacing between views
    'views_per_row': 4       # Maximum views per row
}

# Default templates
DEFAULT_TEMPLATES = {
    'A4_Landscape': '/app/templates/A4_Landscape.svg',
    'A3_Landscape': '/app/templates/A3_Landscape.svg'
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('freecad-worker')


# ==============================================================================
# HEALTH CHECK HTTP SERVER
# ==============================================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check endpoints."""
    
    def do_GET(self):
        """Handle GET requests for health checks."""
        try:
            if self.path.startswith('/health/freecad'):
                self._handle_freecad_health()
            elif self.path == '/health':
                self._handle_basic_health() 
            else:
                self._send_response(404, {'error': 'Not found'})
        except Exception as e:
            logger.error(f"Health check error: {e}")
            self._send_response(500, {'error': 'Internal server error'})
    
    def _handle_freecad_health(self):
        """Handle detailed FreeCAD health check."""
        try:
            health_data = get_freecad_health_data()
            status_code = 200 if health_data['status'] == 'ok' else 503
            self._send_response(status_code, health_data)
        except Exception as e:
            logger.error(f"FreeCAD health check failed: {e}")
            self._send_response(503, {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
    
    def _handle_basic_health(self):
        """Handle basic health check."""
        self._send_response(200, {
            'status': 'ok',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': WORKER_VERSION
        })
    
    def _send_response(self, status_code: int, data: Dict[str, Any]):
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response = json.dumps(data, indent=2)
        self.wfile.write(response.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass


def get_freecad_health_data() -> Dict[str, Any]:
    """Get comprehensive FreeCAD health status."""
    health_data = {
        'status': 'ok',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'worker_version': WORKER_VERSION
    }
    
    try:
        # Import FreeCAD and get version
        import FreeCAD
        version_tuple = FreeCAD.Version()
        freecad_version = '.'.join(str(part) for part in version_tuple[:3])
        health_data['freecad_version'] = freecad_version
        
        # Python version
        health_data['python_version'] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        
        # Package versions
        packages = {}
        for package in ['numpy', 'trimesh', 'pygltflib', 'minio', 'psutil']:
            try:
                module = __import__(package)
                version = getattr(module, '__version__', 'unknown')
                packages[package] = version
            except ImportError:
                packages[package] = 'not_installed'
        
        health_data['packages'] = packages
        
        # Test TechDraw availability
        try:
            import TechDraw
            health_data['techdraw'] = True
        except ImportError:
            health_data['techdraw'] = False
            
        # Test headless document operations
        try:
            doc = FreeCAD.newDocument("health_check")
            FreeCAD.closeDocument(doc.Name)
            health_data['headless_ok'] = True
        except Exception as e:
            health_data['headless_ok'] = False
            health_data['headless_error'] = str(e)
        
        # Cgroup limits detection
        cgroups_info = get_cgroup_limits()
        health_data['cgroups'] = cgroups_info
        
        # Resource usage
        process = psutil.Process()
        health_data['resources'] = {
            'cpu_percent': process.cpu_percent(),
            'memory_mb': process.memory_info().rss / (1024 * 1024),
            'num_threads': process.num_threads()
        }
        
    except Exception as e:
        health_data['status'] = 'error'
        health_data['error'] = str(e)
        logger.error(f"Health check error: {e}")
    
    return health_data


def get_cgroup_limits() -> Dict[str, Any]:
    """Get cgroup resource limits."""
    cgroup_info = {}
    
    try:
        # Memory limit
        memory_paths = [
            '/sys/fs/cgroup/memory/memory.limit_in_bytes',
            '/sys/fs/cgroup/memory.max'
        ]
        
        for path in memory_paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    limit = f.read().strip()
                    if limit != 'max' and limit.isdigit():
                        cgroup_info['memory_limit_mb'] = int(limit) // (1024 * 1024)
                break
        
        # CPU quota/period  
        cpu_quota_paths = [
            '/sys/fs/cgroup/cpu/cpu.cfs_quota_us',
            '/sys/fs/cgroup/cpu.max'
        ]
        
        for path in cpu_quota_paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content != 'max':
                        parts = content.split()
                        if parts:
                            try:
                                if parts[0] != 'max':
                                    cgroup_info['cpu_quota'] = int(parts[0])
                                if len(parts) > 1:
                                    cgroup_info['cpu_period'] = int(parts[1])
                            except (ValueError, IndexError) as e:
                                logger.warning(f"Could not parse cgroup cpu.max content: '{content}'. Error: {e}")
                break
                
        # Only check for v1 period if not already found in v2 or if v2 period is invalid
        if cgroup_info.get('cpu_period') is None or cgroup_info.get('cpu_period', 0) <= 0:
            cpu_period_paths = [
                '/sys/fs/cgroup/cpu/cpu.cfs_period_us',
            ]
            
            for path in cpu_period_paths:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        period = f.read().strip()
                        if period.isdigit() and int(period) > 0:
                            cgroup_info['cpu_period'] = int(period)
                    break
                
    except Exception as e:
        logger.debug(f"Could not read cgroup limits: {e}")
        cgroup_info['error'] = str(e)
    
    return cgroup_info


def start_health_server(port: int = 8080):
    """Start health check HTTP server in background thread."""
    def run_server():
        try:
            server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
            logger.info(f"Health server started on port {port}")
            server.serve_forever()
        except Exception as e:
            logger.error(f"Health server error: {e}")
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    return thread


# ==============================================================================
# RESOURCE MONITORING
# ==============================================================================

class ResourceMonitor:
    """Monitor process resource usage with limits enforcement."""
    
    def __init__(self, interval: float = 2.0, max_time_seconds: int = 0, max_memory_mb: int = 0):
        self.interval = interval
        self.max_time_seconds = max_time_seconds
        self.max_memory_mb = max_memory_mb
        self.process = psutil.Process()
        self.samples = []
        self.peak_rss_mb = 0
        self.avg_cpu_percent = 0
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.last_log_time = time.time()
        self.start_time = time.time()
        self._shutdown_requested = False
        
        # Cache cgroup limits at initialization
        cgroup_limits = get_cgroup_limits()
        self.memory_limit_mb = cgroup_limits.get('memory_limit_mb')
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self._shutdown_requested = True
        self.emit_progress("Shutdown requested, cleaning up...")
    
    def start(self):
        """Start resource monitoring in background thread."""
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info(f"Resource monitoring started (interval: {self.interval}s)")
    
    def stop(self):
        """Stop resource monitoring."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        logger.info("Resource monitoring stopped")
    
    def emit_progress(self, message: str):
        """Emit progress breadcrumb to stderr."""
        elapsed = time.time() - self.start_time
        print(f"[{elapsed:.2f}s] {message}", file=sys.stderr)
    
    def check_limits(self) -> Tuple[bool, Optional[str]]:
        """Check if resource limits are exceeded."""
        # Check shutdown request
        if self._shutdown_requested or CANCELLED.is_set():
            return False, "Shutdown requested"
        
        # Check time limit
        if self.max_time_seconds > 0:
            elapsed = time.time() - self.start_time
            if elapsed > self.max_time_seconds:
                return False, f"Time limit exceeded: {elapsed:.2f}s > {self.max_time_seconds}s"
        
        # Check memory limit
        if self.max_memory_mb > 0:
            try:
                mem_info = self.process.memory_info()
                memory_mb = mem_info.rss / (1024 * 1024)
                self.peak_rss_mb = max(self.peak_rss_mb, memory_mb)
                
                if memory_mb > self.max_memory_mb:
                    return False, f"Memory limit exceeded: {memory_mb:.2f}MB > {self.max_memory_mb}MB"
            except Exception:
                pass  # Ignore memory check errors
        
        return True, None
    
    def get_current_stats(self) -> Dict[str, Any]:
        """Get current resource statistics."""
        try:
            with self.lock:
                memory_info = self.process.memory_info()
                cpu_percent = self.process.cpu_percent()
                io_counters = self.process.io_counters() if hasattr(self.process, 'io_counters') else None
                
                stats = {
                    'cpu_percent': cpu_percent,
                    'rss_mb': memory_info.rss / (1024 * 1024),
                    'vms_mb': memory_info.vms / (1024 * 1024), 
                    'num_threads': self.process.num_threads(),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
                if io_counters:
                    stats['io_read_mb'] = io_counters.read_bytes / (1024 * 1024)
                    stats['io_write_mb'] = io_counters.write_bytes / (1024 * 1024)
                
                return stats
                
        except psutil.NoSuchProcess:
            return {'error': 'Process not found'}
        except Exception as e:
            return {'error': str(e)}
    
    def get_final_metrics(self) -> Dict[str, Any]:
        """Get final aggregated metrics."""
        with self.lock:
            if not self.samples:
                return {'error': 'No samples collected'}
                
            cpu_samples = [s['cpu_percent'] for s in self.samples if s.get('cpu_percent') is not None]
            rss_samples = [s['rss_mb'] for s in self.samples if s.get('rss_mb') is not None]
            
            metrics = {
                'peak_rss_mb': self.peak_rss_mb,
                'avg_cpu_percent': sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0,
                'max_cpu_percent': max(cpu_samples) if cpu_samples else 0,
                'samples_count': len(self.samples),
                'monitoring_duration_seconds': len(self.samples) * self.interval
            }
            
            return metrics
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get resource usage metrics (Task 7.6 compatibility)."""
        elapsed = time.time() - self.start_time
        metrics = {
            "wall_time_seconds": elapsed,
            "peak_memory_mb": self.peak_rss_mb,
        }
        
        try:
            cpu_times = self.process.cpu_times()
            metrics["cpu_user_seconds"] = cpu_times.user
            metrics["cpu_system_seconds"] = cpu_times.system
            metrics["cpu_percent"] = self.process.cpu_percent()
        except Exception:
            pass
        
        return metrics
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                stats = self.get_current_stats()
                if 'error' not in stats:
                    with self.lock:
                        self.samples.append(stats)
                        # Update peak memory
                        if stats.get('rss_mb', 0) > self.peak_rss_mb:
                            self.peak_rss_mb = stats['rss_mb']
                        
                        # Limit sample history
                        if len(self.samples) > RESOURCE_MONITOR_MAX_SAMPLES:
                            self.samples = self.samples[-RESOURCE_MONITOR_MAX_SAMPLES:]
                            
                        # Log periodic updates
                        current_time = time.time()
                        if current_time - self.last_log_time >= RESOURCE_LOG_INTERVAL_SECONDS:
                            logger.info(f"Resource stats: CPU {stats['cpu_percent']:.1f}%, RSS {stats['rss_mb']:.1f}MB, Threads {stats['num_threads']}")
                            self.last_log_time = current_time
                            
                    # Check memory pressure
                    self._check_memory_pressure(stats['rss_mb'])
                    
                time.sleep(self.interval)
                
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
                time.sleep(self.interval)
    
    def _check_memory_pressure(self, current_rss_mb: float):
        """Check for memory pressure and emit warnings."""
        if self.memory_limit_mb:
            pressure_ratio = current_rss_mb / self.memory_limit_mb
            
            if pressure_ratio > 0.85:
                logger.warning(f"High memory pressure: {current_rss_mb:.1f}MB / {self.memory_limit_mb}MB ({pressure_ratio:.1%})")
                
                if pressure_ratio > 0.95:
                    logger.error(f"Critical memory pressure: {current_rss_mb:.1f}MB / {self.memory_limit_mb}MB")


# ==============================================================================
# TECHDRAW INTEGRATION
# ==============================================================================

class TechDrawGenerator:
    """Headless TechDraw technical drawing generation."""
    
    def __init__(self, template_path: str, views: List[str], scale: float = 1.0, dpi: int = 300):
        self.template_path = template_path
        self.views = views
        self.scale = scale
        self.dpi = dpi
        
    def generate_drawing(self, freecad_doc, target_objects: List, output_dir: str, formats: List[str] = None) -> Dict[str, Any]:
        """Generate technical drawing from FreeCAD objects."""
        if formats is None:
            formats = ['pdf', 'svg']
            
        logger.info(f"Generating TechDraw: template={self.template_path}, views={self.views}, scale={self.scale}")
        
        try:
            import TechDraw
            
            # Verify template exists
            template_to_use = self.template_path
            if template_to_use and not os.path.exists(template_to_use):
                logger.warning(f"Template not found: {template_to_use}. Proceeding without a template.")
                template_to_use = None
            
            # Create TechDraw page
            page = freecad_doc.addObject("TechDraw::DrawPage", "DrawingPage")
            
            # Add template
            if template_to_use:
                template = freecad_doc.addObject("TechDraw::DrawSVGTemplate", "Template")
                template.Template = template_to_use
                page.Template = template
            
            # Add views for each requested direction
            created_views = []
            for i, view_name in enumerate(self.views):
                if view_name not in TECHDRAW_VIEWS:
                    logger.warning(f"Unknown view direction: {view_name}")
                    continue
                    
                direction = TECHDRAW_VIEWS[view_name]
                
                try:
                    view_obj = freecad_doc.addObject("TechDraw::DrawViewPart", f"View_{view_name}")
                    view_obj.Source = target_objects
                    view_obj.Direction = direction
                    view_obj.Scale = self.scale
                    
                    # Position views in a grid
                    if i < TECHDRAW_VIEW_GRID['views_per_row']:  # First row
                        view_obj.X = TECHDRAW_VIEW_GRID['start_x'] + (i * TECHDRAW_VIEW_GRID['spacing_x'])
                        view_obj.Y = TECHDRAW_VIEW_GRID['start_y_row1']
                    else:  # Second row
                        view_obj.X = TECHDRAW_VIEW_GRID['start_x'] + ((i - TECHDRAW_VIEW_GRID['views_per_row']) * TECHDRAW_VIEW_GRID['spacing_x'])
                        view_obj.Y = TECHDRAW_VIEW_GRID['start_y_row2']
                    
                    page.addView(view_obj)
                    created_views.append(view_obj)
                    
                    logger.debug(f"Created view: {view_name} at direction {direction}")
                    
                except Exception as e:
                    logger.error(f"Failed to create view {view_name}: {e}")
            
            # Recompute document to update views
            freecad_doc.recompute()
            
            # Export in requested formats
            exported_files = []
            
            if 'pdf' in formats:
                pdf_path = os.path.join(output_dir, 'drawing.pdf')
                try:
                    TechDraw.writePageAsPdf(page, pdf_path)
                    if os.path.exists(pdf_path):
                        exported_files.append({
                            'format': 'pdf',
                            'path': pdf_path,
                            'size_bytes': os.path.getsize(pdf_path)
                        })
                        logger.info(f"PDF drawing exported: {pdf_path}")
                except Exception as e:
                    logger.error(f"PDF export failed: {e}")
            
            if 'svg' in formats:
                svg_path = os.path.join(output_dir, 'drawing.svg')
                try:
                    TechDraw.writePageAsSvg(page, svg_path)
                    if os.path.exists(svg_path):
                        exported_files.append({
                            'format': 'svg',
                            'path': svg_path,
                            'size_bytes': os.path.getsize(svg_path)
                        })
                        logger.info(f"SVG drawing exported: {svg_path}")
                except Exception as e:
                    logger.error(f"SVG export failed: {e}")
            
            return {
                'success': True,
                'views_created': len(created_views),
                'exported_files': exported_files,
                'template_used': self.template_path,
                'scale': self.scale
            }
            
        except ImportError:
            logger.error("TechDraw module not available")
            return {
                'success': False,
                'error': 'TechDraw module not available',
                'exported_files': []
            }
        except Exception as e:
            logger.error(f"TechDraw generation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'exported_files': []
            }


# ==============================================================================
# FREECAD PARAMETRIC GENERATOR (Task 7.6)
# ==============================================================================

class FreeCADParametricGenerator:
    """Generates parametric models in FreeCAD with deterministic output."""
    
    def __init__(self, monitor: ResourceMonitor):
        self.monitor = monitor
        self.doc = None
        
        # Import FreeCAD modules
        import FreeCAD as App
        import Part
        import Mesh
        from FreeCAD import Base
        
        self.App = App
        self.Part = Part
        self.Mesh = Mesh
        self.Base = Base
        
        # Verify FreeCAD version
        self._verify_version()
        
        # Set deterministic parameters
        self._configure_determinism()
    
    def _verify_version(self):
        """Verify FreeCAD version is 1.1.0."""
        version = self.App.Version()
        version_str = f"{version[0]}.{version[1]}.{version[2]}"
        
        # Allow 1.1.0 or newer for compatibility
        if not (version[0] == 1 and version[1] >= 1):
            raise RuntimeError(f"FreeCAD version mismatch: {version_str} != 1.1.0+")
        
        self.monitor.emit_progress(f"FreeCAD version verified: {version_str}")
    
    def _configure_determinism(self):
        """Configure FreeCAD for deterministic output."""
        # Disable parallel operations
        if hasattr(self.App, "ParamGet"):
            param = self.App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/Boolean")
            param.SetBool("UseParallelBooleans", False)
            
            # Disable multi-threading for meshing
            mesh_param = self.App.ParamGet("User parameter:BaseApp/Preferences/Mod/Mesh")
            mesh_param.SetBool("UseParallelMeshing", False)
        
        self.monitor.emit_progress("Determinism configured")
    
    def create_prism_with_hole(
        self, 
        length: float, 
        width: float, 
        height: float, 
        hole_diameter: float,
        units: str = "mm"
    ) -> 'Part.Shape':
        """
        Create a parametric prism with a cylindrical hole.
        
        Args:
            length: Prism length (X dimension)
            width: Prism width (Y dimension)
            height: Prism height (Z dimension)
            hole_diameter: Diameter of the cylindrical hole
            units: Unit system (currently only "mm" supported)
        
        Returns:
            Part.Shape: The resulting shape
        """
        # Validate dimensions (0.1 to 1000 mm)
        for name, value in [("length", length), ("width", width), 
                            ("height", height), ("hole_diameter", hole_diameter)]:
            if not (0.1 <= value <= 1000):
                raise ValueError(f"{name} out of range: {value} mm (must be 0.1-1000 mm)")
        
        # Validate hole can fit
        min_dimension = min(length, width)
        if hole_diameter >= min_dimension:
            raise ValueError(f"Hole diameter {hole_diameter} mm too large for prism {length}x{width} mm")
        
        self.monitor.emit_progress(f"Creating prism {length}x{width}x{height} mm with {hole_diameter} mm hole")
        
        # Create the box (prism)
        box = self.Part.makeBox(length, width, height)
        
        # Create the cylinder (hole)
        cylinder = self.Part.makeCylinder(
            hole_diameter / 2,  # radius
            height + 1,  # slightly taller for clean boolean
            self.Base.Vector(length / 2, width / 2, -0.5),  # centered, slightly below
            self.Base.Vector(0, 0, 1)  # Z-axis direction
        )
        
        # Boolean cut operation
        result = box.cut(cylinder)
        
        # Check resource limits
        ok, error = self.monitor.check_limits()
        if not ok:
            raise RuntimeError(f"Resource limit exceeded: {error}")
        
        return result
    
    def create_box(self, length: float, width: float, height: float) -> 'Part.Shape':
        """
        Create a parametric box shape.
        
        Args:
            length: Box length (X dimension)
            width: Box width (Y dimension)
            height: Box height (Z dimension)
        
        Returns:
            Part.Shape: The resulting box shape
        """
        # Validate dimensions (0.1 to 1000 mm)
        for name, value in [("length", length), ("width", width), ("height", height)]:
            if not (0.1 <= value <= 1000):
                raise ValueError(f"{name} out of range: {value} mm (must be 0.1-1000 mm)")
        
        self.monitor.emit_progress(f"Creating box {length}x{width}x{height} mm")
        
        # Create the box
        box = self.Part.makeBox(length, width, height)
        
        # Check resource limits
        ok, error = self.monitor.check_limits()
        if not ok:
            raise RuntimeError(f"Resource limit exceeded: {error}")
        
        return box
    
    def create_cylinder(self, radius: float, height: float) -> 'Part.Shape':
        """
        Create a parametric cylinder shape.
        
        Args:
            radius: Cylinder radius
            height: Cylinder height
        
        Returns:
            Part.Shape: The resulting cylinder shape
        """
        # Validate dimensions (0.1 to 1000 mm)
        for name, value in [("radius", radius), ("height", height)]:
            if not (0.1 <= value <= 1000):
                raise ValueError(f"{name} out of range: {value} mm (must be 0.1-1000 mm)")
        
        self.monitor.emit_progress(f"Creating cylinder r={radius} h={height} mm")
        
        # Create the cylinder
        cylinder = self.Part.makeCylinder(
            radius,
            height,
            self.Base.Vector(0, 0, 0),
            self.Base.Vector(0, 0, 1)
        )
        
        # Check resource limits
        ok, error = self.monitor.check_limits()
        if not ok:
            raise RuntimeError(f"Resource limit exceeded: {error}")
        
        return cylinder
    
    def create_sphere(self, radius: float) -> 'Part.Shape':
        """
        Create a parametric sphere shape.
        
        Args:
            radius: Sphere radius
        
        Returns:
            Part.Shape: The resulting sphere shape
        """
        # Validate dimensions (0.1 to 1000 mm)
        if not (0.1 <= radius <= 1000):
            raise ValueError(f"radius out of range: {radius} mm (must be 0.1-1000 mm)")
        
        self.monitor.emit_progress(f"Creating sphere r={radius} mm")
        
        # Create the sphere
        sphere = self.Part.makeSphere(radius)
        
        # Check resource limits
        ok, error = self.monitor.check_limits()
        if not ok:
            raise RuntimeError(f"Resource limit exceeded: {error}")
        
        return sphere
    
    def create_document(self, name: str = "parametric") -> 'App.Document':
        """Create a new FreeCAD document."""
        self.doc = self.App.newDocument(name)
        self.monitor.emit_progress(f"Document created: {name}")
        return self.doc
    
    def add_shape_to_document(self, shape: 'Part.Shape', label: str = "ParametricPart") -> 'Part.Feature':
        """Add a shape to the document and return the created object.
        
        This method creates a Part::Feature object in the document and returns it,
        enabling loose coupling by allowing direct access to the created object
        without requiring name-based lookups.
        
        Args:
            shape: The Part.Shape to add to the document
            label: Label for the created object (default: "ParametricPart")
            
        Returns:
            Part.Feature: The created document object containing the shape
            
        Raises:
            RuntimeError: If no document has been created
        """
        if not self.doc:
            raise RuntimeError("No document created")
        
        # Add shape to document as a Part::Feature object
        part = self.doc.addObject("Part::Feature", label)
        part.Shape = shape
        # Label is already set by addObject, no need to set it again
        
        # Recompute deterministically
        self.doc.recompute()
        
        self.monitor.emit_progress(f"Shape added to document: {label}")
        
        # Return the created part object for direct use
        return part
    
    def get_document(self):
        """
        Get the FreeCAD document.
        
        Returns:
            The FreeCAD document instance for this generator.
            
        Note:
            This method provides controlled access to the internal document,
            following encapsulation best practices.
        """
        return self.doc
    
    def export_shape(
        self, 
        shape: 'Part.Shape',
        base_path: Path,
        formats: List[str],
        tessellation_tolerance: float = 0.1
    ) -> Dict[str, Dict[str, Any]]:
        """
        Export shape to multiple formats using DeterministicExporter.
        
        This method now delegates to DeterministicExporter to avoid code duplication
        and ensure consistent deterministic exports across the codebase.
        
        Args:
            shape: The shape to export (unused, document is used instead)
            base_path: Base path for output files (without extension)
            formats: List of formats to export ["FCStd", "STEP", "STL", "GLB"]
            tessellation_tolerance: Tolerance for mesh generation (currently unused)
        
        Returns:
            Dict mapping format to export info (path, sha256, size)
        """
        if not self.doc:
            raise RuntimeError("No document available for export")
        
        # Use DeterministicExporter for all exports to avoid duplication
        exporter = DeterministicExporter(source_date_epoch=int(os.environ.get("SOURCE_DATE_EPOCH", "946684800")))
        
        try:
            # Export using the centralized exporter
            results = exporter.export_all(self.doc, base_path, formats)
            
            # Log progress for each successful export
            for fmt, result in results.items():
                if "error" not in result:
                    self.monitor.emit_progress(
                        f"Exported {fmt}: {Path(result['path']).name} (SHA256: {result['sha256'][:8]}...)"
                    )
                else:
                    self.monitor.emit_progress(f"Failed to export {fmt}: {result['error']}")
            
            return results
            
        except Exception as e:
            self.monitor.emit_progress(f"Export failed: {e}")
            raise
    
    # The following export methods have been removed to use DeterministicExporter instead
    # This eliminates code duplication and ensures consistent deterministic exports
    # All export functionality is now handled by the export_shape method above
    # which delegates to DeterministicExporter.export_all()
    
    def extract_metrics(self, shape: 'Part.Shape') -> Dict[str, Any]:
        """Extract geometric metrics from shape."""
        metrics = {
            "solids": len(shape.Solids),
            "faces": len(shape.Faces),
            "edges": len(shape.Edges),
            "vertices": len(shape.Vertexes),
        }
        
        # Volume and area (if solid)
        if shape.Solids:
            metrics["volume_mm3"] = round(shape.Volume, 6)
            metrics["area_mm2"] = round(shape.Area, 6)
        
        # Bounding box
        bbox = shape.BoundBox
        metrics["bbox"] = {
            "x": round(bbox.XLength, 6),
            "y": round(bbox.YLength, 6),
            "z": round(bbox.ZLength, 6)
        }
        
        # Center of mass (if solid)
        if shape.Solids:
            com = shape.CenterOfMass
            metrics["center_of_mass"] = {
                "x": round(com.x, 6),
                "y": round(com.y, 6),
                "z": round(com.z, 6)
            }
        
        return metrics


# ==============================================================================
# VALIDATION AND NORMALIZATION (Task 7.6)
# ==============================================================================

def validate_material_machine_compatibility(material: str, process: str) -> Tuple[bool, Optional[str]]:
    """
    Validate material-machine compatibility.
    
    Returns:
        (is_valid, error_message)
    """
    # Material-process compatibility matrix
    compatibility = {
        "injection_molding": ["abs", "pla", "petg", "nylon", "pp", "pe"],
        "milling": ["aluminum", "steel", "brass", "copper", "abs", "nylon"],
        "cnc": ["aluminum", "steel", "brass", "copper", "wood", "abs"],
        "3d_printing": ["pla", "abs", "petg", "nylon", "tpu"],
        "laser_cutting": ["steel", "aluminum", "acrylic", "wood", "mdf"]
    }
    
    process_lower = process.lower()
    material_lower = material.lower()
    
    if process_lower not in compatibility:
        return False, f"Unknown process: {process}"
    
    if material_lower not in compatibility[process_lower]:
        allowed = ", ".join(compatibility[process_lower])
        return False, f"Material '{material}' incompatible with {process}. Allowed: {allowed}"
    
    return True, None


def normalize_turkish_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Turkish parameter names to canonical English."""
    turkish_map = {
        "uzunluk": "length",
        "genişlik": "width", 
        "yükseklik": "height",
        "delik_çapı": "hole_diameter",
        "delik çapı": "hole_diameter",
        "malzeme": "material",
        "makine": "machine",
        "süreç": "process",
        "işlem": "process",
        "birim": "units",
        "birimler": "units"
    }
    
    normalized = {}
    for key, value in params.items():
        # Normalize key
        key_lower = key.lower().strip()
        canonical_key = turkish_map.get(key_lower, key)
        normalized[canonical_key] = value
    
    return normalized


# ==============================================================================
# FREECAD WORKFLOW EXECUTION
# ==============================================================================

class FreeCADWorker:
    """Main FreeCAD worker execution engine."""
    
    def __init__(self, args):
        self.args = args
        self.resource_monitor = ResourceMonitor(
            interval=args.metrics_interval,
            max_time_seconds=args.cpu_seconds if args.cpu_seconds > 0 else 20,
            max_memory_mb=args.mem_mb if args.mem_mb > 0 else 2048
        )
        self.start_time = time.time()
        self.cancelled = False
        
        # Setup signal handlers for graceful cancellation
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # CPU time limits
        if self.args.cpu_seconds > 0:
            try:
                import resource
                # Only set limits if SIGXCPU signal is available
                if hasattr(signal, 'SIGXCPU'):
                    resource.setrlimit(resource.RLIMIT_CPU, (self.args.cpu_seconds, self.args.cpu_seconds))
                    signal.signal(signal.SIGXCPU, self._cpu_limit_handler)
            except ImportError:
                logger.warning("Resource module not available, CPU limits cannot be enforced")
    
    @staticmethod
    def _validate_path_security(path: str, allowed_dir: str, path_type: str = "path") -> str:
        """Validate a path is within allowed directory to prevent path traversal."""
        # Resolve the allowed directory first
        real_allowed = os.path.realpath(allowed_dir)
        
        # Check if path is absolute - if so, don't join with allowed_dir
        if os.path.isabs(path):
            real_path = os.path.realpath(path)
        else:
            real_path = os.path.realpath(os.path.join(real_allowed, path))
        
        # Use os.path.commonpath for more robust security check
        if os.path.commonpath([real_path, real_allowed]) != real_allowed:
            raise ValueError(f"Invalid {path_type} (potential path traversal): {path}")
            
        return real_path
        
    def _signal_handler(self, signum, frame):
        """Handle termination signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown")
        self.cancelled = True
        CANCELLED.set()
        
    def _cpu_limit_handler(self, signum, frame):
        """Handle CPU time limit exceeded."""
        logger.error("CPU time limit exceeded")
        sys.exit(EXIT_CODES['TIMEOUT'])
        
    def execute(self) -> int:
        """Main execution entry point."""
        try:
            # Start health server if requested
            if self.args.health_server:
                start_health_server(int(os.getenv('HEALTH_PORT', '8080')))
            
            # Start resource monitoring
            self.resource_monitor.start()
            
            # Log execution start
            logger.info(f"FreeCAD Worker starting: flow={self.args.flow}, request_id={self.args.request_id}")
            logger.info(f"Resource limits: CPU={self.args.cpu_seconds}s, Memory={self.args.mem_mb}MB")
            
            # Execute the requested flow
            result = self._execute_flow()
            
            # Log final metrics
            final_metrics = self.resource_monitor.get_final_metrics()
            execution_time = time.time() - self.start_time
            
            logger.info(f"Execution completed: {result['success']}")
            logger.info(f"Final metrics: {final_metrics}")
            logger.info(f"Total execution time: {execution_time:.2f}s")
            
            # Write final results
            self._write_results(result, final_metrics, execution_time)
            
            return EXIT_CODES['SUCCESS'] if result['success'] else EXIT_CODES['ERROR']
            
        except KeyboardInterrupt:
            logger.info("Execution cancelled by user")
            return EXIT_CODES['CANCELLED']
        except Exception as e:
            logger.error(f"Execution failed: {e}", exc_info=True)
            return EXIT_CODES['ERROR']
        finally:
            self.resource_monitor.stop()
    
    def _execute_flow(self) -> Dict[str, Any]:
        """Execute the requested FreeCAD workflow."""
        try:
            # Check for cancellation before starting
            if self.cancelled or CANCELLED.is_set():
                logger.info("Execution cancelled before flow start")
                return {'success': False, 'flow': self.args.flow, 'request_id': self.args.request_id, 'errors': ['Cancelled before execution']}
            
            # Load input configuration
            with open(self.args.input, 'r', encoding='utf-8') as f:
                input_data = json.load(f)
                
            # Initialize result structure
            result = {
                'success': False,
                'flow': self.args.flow,
                'request_id': self.args.request_id,
                'artefacts': [],
                'warnings': [],
                'errors': []
            }
            
            # Check for cancellation before importing FreeCAD
            if self.cancelled or CANCELLED.is_set():
                result['errors'].append('Cancelled before FreeCAD import')
                return result
            
            # Import FreeCAD
            import FreeCAD
            
            # Execute flow based on type
            if self.args.flow == 'prompt':
                result = self._execute_prompt_flow(input_data, result)
            elif self.args.flow == 'params':
                result = self._execute_params_flow(input_data, result)
            elif self.args.flow == 'upload':
                result = self._execute_upload_flow(input_data, result)
            elif self.args.flow == 'a4':
                result = self._execute_a4_flow(input_data, result)
            else:
                raise ValueError(f"Unknown flow type: {self.args.flow}")
                
            return result
            
        except Exception as e:
            return {
                'success': False,
                'flow': self.args.flow,
                'request_id': self.args.request_id,
                'error': str(e),
                'artefacts': [],
                'warnings': [],
                'errors': [str(e)]
            }
    
    def _execute_prompt_flow(self, input_data: Dict, result: Dict) -> Dict:
        """Execute AI-driven prompt flow."""
        logger.info("Executing prompt-based model generation")
        
        # Check for cancellation
        if self.cancelled or CANCELLED.is_set():
            result['errors'].append('Cancelled during prompt flow')
            return result
        
        try:
            import FreeCAD
            
            prompt = input_data.get('prompt', '')
            if not prompt:
                raise ValueError("Prompt is required for prompt flow")
            
            # Create new document
            doc_name = f"prompt_model_{self.args.request_id[:8]}"
            doc = FreeCAD.newDocument(doc_name)
            
            # This is a placeholder - in real implementation, this would:
            # 1. Call AI service to generate FreeCAD Python script
            # 2. Validate and execute the script
            # 3. Generate the 3D model based on prompt
            
            # For now, create a simple box as example
            box = doc.addObject("Part::Box", "PromptBox")
            box.Length = input_data.get('length', 100.0)
            box.Width = input_data.get('width', 100.0)
            box.Height = input_data.get('height', 100.0)
            
            doc.recompute()
            
            # Export model
            artefacts = self._export_model(doc, "prompt_model")
            result['artefacts'].extend(artefacts)
            
            # Generate TechDraw if requested
            if self.args.techdraw == 'on':
                techdraw_result = self._generate_techdraw(doc, [box])
                result['techdraw'] = techdraw_result
                result['artefacts'].extend(techdraw_result.get('exported_files', []))
            
            FreeCAD.closeDocument(doc.Name)
            result['success'] = True
            result['model_created'] = True
            
            logger.info("Prompt flow completed successfully")
            
        except Exception as e:
            logger.error(f"Prompt flow failed: {e}")
            result['errors'].append(str(e))
            
        return result
    
    def _execute_params_flow(self, input_data: Dict, result: Dict) -> Dict:
        """Execute parametric modeling flow with Task 7.6 enhancements."""
        logger.info("Executing parametric model generation")
        
        # Check for cancellation
        if self.cancelled or CANCELLED.is_set():
            result['errors'].append('Cancelled during parametric flow')
            return result
        
        try:
            # Normalize Turkish parameters
            input_data = normalize_turkish_params(input_data)
            
            # Extract parameters
            model_type = input_data.get('model_type', 'prism_with_hole')
            dimensions = input_data.get('dimensions', {})
            
            # Task 7.6 specific parameters
            length = float(dimensions.get("length", input_data.get("length", 100)))
            width = float(dimensions.get("width", input_data.get("width", 50)))
            height = float(dimensions.get("height", input_data.get("height", 30)))
            hole_diameter = float(dimensions.get("hole_diameter", input_data.get("hole_diameter", 10)))
            units = input_data.get("units", "mm")
            material = input_data.get("material", "aluminum")
            process = input_data.get("process", "milling")
            tessellation = float(input_data.get("tessellation_tolerance", 0.1))
            output_formats = input_data.get("formats", ["FCStd", "STEP", "STL"])
            
            # Validate material-machine compatibility
            valid, error = validate_material_machine_compatibility(material, process)
            if not valid:
                raise ValueError(error)
            
            self.resource_monitor.emit_progress(f"Validated: {material} + {process}")
            
            # Create parametric generator
            generator = FreeCADParametricGenerator(self.resource_monitor)
            
            # Create document
            doc = generator.create_document("parametric_model")
            
            # Generate geometry based on model type
            if model_type == 'prism_with_hole':
                shape = generator.create_prism_with_hole(
                    length, width, height, hole_diameter, units
                )
                # Capture the returned document object for loose coupling
                doc_object = generator.add_shape_to_document(shape, "PrismWithHole")
            else:
                # Legacy simple shapes use dedicated methods to avoid code duplication.
                # This ensures all geometric flows use the same validation and export pipeline
                # with DeterministicExporter for consistency and maintainability.
                if model_type == 'box':
                    # Use the new create_box method
                    shape = generator.create_box(length, width, height)
                    # Capture the returned document object for loose coupling
                    doc_object = generator.add_shape_to_document(shape, "ParametricBox")
                elif model_type == 'cylinder':
                    # Check both dimensions dict and top-level input_data for consistency
                    radius = float(dimensions.get('radius', input_data.get('radius', 50.0)))
                    # Use the new create_cylinder method
                    shape = generator.create_cylinder(radius, height)
                    # Capture the returned document object for loose coupling
                    doc_object = generator.add_shape_to_document(shape, "ParametricCylinder")
                elif model_type == 'sphere':
                    # Check both dimensions dict and top-level input_data for consistency
                    radius = float(dimensions.get('radius', input_data.get('radius', 50.0)))
                    # Use the new create_sphere method
                    shape = generator.create_sphere(radius)
                    # Capture the returned document object for loose coupling
                    doc_object = generator.add_shape_to_document(shape, "ParametricSphere")
                else:
                    raise ValueError(f"Unsupported model type: {model_type}")
                
                # Use generator's document through proper encapsulation
                doc = generator.get_document()
            
            # Export with deterministic hashing (Task 7.6)
            with tempfile.TemporaryDirectory() as tmpdir:
                base_path = Path(tmpdir) / "parametric_output"
                export_results = generator.export_shape(
                    shape, base_path, output_formats, tessellation
                )
                
                # Copy exported files to output directory
                for fmt, export_info in export_results.items():
                    if "path" in export_info and "error" not in export_info:
                        src_path = Path(export_info["path"])
                        if src_path.exists():
                            dst_path = Path(self.args.outdir) / src_path.name
                            shutil.copy2(src_path, dst_path)
                            
                            result['artefacts'].append({
                                'type': 'parametric_model',
                                'format': fmt,
                                'path': str(dst_path),
                                'size_bytes': dst_path.stat().st_size,
                                'sha256': export_info.get('sha256')
                            })
            
            # Extract metrics
            shape_metrics = generator.extract_metrics(shape)
            
            # Generate TechDraw if requested
            if self.args.techdraw == 'on':
                # Use the document object returned from add_shape_to_document
                # This eliminates tight coupling and removes dependency on object naming
                if doc_object:
                    techdraw_result = self._generate_techdraw(doc, [doc_object])
                    result['techdraw'] = techdraw_result
                    result['artefacts'].extend(techdraw_result.get('exported_files', []))
                else:
                    logger.warning("No document object available for TechDraw generation")
            
            generator.App.closeDocument(doc.Name)
            
            result['success'] = True
            result['model_type'] = model_type
            result['parameters'] = {
                "length": length,
                "width": width,
                "height": height,
                "hole_diameter": hole_diameter if model_type == 'prism_with_hole' else None,
                "units": units,
                "material": material,
                "process": process
            }
            result['exports'] = export_results
            result['metrics'] = {
                "geometry": shape_metrics
            }
            result['validation'] = {
                "material_process_compatible": True
            }
            
            logger.info(f"Parametric flow completed: {model_type}")
            
        except Exception as e:
            logger.error(f"Parametric flow failed: {e}")
            result['errors'].append(str(e))
            
        return result
    
    def _execute_upload_flow(self, input_data: Dict, result: Dict) -> Dict:
        """Execute upload normalization flow."""
        logger.info("Executing upload normalization")
        
        # Check for cancellation
        if self.cancelled or CANCELLED.is_set():
            result['errors'].append('Cancelled during upload flow')
            return result
        
        try:
            import FreeCAD
            
            input_file = input_data.get('input_file')
            if not input_file:
                raise ValueError("Input file not provided in input data")
            
            # Security: Prevent path traversal
            input_file = FreeCADWorker._validate_path_security(input_file, '/work', 'input file')
            
            if not os.path.exists(input_file):
                raise ValueError(f"Input file not found: {input_file}")
            
            # Validate input file size
            file_size_mb = os.path.getsize(input_file) / (1024 * 1024)
            if file_size_mb > MAX_INPUT_FILE_SIZE_MB:
                raise ValueError(f"Input file size ({file_size_mb:.1f}MB) exceeds maximum allowed size ({MAX_INPUT_FILE_SIZE_MB}MB)")
            
            # Detect file type and import
            file_ext = os.path.splitext(input_file)[1].lower()
            
            if file_ext in ['.step', '.stp']:
                import Import
                doc = FreeCAD.newDocument("UploadNormalize")
                Import.insert(input_file, doc.Name)
            elif file_ext in ['.iges', '.igs']:
                import Import  
                doc = FreeCAD.newDocument("UploadNormalize")
                Import.insert(input_file, doc.Name)
            elif file_ext == '.fcstd':
                doc = FreeCAD.openDocument(input_file)
            else:
                raise ValueError(f"Unsupported file format: {file_ext}")
            
            doc.recompute()
            
            # Validate geometry
            objects = doc.Objects
            valid_objects = []
            
            for obj in objects:
                if hasattr(obj, 'Shape') and obj.Shape.isValid():
                    valid_objects.append(obj)
                else:
                    result['warnings'].append(f"Invalid geometry in object: {obj.Name}")
            
            if not valid_objects:
                raise ValueError("No valid geometry found in uploaded file")
            
            # Export normalized model
            artefacts = self._export_model(doc, "normalized_model")
            result['artefacts'].extend(artefacts)
            
            # Generate TechDraw if requested
            if self.args.techdraw == 'on':
                techdraw_result = self._generate_techdraw(doc, valid_objects)
                result['techdraw'] = techdraw_result
                result['artefacts'].extend(techdraw_result.get('exported_files', []))
            
            FreeCAD.closeDocument(doc.Name)
            result['success'] = True
            result['original_format'] = file_ext
            result['objects_processed'] = len(valid_objects)
            
            logger.info(f"Upload normalization completed: {len(valid_objects)} objects")
            
        except Exception as e:
            logger.error(f"Upload flow failed: {e}")
            result['errors'].append(str(e))
            
        return result
    
    def _execute_a4_flow(self, input_data: Dict, result: Dict) -> Dict:
        """Execute Assembly4 workflow."""
        logger.info("Executing Assembly4 workflow")
        
        # Check for cancellation
        if self.cancelled or CANCELLED.is_set():
            result['errors'].append('Cancelled during Assembly4 flow')
            return result
        
        try:
            import FreeCAD
            
            # Create assembly document
            doc = FreeCAD.newDocument("Assembly4_Workflow")
            
            # This is a placeholder for Assembly4 workflow
            # In real implementation, this would:
            # 1. Load part definitions
            # 2. Create Assembly4 container
            # 3. Apply constraints and positioning
            # 4. Validate assembly
            
            # For now, create simple multi-part assembly
            parts = input_data.get('parts', [])
            assembly_objects = []
            
            for i, part_def in enumerate(parts[:5]):  # Limit to 5 parts
                if part_def.get('type') == 'box':
                    obj = doc.addObject("Part::Box", f"Part_{i}")
                    obj.Length = part_def.get('length', 50.0)
                    obj.Width = part_def.get('width', 50.0)  
                    obj.Height = part_def.get('height', 50.0)
                    # Apply position offset
                    obj.Placement.Base = FreeCAD.Vector(i * 60, 0, 0)
                    assembly_objects.append(obj)
            
            doc.recompute()
            
            # Export assembly
            artefacts = self._export_model(doc, "assembly4_model")
            result['artefacts'].extend(artefacts)
            
            # Generate TechDraw if requested
            if self.args.techdraw == 'on':
                techdraw_result = self._generate_techdraw(doc, assembly_objects)
                result['techdraw'] = techdraw_result
                result['artefacts'].extend(techdraw_result.get('exported_files', []))
            
            FreeCAD.closeDocument(doc.Name)
            result['success'] = True
            result['parts_processed'] = len(assembly_objects)
            result['assembly_created'] = True
            
            logger.info(f"Assembly4 workflow completed: {len(assembly_objects)} parts")
            
        except Exception as e:
            logger.error(f"Assembly4 flow failed: {e}")
            result['errors'].append(str(e))
            
        return result
    
    def _get_import_error_message(self, exc: Exception) -> str:
        """Return a detailed error message for Import module import failure."""
        return textwrap.dedent(f"""
            Failed to import FreeCAD's Import module, essential for STEP/STL export: {exc}
            Troubleshooting steps:
            1. Verify FreeCAD installation includes the Import module
            2. Check that PYTHONPATH includes FreeCAD modules directory
            3. Ensure all FreeCAD dependencies are installed
            4. Try running 'FreeCADCmd -c "import Import"' to test module availability
            5. If running in Docker, verify the FreeCAD AppImage was properly extracted
        """).strip()
    
    def _export_model(self, doc, base_name: str) -> List[Dict[str, Any]]:
        """Export FreeCAD model in multiple formats using DeterministicExporter.
        
        This method now uses DeterministicExporter to ensure consistent,
        deterministic exports across all workflows (upload, Assembly4, etc.).
        This addresses the issue where not all flows were using deterministic exports.
        """
        artefacts = []
        
        # Use DeterministicExporter for consistent deterministic exports
        exporter = DeterministicExporter(
            source_date_epoch=int(os.environ.get("SOURCE_DATE_EPOCH", "946684800"))
        )
        
        # Define formats to export
        output_formats = ["FCStd", "STEP", "STL"]
        base_path = Path(self.args.outdir) / base_name
        
        try:
            # Export using the centralized deterministic exporter
            export_results = exporter.export_all(doc, base_path, output_formats)
            
            # Convert export results to artefacts format
            for fmt, export_info in export_results.items():
                if "path" in export_info and "error" not in export_info:
                    artefact_type = 'freecad_document' if fmt == 'FCStd' else \
                                   'cad_model' if fmt == 'STEP' else \
                                   'mesh_model'
                    
                    artefacts.append({
                        'type': artefact_type,
                        'format': fmt,
                        'path': export_info['path'],
                        'size_bytes': export_info.get('size_bytes', 0),
                        'sha256': export_info.get('sha256')  # Include deterministic hash
                    })
                    logger.info(f"Exported {fmt}: {export_info['path']} (SHA256: {export_info.get('sha256', 'N/A')[:8]}...)")
                else:
                    logger.error(f"{fmt} export failed: {export_info.get('error', 'Unknown error')}")
        
        except Exception as e:
            logger.error(f"Export failed: {e}")
            # Return partial results if any
        
        logger.info(f"Model exported in {len(artefacts)} formats")
            
        return artefacts
    
    def _generate_techdraw(self, doc, target_objects: List) -> Dict[str, Any]:
        """Generate technical drawing using TechDraw."""
        try:
            # Parse TechDraw options
            template_path = self.args.td_template
            views = self.args.td_views.split(',') if self.args.td_views else ['Front', 'Right', 'Top']
            scale = float(self.args.td_scale)
            formats = self.args.td_fmt.split(',') if self.args.td_fmt else ['pdf', 'svg']
            
            # Create TechDraw generator
            generator = TechDrawGenerator(template_path, views, scale, self.args.td_dpi)
            
            # Generate drawing
            return generator.generate_drawing(doc, target_objects, self.args.outdir, formats)
            
        except Exception as e:
            logger.error(f"TechDraw generation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'exported_files': []
            }
    
    def _write_results(self, result: Dict, metrics: Dict, execution_time: float):
        """Write final results to output file."""
        try:
            # Combine all results
            final_result = {
                'worker_version': WORKER_VERSION,
                'freecad_version': FREECAD_EXPECTED_VERSION,
                'execution_time_seconds': execution_time,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'resource_metrics': metrics,
                **result
            }
            
            # Write to output directory
            result_path = os.path.join(self.args.outdir, 'worker_result.json')
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(final_result, f, indent=2, ensure_ascii=False)
                
            logger.info(f"Results written to: {result_path}")
            
        except Exception as e:
            logger.error(f"Failed to write results: {e}")


# ==============================================================================
# COMMAND LINE INTERFACE
# ==============================================================================

def create_argument_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description='FreeCAD Worker Harness - Merged Tasks 7.5 & 7.6',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Health check
  %(prog)s --health-server
  
  # Prompt-based model generation
  %(prog)s --flow prompt --input /work/input.json --outdir /work/out --request-id 12345
  
  # Parametric model with TechDraw
  %(prog)s --flow params --input /work/input.json --outdir /work/out --request-id 12345 \\
           --techdraw on --td-template /app/templates/A4_Landscape.svg
  
  # Upload normalization with resource limits
  %(prog)s --flow upload --input /work/input.json --outdir /work/out --request-id 12345 \\
           --cpu-seconds 600 --mem-mb 2048

Turkish Flow Names:
  prompt = İstem tabanlı model üretimi
  params = Parametrik modelleme
  upload = Yüklenen dosya normalizasyonu  
  a4     = Assembly4 iş akışı
        """
    )
    
    # Core workflow arguments
    parser.add_argument('--standalone', action='store_true',
                        help='Run in standalone mode (Task 7.6 style with JSON from stdin or file)')
    parser.add_argument('--flow', 
                       choices=['prompt', 'params', 'upload', 'a4'],
                       help='Workflow type (İş akışı türü)')
    
    parser.add_argument('--input',
                       help='Input JSON file path (Girdi JSON dosya yolu)')
    
    parser.add_argument('--outdir', 
                       help='Output directory (Çıktı dizini)')
    
    parser.add_argument('--request-id',
                       help='Request correlation ID (İstek korelasyon kimliği)')
    
    # Resource limits
    parser.add_argument('--cpu-seconds', type=int, default=0,
                       help='CPU time limit in seconds (CPU süresi limiti)')
    
    parser.add_argument('--mem-mb', type=int, default=0,
                       help='Memory limit in MB (Bellek limiti MB)')
    
    # Monitoring
    parser.add_argument('--metrics-interval', type=float, default=2.0,
                       help='Resource metrics sampling interval (Kaynak metrikleri örnekleme aralığı)')
    
    # Health server
    parser.add_argument('--health-server', action='store_true',
                       help='Enable health check HTTP server (Sağlık kontrolü HTTP sunucusunu etkinleştir)')
    
    # TechDraw options
    parser.add_argument('--techdraw', choices=['on', 'off'], default='off',
                       help='Enable TechDraw generation (TechDraw üretimini etkinleştir)')
    
    parser.add_argument('--td-template', default='/app/templates/A4_Landscape.svg',
                       help='TechDraw template path (TechDraw şablon yolu)')
    
    parser.add_argument('--td-views', default='Front,Right,Top,Isometric',
                       help='TechDraw views (comma-separated) (TechDraw görünümleri)')
    
    parser.add_argument('--td-scale', type=float, default=1.0,
                       help='TechDraw scale factor (TechDraw ölçek faktörü)')
    
    parser.add_argument('--td-dpi', type=int, default=300,
                       help='TechDraw export DPI (TechDraw dışa aktarma DPI)')
    
    parser.add_argument('--td-fmt', default='pdf,svg',
                       help='TechDraw export formats (comma-separated) (TechDraw dışa aktarma formatları)')
    
    # Version and help
    parser.add_argument('--version', action='version', version=f'FreeCAD Worker {WORKER_VERSION}')
    
    return parser


def validate_arguments(args) -> List[str]:
    """Validate command line arguments."""
    errors = []
    
    if args.flow:
        work_dir = '/work'
        
        # Validate required arguments for workflow execution
        if not args.input:
            errors.append("--input is required for workflow execution")
        else:
            try:
                # Use the secure static method for path validation
                real_input_path = FreeCADWorker._validate_path_security(
                    args.input, work_dir, "input file"
                )
                if not os.path.exists(real_input_path):
                    errors.append(f"Input file not found: {args.input}")
            except ValueError as e:
                errors.append(str(e))
            except Exception as e:
                errors.append(f"Error validating input path: {e}")
            
        if not args.outdir:
            errors.append("--outdir is required for workflow execution")
        else:
            try:
                # Use the secure static method for path validation
                real_outdir_path = FreeCADWorker._validate_path_security(
                    args.outdir, work_dir, "output directory"
                )
                if not os.path.exists(real_outdir_path):
                    try:
                        os.makedirs(real_outdir_path, exist_ok=True)
                    except Exception as e:
                        errors.append(f"Cannot create output directory {real_outdir_path}: {e}")
            except ValueError as e:
                errors.append(str(e))
            except Exception as e:
                errors.append(f"Error validating output directory: {e}")
        
        if not args.request_id:
            errors.append("--request-id is required for workflow execution")
    
    # Validate TechDraw template
    if args.techdraw == 'on' and args.td_template:
        try:
            # Security: Prevent path traversal - templates must be in /app/templates
            allowed_template_dir = '/app/templates'
            
            # Use the secure static method for path validation
            real_template_path = FreeCADWorker._validate_path_security(
                args.td_template, allowed_template_dir, "TechDraw template"
            )
            if not os.path.exists(real_template_path):
                errors.append(f"TechDraw template not found: {args.td_template}")
        except ValueError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"Error validating TechDraw template path: {e}")
    
    # Validate resource limits
    if args.cpu_seconds < 0:
        errors.append("CPU seconds must be >= 0")
        
    if args.mem_mb < 0:
        errors.append("Memory limit must be >= 0")
    
    return errors


# ==============================================================================
# STANDALONE EXECUTION (Task 7.6 compatibility)
# ==============================================================================

def main_standalone():
    """Main entry point for standalone Task 7.6 execution (used when called directly with JSON input)."""
    monitor = ResourceMonitor(max_time_seconds=20, max_memory_mb=2048)
    monitor.start()  # Start resource monitoring
    logger.info("ResourceMonitor started in standalone mode")
    
    try:
        # Read input JSON
        if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
            # From file (Task 7.6 style)
            with open(sys.argv[1], 'r', encoding='utf-8') as f:
                input_data = json.load(f)
        else:
            # From stdin
            input_data = json.load(sys.stdin)
        
        monitor.emit_progress("Input received")
        
        # Normalize Turkish parameters
        input_data = normalize_turkish_params(input_data)
        
        # Extract parameters
        length = float(input_data.get("length", 100))
        width = float(input_data.get("width", 50))
        height = float(input_data.get("height", 30))
        hole_diameter = float(input_data.get("hole_diameter", 10))
        units = input_data.get("units", "mm")
        material = input_data.get("material", "aluminum")
        process = input_data.get("process", "milling")
        tessellation = float(input_data.get("tessellation_tolerance", 0.1))
        output_formats = input_data.get("formats", ["FCStd", "STEP", "STL"])
        
        # Validate material-machine compatibility
        valid, error = validate_material_machine_compatibility(material, process)
        if not valid:
            raise ValueError(error)
        
        monitor.emit_progress(f"Validated: {material} + {process}")
        
        # Create generator
        generator = FreeCADParametricGenerator(monitor)
        
        # Create document
        doc = generator.create_document("parametric_model")
        
        # Generate geometry
        shape = generator.create_prism_with_hole(
            length, width, height, hole_diameter, units
        )
        
        # Add to document and capture the returned object
        doc_object = generator.add_shape_to_document(shape, "PrismWithHole")
        
        # Export to requested formats
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "parametric_output"
            
            export_results = generator.export_shape(
                shape, base_path, output_formats, tessellation
            )
        
        # Extract metrics
        shape_metrics = generator.extract_metrics(shape)
        
        # Get resource metrics
        resource_metrics = monitor.get_metrics()
        
        # Prepare output
        output = {
            "success": True,
            "parameters": {
                "length": length,
                "width": width,
                "height": height,
                "hole_diameter": hole_diameter,
                "units": units,
                "material": material,
                "process": process
            },
            "exports": export_results,
            "metrics": {
                "geometry": shape_metrics,
                "resources": resource_metrics
            },
            "validation": {
                "material_process_compatible": True
            }
        }
        
        # Output JSON result
        print(json.dumps(output, indent=2))
        
        monitor.emit_progress("Complete")
        
    except Exception as e:
        # Handle errors
        error_output = {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "metrics": {
                "resources": monitor.get_metrics()
            }
        }
        print(json.dumps(error_output, indent=2))
        sys.exit(1)
    finally:
        monitor.stop()  # Stop resource monitoring in finally block
        logger.info("ResourceMonitor stopped, final metrics collected")


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

def main():
    """Main entry point for FreeCAD worker harness."""
    parser = create_argument_parser()
    
    # Check if this is a Task 7.6 style invocation (JSON file as first arg)
    # This maintains backward compatibility with existing invocations
    if len(sys.argv) == 2 and not sys.argv[1].startswith('--') and sys.argv[1].endswith('.json'):
        # Task 7.6 standalone mode for backward compatibility
        return main_standalone()
    
    # Parse arguments
    args = parser.parse_args()
    
    # Handle explicit standalone mode
    if args.standalone:
        return main_standalone()
    
    # Handle special cases
    if args.health_server and not args.flow:
        # Health server only mode
        logger.info("Starting in health server mode")
        start_health_server(int(os.getenv('HEALTH_PORT', '8080')))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Health server stopped")
        return 0
    
    if not args.flow:
        # Check if stdin has JSON (Task 7.6 compatibility)
        if not sys.stdin.isatty():
            return main_standalone()
        
        parser.print_help()
        return EXIT_CODES['VALIDATION_ERROR']
    
    # Validate arguments
    validation_errors = validate_arguments(args)
    if validation_errors:
        logger.error("Validation errors:")
        for error in validation_errors:
            logger.error(f"  - {error}")
        return EXIT_CODES['VALIDATION_ERROR']
    
    # Create and run worker
    try:
        worker = FreeCADWorker(args)
        return worker.execute()
    except Exception as e:
        logger.error(f"Worker execution failed: {e}", exc_info=True)
        return EXIT_CODES['ERROR']


if __name__ == '__main__':
    sys.exit(main())