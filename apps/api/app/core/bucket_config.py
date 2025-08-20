"""
Ultra-Enterprise MinIO Bucket Configuration Module

Task 5.2: Buckets, policies, versioning, lifecycle and object lock
Provides advanced bucket management with enterprise-grade configurations:
- Versioning enabled on all buckets for data protection
- Lifecycle management with configurable retention periods
- Object lock for invoices bucket with compliance mode
- Advanced bucket policies with least-privilege access
- Presigned URL constraints and security validation
- Object tagging standards for audit trail
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Final, Any
from enum import Enum

import structlog
from minio.commonconfig import GOVERNANCE, COMPLIANCE
from minio.objectlockconfig import DAYS, YEARS
from minio.lifecycleconfig import (
    LifecycleConfig,
    Rule as LifecycleRule,
    Filter as LifecycleFilter,
    Transition,
    Expiration,
    AbortIncompleteMultipartUpload,
    NoncurrentVersionTransition,
    NoncurrentVersionExpiration,
)
from minio.objectlockconfig import ObjectLockConfig
from minio.versioningconfig import VersioningConfig, ENABLED as VERSIONING_ENABLED

logger = structlog.get_logger(__name__)

# Constants for bucket configuration
MAX_PRESIGNED_URL_SIZE: Final[int] = 200 * 1024 * 1024  # 200MB
PRESIGNED_URL_EXPIRY_HOURS: Final[int] = 1
MULTIPART_UPLOAD_EXPIRY_DAYS: Final[int] = 7
DEFAULT_COLD_STORAGE_DAYS: Final[int] = 30
DEFAULT_LOGS_RETENTION_DAYS: Final[int] = 90
DEFAULT_REPORTS_RETENTION_DAYS: Final[int] = 365
DEFAULT_INVOICE_RETENTION_YEARS: Final[int] = 7

# Allowed content types for security
ALLOWED_CONTENT_TYPES: Final[Dict[str, List[str]]] = {
    "artefacts": [
        "application/step",
        "application/sla",
        "model/gltf+json",
        "model/gltf-binary",
        "application/json",
        "text/plain",
        "application/zip",
        "application/x-tar",
        "application/gzip",
    ],
    "reports": [
        "application/pdf",
        "text/csv",
        "application/json",
        "text/plain",
    ],
    "invoices": [
        "application/pdf",
        "application/xml",
        "text/xml",
        "application/json",
    ],
    "logs": [
        "text/plain",
        "application/json",
        "text/csv",
    ],
    "temp": [
        "*",  # Temporary files can be any type
    ],
}

# Standard object tags for audit trail
STANDARD_OBJECT_TAGS: Final[List[str]] = ["job_id", "machine", "post"]


class RetentionMode(Enum):
    """Object retention modes for compliance."""
    GOVERNANCE = "GOVERNANCE"
    COMPLIANCE = "COMPLIANCE"


class StorageClass(Enum):
    """Storage classes for lifecycle transitions."""
    STANDARD = "STANDARD"
    REDUCED_REDUNDANCY = "REDUCED_REDUNDANCY"
    GLACIER = "GLACIER"
    DEEP_ARCHIVE = "DEEP_ARCHIVE"


@dataclass
class BucketLifecyclePolicy:
    """Configuration for bucket lifecycle management."""
    
    name: str
    enabled: bool = True
    prefix: Optional[str] = None
    
    # Transition rules
    transition_to_cold_days: Optional[int] = None
    transition_storage_class: StorageClass = StorageClass.GLACIER
    
    # Expiration rules
    current_version_expiry_days: Optional[int] = None
    noncurrent_version_expiry_days: Optional[int] = None
    delete_markers_expiry_days: Optional[int] = None
    
    # Multipart upload cleanup
    multipart_upload_expiry_days: int = MULTIPART_UPLOAD_EXPIRY_DAYS


@dataclass
class BucketPolicy:
    """Bucket policy configuration for security."""
    
    bucket_name: str
    
    # Access control
    deny_list_bucket_public: bool = True
    allow_service_account_prefixes: List[str] = field(default_factory=list)
    allowed_operations: List[str] = field(default_factory=lambda: ["PUT", "GET", "HEAD"])
    deny_delete_objects: bool = False
    
    # IP restrictions (optional)
    allowed_source_ips: List[str] = field(default_factory=list)
    denied_source_ips: List[str] = field(default_factory=list)
    
    def generate_policy_json(self, service_account_arn: str = "*") -> str:
        """Generate bucket policy JSON."""
        statements = []
        
        # Deny public ListBucket access
        if self.deny_list_bucket_public:
            statements.append({
                "Sid": "DenyPublicListBucket",
                "Effect": "Deny",
                "Principal": "*",
                "Action": [
                    "s3:ListBucket",
                    "s3:ListBucketVersions",
                    "s3:ListBucketMultipartUploads"
                ],
                "Resource": f"arn:aws:s3:::{self.bucket_name}",
                "Condition": {
                    "StringNotEquals": {
                        "aws:PrincipalArn": service_account_arn
                    }
                }
            })
        
        # Service account restricted access
        if self.allow_service_account_prefixes:
            for prefix in self.allow_service_account_prefixes:
                statements.append({
                    "Sid": f"ServiceAccountAccess_{prefix.replace('/', '_')}",
                    "Effect": "Allow",
                    "Principal": {"AWS": service_account_arn},
                    "Action": [f"s3:{op}Object" for op in self.allowed_operations],
                    "Resource": f"arn:aws:s3:::{self.bucket_name}/{prefix}*"
                })
        
        # Deny delete operations if configured
        if self.deny_delete_objects:
            statements.append({
                "Sid": "DenyDeleteObjects",
                "Effect": "Deny",
                "Principal": "*",
                "Action": [
                    "s3:DeleteObject",
                    "s3:DeleteObjectVersion"
                ],
                "Resource": f"arn:aws:s3:::{self.bucket_name}/*"
            })
        
        # IP restrictions
        if self.allowed_source_ips:
            statements.append({
                "Sid": "AllowOnlySpecifiedIPs",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [
                    f"arn:aws:s3:::{self.bucket_name}",
                    f"arn:aws:s3:::{self.bucket_name}/*"
                ],
                "Condition": {
                    "IpAddress": {
                        "aws:SourceIp": self.allowed_source_ips
                    }
                }
            })
        
        policy = {
            "Version": "2012-10-17",
            "Statement": statements
        }
        
        return json.dumps(policy, indent=2)


@dataclass
class BucketConfiguration:
    """Complete bucket configuration including all enterprise features."""
    
    name: str
    
    # Basic settings
    versioning_enabled: bool = True
    
    # Object lock settings (for compliance)
    object_lock_enabled: bool = False
    object_lock_mode: RetentionMode = RetentionMode.COMPLIANCE
    object_lock_retention_years: int = DEFAULT_INVOICE_RETENTION_YEARS
    
    # Lifecycle policies
    lifecycle_policies: List[BucketLifecyclePolicy] = field(default_factory=list)
    
    # Bucket policy
    bucket_policy: Optional[BucketPolicy] = None
    
    # Content type restrictions
    allowed_content_types: List[str] = field(default_factory=lambda: ["*"])
    
    # Presigned URL constraints
    max_presigned_size_mb: int = MAX_PRESIGNED_URL_SIZE // (1024 * 1024)
    presigned_expiry_hours: int = PRESIGNED_URL_EXPIRY_HOURS
    
    def get_versioning_config(self) -> VersioningConfig:
        """Get versioning configuration for this bucket."""
        if self.versioning_enabled:
            return VersioningConfig(VERSIONING_ENABLED)
        return VersioningConfig()
    
    def get_object_lock_config(self) -> Optional[ObjectLockConfig]:
        """Get object lock configuration if enabled."""
        if not self.object_lock_enabled:
            return None
        
        mode = COMPLIANCE if self.object_lock_mode == RetentionMode.COMPLIANCE else GOVERNANCE
        return ObjectLockConfig(mode, self.object_lock_retention_years, YEARS)
    
    def get_lifecycle_config(self) -> Optional[LifecycleConfig]:
        """Get lifecycle configuration from policies."""
        if not self.lifecycle_policies:
            return None
        
        
        rules = []
        for policy in self.lifecycle_policies:
            if not policy.enabled:
                continue
            
            # Create rule filter
            rule_filter = None
            if policy.prefix:
                rule_filter = LifecycleFilter(prefix=policy.prefix)
            
            # Create transitions for non-current versions
            noncurrent_transition = None
            if policy.transition_to_cold_days:
                noncurrent_transition = NoncurrentVersionTransition(
                    days=policy.transition_to_cold_days,
                    storage_class=policy.transition_storage_class.value
                )
            
            # Create expiration for current versions
            expiration = None
            if policy.current_version_expiry_days:
                expiration = Expiration(days=policy.current_version_expiry_days)
            
            # Create expiration for non-current versions
            noncurrent_expiration = None
            if policy.noncurrent_version_expiry_days:
                noncurrent_expiration = NoncurrentVersionExpiration(
                    noncurrent_days=policy.noncurrent_version_expiry_days
                )
            
            # Create multipart upload expiration
            multipart_expiration = AbortIncompleteMultipartUpload(
                days_after_initiation=policy.multipart_upload_expiry_days
            )
            
            rule = LifecycleRule(
                status="Enabled",
                rule_filter=rule_filter,
                rule_id=policy.name,
                expiration=expiration,
                abort_incomplete_multipart_upload=multipart_expiration,
                noncurrent_version_transition=noncurrent_transition,
                noncurrent_version_expiration=noncurrent_expiration
            )
            
            rules.append(rule)
        
        return LifecycleConfig(rules) if rules else None


class BucketConfigFactory:
    """Factory for creating enterprise bucket configurations."""
    
    @classmethod
    def from_environment(cls) -> Dict[str, BucketConfiguration]:
        """Create bucket configurations from environment variables."""
        
        # Environment variables for configuration
        cold_storage_days = int(os.getenv("LIFECYCLE_COLD_STORAGE_DAYS", str(DEFAULT_COLD_STORAGE_DAYS)))
        logs_retention_days = int(os.getenv("LOGS_RETENTION_DAYS", str(DEFAULT_LOGS_RETENTION_DAYS)))
        reports_retention_days = int(os.getenv("REPORTS_RETENTION_DAYS", str(DEFAULT_REPORTS_RETENTION_DAYS)))
        invoice_retention_years = int(os.getenv("INVOICE_RETENTION_YEARS", str(DEFAULT_INVOICE_RETENTION_YEARS)))
        multipart_cleanup_days = int(os.getenv("MULTIPART_CLEANUP_DAYS", str(MULTIPART_UPLOAD_EXPIRY_DAYS)))
        
        # Service account configuration
        service_account_arn = os.getenv("MINIO_SERVICE_ACCOUNT_ARN", "arn:aws:iam:::user/freecad-service")
        
        bucket_configs = {}
        
        # Artefacts bucket - versioned, long-term retention per policy
        artefacts_policy = BucketPolicy(
            bucket_name="artefacts",
            allow_service_account_prefixes=["models/", "gcode/", "simulations/"],
            allowed_operations=["PUT", "GET", "HEAD"]
        )
        
        bucket_configs["artefacts"] = BucketConfiguration(
            name="artefacts",
            versioning_enabled=True,
            object_lock_enabled=False,  # Not needed for artefacts
            lifecycle_policies=[
                BucketLifecyclePolicy(
                    name="ArtefactsLifecycle",
                    transition_to_cold_days=cold_storage_days,
                    multipart_upload_expiry_days=multipart_cleanup_days
                )
            ],
            bucket_policy=artefacts_policy,
            allowed_content_types=ALLOWED_CONTENT_TYPES["artefacts"]
        )
        
        # Logs bucket - versioned, automatic cleanup after retention period
        logs_policy = BucketPolicy(
            bucket_name="logs",
            allow_service_account_prefixes=["application/", "audit/", "system/"],
            allowed_operations=["PUT", "GET", "HEAD"]
        )
        
        bucket_configs["logs"] = BucketConfiguration(
            name="logs",
            versioning_enabled=True,
            object_lock_enabled=False,
            lifecycle_policies=[
                BucketLifecyclePolicy(
                    name="LogsLifecycle",
                    transition_to_cold_days=cold_storage_days,
                    current_version_expiry_days=logs_retention_days,
                    noncurrent_version_expiry_days=cold_storage_days,
                    multipart_upload_expiry_days=multipart_cleanup_days
                )
            ],
            bucket_policy=logs_policy,
            allowed_content_types=ALLOWED_CONTENT_TYPES["logs"]
        )
        
        # Reports bucket - versioned, retention after period
        reports_policy = BucketPolicy(
            bucket_name="reports",
            allow_service_account_prefixes=["analysis/", "financial/", "performance/"],
            allowed_operations=["PUT", "GET", "HEAD"]
        )
        
        bucket_configs["reports"] = BucketConfiguration(
            name="reports",
            versioning_enabled=True,
            object_lock_enabled=False,
            lifecycle_policies=[
                BucketLifecyclePolicy(
                    name="ReportsLifecycle",
                    transition_to_cold_days=cold_storage_days,
                    current_version_expiry_days=reports_retention_days,
                    noncurrent_version_expiry_days=cold_storage_days,
                    multipart_upload_expiry_days=multipart_cleanup_days
                )
            ],
            bucket_policy=reports_policy,
            allowed_content_types=ALLOWED_CONTENT_TYPES["reports"]
        )
        
        # Invoices bucket - versioned, object lock for compliance, no deletion
        invoices_policy = BucketPolicy(
            bucket_name="invoices",
            allow_service_account_prefixes=["generated/", "archived/"],
            allowed_operations=["PUT", "GET", "HEAD"],  # No DELETE
            deny_delete_objects=True  # Compliance requirement
        )
        
        bucket_configs["invoices"] = BucketConfiguration(
            name="invoices",
            versioning_enabled=True,
            object_lock_enabled=True,  # Compliance mode
            object_lock_mode=RetentionMode.COMPLIANCE,
            object_lock_retention_years=invoice_retention_years,
            lifecycle_policies=[
                BucketLifecyclePolicy(
                    name="InvoicesLifecycle",
                    transition_to_cold_days=cold_storage_days,
                    # No expiration for invoices - retain indefinitely per compliance
                    multipart_upload_expiry_days=multipart_cleanup_days
                )
            ],
            bucket_policy=invoices_policy,
            allowed_content_types=ALLOWED_CONTENT_TYPES["invoices"]
        )
        
        # Temp bucket - versioned, short-term retention
        temp_policy = BucketPolicy(
            bucket_name="temp",
            allow_service_account_prefixes=["uploads/", "processing/"],
            allowed_operations=["PUT", "GET", "HEAD", "DELETE"]  # Allow delete for temp files
        )
        
        bucket_configs["temp"] = BucketConfiguration(
            name="temp",
            versioning_enabled=True,
            object_lock_enabled=False,
            lifecycle_policies=[
                BucketLifecyclePolicy(
                    name="TempLifecycle",
                    current_version_expiry_days=7,  # Clean temp files after 7 days
                    noncurrent_version_expiry_days=1,  # Clean old versions quickly
                    multipart_upload_expiry_days=1  # Clean multipart uploads daily
                )
            ],
            bucket_policy=temp_policy,
            allowed_content_types=ALLOWED_CONTENT_TYPES["temp"]
        )
        
        logger.info(
            "Bucket configurations created from environment",
            cold_storage_days=cold_storage_days,
            logs_retention_days=logs_retention_days,
            reports_retention_days=reports_retention_days,
            invoice_retention_years=invoice_retention_years,
            multipart_cleanup_days=multipart_cleanup_days
        )
        
        return bucket_configs
    
    @classmethod
    def validate_presigned_constraints(
        cls,
        content_length: int,
        content_type: str,
        bucket_config: BucketConfiguration,
        tags: Optional[Dict[str, str]] = None
    ) -> tuple[bool, str]:
        """
        Validate presigned URL constraints.
        
        Args:
            content_length: Size of content in bytes
            content_type: MIME content type
            bucket_config: Bucket configuration
            tags: Optional object tags
            
        Returns:
            tuple: (is_valid, error_message)
        """
        # Check content length
        max_size_bytes = bucket_config.max_presigned_size_mb * 1024 * 1024
        if content_length > max_size_bytes:
            return False, (
                f"Dosya boyutu çok büyük: {content_length} bayt "
                f"(maksimum: {max_size_bytes} bayt)"
            )
        
        # Check content type
        allowed_types = bucket_config.allowed_content_types
        if "*" not in allowed_types:
            if content_type not in allowed_types:
                # Check for wildcard matches (e.g., image/*, application/*)
                type_match = False
                base_type = content_type.split('/')[0]
                for allowed in allowed_types:
                    if allowed.endswith('*') and content_type.startswith(allowed[:-1]):
                        type_match = True
                        break
                    elif allowed == f"{base_type}/*":
                        type_match = True
                        break
                
                if not type_match:
                    return False, (
                        f"Desteklenmeyen dosya türü: {content_type}. "
                        f"İzin verilen türler: {', '.join(allowed_types)}"
                    )
        
        # Validate standard object tags if provided
        if tags:
            for tag_key in STANDARD_OBJECT_TAGS:
                if tag_key not in tags:
                    logger.warning(
                        "Önerilen nesne etiketi eksik",
                        missing_tag=tag_key,
                        provided_tags=list(tags.keys())
                    )
        
        return True, ""


__all__ = [
    "BucketConfiguration",
    "BucketLifecyclePolicy", 
    "BucketPolicy",
    "BucketConfigFactory",
    "RetentionMode",
    "StorageClass",
    "STANDARD_OBJECT_TAGS",
    "ALLOWED_CONTENT_TYPES",
    "MAX_PRESIGNED_URL_SIZE",
]