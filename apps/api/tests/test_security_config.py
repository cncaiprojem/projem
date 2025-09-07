"""
Tests for Task 7.18: Security Configuration and Hardening
"""

import pytest
import platform
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile

from app.core.security_config import (
    SecurityLevel,
    ResourceLimits,
    PythonModulePolicy,
    WorkbenchPolicy,
    GeometryLimits,
    SecurityConfig,
    get_security_config,
    set_security_config,
)


class TestResourceLimits:
    """Test resource limit configuration."""
    
    def test_default_limits(self):
        """Test default resource limits."""
        limits = ResourceLimits()
        
        assert limits.cpu_time_seconds == 300
        assert limits.memory_mb == 2048
        assert limits.file_size_mb == 100
        assert limits.max_open_files == 256
        assert limits.max_processes == 1
    
    @pytest.mark.skipif(platform.system() == "Windows", reason="resource module not available on Windows")
    def test_to_rlimit_dict(self):
        """Test conversion to resource.setrlimit format."""
        limits = ResourceLimits(
            cpu_time_seconds=60,
            memory_mb=1024,
            file_size_mb=50,
            max_open_files=128,
            max_processes=2
        )
        
        rlimit_dict = limits.to_rlimit_dict()
        
        import resource
        assert resource.RLIMIT_CPU in rlimit_dict
        assert rlimit_dict[resource.RLIMIT_CPU] == (60, 60)
        assert resource.RLIMIT_AS in rlimit_dict
        assert rlimit_dict[resource.RLIMIT_AS] == (1024 * 1024 * 1024, 1024 * 1024 * 1024)


class TestPythonModulePolicy:
    """Test Python module access policy."""
    
    def test_core_allowed_modules(self):
        """Test core allowed modules are present."""
        policy = PythonModulePolicy()
        
        assert "FreeCAD" in policy.core_allowed
        assert "Part" in policy.core_allowed
        assert "math" in policy.core_allowed
        assert "json" in policy.core_allowed
    
    def test_blocked_modules(self):
        """Test dangerous modules are blocked."""
        policy = PythonModulePolicy()
        
        assert "os" in policy.blocked_modules
        assert "subprocess" in policy.blocked_modules
        assert "socket" in policy.blocked_modules
        assert "ctypes" in policy.blocked_modules
    
    def test_get_allowed_modules_by_security_level(self):
        """Test allowed modules change by security level."""
        policy = PythonModulePolicy()
        
        # Development allows more modules
        dev_modules = policy.get_allowed_modules(SecurityLevel.DEVELOPMENT)
        assert "numpy" in dev_modules
        assert "pandas" in dev_modules
        
        # Production is more restrictive
        prod_modules = policy.get_allowed_modules(SecurityLevel.PRODUCTION)
        assert "numpy" not in prod_modules
        assert "pandas" not in prod_modules
        
        # Core modules are always allowed
        assert "FreeCAD" in dev_modules
        assert "FreeCAD" in prod_modules
    
    def test_is_module_allowed(self):
        """Test module allowance checking."""
        policy = PythonModulePolicy()
        
        # Blocked modules are never allowed
        assert not policy.is_module_allowed("os", SecurityLevel.DEVELOPMENT)
        assert not policy.is_module_allowed("subprocess", SecurityLevel.PRODUCTION)
        
        # Core modules are always allowed
        assert policy.is_module_allowed("FreeCAD", SecurityLevel.PRODUCTION)
        assert policy.is_module_allowed("math", SecurityLevel.DEVELOPMENT)
        
        # Conditional modules depend on level
        assert policy.is_module_allowed("numpy", SecurityLevel.DEVELOPMENT)
        assert not policy.is_module_allowed("numpy", SecurityLevel.PRODUCTION)
    
    def test_generate_import_hook(self):
        """Test import hook generation."""
        policy = PythonModulePolicy()
        hook_code = policy.generate_import_hook(SecurityLevel.PRODUCTION)
        
        assert "restricted_import" in hook_code
        assert "ALLOWED_MODULES" in hook_code
        assert "BLOCKED_MODULES" in hook_code
        assert "del builtins.eval" in hook_code
        assert "del builtins.exec" in hook_code


class TestWorkbenchPolicy:
    """Test workbench access policy."""
    
    def test_approved_workbenches(self):
        """Test approved workbenches are configured."""
        policy = WorkbenchPolicy()
        
        assert "Core" in policy.approved_workbenches
        assert "Part" in policy.approved_workbenches
        assert "Assembly4" in policy.approved_workbenches
    
    def test_blocked_workbenches(self):
        """Test dangerous workbenches are blocked."""
        policy = WorkbenchPolicy()
        
        assert "Macro" in policy.blocked_workbenches
        assert "AddonManager" in policy.blocked_workbenches
        assert "PythonConsole" in policy.blocked_workbenches
    
    def test_is_workbench_allowed(self):
        """Test workbench allowance checking."""
        policy = WorkbenchPolicy()
        
        # Blocked workbenches are never allowed
        assert not policy.is_workbench_allowed("Macro", enable_experimental=True)
        assert not policy.is_workbench_allowed("AddonManager", enable_experimental=False)
        
        # Approved workbenches are allowed
        assert policy.is_workbench_allowed("Part", enable_experimental=False)
        assert policy.is_workbench_allowed("Core", enable_experimental=False)
        
        # Experimental workbenches need flag
        assert not policy.is_workbench_allowed("Assembly4", enable_experimental=False)
        assert policy.is_workbench_allowed("Assembly4", enable_experimental=True)


class TestGeometryLimits:
    """Test geometry operation limits."""
    
    def test_default_limits(self):
        """Test default geometry limits."""
        limits = GeometryLimits()
        
        assert limits.max_faces == 10000
        assert limits.max_edges == 50000
        assert limits.max_vertices == 100000
        assert limits.max_mesh_triangles == 1000000
    
    def test_positive_validation(self):
        """Test that limits must be positive."""
        with pytest.raises(ValueError, match="Must be positive"):
            GeometryLimits(max_faces=-1)
        
        with pytest.raises(ValueError, match="Must be positive"):
            GeometryLimits(max_edges=0)


class TestSecurityConfig:
    """Test complete security configuration."""
    
    def test_default_configuration(self):
        """Test default security configuration."""
        config = SecurityConfig()
        
        assert config.security_level == SecurityLevel.PRODUCTION
        assert isinstance(config.resource_limits, ResourceLimits)
        assert isinstance(config.python_policy, PythonModulePolicy)
        assert isinstance(config.workbench_policy, WorkbenchPolicy)
        assert isinstance(config.geometry_limits, GeometryLimits)
        assert config.sandbox_dir == Path("/tmp/freecad_sandbox")
        assert not config.enable_network
        assert not config.enable_filesystem_write
        assert not config.enable_user_macros
    
    def test_get_sandbox_path(self):
        """Test sandbox path generation."""
        config = SecurityConfig()
        job_id = "test_job_123"
        
        sandbox_path = config.get_sandbox_path(job_id)
        assert sandbox_path == Path("/tmp/freecad_sandbox/job_test_job_123")
    
    def test_create_sandbox(self):
        """Test sandbox directory creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SecurityConfig(sandbox_dir=Path(tmpdir))
            job_id = "test_job"
            
            sandbox_path = config.create_sandbox(job_id)
            
            assert sandbox_path.exists()
            assert sandbox_path.is_dir()
            assert (sandbox_path / "input").exists()
            assert (sandbox_path / "output").exists()
            assert (sandbox_path / "temp").exists()
    
    def test_cleanup_sandbox(self):
        """Test sandbox cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SecurityConfig(sandbox_dir=Path(tmpdir))
            job_id = "test_job"
            
            # Create sandbox
            sandbox_path = config.create_sandbox(job_id)
            assert sandbox_path.exists()
            
            # Clean up
            result = config.cleanup_sandbox(job_id)
            assert result is True
            assert not sandbox_path.exists()
    
    def test_generate_seccomp_profile(self):
        """Test seccomp profile generation."""
        config = SecurityConfig()
        profile = config.generate_seccomp_profile()
        
        assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
        assert "SCMP_ARCH_X86_64" in profile["architectures"]
        assert len(profile["syscalls"]) > 0
        assert profile["syscalls"][0]["action"] == "SCMP_ACT_ALLOW"
    
    def test_generate_apparmor_profile(self):
        """Test AppArmor profile generation."""
        config = SecurityConfig()
        profile = config.generate_apparmor_profile()
        
        assert "profile freecad_sandbox_production" in profile
        assert "deny network" in profile
        assert "deny capability" in profile
        assert "/usr/bin/FreeCAD" in profile
        assert str(config.sandbox_dir) in profile
    
    def test_get_subprocess_env(self):
        """Test subprocess environment generation."""
        config = SecurityConfig()
        job_id = "test_job"
        
        env = config.get_subprocess_env(job_id)
        
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        assert env["PYTHONNOUSERSITE"] == "1"
        assert env["PYTHONPATH"] == ""
        assert env["FREECAD_SECURITY_LEVEL"] == "production"
        assert env["FREECAD_SANDBOX_MODE"] == "1"
        assert env["FREECAD_DISABLE_MACROS"] == "1"
        assert env["NO_PROXY"] == "*"  # Network disabled in production
    
    def test_validate_freecad_script(self):
        """Test FreeCAD script validation."""
        config = SecurityConfig()
        
        # Valid script
        valid_script = """
import FreeCAD
import Part
doc = FreeCAD.newDocument()
"""
        issues = config.validate_freecad_script(valid_script)
        assert "import os" not in valid_script
        
        # Script with blocked module
        dangerous_script = """
import os
os.system("rm -rf /")
"""
        issues = config.validate_freecad_script(dangerous_script)
        assert len(issues) > 0
        assert any("os" in issue for issue in issues)
        
        # Script with eval
        eval_script = """
result = eval("1 + 1")
"""
        issues = config.validate_freecad_script(eval_script)
        assert len(issues) > 0
        assert any("eval" in issue for issue in issues)


class TestGlobalConfig:
    """Test global configuration singleton."""
    
    @patch.dict("os.environ", {"SECURITY_LEVEL": "development"})
    def test_get_security_config_development(self):
        """Test getting config with development level."""
        # Reset any existing config
        set_security_config(None)
        
        config = get_security_config()
        assert config.security_level == SecurityLevel.DEVELOPMENT
    
    @patch.dict("os.environ", {"SECURITY_LEVEL": "production"})
    def test_get_security_config_production(self):
        """Test getting config with production level."""
        # Reset any existing config
        set_security_config(None)
        
        config = get_security_config()
        assert config.security_level == SecurityLevel.PRODUCTION
    
    @patch.dict("os.environ", {"SECURITY_LEVEL": "invalid"})
    def test_get_security_config_invalid_level(self):
        """Test getting config with invalid level defaults to production."""
        # Reset any existing config
        set_security_config(None)
        
        config = get_security_config()
        assert config.security_level == SecurityLevel.PRODUCTION
    
    def test_set_security_config(self):
        """Test setting custom config."""
        custom_config = SecurityConfig(security_level=SecurityLevel.STAGING)
        set_security_config(custom_config)
        
        config = get_security_config()
        assert config.security_level == SecurityLevel.STAGING