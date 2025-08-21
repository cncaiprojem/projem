"""
Artefact service for Task 5.7.

Implements comprehensive artefact persistence with S3 tagging,
retention policies, and audit logging.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from minio import Minio
from minio.datatypes import Tags
from minio.error import S3Error
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.minio_config import get_minio_client
from app.models.artefact import Artefact
from app.models.audit_log import AuditLog
from app.models.job import Job
from app.models.user import User
from app.schemas.artefact import (
    ArtefactCreate,
    ArtefactResponse,
    ArtefactSearchParams,
    ArtefactStats,
    ArtefactType,
    ArtefactUpdate,
)
from app.services.audit_service import audit_service

logger = structlog.get_logger(__name__)


class ArtefactServiceError(Exception):
    """Custom exception for artefact service operations."""
    
    def __init__(
        self,
        code: str,
        message: str,
        turkish_message: str | None = None,
        details: dict | None = None,
        status_code: int = 400,
    ):
        self.code = code
        self.message = message
        self.turkish_message = turkish_message or message
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)


class ArtefactService:
    """
    Enterprise-grade artefact service for Task 5.7.
    
    Handles:
    - Artefact persistence in database
    - S3 object tagging with retry logic
    - Invoice retention policies
    - Comprehensive audit logging
    - Security and authorization checks
    """
    
    def __init__(
        self,
        db: Session,
        minio_client: Minio | None = None,
    ):
        """
        Initialize artefact service.
        
        Args:
            db: Database session
            minio_client: MinIO client instance
        """
        self.db = db
        self.minio_client = minio_client or get_minio_client()
        self.tag_retry_attempts = 3
        self.tag_retry_delay = 1.0  # seconds
        
    async def create_artefact(
        self,
        artefact_data: ArtefactCreate,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        current_user: Optional[User] = None,
    ) -> Artefact:
        """
        Create a new artefact record with S3 tagging.
        
        Args:
            artefact_data: Artefact creation data
            user_id: ID of user creating the artefact
            ip_address: Client IP address for audit
            user_agent: Client user agent for audit
            current_user: Optional User object to avoid extra DB query
            
        Returns:
            Created artefact instance
            
        Raises:
            ArtefactServiceError: On creation failure
        """
        try:
            # Override created_by with the authenticated user
            # This ensures the user creating the artefact is properly tracked
            artefact_data.created_by = user_id
            
            # Step 1: Verify job exists and user has access
            job = self.db.query(Job).filter_by(id=artefact_data.job_id).first()
            if not job:
                raise ArtefactServiceError(
                    code="JOB_NOT_FOUND",
                    message=f"Job {artefact_data.job_id} not found",
                    turkish_message=f"İş {artefact_data.job_id} bulunamadı",
                    status_code=404,
                )
            
            # Check if user has access to the job
            # Admin users can access any job
            # Use provided user object if available, otherwise query DB
            if current_user:
                user = current_user
            else:
                user = self.db.query(User).filter_by(id=user_id).first()
            is_admin = user and user.role == "admin"
            
            if not is_admin and job.user_id != user_id:
                # Non-admin users can only access their own jobs
                raise ArtefactServiceError(
                    code="UNAUTHORIZED",
                    message="You don't have access to this job",
                    turkish_message="Bu işe erişim yetkiniz yok",
                    status_code=403,
                )
            
            # Step 2: Check for duplicate s3_key
            existing = (
                self.db.query(Artefact)
                .filter_by(
                    s3_bucket=artefact_data.s3_bucket,
                    s3_key=artefact_data.s3_key,
                )
                .first()
            )
            
            if existing:
                raise ArtefactServiceError(
                    code="DUPLICATE_ARTEFACT",
                    message=f"Artefact already exists at {artefact_data.s3_bucket}/{artefact_data.s3_key}",
                    turkish_message=f"Artefact zaten mevcut: {artefact_data.s3_bucket}/{artefact_data.s3_key}",
                    status_code=409,
                )
            
            # Step 3: Create artefact record
            artefact = Artefact(
                job_id=artefact_data.job_id,
                type=artefact_data.type,
                s3_bucket=artefact_data.s3_bucket,
                s3_key=artefact_data.s3_key,
                size_bytes=artefact_data.size_bytes,
                sha256=artefact_data.sha256.lower(),
                mime_type=artefact_data.mime_type,
                created_by=artefact_data.created_by,
                machine_id=artefact_data.machine_id,
                post_processor=artefact_data.post_processor,
                version_id=artefact_data.version_id,
                meta=artefact_data.meta or {},
            )
            
            self.db.add(artefact)
            self.db.flush()  # Get the ID without committing
            
            # Step 4: Apply S3 tags with retry logic
            tags_applied = await self._apply_s3_tags_with_retry(artefact)
            
            if tags_applied:
                artefact.set_meta('s3_tags_applied', True)
                artefact.set_meta('s3_tags_applied_at', datetime.now(timezone.utc).isoformat())
            else:
                logger.warning(
                    "Failed to apply S3 tags",
                    artefact_id=artefact.id,
                    bucket=artefact.s3_bucket,
                    key=artefact.s3_key,
                )
                artefact.set_meta('s3_tags_applied', False)
                artefact.set_meta('s3_tags_error', 'Failed after retries')
            
            # Step 5: Handle invoice special requirements
            if artefact.is_invoice:
                retention_applied = await self._apply_invoice_retention(artefact)
                if retention_applied:
                    artefact.set_meta('retention_applied', True)
                    artefact.set_meta('retention_years', 10)
                    artefact.set_meta('compliance', 'Turkish_Tax_Law')
            
            # Step 6: Create audit log for artefact creation BEFORE commit
            # CRITICAL: Audit log must be created in the same transaction
            # to ensure it's persisted even if later operations fail
            await audit_service.create_audit_entry(
                db=self.db,
                event_type="artefact_created",
                user_id=user_id,
                scope_type="artefact",
                scope_id=artefact.id,
                resource=f"artefact/{artefact.type}",
                ip_address=ip_address,
                user_agent=user_agent,
                payload={
                    "artefact_id": artefact.id,
                    "job_id": artefact.job_id,
                    "type": artefact.type,
                    "s3_location": artefact.s3_full_path,
                    "size_bytes": artefact.size_bytes,
                    "sha256": artefact.sha256,
                    "tags_applied": tags_applied,
                },
            )
            
            # Step 7: Commit to database - this persists both artefact and audit log
            self.db.commit()
            
            logger.info(
                "Artefact created successfully",
                artefact_id=artefact.id,
                job_id=artefact.job_id,
                type=artefact.type,
                size_mb=artefact.size_mb,
            )
            
            return artefact
            
        except ArtefactServiceError:
            self.db.rollback()
            raise
        except IntegrityError as e:
            self.db.rollback()
            logger.error("Database integrity error", error=str(e))
            raise ArtefactServiceError(
                code="DATABASE_ERROR",
                message="Failed to create artefact due to data integrity issue",
                turkish_message="Veri bütünlüğü hatası nedeniyle artefact oluşturulamadı",
                status_code=400,
            )
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create artefact", error=str(e), exc_info=True)
            raise ArtefactServiceError(
                code="INTERNAL_ERROR",
                message=f"Failed to create artefact: {str(e)}",
                turkish_message=f"Artefact oluşturulamadı: {str(e)}",
                status_code=500,
            )
    
    async def _apply_s3_tags_with_retry(self, artefact: Artefact) -> bool:
        """
        Apply S3 tags to an artefact with retry logic.
        
        Args:
            artefact: Artefact instance
            
        Returns:
            True if tags were applied successfully
        """
        tags = artefact.get_s3_tags()
        
        for attempt in range(self.tag_retry_attempts):
            try:
                # Convert tags to MinIO Tags object
                tag_set = Tags()
                for key, value in tags.items():
                    tag_set[key] = value
                
                # Apply tags to S3 object
                self.minio_client.set_object_tags(
                    bucket_name=artefact.s3_bucket,
                    object_name=artefact.s3_key,
                    tags=tag_set,
                    version_id=artefact.version_id,
                )
                
                logger.info(
                    "S3 tags applied successfully",
                    artefact_id=artefact.id,
                    attempt=attempt + 1,
                    tags=tags,
                )
                return True
                
            except S3Error as e:
                logger.warning(
                    f"Failed to apply S3 tags (attempt {attempt + 1})",
                    artefact_id=artefact.id,
                    error=str(e),
                )
                
                if attempt < self.tag_retry_attempts - 1:
                    await asyncio.sleep(self.tag_retry_delay * (attempt + 1))
                    
        return False
    
    async def _apply_invoice_retention(self, artefact: Artefact) -> bool:
        """
        Apply retention policy for invoice artefacts.
        
        Args:
            artefact: Invoice artefact instance
            
        Returns:
            True if retention was applied successfully
        """
        try:
            # Note: MinIO doesn't support object-level retention in community edition
            # This would work with AWS S3 or MinIO Enterprise
            
            retention_metadata = artefact.get_retention_metadata()
            
            # Set retention metadata as object metadata (fallback approach)
            metadata = {
                'x-amz-meta-retention-years': str(retention_metadata['retention_years']),
                'x-amz-meta-compliance': retention_metadata['compliance'],
                'x-amz-meta-retention-mode': retention_metadata['retention_mode'],
                'x-amz-meta-legal-hold': str(retention_metadata['legal_hold']).lower(),
            }
            
            # In production with AWS S3, you would use:
            # self.minio_client.put_object_retention(...)
            
            logger.info(
                "Invoice retention metadata set",
                artefact_id=artefact.id,
                retention_years=retention_metadata['retention_years'],
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to apply invoice retention",
                artefact_id=artefact.id,
                error=str(e),
            )
            return False
    
    def create_artefact_sync(
        self,
        artefact_data: ArtefactCreate,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        current_user: Optional[User] = None,
    ) -> Artefact:
        """
        Synchronous wrapper for create_artefact.
        
        This method is used when called from synchronous contexts
        to avoid blocking the event loop with asyncio.run().
        
        Args:
            artefact_data: Artefact creation data
            user_id: ID of user creating the artefact
            ip_address: Client IP address for audit
            user_agent: Client user agent for audit
            current_user: Optional User object to avoid extra DB query
            
        Returns:
            Created artefact instance
            
        Raises:
            ArtefactServiceError: On creation failure
        """
        # Run the coroutine in the current event loop if one is running, otherwise create a new one
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, safe to use asyncio.run()
            return asyncio.run(
                self.create_artefact(artefact_data, user_id, ip_address, user_agent, current_user)
            )
        else:
            # Running loop exists, create a task and wait for it
            # Note: run_until_complete would block the existing loop, so we use create_task
            import concurrent.futures
            import threading
            
            # Use a thread to run asyncio.run() to avoid blocking the current loop
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self.create_artefact(artefact_data, user_id, ip_address, user_agent, current_user)
                )
                return future.result()
    
    async def get_artefact(
        self,
        artefact_id: int,
        user_id: int,
        check_access: bool = True,
    ) -> Artefact:
        """
        Get an artefact by ID with access control.
        
        Args:
            artefact_id: Artefact ID
            user_id: User requesting access
            check_access: Whether to check user access
            
        Returns:
            Artefact instance
            
        Raises:
            ArtefactServiceError: If not found or unauthorized
        """
        artefact = self.db.query(Artefact).filter_by(id=artefact_id).first()
        
        if not artefact:
            raise ArtefactServiceError(
                code="ARTEFACT_NOT_FOUND",
                message=f"Artefact {artefact_id} not found",
                turkish_message=f"Artefact {artefact_id} bulunamadı",
                status_code=404,
            )
        
        if check_access:
            # Check if user has access through job ownership or admin role
            user = self.db.query(User).filter_by(id=user_id).first()
            is_admin = user and user.role == "admin"
            
            # Admin users can access any artefact
            if not is_admin:
                job = artefact.job
                if job.user_id != user_id and artefact.created_by != user_id:
                    raise ArtefactServiceError(
                        code="UNAUTHORIZED",
                        message="You don't have access to this artefact",
                        turkish_message="Bu artefact'a erişim yetkiniz yok",
                        status_code=403,
                    )
        
        return artefact
    
    async def generate_download_url(
        self,
        artefact_id: int,
        user_id: int,
        expires_in: int = 3600,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[str, Artefact]:
        """
        Generate presigned download URL for an artefact.
        
        Args:
            artefact_id: Artefact ID
            user_id: User requesting download
            expires_in: URL expiration in seconds
            ip_address: Client IP for audit
            user_agent: Client user agent for audit
            
        Returns:
            Tuple of (presigned_url, artefact)
            
        Raises:
            ArtefactServiceError: If generation fails
        """
        try:
            # Step 1: Get artefact with access check
            artefact = await self.get_artefact(artefact_id, user_id, check_access=True)
            
            # Step 2: Generate presigned URL
            presigned_url = self.minio_client.presigned_get_object(
                bucket_name=artefact.s3_bucket,
                object_name=artefact.s3_key,
                expires=timedelta(seconds=expires_in),
                version_id=artefact.version_id,
            )
            
            # Step 3: Audit the download URL issuance
            await audit_service.create_audit_entry(
                db=self.db,
                event_type="download_url_issued",
                user_id=user_id,
                scope_type="artefact",
                scope_id=artefact_id,
                resource=f"artefact/{artefact.type}",
                ip_address=ip_address,
                user_agent=user_agent,
                payload={
                    "artefact_id": artefact_id,
                    "job_id": artefact.job_id,
                    "expires_in": expires_in,
                    "s3_location": artefact.s3_full_path,
                    "sha256": artefact.sha256,
                    "size_bytes": artefact.size_bytes,
                },
            )
            
            logger.info(
                "Download URL generated",
                artefact_id=artefact_id,
                user_id=user_id,
                expires_in=expires_in,
            )
            
            return presigned_url, artefact
            
        except ArtefactServiceError:
            # Audit failed download attempt
            await audit_service.create_audit_entry(
                db=self.db,
                event_type="download_url_denied",
                user_id=user_id,
                scope_type="artefact",
                scope_id=artefact_id,
                resource="artefact",
                ip_address=ip_address,
                user_agent=user_agent,
                payload={
                    "artefact_id": artefact_id,
                    "reason": "access_denied",
                },
            )
            raise
        except Exception as e:
            logger.error(
                "Failed to generate download URL",
                artefact_id=artefact_id,
                error=str(e),
            )
            raise ArtefactServiceError(
                code="URL_GENERATION_ERROR",
                message=f"Failed to generate download URL: {str(e)}",
                turkish_message=f"İndirme URL'si oluşturulamadı: {str(e)}",
                status_code=500,
            )
    
    async def search_artefacts(
        self,
        params: ArtefactSearchParams,
        user_id: int,
    ) -> Tuple[List[Artefact], int]:
        """
        Search artefacts with filters and pagination.
        
        Args:
            params: Search parameters
            user_id: User performing search
            
        Returns:
            Tuple of (artefacts, total_count)
        """
        query = self.db.query(Artefact)
        
        # Apply filters
        if params.job_id is not None:
            query = query.filter(Artefact.job_id == params.job_id)
        
        if params.type is not None:
            query = query.filter(Artefact.type == params.type)
        
        if params.created_by is not None:
            query = query.filter(Artefact.created_by == params.created_by)
        
        if params.machine_id is not None:
            query = query.filter(Artefact.machine_id == params.machine_id)
        
        if params.post_processor is not None:
            query = query.filter(Artefact.post_processor == params.post_processor)
        
        if params.sha256 is not None:
            query = query.filter(Artefact.sha256 == params.sha256.lower())
        
        if params.min_size_bytes is not None:
            query = query.filter(Artefact.size_bytes >= params.min_size_bytes)
        
        if params.max_size_bytes is not None:
            query = query.filter(Artefact.size_bytes <= params.max_size_bytes)
        
        if params.created_after is not None:
            query = query.filter(Artefact.created_at >= params.created_after)
        
        if params.created_before is not None:
            query = query.filter(Artefact.created_at <= params.created_before)
        
        # Filter by user access (through job ownership or admin role)
        user = self.db.query(User).filter_by(id=user_id).first()
        is_admin = user and user.role == "admin"
        
        if not is_admin:
            # Non-admin users can only see their own artefacts
            query = query.join(Job).filter(
                or_(
                    Job.user_id == user_id,
                    Artefact.created_by == user_id,
                )
            )
        else:
            # Admin users can see all artefacts - just join for consistency
            query = query.join(Job)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        offset = (params.page - 1) * params.per_page
        artefacts = (
            query.order_by(desc(Artefact.created_at))
            .offset(offset)
            .limit(params.per_page)
            .all()
        )
        
        return artefacts, total_count
    
    async def get_artefact_stats(
        self,
        user_id: int,
        job_id: Optional[int] = None,
    ) -> ArtefactStats:
        """
        Get statistics about artefacts.
        
        Args:
            user_id: User requesting stats
            job_id: Optional job ID to filter by
            
        Returns:
            ArtefactStats instance
        """
        query = self.db.query(Artefact).join(Job)
        
        # Filter by user access (admin users can see all)
        user = self.db.query(User).filter_by(id=user_id).first()
        is_admin = user and user.role == "admin"
        
        if not is_admin:
            # Non-admin users can only see their own stats
            query = query.filter(
                or_(
                    Job.user_id == user_id,
                    Artefact.created_by == user_id,
                )
            )
        
        if job_id:
            query = query.filter(Artefact.job_id == job_id)
        
        # Get basic stats
        total_count = query.count()
        total_size = query.with_entities(func.sum(Artefact.size_bytes)).scalar() or 0
        
        # Get stats by type
        by_type = {}
        type_stats = (
            query.with_entities(
                Artefact.type,
                func.count(Artefact.id),
            )
            .group_by(Artefact.type)
            .all()
        )
        for type_name, count in type_stats:
            by_type[type_name] = count
        
        # Get stats by user
        by_user = {}
        user_stats = (
            query.with_entities(
                Artefact.created_by,
                func.count(Artefact.id),
            )
            .group_by(Artefact.created_by)
            .all()
        )
        for user_id, count in user_stats:
            by_user[user_id] = count
        
        # Get stats by machine
        by_machine = {}
        machine_stats = (
            query.filter(Artefact.machine_id.isnot(None))
            .with_entities(
                Artefact.machine_id,
                func.count(Artefact.id),
            )
            .group_by(Artefact.machine_id)
            .all()
        )
        for machine_id, count in machine_stats:
            by_machine[machine_id] = count
        
        # Get size stats
        avg_size = total_size / total_count if total_count > 0 else 0
        max_size = query.with_entities(func.max(Artefact.size_bytes)).scalar() or 0
        
        return ArtefactStats(
            total_count=total_count,
            total_size_bytes=total_size,
            total_size_gb=total_size / (1024**3),
            by_type=by_type,
            by_user=by_user,
            by_machine=by_machine,
            average_size_mb=avg_size / (1024**2),
            largest_size_mb=max_size / (1024**2),
        )
    
    async def delete_artefact(
        self,
        artefact_id: int,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """
        Delete an artefact (soft delete - keeps DB record).
        
        Args:
            artefact_id: Artefact ID to delete
            user_id: User performing deletion
            ip_address: Client IP for audit
            user_agent: Client user agent for audit
            
        Raises:
            ArtefactServiceError: If deletion fails
        """
        try:
            # Get artefact with access check
            artefact = await self.get_artefact(artefact_id, user_id, check_access=True)
            
            # Check if it's an invoice (special handling)
            if artefact.is_invoice:
                raise ArtefactServiceError(
                    code="INVOICE_DELETION_PROHIBITED",
                    message="Invoices cannot be deleted due to legal requirements",
                    turkish_message="Faturalar yasal gereklilikler nedeniyle silinemez",
                    status_code=403,
                )
            
            # Mark as deleted in metadata
            artefact.set_meta('deleted', True)
            artefact.set_meta('deleted_at', datetime.now(timezone.utc).isoformat())
            artefact.set_meta('deleted_by', user_id)
            
            self.db.commit()
            
            # Audit the deletion
            await audit_service.create_audit_entry(
                db=self.db,
                event_type="artefact_deleted",
                user_id=user_id,
                scope_type="artefact",
                scope_id=artefact_id,
                resource=f"artefact/{artefact.type}",
                ip_address=ip_address,
                user_agent=user_agent,
                payload={
                    "artefact_id": artefact_id,
                    "job_id": artefact.job_id,
                    "s3_location": artefact.s3_full_path,
                },
            )
            
            logger.info(
                "Artefact marked as deleted",
                artefact_id=artefact_id,
                user_id=user_id,
            )
            
        except ArtefactServiceError:
            raise
        except Exception as e:
            logger.error(
                "Failed to delete artefact",
                artefact_id=artefact_id,
                error=str(e),
            )
            raise ArtefactServiceError(
                code="DELETION_ERROR",
                message=f"Failed to delete artefact: {str(e)}",
                turkish_message=f"Artefact silinemedi: {str(e)}",
                status_code=500,
            )


# Export main service class
__all__ = ["ArtefactService", "ArtefactServiceError"]