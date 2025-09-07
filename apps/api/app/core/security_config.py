"""
Task 7.18: Security Configuration and Hardening for FreeCAD 1.1.0/OCCT 7.8.x

This module implements comprehensive security controls for FreeCAD subprocess execution:
- Subprocess sandboxing with resource limits
- Python module allowlist/blocklist
- Resource limits (CPU, memory, time)
- Workbench restrictions
- Security policies and hardening
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import platform

# resource module is Unix-only
if platform.system() != 'Windows':
    import resource
else:
    # Mock resource module for Windows development
    class resource:
        RLIMIT_CPU = 0
        RLIMIT_AS = 1
        RLIMIT_FSIZE = 2
        RLIMIT_NOFILE = 3
        RLIMIT_NPROC = 4
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from datetime import timedelta

from pydantic import BaseModel, Field, field_validator, ConfigDict

from .constants import FREECAD_VERSION, OCCT_VERSION
from .logging import get_logger

logger = get_logger(__name__)


class SecurityLevel(str, Enum):
    """Security levels for FreeCAD execution."""
    DEVELOPMENT = "development"  # Relaxed for development
    STAGING = "staging"          # Moderate restrictions
    PRODUCTION = "production"    # Maximum security


class ResourceLimitType(str, Enum):
    """Resource limit types for subprocess execution."""
    CPU_TIME = "cpu_time"
    MEMORY = "memory"
    FILE_SIZE = "file_size"
    OPEN_FILES = "open_files"
    PROCESSES = "processes"


@dataclass
class ResourceLimits:
    """Resource limits for FreeCAD subprocess execution."""
    cpu_time_seconds: int = 300  # 5 minutes default
    memory_mb: int = 2048        # 2GB default
    file_size_mb: int = 100      # 100MB max file size
    max_open_files: int = 256    # Max open file descriptors
    max_processes: int = 1        # Single process only
    
    def to_rlimit_dict(self) -> Dict[int, tuple]:
        """Convert to resource.setrlimit format (Unix only)."""
        if platform.system() == 'Windows':
            # Return empty dict on Windows (resource limits not supported)
            return {}
        
        return {
            resource.RLIMIT_CPU: (self.cpu_time_seconds, self.cpu_time_seconds),
            resource.RLIMIT_AS: (self.memory_mb * 1024 * 1024, self.memory_mb * 1024 * 1024),
            resource.RLIMIT_FSIZE: (self.file_size_mb * 1024 * 1024, self.file_size_mb * 1024 * 1024),
            resource.RLIMIT_NOFILE: (self.max_open_files, self.max_open_files),
            resource.RLIMIT_NPROC: (self.max_processes, self.max_processes),
        }


class PythonModulePolicy(BaseModel):
    """Python module access policy for FreeCAD scripts."""
    model_config = ConfigDict(validate_assignment=True)
    
    # Core allowed modules (always available)
    core_allowed: Set[str] = Field(
        default_factory=lambda: {
            "FreeCAD", "FreeCADGui", "Part", "Draft", "Sketcher",
            "math", "decimal", "datetime", "json", "base64",
            "collections", "itertools", "functools", "typing",
            "dataclasses", "enum", "abc", "numbers", "fractions"
        },
        description="Core modules always allowed"
    )
    
    # Explicitly blocked modules (security risk)
    blocked_modules: Set[str] = Field(
        default_factory=lambda: {
            "os", "sys", "subprocess", "socket", "ctypes", 
            "importlib", "shlex", "mmap", "pty", "fcntl",
            "signal", "multiprocessing", "threading", "asyncio",
            "pickle", "marshal", "shelve", "sqlite3", "dbm",
            "urllib", "http", "ftplib", "telnetlib", "smtplib",
            "poplib", "imaplib", "xmlrpc", "cgi", "cgitb",
            "__builtin__", "__builtins__", "eval", "exec",
            "compile", "__import__", "open", "input", "raw_input"
        },
        description="Modules that are always blocked"
    )
    
    # Conditional modules (based on security level)
    conditional_modules: Dict[SecurityLevel, Set[str]] = Field(
        default_factory=lambda: {
            SecurityLevel.DEVELOPMENT: {
                "numpy", "scipy", "pandas", "matplotlib",
                "pathlib", "tempfile", "logging", "warnings"
            },
            SecurityLevel.STAGING: {
                "numpy", "pathlib", "logging"
            },
            SecurityLevel.PRODUCTION: set()  # None in production
        },
        description="Modules allowed based on security level"
    )
    
    def get_allowed_modules(self, security_level: SecurityLevel) -> Set[str]:
        """Get all allowed modules for a security level."""
        allowed = self.core_allowed.copy()
        if security_level in self.conditional_modules:
            allowed.update(self.conditional_modules[security_level])
        return allowed
    
    def is_module_allowed(self, module_name: str, security_level: SecurityLevel) -> bool:
        """Check if a module is allowed."""
        if module_name in self.blocked_modules:
            return False
        return module_name in self.get_allowed_modules(security_level)
    
    def generate_import_hook(self, security_level: SecurityLevel, sandbox_dir: Path) -> str:
        """Generate Python code for import restrictions.
        
        Args:
            security_level: Security level for module restrictions
            sandbox_dir: Required sandbox directory path for file operations (job-specific)
        """
        allowed = self.get_allowed_modules(security_level)
        blocked = self.blocked_modules
        # sandbox_dir is now required - no fallback to shared path
        sandbox_path = str(sandbox_dir)
        
        hook_code = f'''
import builtins
import sys

# Original import function
_original_import = builtins.__import__

# Allowed modules
ALLOWED_MODULES = {allowed!r}

# Blocked modules
BLOCKED_MODULES = {blocked!r}

def restricted_import(name, *args, **kwargs):
    """Restricted import that checks module allowlist/blocklist."""
    # Get the base module name
    base_name = name.split('.')[0]
    
    # Check blocklist first
    if base_name in BLOCKED_MODULES:
        raise ImportError(f"Module '{{base_name}}' is blocked for security reasons")
    
    # Check allowlist
    if base_name not in ALLOWED_MODULES:
        raise ImportError(f"Module '{{base_name}}' is not in the allowed list")
    
    # Allow the import
    return _original_import(name, *args, **kwargs)

# Replace the import function
builtins.__import__ = restricted_import

# Remove dangerous built-ins
if hasattr(builtins, 'eval'):
    del builtins.eval
if hasattr(builtins, 'exec'):
    del builtins.exec
if hasattr(builtins, 'compile'):
    del builtins.compile
if hasattr(builtins, 'open'):
    # Replace open with restricted version
    def restricted_open(file, mode='r', *args, **kwargs):
        if 'w' in mode or 'a' in mode or 'x' in mode or '+' in mode:
            raise PermissionError("Write access is not allowed")
        if not str(file).startswith('{sandbox_path}/'):
            raise PermissionError(f"Access to '{{file}}' is not allowed")
        return _original_open(file, mode, *args, **kwargs)
    _original_open = builtins.open
    builtins.open = restricted_open
'''
        return hook_code


class WorkbenchPolicy(BaseModel):
    """Workbench access policy for FreeCAD."""
    model_config = ConfigDict(validate_assignment=True)
    
    # Approved workbenches with version pins
    approved_workbenches: Dict[str, str] = Field(
        default_factory=lambda: {
            "Core": FREECAD_VERSION,
            "Part": FREECAD_VERSION,
            "PartDesign": FREECAD_VERSION,
            "Sketcher": FREECAD_VERSION,
            "Draft": FREECAD_VERSION,
            "Assembly4": "0.50.0",  # Pinned Assembly4 version
            "Material": FREECAD_VERSION,
        },
        description="Approved workbenches with version requirements"
    )
    
    # Blocked workbenches (security risk or unstable)
    blocked_workbenches: Set[str] = Field(
        default_factory=lambda: {
            "Macro", "AddonManager", "WebTools", 
            "ExternalTools", "PythonConsole"
        },
        description="Workbenches that are blocked"
    )
    
    # Experimental workbenches (require feature flag)
    experimental_workbenches: Set[str] = Field(
        default_factory=lambda: {
            "Assembly4", "Assembly3", "A2plus"
        },
        description="Experimental workbenches requiring feature flag"
    )
    
    def is_workbench_allowed(
        self, 
        workbench: str, 
        enable_experimental: bool = False
    ) -> bool:
        """Check if a workbench is allowed."""
        if workbench in self.blocked_workbenches:
            return False
        
        if workbench in self.experimental_workbenches and not enable_experimental:
            return False
        
        return workbench in self.approved_workbenches
    
    def get_workbench_version(self, workbench: str) -> Optional[str]:
        """Get required version for a workbench."""
        return self.approved_workbenches.get(workbench)


class GeometryLimits(BaseModel):
    """Geometry operation limits for OCCT 7.8.x."""
    model_config = ConfigDict(validate_assignment=True)
    
    max_faces: int = Field(default=10000, description="Maximum number of faces")
    max_edges: int = Field(default=50000, description="Maximum number of edges")
    max_vertices: int = Field(default=100000, description="Maximum number of vertices")
    max_mesh_triangles: int = Field(default=1000000, description="Maximum mesh triangles")
    max_boolean_timeout_seconds: int = Field(default=30, description="Boolean operation timeout")
    max_fillet_iterations: int = Field(default=100, description="Maximum fillet iterations")
    max_shape_healing_iterations: int = Field(default=10, description="Shape healing iterations")
    max_file_size_mb: int = Field(default=100, description="Maximum CAD file size")
    
    @field_validator('max_faces', 'max_edges', 'max_vertices', 'max_mesh_triangles')
    @classmethod
    def validate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Must be positive")
        return v


class SecurityConfig(BaseModel):
    """Complete security configuration for FreeCAD execution."""
    model_config = ConfigDict(validate_assignment=True)
    
    security_level: SecurityLevel = Field(
        default=SecurityLevel.PRODUCTION,
        description="Current security level"
    )
    
    resource_limits: ResourceLimits = Field(
        default_factory=ResourceLimits,
        description="Resource limits for subprocess"
    )
    
    python_policy: PythonModulePolicy = Field(
        default_factory=PythonModulePolicy,
        description="Python module access policy"
    )
    
    workbench_policy: WorkbenchPolicy = Field(
        default_factory=WorkbenchPolicy,
        description="Workbench access policy"
    )
    
    geometry_limits: GeometryLimits = Field(
        default_factory=GeometryLimits,
        description="OCCT geometry operation limits"
    )
    
    sandbox_dir: Path = Field(
        default_factory=lambda: Path("/tmp/freecad_sandbox"),
        description="Sandbox directory for FreeCAD execution"
    )
    
    enable_network: bool = Field(
        default=False,
        description="Allow network access (always False in production)"
    )
    
    enable_filesystem_write: bool = Field(
        default=False,
        description="Allow filesystem writes outside sandbox"
    )
    
    enable_user_macros: bool = Field(
        default=False,
        description="Allow user macros and addons"
    )
    
    freecad_version: str = Field(
        default=FREECAD_VERSION,
        description="Required FreeCAD version"
    )
    
    occt_version: str = Field(
        default=OCCT_VERSION,
        description="Required OCCT version"
    )
    
    def get_sandbox_path(self, job_id: str) -> Path:
        """Get sandbox path for a specific job."""
        return self.sandbox_dir / f"job_{job_id}"
    
    def create_sandbox(self, job_id: str) -> Path:
        """Create sandbox directory for job execution."""
        sandbox_path = self.get_sandbox_path(job_id)
        sandbox_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        
        # Create subdirectories
        (sandbox_path / "input").mkdir(exist_ok=True)
        (sandbox_path / "output").mkdir(exist_ok=True)
        (sandbox_path / "temp").mkdir(exist_ok=True)
        
        logger.info(
            "Created sandbox",
            job_id=job_id,
            path=str(sandbox_path)
        )
        
        return sandbox_path
    
    def cleanup_sandbox(self, job_id: str) -> bool:
        """Clean up sandbox after job completion."""
        sandbox_path = self.get_sandbox_path(job_id)
        
        if not sandbox_path.exists():
            return True
        
        try:
            import shutil
            shutil.rmtree(sandbox_path)
            logger.info(
                "Cleaned up sandbox",
                job_id=job_id,
                path=str(sandbox_path)
            )
            return True
        except Exception as e:
            logger.error(
                "Failed to clean up sandbox",
                job_id=job_id,
                path=str(sandbox_path),
                error=str(e)
            )
            return False
    
    def generate_seccomp_profile(self) -> Dict[str, Any]:
        """Generate seccomp profile for container/subprocess."""
        # Basic seccomp profile for FreeCAD
        # This is a restrictive profile that only allows necessary syscalls
        return {
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": ["SCMP_ARCH_X86_64"],
            "syscalls": [
                {
                    "names": [
                        # Essential syscalls
                        "read", "write", "close", "fstat", "lseek",
                        "mmap", "mprotect", "munmap", "brk", "rt_sigaction",
                        "rt_sigprocmask", "ioctl", "access", "getpid",
                        "clone", "execve", "wait4", "exit", "exit_group",
                        
                        # File operations (read-only)
                        "open", "openat", "stat", "lstat", "fcntl",
                        "dup", "dup2", "pipe", "select", "poll",
                        
                        # Memory management
                        "mremap", "madvise", "shmget", "shmat", "shmctl",
                        
                        # Time
                        "gettimeofday", "clock_gettime", "nanosleep",
                        
                        # Process info
                        "getuid", "getgid", "geteuid", "getegid",
                        "getpgrp", "getppid", "getpgid", "getsid",
                        
                        # Threading (limited)
                        "futex", "set_tid_address", "set_robust_list"
                    ],
                    "action": "SCMP_ACT_ALLOW"
                }
            ]
        }
    
    def generate_apparmor_profile(self) -> str:
        """Generate AppArmor profile for FreeCAD execution."""
        profile = f"""
#include <tunables/global>

profile freecad_sandbox_{self.security_level.value} {{
  #include <abstractions/base>
  #include <abstractions/python>
  
  # FreeCAD binary execution
  /usr/bin/FreeCAD{self.freecad_version.replace('.', '_')} ix,
  /usr/bin/FreeCADCmd ix,
  
  # Read-only access to FreeCAD libraries
  /usr/lib/freecad/** r,
  /usr/share/freecad/** r,
  
  # Python libraries (read-only)
  /usr/lib/python3*/** r,
  /usr/local/lib/python3*/** r,
  
  # Sandbox directory (read-write)
  {self.sandbox_dir}/** rw,
  
  # Temp directory (limited)
  /tmp/freecad_* rw,
  
  # Deny network access
  deny network,
  
  # Deny capability access
  deny capability,
  
  # Deny mount operations
  deny mount,
  
  # Deny ptrace
  deny ptrace,
  
  # Deny signal to other processes
  deny signal peer!=@{{profile_name}},
}}
"""
        return profile
    
    def get_subprocess_env(self, job_id: str) -> Dict[str, str]:
        """Get environment variables for secure subprocess execution."""
        sandbox_path = self.get_sandbox_path(job_id)
        
        env = {
            # Python security settings
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": "",  # Clear PYTHONPATH
            
            # FreeCAD settings
            "FREECAD_USER_DATA": str(sandbox_path / "temp"),
            "FREECAD_USER_CACHE": str(sandbox_path / "temp"),
            "FREECAD_USER_CONFIG": str(sandbox_path / "temp"),
            
            # Disable user customization
            "FREECAD_DISABLE_MACROS": "1" if not self.enable_user_macros else "0",
            "FREECAD_DISABLE_ADDONS": "1" if not self.enable_user_macros else "0",
            
            # Security markers
            "FREECAD_SECURITY_LEVEL": self.security_level.value,
            "FREECAD_SANDBOX_MODE": "1",
            
            # Temp directory
            "TMPDIR": str(sandbox_path / "temp"),
            "TEMP": str(sandbox_path / "temp"),
            "TMP": str(sandbox_path / "temp"),
            
            # Disable network if required
            "no_proxy": "*" if not self.enable_network else "",
            "NO_PROXY": "*" if not self.enable_network else "",
        }
        
        return env
    
    def validate_freecad_script(self, script_content: str) -> List[str]:
        """Validate FreeCAD Python script for security issues."""
        issues = []
        
        # Check for blocked modules
        for module in self.python_policy.blocked_modules:
            if f"import {module}" in script_content or f"from {module}" in script_content:
                issues.append(f"Blocked module '{module}' detected")
        
        # Check for dangerous functions
        dangerous_patterns = [
            ("eval(", "Use of eval() is prohibited"),
            ("exec(", "Use of exec() is prohibited"),
            ("compile(", "Use of compile() is prohibited"),
            ("__import__", "Use of __import__ is prohibited"),
            ("os.system", "System calls are prohibited"),
            ("subprocess.", "Subprocess calls are prohibited"),
            ("open(", "Direct file operations may be restricted"),
        ]
        
        for pattern, message in dangerous_patterns:
            if pattern in script_content:
                issues.append(message)
        
        # Check for network operations
        if not self.enable_network:
            network_patterns = ["socket.", "urllib.", "http.", "requests."]
            for pattern in network_patterns:
                if pattern in script_content:
                    issues.append(f"Network operation '{pattern}' is not allowed")
        
        return issues


# Global security configuration instance
_security_config: Optional[SecurityConfig] = None


def get_security_config() -> SecurityConfig:
    """Get global security configuration instance."""
    global _security_config
    if _security_config is None:
        # Determine security level from environment
        env_level = os.getenv("SECURITY_LEVEL", "production").lower()
        
        try:
            security_level = SecurityLevel(env_level)
        except ValueError:
            logger.warning(
                f"Invalid security level '{env_level}', using production",
                env_level=env_level
            )
            security_level = SecurityLevel.PRODUCTION
        
        _security_config = SecurityConfig(security_level=security_level)
        
        logger.info(
            "Initialized security configuration",
            level=security_level.value,
            freecad_version=_security_config.freecad_version,
            occt_version=_security_config.occt_version
        )
    
    return _security_config


def set_security_config(config: SecurityConfig) -> None:
    """Set global security configuration (for testing)."""
    global _security_config
    _security_config = config