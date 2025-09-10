"""
FastAPI endpoints for FreeCAD Model Version Control (Task 7.22).

This module provides REST API endpoints for the Git-like version control system
for FreeCAD models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.user import User
from app.models.version_control import (
    Branch,
    CheckoutResult,
    CommitDiff,
    CommitInfo,
    ConflictResolutionStrategy,
    MergeResult,
    MergeStrategy,
    Repository,
    Tag,
    VERSION_CONTROL_TR,
)
from app.services.model_version_control import ModelVersionControl, ModelVersionControlError
from app.services.vcs_repository_registry import get_vcs_registry, VCSRepositoryRegistryError
from app.utils.vcs_error_handler import handle_vcs_errors

router = APIRouter(prefix="/version-control", tags=["version-control"])
logger = structlog.get_logger(__name__)


# Request/Response schemas

class InitRepositoryRequest(BaseModel):
    """Request to initialize a repository."""
    name: str = Field(description="Repository name")
    description: Optional[str] = Field(default=None, description="Repository description")
    use_real_freecad: bool = Field(default=False, description="Use real FreeCAD API")


class CommitRequest(BaseModel):
    """Request to commit changes."""
    job_id: str = Field(description="Job ID for document")
    message: str = Field(description="Commit message")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")


class CreateBranchRequest(BaseModel):
    """Request to create a branch."""
    branch_name: str = Field(description="Branch name")
    from_commit: Optional[str] = Field(default=None, description="Starting commit hash")


class MergeBranchesRequest(BaseModel):
    """Request to merge branches."""
    source_branch: str = Field(description="Source branch")
    target_branch: str = Field(description="Target branch")
    strategy: MergeStrategy = Field(default=MergeStrategy.RECURSIVE, description="Merge strategy")


class CheckoutRequest(BaseModel):
    """Request to checkout a commit."""
    commit_hash: str = Field(description="Commit hash to checkout")
    create_branch: bool = Field(default=False, description="Create new branch")
    branch_name: Optional[str] = Field(default=None, description="New branch name")


class DiffRequest(BaseModel):
    """Request to calculate diff."""
    from_commit: str = Field(description="Source commit hash")
    to_commit: str = Field(description="Target commit hash")


class RollbackRequest(BaseModel):
    """Request to rollback to a commit."""
    commit_hash: str = Field(description="Commit hash to rollback to")
    branch: Optional[str] = Field(default=None, description="Branch to rollback")


class CreateTagRequest(BaseModel):
    """Request to create a tag."""
    tag_name: str = Field(description="Tag name")
    target_commit: str = Field(description="Target commit hash")
    message: Optional[str] = Field(default=None, description="Tag message")


class ResolveConflictRequest(BaseModel):
    """Request to resolve a conflict."""
    conflict_id: str = Field(description="Conflict ID")
    strategy: ConflictResolutionStrategy = Field(description="Resolution strategy")
    custom_resolution: Optional[Dict[str, Any]] = Field(default=None, description="Custom resolution data")


# Repository registry for managing VCS instances
_registry = get_vcs_registry()


@router.post("/init", response_model=Repository)
async def init_repository(
    request: InitRepositoryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Initialize a new version control repository for FreeCAD models.
    
    Creates the repository structure and initializes the default branch.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_init_repository", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.name", request.name)
        
        try:
            # Create repository with registry
            db_repo, vcs = await _registry.create_repository(
                db=db,
                name=request.name,
                owner=current_user,
                description=request.description,
                use_real_freecad=request.use_real_freecad
            )
            
            metrics.freecad_vcs_operations_total.labels(operation="init").inc()
            
            # Return repository info
            return Repository(
                id=db_repo.repository_id,
                name=db_repo.name,
                description=db_repo.description,
                created_at=db_repo.created_at,
                updated_at=db_repo.updated_at,
                default_branch="main",
                commit_count=db_repo.commit_count,
                branch_count=db_repo.branch_count,
                tag_count=db_repo.tag_count,
                metadata=db_repo.metadata or {}
            )
            
        except VCSRepositoryRegistryError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "repository_init_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_name=request.name
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to initialize repository. Please try again later."
            )


@router.post("/{repo_id}/commit", response_model=Dict[str, str])
async def commit_changes(
    repo_id: str,
    request: CommitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Commit changes to the repository.
    
    Creates a new commit with the current document state.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_commit_changes", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        span.set_attribute("job.id", request.job_id)
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Commit changes
            commit_hash = await vcs.commit_changes(
                job_id=request.job_id,
                message=request.message,
                author=f"{current_user.name} <{current_user.email}>",
                metadata=request.metadata
            )
            
            metrics.freecad_vcs_commits_total.inc()
            
            return {
                "commit_hash": commit_hash,
                "message": VERSION_CONTROL_TR['commit_created'].format(hash=commit_hash[:8])
            }
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )


@router.post("/{repo_id}/branch", response_model=Branch)
async def create_branch(
    repo_id: str,
    request: CreateBranchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new branch in the repository.
    
    Creates a branch from the specified commit or current HEAD.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_create_branch", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        span.set_attribute("branch.name", request.branch_name)
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Create branch
            branch = await vcs.create_branch(
                branch_name=request.branch_name,
                from_commit=request.from_commit
            )
            
            metrics.freecad_vcs_branches_total.inc()
            
            return branch
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )


@router.post("/{repo_id}/merge", response_model=MergeResult)
async def merge_branches(
    repo_id: str,
    request: MergeBranchesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Merge two branches.
    
    Performs a merge operation with the specified strategy.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_merge_branches", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        span.set_attribute("source.branch", request.source_branch)
        span.set_attribute("target.branch", request.target_branch)
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Merge branches
            result = await vcs.merge_branches(
                source_branch=request.source_branch,
                target_branch=request.target_branch,
                strategy=request.strategy,
                author=f"{current_user.name} <{current_user.email}>"
            )
            
            metrics.freecad_vcs_merges_total.labels(
                status="success" if result.success else "conflict"
            ).inc()
            
            return result
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )


@router.post("/{repo_id}/checkout", response_model=CheckoutResult)
async def checkout_commit(
    repo_id: str,
    request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Checkout a specific commit.
    
    Switches to a specific commit version, optionally creating a new branch.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_checkout_commit", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        span.set_attribute("commit.hash", request.commit_hash[:8])
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Checkout commit
            result = await vcs.checkout_commit(
                commit_hash=request.commit_hash,
                create_branch=request.create_branch,
                branch_name=request.branch_name
            )
            
            metrics.freecad_vcs_checkouts_total.inc()
            
            return result
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )


@router.get("/{repo_id}/history", response_model=List[CommitInfo])
async def get_history(
    repo_id: str,
    branch: Optional[str] = Query(default=None, description="Branch name"),
    limit: int = Query(default=100, description="Maximum commits to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get commit history.
    
    Returns the commit history for a branch.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_get_history", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        span.set_attribute("branch", branch or "current")
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Get history
            history = await vcs.get_history(
                branch=branch,
                limit=limit
            )
            
            return history
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )


@router.post("/{repo_id}/diff", response_model=CommitDiff)
async def diff_commits(
    repo_id: str,
    request: DiffRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate diff between commits.
    
    Returns detailed differences between two commits.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_diff_commits", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        span.set_attribute("from.commit", request.from_commit[:8])
        span.set_attribute("to.commit", request.to_commit[:8])
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Calculate diff
            diff = await vcs.diff_commits(
                from_commit=request.from_commit,
                to_commit=request.to_commit
            )
            
            return diff
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )


@router.post("/{repo_id}/rollback", response_model=Dict[str, Any])
async def rollback_to_commit(
    repo_id: str,
    request: RollbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rollback to a specific commit.
    
    Resets the branch to a previous commit state.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_rollback", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        span.set_attribute("commit.hash", request.commit_hash[:8])
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Rollback
            success = await vcs.rollback_to_commit(
                commit_hash=request.commit_hash,
                branch=request.branch
            )
            
            metrics.freecad_vcs_rollbacks_total.inc()
            
            return {
                "success": success,
                "message": VERSION_CONTROL_TR['rollback'].format(commit=request.commit_hash[:8])
            }
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )


@router.post("/{repo_id}/optimize", response_model=Dict[str, Any])
async def optimize_storage(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Optimize repository storage.
    
    Performs garbage collection and delta compression.
    """
    correlation_id = get_correlation_id()
    
    with create_span("api_optimize_storage", correlation_id=correlation_id) as span:
        span.set_attribute("user.id", current_user.id)
        span.set_attribute("repository.id", repo_id)
        
        try:
            # Get repository and VCS instance from registry
            db_repo, vcs = await _registry.get_repository(
                db=db,
                repository_id=repo_id,
                user=current_user,
                check_access=True
            )
            
            # Optimize storage
            stats = await vcs.optimize_storage()
            
            metrics.freecad_vcs_gc_runs_total.inc()
            
            return stats
            
        except VCSRepositoryRegistryError as e:
            if e.code == "REPOSITORY_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": e.code,
                        "message": e.message,
                        "turkish_message": e.turkish_message
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except ModelVersionControlError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": e.code,
                    "message": e.message,
                    "turkish_message": e.turkish_message
                }
            )
        except Exception as e:
            # Log the full error for debugging
            logger.error(
                "vcs_operation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=current_user.id,
                repository_id=repo_id
            )
            # Return generic error to client
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Operation failed. Please try again later."
            )