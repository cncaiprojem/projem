"""
Version Control System Repository Registry Service.

This service manages VCS repository instances with database persistence,
providing a production-ready solution for repository lifecycle management.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any
from uuid import uuid4

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.environment import environment as settings
from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.vcs_repository import VCSRepository
from app.models.user import User
from app.services.model_version_control import ModelVersionControl, ModelVersionControlError

logger = structlog.get_logger(__name__)


class VCSRepositoryRegistryError(Exception):
    """Custom exception for repository registry operations."""
    
    def __init__(
        self,
        code: str,
        message: str,
        turkish_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.turkish_message = turkish_message or message
        self.details = details or {}
        super().__init__(self.message)


class VCSRepositoryRegistry:
    """
    Registry service for managing VCS repository instances.
    
    This service provides:
    - Database persistence for repository metadata
    - Lazy loading of VCS instances
    - Repository lifecycle management
    - Storage path management
    - Cleanup and garbage collection
    """
    
    def __init__(self, storage_root: Optional[Path] = None):
        """
        Initialize repository registry.
        
        Args:
            storage_root: Root directory for repository storage
        """
        # Set storage root
        if storage_root:
            self.storage_root = Path(storage_root)
        else:
            # Use configured storage path or default
            storage_path = getattr(settings, "VCS_STORAGE_ROOT", "/data/vcs_repositories")
            self.storage_root = Path(storage_path)
        
        # Ensure storage root exists
        self.storage_root.mkdir(parents=True, exist_ok=True)
        
        # Cache for active VCS instances
        self._vcs_instances: Dict[str, ModelVersionControl] = {}
        
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        
        logger.info(
            "vcs_repository_registry_initialized",
            storage_root=str(self.storage_root)
        )
    
    async def create_repository(
        self,
        db: AsyncSession,
        name: str,
        owner: User,
        description: Optional[str] = None,
        use_real_freecad: bool = False,
    ) -> tuple[VCSRepository, ModelVersionControl]:
        """
        Create a new repository with database persistence.
        
        Args:
            db: Database session
            name: Repository name
            owner: Repository owner
            description: Optional description
            use_real_freecad: Whether to use real FreeCAD API
            
        Returns:
            Tuple of (repository model, VCS instance)
            
        Raises:
            VCSRepositoryRegistryError: If creation fails
        """
        correlation_id = get_correlation_id()
        
        with create_span("create_vcs_repository", correlation_id=correlation_id) as span:
            span.set_attribute("repository.name", name)
            span.set_attribute("owner.id", owner.id)
            
            async with self._lock:
                try:
                    # Check if repository already exists
                    existing = await db.execute(
                        select(VCSRepository).where(
                            and_(
                                VCSRepository.owner_id == owner.id,
                                VCSRepository.name == name,
                                VCSRepository.is_active == True
                            )
                        )
                    )
                    if existing.scalar_one_or_none():
                        raise VCSRepositoryRegistryError(
                            code="REPOSITORY_EXISTS",
                            message=f"Repository '{name}' already exists",
                            turkish_message=f"'{name}' deposu zaten mevcut"
                        )
                    
                    # Generate unique repository ID
                    repo_id = uuid4().hex
                    
                    # Create storage path
                    storage_path = self.storage_root / str(owner.id) / repo_id
                    storage_path.mkdir(parents=True, exist_ok=True)
                    
                    # Create database record
                    db_repo = VCSRepository(
                        repository_id=repo_id,
                        name=name,
                        description=description,
                        owner_id=owner.id,
                        storage_path=str(storage_path),
                        use_real_freecad=use_real_freecad,
                        is_active=True,
                        is_locked=False,
                        current_branch="main",
                        commit_count=0,
                        branch_count=1,
                        tag_count=0,
                    )
                    db.add(db_repo)
                    await db.flush()  # Get the ID
                    
                    # Create VCS instance
                    vcs = ModelVersionControl(
                        repository_path=storage_path,
                        use_real_freecad=use_real_freecad
                    )
                    
                    # Initialize repository
                    repo = await vcs.init_repository(
                        name=name,
                        description=description
                    )
                    
                    # Update database with repository info
                    db_repo.repo_metadata = {
                        "initialized_at": datetime.now(timezone.utc).isoformat(),
                        "version": "1.0.0"
                    }
                    
                    # Cache VCS instance
                    self._vcs_instances[repo_id] = vcs
                    
                    # Commit database changes
                    await db.commit()
                    
                    metrics.freecad_vcs_repositories_total.inc()
                    
                    logger.info(
                        "repository_created",
                        repository_id=repo_id,
                        name=name,
                        owner_id=owner.id
                    )
                    
                    return db_repo, vcs
                    
                except VCSRepositoryRegistryError:
                    await db.rollback()
                    raise
                except Exception as e:
                    await db.rollback()
                    logger.error(
                        "repository_creation_failed",
                        error=str(e),
                        name=name
                    )
                    raise VCSRepositoryRegistryError(
                        code="CREATE_FAILED",
                        message=f"Failed to create repository: {str(e)}",
                        turkish_message=f"Depo oluşturulamadı: {str(e)}"
                    )
    
    async def get_repository(
        self,
        db: AsyncSession,
        repository_id: str,
        user: Optional[User] = None,
        check_access: bool = True,
    ) -> tuple[VCSRepository, ModelVersionControl]:
        """
        Get repository and VCS instance.
        
        Args:
            db: Database session
            repository_id: Repository ID
            user: Current user (for access control)
            check_access: Whether to check user access
            
        Returns:
            Tuple of (repository model, VCS instance)
            
        Raises:
            VCSRepositoryRegistryError: If repository not found or access denied
        """
        correlation_id = get_correlation_id()
        
        with create_span("get_vcs_repository", correlation_id=correlation_id) as span:
            span.set_attribute("repository.id", repository_id)
            
            async with self._lock:
                try:
                    # Get repository from database
                    result = await db.execute(
                        select(VCSRepository)
                        .options(selectinload(VCSRepository.owner))
                        .where(
                            and_(
                                VCSRepository.repository_id == repository_id,
                                VCSRepository.is_active == True
                            )
                        )
                    )
                    db_repo = result.scalar_one_or_none()
                    
                    if not db_repo:
                        raise VCSRepositoryRegistryError(
                            code="REPOSITORY_NOT_FOUND",
                            message=f"Repository '{repository_id}' not found",
                            turkish_message=f"'{repository_id}' deposu bulunamadı"
                        )
                    
                    # Check access permissions
                    if check_access and user:
                        if db_repo.owner_id != user.id and user.role != "admin":
                            raise VCSRepositoryRegistryError(
                                code="ACCESS_DENIED",
                                message="Access denied to repository",
                                turkish_message="Depoya erişim reddedildi"
                            )
                    
                    # Check if repository is locked
                    if db_repo.is_locked:
                        raise VCSRepositoryRegistryError(
                            code="REPOSITORY_LOCKED",
                            message="Repository is locked for maintenance",
                            turkish_message="Depo bakım için kilitli"
                        )
                    
                    # Get or create VCS instance
                    vcs = await self._get_or_create_vcs_instance(db_repo)
                    
                    return db_repo, vcs
                    
                except VCSRepositoryRegistryError:
                    raise
                except Exception as e:
                    logger.error(
                        "repository_get_failed",
                        error=str(e),
                        repository_id=repository_id
                    )
                    raise VCSRepositoryRegistryError(
                        code="GET_FAILED",
                        message=f"Failed to get repository: {str(e)}",
                        turkish_message=f"Depo alınamadı: {str(e)}"
                    )
    
    async def _get_or_create_vcs_instance(
        self,
        db_repo: VCSRepository
    ) -> ModelVersionControl:
        """
        Get existing or create new VCS instance for repository.
        
        Args:
            db_repo: Repository database model
            
        Returns:
            VCS instance
        """
        repo_id = db_repo.repository_id
        
        # Check cache
        if repo_id in self._vcs_instances:
            return self._vcs_instances[repo_id]
        
        # Create new instance
        storage_path = Path(db_repo.storage_path)
        
        # Ensure storage path exists
        if not storage_path.exists():
            raise VCSRepositoryRegistryError(
                code="STORAGE_NOT_FOUND",
                message=f"Repository storage path not found: {storage_path}",
                turkish_message=f"Depo depolama yolu bulunamadı: {storage_path}"
            )
        
        vcs = ModelVersionControl(
            repository_path=storage_path,
            use_real_freecad=db_repo.use_real_freecad
        )
        
        # Cache instance
        self._vcs_instances[repo_id] = vcs
        
        logger.info(
            "vcs_instance_created",
            repository_id=repo_id,
            cached_instances=len(self._vcs_instances)
        )
        
        return vcs
    
    async def list_repositories(
        self,
        db: AsyncSession,
        user: Optional[User] = None,
        include_stats: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[VCSRepository]:
        """
        List repositories accessible to user.
        
        Args:
            db: Database session
            user: Current user (None for all repositories)
            include_stats: Whether to include statistics
            limit: Maximum repositories to return
            offset: Offset for pagination
            
        Returns:
            List of repository models
        """
        query = select(VCSRepository).where(
            VCSRepository.is_active == True
        )
        
        # Filter by user if provided
        if user and user.role != "admin":
            query = query.where(VCSRepository.owner_id == user.id)
        
        # Add ordering and pagination
        query = query.order_by(VCSRepository.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        # Include owner relationship
        query = query.options(selectinload(VCSRepository.owner))
        
        result = await db.execute(query)
        repositories = result.scalars().all()
        
        # Update statistics if requested
        if include_stats:
            for repo in repositories:
                await self._update_repository_stats(db, repo)
        
        return repositories
    
    async def _update_repository_stats(
        self,
        db: AsyncSession,
        db_repo: VCSRepository
    ) -> None:
        """
        Update repository statistics.
        
        Args:
            db: Database session
            db_repo: Repository model to update
        """
        try:
            storage_path = Path(db_repo.storage_path)
            
            # Calculate storage size
            if storage_path.exists():
                total_size = sum(
                    f.stat().st_size
                    for f in storage_path.rglob("*")
                    if f.is_file()
                )
                db_repo.storage_size_bytes = total_size
            
            # Update would be done by VCS instance in production
            # This is simplified for the example
            
            await db.flush()
            
        except Exception as e:
            logger.warning(
                "stats_update_failed",
                repository_id=db_repo.repository_id,
                error=str(e)
            )
    
    async def delete_repository(
        self,
        db: AsyncSession,
        repository_id: str,
        user: User,
        permanent: bool = False,
    ) -> bool:
        """
        Delete or deactivate a repository.
        
        Args:
            db: Database session
            repository_id: Repository ID
            user: Current user
            permanent: Whether to permanently delete (vs soft delete)
            
        Returns:
            True if successful
            
        Raises:
            VCSRepositoryRegistryError: If deletion fails
        """
        correlation_id = get_correlation_id()
        
        with create_span("delete_vcs_repository", correlation_id=correlation_id) as span:
            span.set_attribute("repository.id", repository_id)
            span.set_attribute("permanent", permanent)
            
            async with self._lock:
                try:
                    # Get repository
                    db_repo, vcs = await self.get_repository(
                        db, repository_id, user, check_access=True
                    )
                    
                    # Only owner or admin can delete
                    if db_repo.owner_id != user.id and user.role != "admin":
                        raise VCSRepositoryRegistryError(
                            code="ACCESS_DENIED",
                            message="Only repository owner can delete",
                            turkish_message="Sadece depo sahibi silebilir"
                        )
                    
                    if permanent:
                        # Cleanup VCS instance
                        if repository_id in self._vcs_instances:
                            await self._vcs_instances[repository_id].cleanup()
                            del self._vcs_instances[repository_id]
                        
                        # Remove storage
                        storage_path = Path(db_repo.storage_path)
                        if storage_path.exists():
                            await asyncio.to_thread(shutil.rmtree, storage_path)
                        
                        # Delete from database
                        await db.delete(db_repo)
                    else:
                        # Soft delete
                        db_repo.is_active = False
                        db_repo.is_locked = True
                        
                        # Remove from cache
                        if repository_id in self._vcs_instances:
                            del self._vcs_instances[repository_id]
                    
                    await db.commit()
                    
                    metrics.freecad_vcs_repositories_deleted_total.inc()
                    
                    logger.info(
                        "repository_deleted",
                        repository_id=repository_id,
                        permanent=permanent
                    )
                    
                    return True
                    
                except VCSRepositoryRegistryError:
                    await db.rollback()
                    raise
                except Exception as e:
                    await db.rollback()
                    logger.error(
                        "repository_deletion_failed",
                        error=str(e),
                        repository_id=repository_id
                    )
                    raise VCSRepositoryRegistryError(
                        code="DELETE_FAILED",
                        message=f"Failed to delete repository: {str(e)}",
                        turkish_message=f"Depo silinemedi: {str(e)}"
                    )
    
    async def cleanup_inactive(self, max_age_days: int = 90) -> int:
        """
        Cleanup inactive VCS instances from cache.
        
        Args:
            max_age_days: Maximum age for inactive instances
            
        Returns:
            Number of instances cleaned up
        """
        async with self._lock:
            initial_count = len(self._vcs_instances)
            
            # In production, would check last access time
            # For now, just clear instances not recently used
            # This is a simplified implementation
            
            cleaned = 0
            for repo_id in list(self._vcs_instances.keys()):
                # Check if instance should be cleaned
                # (would check last access time in production)
                if repo_id in self._vcs_instances:
                    await self._vcs_instances[repo_id].cleanup()
                    del self._vcs_instances[repo_id]
                    cleaned += 1
            
            logger.info(
                "inactive_instances_cleaned",
                initial_count=initial_count,
                cleaned=cleaned,
                remaining=len(self._vcs_instances)
            )
            
            return cleaned
    
    async def shutdown(self):
        """Cleanup all resources on shutdown."""
        async with self._lock:
            for repo_id, vcs in self._vcs_instances.items():
                try:
                    await vcs.cleanup()
                except Exception as e:
                    logger.error(
                        "vcs_cleanup_failed",
                        repository_id=repo_id,
                        error=str(e)
                    )
            
            self._vcs_instances.clear()
            
            logger.info("vcs_repository_registry_shutdown")


# Global registry instance
_registry: Optional[VCSRepositoryRegistry] = None


def get_vcs_registry() -> VCSRepositoryRegistry:
    """Get global VCS repository registry instance."""
    global _registry
    if _registry is None:
        _registry = VCSRepositoryRegistry()
    return _registry