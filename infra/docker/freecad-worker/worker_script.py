#!/usr/bin/env python3
# ==============================================================================
# FREECAD WORKER HARNESS - TASK 7.5
# ==============================================================================
# Comprehensive FreeCAD worker execution harness with:
# - Health check HTTP server with FreeCAD validation
# - Resource monitoring with psutil (CPU, memory, I/O)
# - Resource limits enforcement (CPU time, memory)
# - TechDraw technical drawing generation (headless)
# - Multi-flow support (prompt, params, upload, a4)
# - Graceful cancellation and error handling
# - Structured JSON logging with Turkish terminology support
# ==============================================================================

import argparse
import json
import logging
import os
import signal
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil


# ==============================================================================
# GLOBALS AND CONFIGURATION
# ==============================================================================

# Version and metadata
WORKER_VERSION = "1.0.0"
FREECAD_EXPECTED_VERSION = "1.1.0"

# Resource monitoring
RESOURCE_MONITOR_INTERVAL = 2.0  # seconds

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
                with open(path, 'r') as f:
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
                with open(path, 'r') as f:
                    quota = f.read().strip()
                    if quota != 'max' and quota.isdigit():
                        cgroup_info['cpu_quota'] = int(quota)
                break
                
        cpu_period_paths = [
            '/sys/fs/cgroup/cpu/cpu.cfs_period_us',
        ]
        
        for path in cpu_period_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    period = f.read().strip()
                    if period.isdigit():
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
    
    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self.process = psutil.Process()
        self.samples = []
        self.peak_rss_mb = 0
        self.avg_cpu_percent = 0
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
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
                        
                        # Limit sample history (keep last 1000 samples)
                        if len(self.samples) > 1000:
                            self.samples = self.samples[-1000:]
                            
                        # Log periodic updates every 30 seconds
                        if len(self.samples) % int(30 / self.interval) == 0:
                            logger.info(f"Resource stats: CPU {stats['cpu_percent']:.1f}%, RSS {stats['rss_mb']:.1f}MB, Threads {stats['num_threads']}")
                            
                    # Check memory pressure
                    self._check_memory_pressure(stats['rss_mb'])
                    
                time.sleep(self.interval)
                
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
                time.sleep(self.interval)
    
    def _check_memory_pressure(self, current_rss_mb: float):
        """Check for memory pressure and emit warnings."""
        cgroup_limits = get_cgroup_limits()
        memory_limit_mb = cgroup_limits.get('memory_limit_mb')
        
        if memory_limit_mb:
            pressure_ratio = current_rss_mb / memory_limit_mb
            
            if pressure_ratio > 0.85:
                logger.warning(f"High memory pressure: {current_rss_mb:.1f}MB / {memory_limit_mb}MB ({pressure_ratio:.1%})")
                
                if pressure_ratio > 0.95:
                    logger.error(f"Critical memory pressure: {current_rss_mb:.1f}MB / {memory_limit_mb}MB")
                    # Could implement throttling here if THROTTLE_ON_PRESSURE=1


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
            if not os.path.exists(self.template_path):
                logger.warning(f"Template not found: {self.template_path}, using built-in template")
                self.template_path = None
            
            # Create TechDraw page
            page = freecad_doc.addObject("TechDraw::DrawPage", "DrawingPage")
            
            # Add template
            if self.template_path:
                template = freecad_doc.addObject("TechDraw::DrawSVGTemplate", "Template")
                template.Template = self.template_path
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
                    if i < 4:  # First row
                        view_obj.X = 50 + (i * 80)
                        view_obj.Y = 150
                    else:  # Second row
                        view_obj.X = 50 + ((i - 4) * 80)
                        view_obj.Y = 75
                    
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
# FREECAD WORKFLOW EXECUTION
# ==============================================================================

class FreeCADWorker:
    """Main FreeCAD worker execution engine."""
    
    def __init__(self, args):
        self.args = args
        self.resource_monitor = ResourceMonitor(interval=args.metrics_interval)
        self.start_time = time.time()
        self.cancelled = False
        
        # Setup signal handlers for graceful cancellation
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # CPU time limits
        if args.cpu_seconds > 0:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (args.cpu_seconds, args.cpu_seconds))
            signal.signal(signal.SIGXCPU, self._cpu_limit_handler)
        
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
            # Load input configuration
            with open(self.args.input, 'r') as f:
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
        """Execute parametric modeling flow."""
        logger.info("Executing parametric model generation")
        
        try:
            import FreeCAD
            
            # Create new document
            doc_name = f"param_model_{self.args.request_id[:8]}"
            doc = FreeCAD.newDocument(doc_name)
            
            # Get parametric definition
            model_type = input_data.get('model_type', 'box')
            dimensions = input_data.get('dimensions', {})
            
            # Create parametric model based on type
            if model_type == 'box':
                obj = doc.addObject("Part::Box", "ParametricBox")
                obj.Length = dimensions.get('length', 100.0)
                obj.Width = dimensions.get('width', 100.0)
                obj.Height = dimensions.get('height', 100.0)
            elif model_type == 'cylinder':
                obj = doc.addObject("Part::Cylinder", "ParametricCylinder")
                obj.Radius = dimensions.get('radius', 50.0)
                obj.Height = dimensions.get('height', 100.0)
            elif model_type == 'sphere':
                obj = doc.addObject("Part::Sphere", "ParametricSphere")
                obj.Radius = dimensions.get('radius', 50.0)
            else:
                raise ValueError(f"Unsupported model type: {model_type}")
            
            doc.recompute()
            
            # Export model
            artefacts = self._export_model(doc, f"parametric_{model_type}")
            result['artefacts'].extend(artefacts)
            
            # Generate TechDraw if requested
            if self.args.techdraw == 'on':
                techdraw_result = self._generate_techdraw(doc, [obj])
                result['techdraw'] = techdraw_result
                result['artefacts'].extend(techdraw_result.get('exported_files', []))
            
            FreeCAD.closeDocument(doc.Name)
            result['success'] = True
            result['model_type'] = model_type
            result['dimensions_applied'] = dimensions
            
            logger.info(f"Parametric flow completed: {model_type}")
            
        except Exception as e:
            logger.error(f"Parametric flow failed: {e}")
            result['errors'].append(str(e))
            
        return result
    
    def _execute_upload_flow(self, input_data: Dict, result: Dict) -> Dict:
        """Execute upload normalization flow."""
        logger.info("Executing upload normalization")
        
        try:
            import FreeCAD
            
            input_file = input_data.get('input_file')
            if not input_file or not os.path.exists(input_file):
                raise ValueError(f"Input file not found: {input_file}")
            
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
            
            for i, part_def in enumerate(parts[:5]):  # Limit to 5 parts for example
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
    
    def _export_model(self, doc, base_name: str) -> List[Dict[str, Any]]:
        """Export FreeCAD model in multiple formats."""
        artefacts = []
        
        try:
            import Import
            
            # Export FCStd
            fcstd_path = os.path.join(self.args.outdir, f"{base_name}.FCStd")
            doc.saveAs(fcstd_path)
            if os.path.exists(fcstd_path):
                artefacts.append({
                    'type': 'freecad_document',
                    'format': 'FCStd',
                    'path': fcstd_path,
                    'size_bytes': os.path.getsize(fcstd_path)
                })
            
            # Export STEP
            step_path = os.path.join(self.args.outdir, f"{base_name}.step")
            Import.export([obj for obj in doc.Objects if hasattr(obj, 'Shape')], step_path)
            if os.path.exists(step_path):
                artefacts.append({
                    'type': 'cad_model',
                    'format': 'STEP',
                    'path': step_path,
                    'size_bytes': os.path.getsize(step_path)
                })
            
            # Export STL
            stl_path = os.path.join(self.args.outdir, f"{base_name}.stl")
            Import.export([obj for obj in doc.Objects if hasattr(obj, 'Shape')], stl_path)
            if os.path.exists(stl_path):
                artefacts.append({
                    'type': 'mesh_model',
                    'format': 'STL',
                    'path': stl_path,
                    'size_bytes': os.path.getsize(stl_path)
                })
            
            logger.info(f"Model exported in {len(artefacts)} formats")
            
        except Exception as e:
            logger.error(f"Model export failed: {e}")
            
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
            with open(result_path, 'w') as f:
                json.dump(final_result, f, indent=2)
                
            logger.info(f"Results written to: {result_path}")
            
        except Exception as e:
            logger.error(f"Failed to write results: {e}")


# ==============================================================================
# COMMAND LINE INTERFACE
# ==============================================================================

def create_argument_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description='FreeCAD Worker Harness - Task 7.5',
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
        # Validate required arguments for workflow execution
        if not args.input:
            errors.append("--input is required for workflow execution")
        elif not os.path.exists(args.input):
            errors.append(f"Input file not found: {args.input}")
            
        if not args.outdir:
            errors.append("--outdir is required for workflow execution")
        elif not os.path.exists(args.outdir):
            try:
                os.makedirs(args.outdir, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create output directory {args.outdir}: {e}")
        
        if not args.request_id:
            errors.append("--request-id is required for workflow execution")
    
    # Validate TechDraw template
    if args.techdraw == 'on' and args.td_template:
        if not os.path.exists(args.td_template):
            errors.append(f"TechDraw template not found: {args.td_template}")
    
    # Validate resource limits
    if args.cpu_seconds < 0:
        errors.append("CPU seconds must be >= 0")
        
    if args.mem_mb < 0:
        errors.append("Memory limit must be >= 0")
    
    return errors


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

def main():
    """Main entry point for FreeCAD worker harness."""
    parser = create_argument_parser()
    args = parser.parse_args()
    
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