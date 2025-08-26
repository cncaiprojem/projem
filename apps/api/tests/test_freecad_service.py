"""
Ultra-Enterprise FreeCAD Service Tests

Comprehensive test suite covering:
- License-based feature control and resource limits
- Process monitoring and resource enforcement  
- Circuit breaker pattern and failure scenarios
- Input sanitization and validation
- Metrics collection and health checks
- Subprocess isolation and cleanup
- Error handling with Turkish messages
- Retry mechanisms and timeout management
"""

import json
import os
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.services.freecad_service import (
    UltraEnterpriseFreeCADService,
    LicenseFeatureController,
    LicenseTier,
    FreeCADErrorCode,
    FreeCADException,
    ProcessMonitor,
    CircuitBreaker,
    ResourceLimits
)
from app.models.license import License
from app.models.user import User
from app.services.license_service import LicenseService


class TestLicenseFeatureController:
    """Test license-based feature control."""
    
    def test_get_license_tier_basic(self):
        """Test basic license tier detection."""
        license = Mock(spec=License)
        license.type = '3m'
        
        tier = LicenseFeatureController.get_license_tier(license)
        assert tier == LicenseTier.BASIC
    
    def test_get_license_tier_pro(self):
        """Test pro license tier detection."""
        license = Mock(spec=License)
        license.type = '6m'
        
        tier = LicenseFeatureController.get_license_tier(license)
        assert tier == LicenseTier.PRO
    
    def test_get_license_tier_enterprise(self):
        """Test enterprise license tier detection."""
        license = Mock(spec=License)
        license.type = '12m'
        
        tier = LicenseFeatureController.get_license_tier(license)
        assert tier == LicenseTier.ENTERPRISE
    
    def test_get_license_tier_no_license(self):
        """Test default tier when no license."""
        tier = LicenseFeatureController.get_license_tier(None)
        assert tier == LicenseTier.BASIC
    
    def test_get_resource_limits_basic(self):
        """Test basic license resource limits."""
        license = Mock(spec=License)
        license.type = '3m'
        
        limits = LicenseFeatureController.get_resource_limits(license)
        
        assert limits.max_memory_mb == 512
        assert limits.max_cpu_percent == 50.0
        assert limits.max_execution_time_seconds == 300
        assert limits.max_concurrent_operations == 1
        assert 'FCStd' in limits.allowed_export_formats
        assert 'STL' in limits.allowed_export_formats
        assert 'STEP' not in limits.allowed_export_formats
    
    def test_get_resource_limits_enterprise(self):
        """Test enterprise license resource limits."""
        license = Mock(spec=License)
        license.type = '12m'
        
        limits = LicenseFeatureController.get_resource_limits(license)
        
        assert limits.max_memory_mb == 8192
        assert limits.max_cpu_percent == 100.0
        assert limits.max_execution_time_seconds == 7200
        assert limits.max_concurrent_operations == 10
        assert 'IFC' in limits.allowed_export_formats
        assert 'DXF' in limits.allowed_export_formats
    
    def test_check_feature_access_basic_allowed(self):
        """Test basic license allows basic features."""
        license = Mock(spec=License)
        license.type = '3m'
        
        assert LicenseFeatureController.check_feature_access(license, 'basic_modeling')
        assert LicenseFeatureController.check_feature_access(license, 'stl_export')
        assert LicenseFeatureController.check_feature_access(license, 'fcstd_export')
    
    def test_check_feature_access_basic_denied(self):
        """Test basic license denies advanced features."""
        license = Mock(spec=License)
        license.type = '3m'
        
        assert not LicenseFeatureController.check_feature_access(license, 'advanced_modeling')
        assert not LicenseFeatureController.check_feature_access(license, 'step_export')
        assert not LicenseFeatureController.check_feature_access(license, 'batch_processing')
    
    def test_check_feature_access_enterprise_all(self):
        """Test enterprise license allows all features."""
        license = Mock(spec=License)
        license.type = '12m'
        
        assert LicenseFeatureController.check_feature_access(license, 'basic_modeling')
        assert LicenseFeatureController.check_feature_access(license, 'advanced_modeling')
        assert LicenseFeatureController.check_feature_access(license, 'batch_processing')
        assert LicenseFeatureController.check_feature_access(license, 'api_access')


class TestCircuitBreaker:
    """Test circuit breaker pattern."""
    
    def test_circuit_breaker_closed_state(self):
        """Test circuit breaker in closed state allows operations."""
        
        @CircuitBreaker(failure_threshold=3)
        def test_function():
            return "success"
        
        result = test_function()
        assert result == "success"
    
    def test_circuit_breaker_opens_after_failures(self):
        """Test circuit breaker opens after failure threshold."""
        
        @CircuitBreaker(failure_threshold=2, expected_exception=ValueError)
        def failing_function():
            raise ValueError("Test error")
        
        # First failure
        with pytest.raises(ValueError):
            failing_function()
        
        # Second failure should open circuit breaker
        with pytest.raises(ValueError):
            failing_function()
        
        # Third call should raise circuit breaker exception
        with pytest.raises(FreeCADException) as exc_info:
            failing_function()
        
        assert exc_info.value.error_code == FreeCADErrorCode.CIRCUIT_BREAKER_OPEN
    
    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after timeout."""
        
        @CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        def sometimes_failing_function():
            if hasattr(sometimes_failing_function, 'fail'):
                delattr(sometimes_failing_function, 'fail')
                raise ValueError("Test error")
            return "success"
        
        # Cause failure to open circuit breaker
        sometimes_failing_function.fail = True
        with pytest.raises(ValueError):
            sometimes_failing_function()
        
        # Should raise circuit breaker exception
        with pytest.raises(FreeCADException):
            sometimes_failing_function()
        
        # Wait for recovery timeout
        time.sleep(0.15)
        
        # Should succeed and close circuit breaker
        result = sometimes_failing_function()
        assert result == "success"


class TestProcessMonitor:
    """Test process resource monitoring."""
    
    @patch('psutil.Process')
    def test_process_monitor_initialization(self, mock_process_class):
        """Test process monitor initialization."""
        mock_process = Mock()
        mock_process_class.return_value = mock_process
        
        limits = ResourceLimits(
            max_memory_mb=1024,
            max_cpu_percent=80.0,
            max_execution_time_seconds=300,
            max_model_complexity=1000,
            max_concurrent_operations=2,
            allowed_export_formats={'FCStd', 'STL'},
            max_file_size_mb=100
        )
        
        monitor = ProcessMonitor(12345, limits)
        
        assert monitor.pid == 12345
        assert monitor.limits == limits
        assert monitor.metrics.peak_memory_mb == 0.0
        assert monitor._monitoring is True
    
    @patch('psutil.Process')
    def test_process_monitor_memory_limit_enforcement(self, mock_process_class):
        """Test memory limit enforcement."""
        mock_process = Mock()
        mock_process_class.return_value = mock_process
        
        # Mock memory info to exceed limit
        mock_memory_info = Mock()
        mock_memory_info.rss = 2048 * 1024 * 1024  # 2048 MB in bytes
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.cpu_percent.return_value = 10.0
        mock_process.is_running.return_value = True
        
        limits = ResourceLimits(
            max_memory_mb=1024,  # Limit is 1024 MB
            max_cpu_percent=80.0,
            max_execution_time_seconds=300,
            max_model_complexity=1000,
            max_concurrent_operations=2,
            allowed_export_formats={'FCStd', 'STL'},
            max_file_size_mb=100
        )
        
        monitor = ProcessMonitor(12345, limits)
        
        # Start monitoring in background
        monitor.start_monitoring()
        
        # Wait a bit for monitoring to detect limit violation
        time.sleep(0.1)
        
        # Stop monitoring
        monitor.stop_monitoring()
        
        # Verify process termination was attempted
        mock_process.terminate.assert_called()


class TestUltraEnterpriseFreeCADService:
    """Test ultra-enterprise FreeCAD service."""
    
    @pytest.fixture
    def freecad_service(self):
        """Create FreeCAD service instance for testing."""
        return UltraEnterpriseFreeCADService()
    
    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        return Mock(spec=Session)
    
    @pytest.fixture
    def basic_license(self):
        """Create basic license mock."""
        license = Mock(spec=License)
        license.id = 1
        license.type = '3m'
        license.user_id = 1
        license.status = 'active'
        return license
    
    @pytest.fixture
    def enterprise_license(self):
        """Create enterprise license mock."""
        license = Mock(spec=License)
        license.id = 1
        license.type = '12m'
        license.user_id = 1
        license.status = 'active'
        return license
    
    def test_find_freecadcmd_path_configured(self, freecad_service):
        """Test finding FreeCAD path when configured."""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.freecadcmd_path = '/usr/bin/FreeCADCmd'
            with patch('os.path.isfile', return_value=True):
                path = freecad_service.find_freecadcmd_path()
                assert path == '/usr/bin/FreeCADCmd'
    
    def test_find_freecadcmd_path_not_found(self, freecad_service):
        """Test behavior when FreeCAD not found."""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.freecadcmd_path = None
            with patch('shutil.which', return_value=None):
                with patch('os.path.isfile', return_value=False):
                    path = freecad_service.find_freecadcmd_path()
                    assert path is None
    
    def test_validate_freecad_version_valid(self, freecad_service):
        """Test FreeCAD version validation with valid version."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "FreeCAD 1.1.0"
        
        with patch('subprocess.run', return_value=mock_result):
            valid, version = freecad_service.validate_freecad_version('/usr/bin/FreeCADCmd')
            
            assert valid is True
            assert version == "1.1.0"
    
    def test_validate_freecad_version_invalid(self, freecad_service):
        """Test FreeCAD version validation with invalid version."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "FreeCAD 0.20.0"
        
        with patch('subprocess.run', return_value=mock_result):
            valid, version = freecad_service.validate_freecad_version('/usr/bin/FreeCADCmd')
            
            assert valid is False
            assert version == "0.20.0"
    
    def test_sanitize_input_removes_dangerous_keys(self, freecad_service):
        """Test input sanitization removes dangerous keys."""
        dangerous_input = {
            'normal_key': 'normal_value',
            '__dangerous__': 'should_be_removed',
            'eval_something': 'also_removed',
            'safe_key': 'safe_value'
        }
        
        sanitized = freecad_service.sanitize_input(dangerous_input)
        
        assert 'normal_key' in sanitized
        assert 'safe_key' in sanitized
        assert '__dangerous__' not in sanitized
        assert 'eval_something' not in sanitized
    
    def test_sanitize_input_removes_dangerous_patterns(self, freecad_service):
        """Test input sanitization removes dangerous patterns from values."""
        dangerous_input = {
            'script': 'import os; os.system("rm -rf /")',
            'safe_script': 'create_box(10, 10, 10)'
        }
        
        sanitized = freecad_service.sanitize_input(dangerous_input)
        
        assert 'import ' not in sanitized['script']
        assert 'os.' not in sanitized['script']
        assert sanitized['safe_script'] == 'create_box(10, 10, 10)'
    
    def test_compute_file_hash(self, freecad_service):
        """Test file hash computation."""
        import hashlib
        
        test_file_content = 'test content'
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(test_file_content)
            temp_path = Path(f.name)
        
        try:
            hash_value = freecad_service.compute_file_hash(temp_path)
            
            # Compute expected SHA256 dynamically
            expected_hash = hashlib.sha256(test_file_content.encode()).hexdigest()
            assert hash_value == expected_hash
            
        finally:
            os.unlink(temp_path)
    
    @patch('app.services.license_service.LicenseService.get_active_license')
    def test_license_restriction_enforcement(self, mock_get_license, freecad_service, 
                                           mock_db_session, basic_license):
        """Test license restriction enforcement."""
        mock_get_license.return_value = basic_license
        
        # Basic license should not allow STEP export
        with pytest.raises(FreeCADException) as exc_info:
            freecad_service.execute_freecad_operation(
                db=mock_db_session,
                user_id=1,
                operation_type="modeling",
                script_content="# test script",
                parameters={},
                output_formats=['STEP'],  # Not allowed for basic license
                correlation_id="test-123"
            )
        
        assert exc_info.value.error_code == FreeCADErrorCode.LICENSE_RESTRICTION
        assert "step_export" in exc_info.value.turkish_message.lower() or "step" in exc_info.value.turkish_message.lower()
    
    @patch('app.services.license_service.LicenseService.get_active_license')
    def test_concurrent_operations_limit(self, mock_get_license, freecad_service,
                                       mock_db_session, basic_license):
        """Test concurrent operations limit enforcement."""
        mock_get_license.return_value = basic_license
        
        # Fill up the user_active_operations dictionary to simulate max concurrent operations
        # Basic license allows only 1 concurrent operation per user
        freecad_service.user_active_operations = {
            1: 1  # User ID 1 has 1 active operation (the max for basic license)
        }
        
        with pytest.raises(FreeCADException) as exc_info:
            freecad_service.execute_freecad_operation(
                db=mock_db_session,
                user_id=1,
                operation_type="modeling",
                script_content="# test script",
                parameters={},
                output_formats=['FCStd'],
                correlation_id="test-123"
            )
        
        assert exc_info.value.error_code == FreeCADErrorCode.RESOURCE_EXHAUSTED
    
    def test_health_check_freecad_not_found(self, freecad_service):
        """Test health check when FreeCAD not found."""
        with patch.object(freecad_service, 'find_freecadcmd_path', return_value=None):
            health = freecad_service.health_check()
            
            assert health['healthy'] is False
            assert health['checks']['freecad']['available'] is False
            assert 'not found' in health['checks']['freecad']['error']
    
    def test_health_check_freecad_available(self, freecad_service):
        """Test health check when FreeCAD is available."""
        with patch.object(freecad_service, 'find_freecadcmd_path', return_value='/usr/bin/FreeCADCmd'):
            with patch.object(freecad_service, 'validate_freecad_version', return_value=(True, '1.1.0')):
                health = freecad_service.health_check()
                
                assert health['checks']['freecad']['available'] is True
                assert health['checks']['freecad']['version'] == '1.1.0'
                assert health['checks']['freecad']['version_valid'] is True
    
    def test_health_check_invalid_version(self, freecad_service):
        """Test health check with invalid FreeCAD version."""
        with patch.object(freecad_service, 'find_freecadcmd_path', return_value='/usr/bin/FreeCADCmd'):
            with patch.object(freecad_service, 'validate_freecad_version', return_value=(False, '0.20.0')):
                health = freecad_service.health_check()
                
                assert health['healthy'] is False
                assert health['checks']['freecad']['version_valid'] is False
    
    def test_managed_temp_directory_cleanup(self, freecad_service):
        """Test temporary directory is cleaned up properly."""
        temp_dir_path = None
        
        with freecad_service.managed_temp_directory() as temp_dir:
            temp_dir_path = temp_dir
            assert temp_dir.exists()
            assert temp_dir.is_dir()
        
        # Directory should be cleaned up after context manager exits
        assert not temp_dir_path.exists()
    
    def test_retry_with_exponential_backoff_success(self, freecad_service):
        """Test retry mechanism with eventual success."""
        call_count = 0
        
        def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise FreeCADException(
                    "Temporary failure",
                    FreeCADErrorCode.TEMPORARY_FAILURE
                )
            return "success"
        
        result = freecad_service.retry_with_exponential_backoff(
            operation,
            max_retries=3,
            base_delay=0.01  # Small delay for test speed
        )
        
        assert result == "success"
        assert call_count == 3
    
    def test_retry_with_exponential_backoff_permanent_failure(self, freecad_service):
        """Test retry mechanism doesn't retry permanent failures."""
        call_count = 0
        
        def operation():
            nonlocal call_count
            call_count += 1
            raise FreeCADException(
                "License restriction",
                FreeCADErrorCode.LICENSE_RESTRICTION
            )
        
        with pytest.raises(FreeCADException) as exc_info:
            freecad_service.retry_with_exponential_backoff(
                operation,
                max_retries=3
            )
        
        assert exc_info.value.error_code == FreeCADErrorCode.LICENSE_RESTRICTION
        assert call_count == 1  # Should not retry
    
    def test_turkish_error_messages(self, freecad_service):
        """Test Turkish error messages are properly set."""
        assert FreeCADErrorCode.FREECAD_NOT_FOUND in freecad_service.turkish_errors
        assert FreeCADErrorCode.MEMORY_LIMIT_EXCEEDED in freecad_service.turkish_errors
        
        # Test that messages are in Turkish
        memory_error = freecad_service.turkish_errors[FreeCADErrorCode.MEMORY_LIMIT_EXCEEDED]
        assert "bellek" in memory_error.lower() or "sınır" in memory_error.lower()
        
        timeout_error = freecad_service.turkish_errors[FreeCADErrorCode.TIMEOUT_EXCEEDED]
        assert "zaman" in timeout_error.lower() or "aşım" in timeout_error.lower()
    
    def test_get_metrics_summary(self, freecad_service):
        """Test metrics summary generation."""
        # Add some active processes
        freecad_service.active_processes = {
            'process_1': Mock(),
            'process_2': Mock()
        }
        
        metrics = freecad_service.get_metrics_summary()
        
        assert metrics['active_processes'] == 2
        assert 'circuit_breaker_state' in metrics
        assert 'circuit_breaker_failures' in metrics
        assert 'timestamp' in metrics
    
    def test_shutdown_graceful(self, freecad_service):
        """Test graceful service shutdown."""
        # Add mock active processes
        mock_monitor = Mock()
        mock_process = Mock()
        mock_process.is_running.return_value = True
        mock_monitor.process = mock_process
        
        freecad_service.active_processes = {
            'test_process': mock_monitor
        }
        
        freecad_service.shutdown()
        
        # Verify cleanup was attempted
        mock_monitor.stop_monitoring.assert_called_once()
        mock_process.terminate.assert_called_once()


class TestFreeCADIntegration:
    """Integration tests for FreeCAD service."""
    
    @pytest.mark.integration
    @patch('subprocess.Popen')
    @patch('app.services.license_service.LicenseService.get_active_license')
    def test_full_operation_execution_simulation(self, mock_get_license, mock_popen):
        """Test full operation execution simulation."""
        # Setup license mock
        license = Mock(spec=License)
        license.type = '12m'  # Enterprise license
        mock_get_license.return_value = license
        
        # Setup subprocess mock
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = 0
        mock_process.communicate.return_value = ('Success output', '')
        mock_popen.return_value = mock_process
        
        # Mock psutil for process monitoring
        with patch('psutil.Process') as mock_psutil:
            mock_psutil_instance = Mock()
            mock_psutil_instance.memory_info.return_value = Mock(rss=100*1024*1024)  # 100MB
            mock_psutil_instance.cpu_percent.return_value = 25.0
            mock_psutil_instance.is_running.return_value = True
            mock_psutil.return_value = mock_psutil_instance
            
            service = UltraEnterpriseFreeCADService()
            
            # Mock finding FreeCAD
            with patch.object(service, 'find_freecadcmd_path', return_value='/usr/bin/FreeCADCmd'):
                with patch.object(service, 'validate_freecad_version', return_value=(True, '1.1.0')):
                    # Mock temp directory and file creation
                    with patch('tempfile.mkdtemp') as mock_mkdtemp:
                        mock_temp_dir = '/tmp/freecad_test'
                        mock_mkdtemp.return_value = mock_temp_dir
                        
                        # Mock file operations
                        with patch('builtins.open', Mock()):
                            with patch('json.dump'):
                                with patch('pathlib.Path.iterdir') as mock_iterdir:
                                    # Mock output files
                                    mock_file = Mock()
                                    mock_file.is_file.return_value = True
                                    mock_file.suffix = '.fcstd'
                                    mock_file.name = 'model.fcstd'
                                    mock_iterdir.return_value = [mock_file]
                                    
                                    with patch.object(service, 'compute_file_hash', return_value='abc123'):
                                        with patch('shutil.rmtree'):
                                            # Execute operation
                                            result = service.execute_freecad_operation(
                                                db=Mock(spec=Session),
                                                user_id=1,
                                                operation_type="modeling",
                                                script_content="# Test script",
                                                parameters={'width': 10, 'height': 20},
                                                output_formats=['FCStd'],
                                                correlation_id="test-integration"
                                            )
                                            
                                            # Verify result
                                            assert result.success is True
                                            assert len(result.output_files) == 1
                                            assert 'model.fcstd' in result.sha256_hashes
                                            assert result.sha256_hashes['model.fcstd'] == 'abc123'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])