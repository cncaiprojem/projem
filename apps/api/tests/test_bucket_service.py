"""
Comprehensive Tests for MinIO Bucket Service

Task 5.2: Test bucket policies, versioning, lifecycle, and object lock
Tests enterprise-grade bucket management including:
- Bucket configuration and creation
- Versioning setup and validation
- Lifecycle policy application
- Object lock configuration for compliance
- Bucket policy enforcement
- Presigned URL constraint validation
"""

import json
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from minio.error import S3Error
from minio.commonconfig import GOVERNANCE, COMPLIANCE
from minio.objectlockconfig import DAYS, YEARS
from minio.lifecycleconfig import LifecycleConfig, Rule as LifecycleRule
from minio.objectlockconfig import ObjectLockConfig
from minio.versioningconfig import VersioningConfig, ENABLED as VERSIONING_ENABLED

from app.services.bucket_service import BucketService, BucketServiceError
from app.core.bucket_config import (
    BucketConfiguration,
    BucketConfigFactory,
    BucketLifecyclePolicy,
    BucketPolicy,
    RetentionMode,
    StorageClass,
    STANDARD_OBJECT_TAGS,
    MAX_PRESIGNED_URL_SIZE,
)
from app.core.minio_config import StorageErrorCode


class TestBucketConfiguration:
    """Test bucket configuration classes."""
    
    def test_bucket_configuration_defaults(self):
        """Test default bucket configuration."""
        config = BucketConfiguration(name="test-bucket")
        
        assert config.name == "test-bucket"
        assert config.versioning_enabled is True
        assert config.object_lock_enabled is False
        assert config.object_lock_mode == RetentionMode.COMPLIANCE
        assert config.object_lock_retention_years == 7
        assert config.lifecycle_policies == []
        assert config.bucket_policy is None
        assert config.allowed_content_types == ["*"]
        assert config.max_presigned_size_mb == 200
        assert config.presigned_expiry_hours == 1
    
    def test_get_versioning_config(self):
        """Test versioning configuration generation."""
        # Enabled versioning
        config = BucketConfiguration(name="test", versioning_enabled=True)
        versioning_config = config.get_versioning_config()
        assert isinstance(versioning_config, VersioningConfig)
        
        # Disabled versioning
        config = BucketConfiguration(name="test", versioning_enabled=False)
        versioning_config = config.get_versioning_config()
        assert isinstance(versioning_config, VersioningConfig)
    
    def test_get_object_lock_config(self):
        """Test object lock configuration generation."""
        # Object lock disabled
        config = BucketConfiguration(name="test", object_lock_enabled=False)
        assert config.get_object_lock_config() is None
        
        # Object lock enabled with compliance mode
        config = BucketConfiguration(
            name="test",
            object_lock_enabled=True,
            object_lock_mode=RetentionMode.COMPLIANCE,
            object_lock_retention_years=5
        )
        lock_config = config.get_object_lock_config()
        assert isinstance(lock_config, ObjectLockConfig)
        assert lock_config.mode == COMPLIANCE
        # ObjectLockConfig.duration is a tuple (value, unit)
        assert lock_config.duration[0] == 5
        assert lock_config.duration[1] == "Years"
    
    def test_get_lifecycle_config(self):
        """Test lifecycle configuration generation."""
        # No lifecycle policies
        config = BucketConfiguration(name="test")
        assert config.get_lifecycle_config() is None
        
        # With lifecycle policies
        lifecycle_policy = BucketLifecyclePolicy(
            name="TestPolicy",
            enabled=True,
            prefix="logs/",
            transition_to_cold_days=30,
            current_version_expiry_days=90
        )
        
        config = BucketConfiguration(
            name="test",
            lifecycle_policies=[lifecycle_policy]
        )
        
        lifecycle_config = config.get_lifecycle_config()
        assert isinstance(lifecycle_config, LifecycleConfig)
        assert len(lifecycle_config.rules) == 1
        
        rule = lifecycle_config.rules[0]
        assert rule.rule_id == "TestPolicy"
        assert rule.status == "Enabled"


class TestBucketPolicy:
    """Test bucket policy generation."""
    
    def test_generate_policy_json_basic(self):
        """Test basic policy JSON generation."""
        policy = BucketPolicy(
            bucket_name="test-bucket",
            deny_list_bucket_public=True,
            allow_service_account_prefixes=["data/", "logs/"],
            allowed_operations=["PUT", "GET", "HEAD"]
        )
        
        policy_json = policy.generate_policy_json("arn:aws:iam:::user/service")
        policy_dict = json.loads(policy_json)
        
        assert policy_dict["Version"] == "2012-10-17"
        assert "Statement" in policy_dict
        assert len(policy_dict["Statement"]) >= 2  # At least deny public + service account
        
        # Check for deny public statement
        deny_statements = [s for s in policy_dict["Statement"] if s["Effect"] == "Deny"]
        assert len(deny_statements) >= 1
        
        # Check for allow service account statements
        allow_statements = [s for s in policy_dict["Statement"] if s["Effect"] == "Allow"]
        assert len(allow_statements) >= 2  # One for each prefix
    
    def test_generate_policy_json_with_delete_deny(self):
        """Test policy with delete operations denied."""
        policy = BucketPolicy(
            bucket_name="invoices",
            deny_delete_objects=True
        )
        
        policy_json = policy.generate_policy_json()
        policy_dict = json.loads(policy_json)
        
        # Find delete deny statement
        delete_deny = None
        for statement in policy_dict["Statement"]:
            if (statement["Effect"] == "Deny" and 
                "s3:DeleteObject" in statement.get("Action", [])):
                delete_deny = statement
                break
        
        assert delete_deny is not None
        assert "s3:DeleteObject" in delete_deny["Action"]
        assert "s3:DeleteObjectVersion" in delete_deny["Action"]


class TestBucketConfigFactory:
    """Test bucket configuration factory."""
    
    @patch.dict(os.environ, {
        "LIFECYCLE_COLD_STORAGE_DAYS": "30",
        "LOGS_RETENTION_DAYS": "90", 
        "REPORTS_RETENTION_DAYS": "365",
        "INVOICE_RETENTION_YEARS": "7",
        "MULTIPART_CLEANUP_DAYS": "7"
    })
    def test_from_environment(self):
        """Test configuration creation from environment variables."""
        configs = BucketConfigFactory.from_environment()
        
        # Check all expected buckets are configured
        expected_buckets = ["artefacts", "logs", "reports", "invoices", "temp"]
        assert set(configs.keys()) == set(expected_buckets)
        
        # Check invoices bucket has object lock
        invoices_config = configs["invoices"]
        assert invoices_config.object_lock_enabled is True
        assert invoices_config.object_lock_mode == RetentionMode.COMPLIANCE
        assert invoices_config.object_lock_retention_years == 7
        
        # Check invoices bucket denies delete
        assert invoices_config.bucket_policy.deny_delete_objects is True
        
        # Check all buckets have versioning enabled
        for config in configs.values():
            assert config.versioning_enabled is True
        
        # Check lifecycle policies exist
        for bucket_name, config in configs.items():
            assert len(config.lifecycle_policies) >= 1
    
    def test_validate_presigned_constraints_size_limit(self):
        """Test presigned URL size constraint validation."""
        config = BucketConfiguration(
            name="test",
            max_presigned_size_mb=200
        )
        
        # File within limit
        valid, error = BucketConfigFactory.validate_presigned_constraints(
            content_length=100 * 1024 * 1024,  # 100MB
            content_type="application/json",
            bucket_config=config
        )
        assert valid is True
        assert error == ""
        
        # File exceeds limit
        valid, error = BucketConfigFactory.validate_presigned_constraints(
            content_length=250 * 1024 * 1024,  # 250MB
            content_type="application/json",
            bucket_config=config
        )
        assert valid is False
        assert "çok büyük" in error.lower()
    
    def test_validate_presigned_constraints_content_type(self):
        """Test presigned URL content type constraint validation."""
        config = BucketConfiguration(
            name="test",
            allowed_content_types=["application/json", "text/plain", "image/*"]
        )
        
        # Allowed content type
        valid, error = BucketConfigFactory.validate_presigned_constraints(
            content_length=1024,
            content_type="application/json",
            bucket_config=config
        )
        assert valid is True
        
        # Wildcard match
        valid, error = BucketConfigFactory.validate_presigned_constraints(
            content_length=1024,
            content_type="image/png",
            bucket_config=config
        )
        assert valid is True
        
        # Disallowed content type
        valid, error = BucketConfigFactory.validate_presigned_constraints(
            content_length=1024,
            content_type="video/mp4",
            bucket_config=config
        )
        assert valid is False
        assert "desteklenmeyen" in error.lower()


class TestBucketService:
    """Test bucket service operations."""
    
    @pytest.fixture
    def mock_client(self):
        """Create mock MinIO client."""
        client = Mock()
        client.bucket_exists.return_value = True
        client.list_buckets.return_value = []
        client.get_bucket_versioning.return_value = Mock(status="Enabled")
        client.get_bucket_lifecycle.return_value = None
        client.get_object_lock_config.return_value = None
        client.get_bucket_policy.return_value = None
        return client
    
    @pytest.fixture
    def mock_config(self):
        """Create mock MinIO config."""
        config = Mock()
        config.bucket_artefacts = "artefacts"
        config.bucket_logs = "logs"
        config.bucket_reports = "reports"
        config.bucket_invoices = "invoices"
        config.bucket_temp = "temp"
        return config
    
    def test_bucket_service_initialization(self, mock_client, mock_config):
        """Test bucket service initialization."""
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            assert service.client == mock_client
            assert service.config == mock_config
            assert isinstance(service._initialization_time, datetime)
    
    def test_ensure_bucket_exists_new_bucket(self, mock_client, mock_config):
        """Test creating a new bucket."""
        mock_client.bucket_exists.return_value = False
        
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            bucket_config = BucketConfiguration(name="test-bucket", object_lock_enabled=True)
            service._ensure_bucket_exists("test-bucket", bucket_config)
            
            mock_client.make_bucket.assert_called_once_with("test-bucket", object_lock=True)
    
    def test_ensure_bucket_exists_existing_bucket(self, mock_client, mock_config):
        """Test handling existing bucket."""
        mock_client.bucket_exists.return_value = True
        
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            bucket_config = BucketConfiguration(name="test-bucket")
            service._ensure_bucket_exists("test-bucket", bucket_config)
            
            mock_client.make_bucket.assert_not_called()
    
    def test_configure_bucket_versioning(self, mock_client, mock_config):
        """Test bucket versioning configuration."""
        # Mock current versioning status as disabled
        mock_client.get_bucket_versioning.return_value = Mock(status="Suspended")
        
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            bucket_config = BucketConfiguration(name="test-bucket", versioning_enabled=True)
            service._configure_bucket_versioning("test-bucket", bucket_config)
            
            mock_client.set_bucket_versioning.assert_called_once()
            
            # Check the versioning config argument
            args, kwargs = mock_client.set_bucket_versioning.call_args
            assert args[0] == "test-bucket"
            assert isinstance(args[1], VersioningConfig)
    
    def test_configure_bucket_lifecycle(self, mock_client, mock_config):
        """Test bucket lifecycle configuration."""
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            lifecycle_policy = BucketLifecyclePolicy(
                name="TestPolicy",
                enabled=True,
                transition_to_cold_days=30
            )
            
            bucket_config = BucketConfiguration(
                name="test-bucket",
                lifecycle_policies=[lifecycle_policy]
            )
            
            service._configure_bucket_lifecycle("test-bucket", bucket_config)
            
            mock_client.set_bucket_lifecycle.assert_called_once()
            
            # Check the lifecycle config argument
            args, kwargs = mock_client.set_bucket_lifecycle.call_args
            assert args[0] == "test-bucket"
            assert isinstance(args[1], LifecycleConfig)
    
    def test_configure_object_lock(self, mock_client, mock_config):
        """Test object lock configuration."""
        # Mock that object lock is not currently configured
        mock_client.get_object_lock_config.side_effect = S3Error(
            code="ObjectLockConfigurationNotFoundError",
            message="Object lock not configured",
            resource="test-bucket",
            request_id="test",
            host_id="test",
            response=Mock()
        )
        
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            bucket_config = BucketConfiguration(
                name="test-bucket",
                object_lock_enabled=True,
                object_lock_mode=RetentionMode.COMPLIANCE,
                object_lock_retention_years=7
            )
            
            service._configure_object_lock("test-bucket", bucket_config)
            
            mock_client.set_object_lock_config.assert_called_once()
            
            # Check the object lock config argument
            args, kwargs = mock_client.set_object_lock_config.call_args
            assert args[0] == "test-bucket"
            assert isinstance(args[1], ObjectLockConfig)
    
    def test_apply_bucket_policy(self, mock_client, mock_config):
        """Test bucket policy application."""
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            bucket_policy = BucketPolicy(
                bucket_name="test-bucket",
                deny_list_bucket_public=True
            )
            
            bucket_config = BucketConfiguration(
                name="test-bucket",
                bucket_policy=bucket_policy
            )
            
            service._apply_bucket_policy("test-bucket", bucket_config)
            
            mock_client.set_bucket_policy.assert_called_once()
            
            # Check the policy argument
            args, kwargs = mock_client.set_bucket_policy.call_args
            assert args[0] == "test-bucket"
            
            # Validate JSON policy
            policy_json = args[1]
            policy_dict = json.loads(policy_json)
            assert policy_dict["Version"] == "2012-10-17"
            assert "Statement" in policy_dict
    
    def test_validate_presigned_url_constraints(self, mock_client, mock_config):
        """Test presigned URL constraint validation."""
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            test_config = BucketConfiguration(
                name="test-bucket",
                max_presigned_size_mb=200,
                allowed_content_types=["application/json"]
            )
            mock_factory.return_value = {"test-bucket": test_config}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            # Valid request
            valid, error = service.validate_presigned_url_constraints(
                bucket_name="test-bucket",
                content_length=100 * 1024 * 1024,  # 100MB
                content_type="application/json"
            )
            assert valid is True
            assert error == ""
            
            # Invalid size
            valid, error = service.validate_presigned_url_constraints(
                bucket_name="test-bucket",
                content_length=250 * 1024 * 1024,  # 250MB
                content_type="application/json"
            )
            assert valid is False
            assert "çok büyük" in error.lower()
            
            # Invalid content type
            valid, error = service.validate_presigned_url_constraints(
                bucket_name="test-bucket",
                content_length=1024,
                content_type="video/mp4"
            )
            assert valid is False
            assert "desteklenmeyen" in error.lower()
    
    def test_get_bucket_status(self, mock_client, mock_config):
        """Test bucket status retrieval."""
        # Configure mock responses
        mock_client.bucket_exists.return_value = True
        mock_client.get_bucket_versioning.return_value = Mock(status="Enabled")
        mock_client.get_bucket_lifecycle.return_value = Mock(rules=[Mock(), Mock()])
        mock_client.get_object_lock_config.return_value = Mock(mode="COMPLIANCE", duration=7)
        mock_client.get_bucket_policy.return_value = "{}"
        
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            test_config = BucketConfiguration(name="test-bucket")
            mock_factory.return_value = {"test-bucket": test_config}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            status = service.get_bucket_status("test-bucket")
            
            assert status["bucket_name"] == "test-bucket"
            assert status["exists"] is True
            assert status["versioning"]["enabled"] is True
            assert status["versioning"]["status"] == "Enabled"
            assert status["lifecycle"]["configured"] is True
            assert status["lifecycle"]["rules_count"] == 2
            assert status["object_lock"]["enabled"] is True
            assert status["object_lock"]["mode"] == "COMPLIANCE"
            assert status["policy"]["configured"] is True
    
    def test_error_handling_s3_error(self, mock_client, mock_config):
        """Test S3 error handling."""
        mock_client.bucket_exists.side_effect = S3Error(
            code="AccessDenied",
            message="Access denied",
            resource="test-bucket",
            request_id="test",
            host_id="test",
            response=Mock()
        )
        
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            mock_factory.return_value = {"test": BucketConfiguration(name="test")}
            
            service = BucketService(client=mock_client, config=mock_config)
            
            bucket_config = BucketConfiguration(name="test-bucket")
            
            with pytest.raises(BucketServiceError) as exc_info:
                service._ensure_bucket_exists("test-bucket", bucket_config)
            
            assert exc_info.value.code == StorageErrorCode.STORAGE_OPERATION_FAILED
            assert "access denied" in exc_info.value.turkish_message.lower() or \
                   "erişimi reddedildi" in exc_info.value.turkish_message.lower()


class TestIntegration:
    """Integration tests for bucket service."""
    
    @pytest.mark.integration
    def test_full_bucket_configuration_flow(self, mock_client, mock_config):
        """Test complete bucket configuration flow."""
        # Configure mocks for successful flow
        mock_client.bucket_exists.return_value = False
        mock_client.get_bucket_versioning.return_value = Mock(status="Suspended")
        mock_client.get_object_lock_config.side_effect = S3Error(
            code="ObjectLockConfigurationNotFoundError",
            message="Not configured",
            resource="test",
            request_id="test",
            host_id="test",
            response=Mock()
        )
        mock_client.get_bucket_lifecycle.side_effect = S3Error(
            code="NoSuchLifecycleConfiguration",
            message="Not configured",
            resource="test",
            request_id="test",
            host_id="test",
            response=Mock()
        )
        mock_client.get_bucket_policy.side_effect = S3Error(
            code="NoSuchBucketPolicy",
            message="Not configured",
            resource="test",
            request_id="test",
            host_id="test",
            response=Mock()
        )
        
        with patch('app.services.bucket_service.get_minio_client', return_value=mock_client), \
             patch('app.services.bucket_service.get_minio_config', return_value=mock_config), \
             patch('app.services.bucket_service.BucketConfigFactory.from_environment') as mock_factory:
            
            # Create test configuration
            test_config = BucketConfiguration(
                name="test-bucket",
                versioning_enabled=True,
                object_lock_enabled=True,
                object_lock_mode=RetentionMode.COMPLIANCE,
                object_lock_retention_years=7,
                lifecycle_policies=[
                    BucketLifecyclePolicy(
                        name="TestPolicy",
                        enabled=True,
                        transition_to_cold_days=30
                    )
                ],
                bucket_policy=BucketPolicy(
                    bucket_name="test-bucket",
                    deny_list_bucket_public=True
                )
            )
            
            mock_factory.return_value = {"test-bucket": test_config}
            
            service = BucketService(client=mock_client, config=mock_config)
            results = service.ensure_all_buckets_configured()
            
            # Verify all operations were called
            mock_client.make_bucket.assert_called()
            mock_client.set_bucket_versioning.assert_called()
            mock_client.set_bucket_lifecycle.assert_called()
            mock_client.set_object_lock_config.assert_called()
            mock_client.set_bucket_policy.assert_called()
            
            # Verify results
            assert results["test-bucket"] is True


if __name__ == "__main__":
    pytest.main([__file__])