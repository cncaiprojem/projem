"""
Main FreeCAD Model Version Control Service (Task 7.22).

This service provides Git-like version control functionality specifically designed
for FreeCAD models, including branching, merging, diffing, and rollback capabilities.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.environment import environment as settings
from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.version_control import (
    Branch,
    CheckoutResult,
    Commit,
    CommitDiff,
    CommitInfo,
    ConflictResolutionStrategy,
    MergeResult,
    MergeStrategy,
    Repository,
    Tree,
    VERSION_CONTROL_TR,
)
from app.services.freecad_document_manager import FreeCADDocumentManager
from app.services.model_object_store import ModelObjectStore
from app.services.model_commit_manager import ModelCommitManager
from app.services.model_branch_manager import ModelBranchManager
from app.services.model_differ import ModelDiffer
from app.services.model_conflict_resolver import ModelConflictResolver

logger = structlog.get_logger(__name__)


class ModelVersionControlError(Exception):
    """Custom exception for version control operations."""
    
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


class ModelVersionControl:
    """
    Git-like version control system for FreeCAD models.
    
    Features:
    - Content-addressable storage using SHA-256
    - Commit system with tree structures
    - Branching and merging
    - Model diffing for geometry and properties
    - Conflict resolution strategies
    - History tracking and rollback
    - Storage optimization with delta compression
    """
    
    def __init__(
        self,
        repository_path: Optional[Path] = None,
        use_real_freecad: bool = False,
    ):
        """
        Initialize version control system.
        
        Args:
            repository_path: Path to repository root (uses temp if not provided)
            use_real_freecad: Whether to use real FreeCAD API
        """
        # Set repository path
        if repository_path:
            self.repo_path = Path(repository_path)
        else:
            # Use temp directory if not specified
            self.repo_path = Path(tempfile.gettempdir()) / f"mvc_repo_{uuid4().hex[:8]}"
        
        # Initialize FreeCAD document manager first (needed by commit manager)
        from app.services.freecad_document_manager import DocumentManagerConfig
        config = DocumentManagerConfig(
            base_dir=str(self.repo_path / "working"),
            use_real_freecad=use_real_freecad
        )
        self.doc_manager = FreeCADDocumentManager(config)
        
        # Initialize components (doc_manager must be initialized before commit_manager)
        self.object_store = ModelObjectStore(self.repo_path / ".mvcstore")
        self.commit_manager = ModelCommitManager(self.object_store, self.doc_manager)
        self.branch_manager = ModelBranchManager(self.repo_path / ".mvcstore" / "refs", self.object_store)
        self.differ = ModelDiffer(self.object_store)
        self.conflict_resolver = ModelConflictResolver()
        
        # Repository metadata
        self.repository: Optional[Repository] = None
        
        # Cache for frequently accessed objects
        self._object_cache: Dict[str, Any] = {}
        self._cache_size_limit = 100  # Maximum cache entries
        
        logger.info(
            "model_version_control_initialized",
            repo_path=str(self.repo_path),
            use_real_freecad=use_real_freecad
        )
    
    async def init_repository(
        self,
        name: str = "default",
        description: Optional[str] = None,
    ) -> Repository:
        """
        Initialize a new model repository.
        
        Args:
            name: Repository name
            description: Repository description
            
        Returns:
            Repository metadata
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_init_repository", correlation_id=correlation_id) as span:
            span.set_attribute("repository.name", name)
            
            try:
                # Create repository metadata
                repo = Repository(
                    name=name,
                    description=description,
                    created_at=datetime.now(timezone.utc),
                    default_branch="main",
                    config={
                        "version": "1.0.0",
                        "compression": True,
                        "delta_compression": True,
                        "auto_gc": True,
                    }
                )
                
                # Initialize storage
                await self.object_store.init_store()
                
                # Create default branch
                await self.branch_manager.create_branch("main")
                
                # Save repository metadata
                repo_meta_path = self.repo_path / ".mvcstore" / "repository.json"
                repo_meta_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(repo_meta_path, 'w') as f:
                    json.dump(repo.model_dump(), f, indent=2, default=str)
                
                self.repository = repo
                
                logger.info(
                    "repository_initialized",
                    repo_id=str(repo.id),
                    name=name,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['init_repo']
                )
                
                metrics.freecad_vcs_operations_total.labels(operation="init").inc()
                
                return repo
                
            except Exception as e:
                logger.error(
                    "repository_init_failed",
                    error=str(e),
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="INIT_FAILED",
                    message=f"Failed to initialize repository: {str(e)}",
                    turkish_message=f"Depo başlatılamadı: {str(e)}"
                )
    
    async def commit_changes(
        self,
        job_id: str,
        message: str,
        author: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Commit current document state.
        
        Args:
            job_id: Job ID for document
            message: Commit message
            author: Author name/email
            metadata: Additional metadata
            
        Returns:
            Commit hash
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_commit_changes", correlation_id=correlation_id) as span:
            span.set_attribute("job.id", job_id)
            span.set_attribute("author", author)
            
            try:
                # Get or create document
                doc_metadata = await asyncio.to_thread(
                    self.doc_manager.open_document,
                    job_id=job_id,
                    create_if_not_exists=True
                )
                
                # Get current branch
                current_branch = await self.branch_manager.get_current_branch()
                
                # Get parent commit
                parent_hash = None
                if current_branch:
                    parent_hash = await self.branch_manager.get_branch_head(current_branch)
                
                # Create commit through commit manager
                commit_hash = await self.commit_manager.commit_document(
                    document_id=doc_metadata.document_id,
                    message=message,
                    author=author,
                    parent_hash=parent_hash,
                    metadata=metadata
                )
                
                # Update branch reference
                if current_branch:
                    await self.branch_manager.update_branch(current_branch, commit_hash)
                
                logger.info(
                    "changes_committed",
                    commit_hash=commit_hash,
                    job_id=job_id,
                    branch=current_branch,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['commit_created'].format(hash=commit_hash[:8])
                )
                
                metrics.freecad_vcs_commits_total.inc()
                
                return commit_hash
                
            except Exception as e:
                logger.error(
                    "commit_failed",
                    error=str(e),
                    job_id=job_id,
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="COMMIT_FAILED",
                    message=f"Failed to commit changes: {str(e)}",
                    turkish_message=f"Değişiklikler kaydedilemedi: {str(e)}"
                )
    
    async def create_branch(
        self,
        branch_name: str,
        from_commit: Optional[str] = None,
    ) -> Branch:
        """
        Create a new branch.
        
        Args:
            branch_name: Name of the new branch
            from_commit: Commit to branch from (uses current HEAD if not specified)
            
        Returns:
            Branch object
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_create_branch", correlation_id=correlation_id) as span:
            span.set_attribute("branch.name", branch_name)
            
            try:
                branch = await self.branch_manager.create_branch(
                    branch_name=branch_name,
                    from_commit=from_commit
                )
                
                logger.info(
                    "branch_created",
                    branch_name=branch_name,
                    head=branch.head[:8] if branch.head else None,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['branch_created'].format(name=branch_name)
                )
                
                metrics.freecad_vcs_branches_total.inc()
                
                return branch
                
            except Exception as e:
                logger.error(
                    "branch_creation_failed",
                    error=str(e),
                    branch_name=branch_name,
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="BRANCH_FAILED",
                    message=f"Failed to create branch: {str(e)}",
                    turkish_message=f"Dal oluşturulamadı: {str(e)}"
                )
    
    async def merge_branches(
        self,
        source_branch: str,
        target_branch: str,
        strategy: MergeStrategy = MergeStrategy.RECURSIVE,
        author: str = "System",
    ) -> MergeResult:
        """
        Merge source branch into target branch.
        
        Args:
            source_branch: Source branch name
            target_branch: Target branch name
            strategy: Merge strategy to use
            author: Author of merge commit
            
        Returns:
            MergeResult with success status and any conflicts
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_merge_branches", correlation_id=correlation_id) as span:
            span.set_attribute("source.branch", source_branch)
            span.set_attribute("target.branch", target_branch)
            span.set_attribute("strategy", strategy.value)
            
            try:
                # Get branch heads
                source_head = await self.branch_manager.get_branch_head(source_branch)
                target_head = await self.branch_manager.get_branch_head(target_branch)
                
                if not source_head or not target_head:
                    raise ValueError("Branch heads not found")
                
                # Find common ancestor
                common_ancestor = await self._find_common_ancestor(source_head, target_head)
                
                # Check for fast-forward merge
                if common_ancestor == target_head:
                    # Fast-forward merge possible
                    await self.branch_manager.update_branch(target_branch, source_head)
                    
                    result = MergeResult(
                        success=True,
                        commit_hash=source_head,
                        conflicts=[],
                        merged_tree=None,
                        strategy_used=strategy
                    )
                    
                    logger.info(
                        "fast_forward_merge",
                        source=source_branch,
                        target=target_branch,
                        correlation_id=correlation_id,
                        message=VERSION_CONTROL_TR['merge_success']
                    )
                    
                else:
                    # Three-way merge required
                    result = await self._three_way_merge(
                        common_ancestor,
                        source_head,
                        target_head,
                        source_branch,
                        target_branch,
                        strategy,
                        author
                    )
                    
                    if result.success:
                        logger.info(
                            "merge_successful",
                            source=source_branch,
                            target=target_branch,
                            commit_hash=result.commit_hash,
                            correlation_id=correlation_id,
                            message=VERSION_CONTROL_TR['merge_success']
                        )
                    else:
                        logger.warning(
                            "merge_conflicts",
                            source=source_branch,
                            target=target_branch,
                            conflicts=len(result.conflicts),
                            correlation_id=correlation_id,
                            message=VERSION_CONTROL_TR['merge_conflict']
                        )
                
                metrics.freecad_vcs_merges_total.labels(
                    status="success" if result.success else "conflict"
                ).inc()
                
                return result
                
            except Exception as e:
                logger.error(
                    "merge_failed",
                    error=str(e),
                    source=source_branch,
                    target=target_branch,
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="MERGE_FAILED",
                    message=f"Failed to merge branches: {str(e)}",
                    turkish_message=f"Dallar birleştirilemedi: {str(e)}"
                )
    
    async def checkout_commit(
        self,
        commit_hash: str,
        create_branch: bool = False,
        branch_name: Optional[str] = None,
    ) -> CheckoutResult:
        """
        Checkout a specific commit version.
        
        Args:
            commit_hash: Commit hash to checkout
            create_branch: Whether to create a new branch
            branch_name: Name for new branch (auto-generated if not provided)
            
        Returns:
            CheckoutResult with reconstructed document
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_checkout_commit", correlation_id=correlation_id) as span:
            span.set_attribute("commit.hash", commit_hash[:8])
            span.set_attribute("create_branch", create_branch)
            
            try:
                # Get commit object
                commit = await self.object_store.get_commit(commit_hash)
                if not commit:
                    raise ValueError(f"Commit {commit_hash} not found")
                
                # Get tree object
                tree = await self.object_store.get_tree(commit.tree)
                if not tree:
                    raise ValueError(f"Tree {commit.tree} not found")
                
                # Reconstruct document from tree
                doc_path = await self._reconstruct_document_from_tree(tree)
                
                # Create branch if requested
                if create_branch:
                    if not branch_name:
                        branch_name = f"detached-{commit_hash[:8]}"
                    await self.branch_manager.create_branch(branch_name, commit_hash)
                    await self.branch_manager.switch_branch(branch_name)
                
                result = CheckoutResult(
                    success=True,
                    commit_hash=commit_hash,
                    branch=branch_name if create_branch else None,
                    document_path=str(doc_path) if doc_path else None,
                    warnings=[]
                )
                
                logger.info(
                    "commit_checked_out",
                    commit_hash=commit_hash[:8],
                    branch=branch_name,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['checkout'].format(ref=commit_hash[:8])
                )
                
                metrics.freecad_vcs_checkouts_total.inc()
                
                return result
                
            except Exception as e:
                logger.error(
                    "checkout_failed",
                    error=str(e),
                    commit_hash=commit_hash,
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="CHECKOUT_FAILED",
                    message=f"Failed to checkout commit: {str(e)}",
                    turkish_message=f"Commit değiştirilemedi: {str(e)}"
                )
    
    async def get_history(
        self,
        branch: Optional[str] = None,
        limit: int = 100,
    ) -> List[CommitInfo]:
        """
        Get commit history for a branch.
        
        Args:
            branch: Branch name (uses current branch if not specified)
            limit: Maximum number of commits to return
            
        Returns:
            List of commit information
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_get_history", correlation_id=correlation_id) as span:
            span.set_attribute("branch", branch or "current")
            span.set_attribute("limit", limit)
            
            try:
                # Get branch head
                if not branch:
                    branch = await self.branch_manager.get_current_branch()
                
                if not branch:
                    return []
                
                head = await self.branch_manager.get_branch_head(branch)
                if not head:
                    return []
                
                # Walk commit history
                history = []
                current = head
                
                while current and len(history) < limit:
                    commit = await self.object_store.get_commit(current)
                    if not commit:
                        break
                    
                    # Get associated tags
                    tags = await self.branch_manager.get_tags_for_commit(current)
                    
                    history.append(CommitInfo(
                        hash=commit.hash or current,
                        author=commit.author,
                        timestamp=commit.timestamp,
                        message=commit.message,
                        parents=commit.parents,
                        branch=branch,
                        tags=tags
                    ))
                    
                    # Move to first parent
                    current = commit.parents[0] if commit.parents else None
                
                logger.info(
                    "history_retrieved",
                    branch=branch,
                    commits=len(history),
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['history']
                )
                
                return history
                
            except Exception as e:
                logger.error(
                    "history_retrieval_failed",
                    error=str(e),
                    branch=branch,
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="HISTORY_FAILED",
                    message=f"Failed to get history: {str(e)}",
                    turkish_message=f"Geçmiş alınamadı: {str(e)}"
                )
    
    async def diff_commits(
        self,
        from_commit: str,
        to_commit: str,
    ) -> CommitDiff:
        """
        Calculate differences between two commits.
        
        Args:
            from_commit: Source commit hash
            to_commit: Target commit hash
            
        Returns:
            CommitDiff with detailed changes
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_diff_commits", correlation_id=correlation_id) as span:
            span.set_attribute("from.commit", from_commit[:8])
            span.set_attribute("to.commit", to_commit[:8])
            
            try:
                # Get commit objects
                from_obj = await self.object_store.get_commit(from_commit)
                to_obj = await self.object_store.get_commit(to_commit)
                
                if not from_obj or not to_obj:
                    raise ValueError("Commit(s) not found")
                
                # Get trees
                from_tree = await self.object_store.get_tree(from_obj.tree)
                to_tree = await self.object_store.get_tree(to_obj.tree)
                
                # Calculate diff
                diff = await self.differ.diff_trees(from_tree, to_tree)
                
                logger.info(
                    "diff_calculated",
                    from_commit=from_commit[:8],
                    to_commit=to_commit[:8],
                    changes=len(diff.object_diffs),
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['diff_calculated']
                )
                
                return diff
                
            except Exception as e:
                logger.error(
                    "diff_failed",
                    error=str(e),
                    from_commit=from_commit,
                    to_commit=to_commit,
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="DIFF_FAILED",
                    message=f"Failed to calculate diff: {str(e)}",
                    turkish_message=f"Farklar hesaplanamadı: {str(e)}"
                )
    
    async def rollback_to_commit(
        self,
        commit_hash: str,
        branch: Optional[str] = None,
    ) -> bool:
        """
        Rollback branch to a specific commit.
        
        Args:
            commit_hash: Commit hash to rollback to
            branch: Branch to rollback (uses current if not specified)
            
        Returns:
            Success status
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_rollback", correlation_id=correlation_id) as span:
            span.set_attribute("commit.hash", commit_hash[:8])
            span.set_attribute("branch", branch or "current")
            
            try:
                # Get branch
                if not branch:
                    branch = await self.branch_manager.get_current_branch()
                
                if not branch:
                    raise ValueError("No branch specified or current branch not found")
                
                # Verify commit exists
                commit = await self.object_store.get_commit(commit_hash)
                if not commit:
                    raise ValueError(f"Commit {commit_hash} not found")
                
                # Update branch reference
                await self.branch_manager.update_branch(branch, commit_hash)
                
                # Checkout the commit
                await self.checkout_commit(commit_hash)
                
                logger.info(
                    "rollback_successful",
                    commit_hash=commit_hash[:8],
                    branch=branch,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['rollback'].format(commit=commit_hash[:8])
                )
                
                metrics.freecad_vcs_rollbacks_total.inc()
                
                return True
                
            except Exception as e:
                logger.error(
                    "rollback_failed",
                    error=str(e),
                    commit_hash=commit_hash,
                    branch=branch,
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="ROLLBACK_FAILED",
                    message=f"Failed to rollback: {str(e)}",
                    turkish_message=f"Geri dönüş başarısız: {str(e)}"
                )
    
    async def optimize_storage(self) -> Dict[str, Any]:
        """
        Optimize repository storage with delta compression and garbage collection.
        
        Returns:
            Storage statistics after optimization
        """
        correlation_id = get_correlation_id()
        
        with create_span("mvc_optimize_storage", correlation_id=correlation_id) as span:
            try:
                stats = await self.object_store.optimize_storage()
                
                logger.info(
                    "storage_optimized",
                    total_objects=stats.get("total_objects"),
                    saved_bytes=stats.get("saved_bytes"),
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['storage_optimized']
                )
                
                metrics.freecad_vcs_gc_runs_total.inc()
                
                return stats
                
            except Exception as e:
                logger.error(
                    "optimization_failed",
                    error=str(e),
                    correlation_id=correlation_id
                )
                raise ModelVersionControlError(
                    code="OPTIMIZATION_FAILED",
                    message=f"Failed to optimize storage: {str(e)}",
                    turkish_message=f"Depolama optimize edilemedi: {str(e)}"
                )
    
    # Private helper methods
    
    async def _find_common_ancestor(
        self,
        commit1: str,
        commit2: str,
    ) -> Optional[str]:
        """Find common ancestor of two commits."""
        # Build ancestry sets
        ancestors1 = set()
        ancestors2 = set()
        
        # Walk back from commit1
        current = commit1
        while current:
            ancestors1.add(current)
            commit = await self.object_store.get_commit(current)
            if commit and commit.parents:
                current = commit.parents[0]
            else:
                break
        
        # Walk back from commit2, checking for common ancestor
        current = commit2
        while current:
            if current in ancestors1:
                return current
            ancestors2.add(current)
            commit = await self.object_store.get_commit(current)
            if commit and commit.parents:
                current = commit.parents[0]
            else:
                break
        
        return None
    
    async def _three_way_merge(
        self,
        base: str,
        source: str,
        target: str,
        source_branch: str,
        target_branch: str,
        strategy: MergeStrategy,
        author: str,
    ) -> MergeResult:
        """Perform three-way merge."""
        # Get trees
        base_commit = await self.object_store.get_commit(base)
        source_commit = await self.object_store.get_commit(source)
        target_commit = await self.object_store.get_commit(target)
        
        base_tree = await self.object_store.get_tree(base_commit.tree) if base_commit else None
        source_tree = await self.object_store.get_tree(source_commit.tree)
        target_tree = await self.object_store.get_tree(target_commit.tree)
        
        # Merge trees
        merged_tree, conflicts = await self.branch_manager.merge_trees(
            base_tree,
            source_tree,
            target_tree,
            strategy
        )
        
        # Initialize auto_resolved counter
        auto_resolved_count = 0
        
        if conflicts:
            # Try to auto-resolve conflicts
            auto_resolved = []
            for conflict in conflicts:
                resolved = await self.conflict_resolver.resolve_conflict(
                    conflict,
                    ConflictResolutionStrategy.AUTO
                )
                if resolved.object_data:
                    auto_resolved.append(conflict)
            
            # Remove auto-resolved conflicts from the conflicts list
            # We need to remove the actual MergeConflict, not the ResolvedObject
            for conflict in auto_resolved:
                if conflict in conflicts:
                    conflicts.remove(conflict)
            
            # Update counter
            auto_resolved_count = len(auto_resolved)
        
        if not conflicts:
            # Create merge commit
            merge_message = f"Merge branch '{source_branch}' into '{target_branch}'"
            merge_commit = await self.commit_manager.create_merge_commit(
                tree_hash=merged_tree,
                parent_hashes=[target, source],
                message=merge_message,
                author=author
            )
            
            # Update target branch
            await self.branch_manager.update_branch(target_branch, merge_commit)
            
            return MergeResult(
                success=True,
                commit_hash=merge_commit,
                conflicts=[],
                merged_tree=merged_tree,
                strategy_used=strategy,
                auto_resolved_count=auto_resolved_count
            )
        else:
            return MergeResult(
                success=False,
                commit_hash=None,
                conflicts=conflicts,
                merged_tree=merged_tree,
                strategy_used=strategy,
                auto_resolved_count=auto_resolved_count
            )
    
    async def _reconstruct_document_from_tree(self, tree: Tree) -> Optional[Path]:
        """
        Reconstruct FreeCAD document from tree.
        
        This method takes a tree object (containing FreeCAD object data)
        and reconstructs a FreeCAD document file from it.
        
        Args:
            tree: Tree object containing document structure
            
        Returns:
            Path to reconstructed document file, or None if reconstruction fails
        """
        try:
            if not tree:
                logger.warning("Cannot reconstruct document from empty tree")
                return None
            
            # Create temporary file for reconstructed document
            temp_path = Path(tempfile.gettempdir()) / f"reconstructed_{uuid4().hex[:8]}.FCStd"
            
            # Get tree entries (objects in the document) - use attribute access
            entries = tree.entries if hasattr(tree, 'entries') else []
            if not entries:
                logger.warning("Tree has no entries to reconstruct")
                return None
            
            # Create new document using document manager
            doc_id = f"reconstruct_{uuid4().hex[:8]}"
            doc_handle = await asyncio.to_thread(
                self.doc_manager.create_document, 
                doc_id
            )
            
            if not doc_handle:
                logger.error("Failed to create document for reconstruction")
                return None
            
            # Reconstruct objects in document
            for entry in entries:
                # TreeEntry has object_type field as direct attribute
                # Check if entry is a TreeEntry object or dict for compatibility
                if hasattr(entry, 'object_type'):
                    # TreeEntry object
                    if entry.object_type == ObjectType.BLOB:
                        # Get object data from object store
                        obj_hash = entry.hash
                        if obj_hash:
                            obj_data = await self.object_store.get_object(obj_hash)
                            if obj_data and isinstance(obj_data, dict):
                                # Reconstruct object in document
                                await self._reconstruct_object_in_document(
                                    doc_handle, 
                                    entry.name,
                                    obj_data
                                )
                elif isinstance(entry, dict):
                    # Dictionary (backward compatibility)
                    if entry.get("object_type") == ObjectType.BLOB.value:
                        # Get object data from object store
                        obj_hash = entry.get("hash")
                        if obj_hash:
                            obj_data = await self.object_store.get_object(obj_hash)
                            if obj_data and isinstance(obj_data, dict):
                                # Reconstruct object in document
                                await self._reconstruct_object_in_document(
                                    doc_handle, 
                                    entry.get("name", "Object"),
                                    obj_data
                                )
            
            # Save reconstructed document
            await asyncio.to_thread(
                self.doc_manager.save_document,
                doc_id,
                owner_id="system"  # System owner for reconstruction
            )
            
            # Get the saved document path
            saved_path = self.doc_manager.get_document_path(doc_id)
            if saved_path and saved_path.exists():
                # Move to our temp location
                await asyncio.to_thread(shutil.move, str(saved_path), str(temp_path))
                
                logger.info(
                    "document_reconstructed_from_tree",
                    tree_entries=len(entries),
                    document_path=str(temp_path)
                )
                
                return temp_path
            
            logger.warning("Failed to get saved document path")
            return None
            
        except Exception as e:
            logger.error(
                "document_reconstruction_failed",
                error=str(e),
                tree_entries=len(tree.get("entries", []))
            )
            return None
    
    async def _reconstruct_object_in_document(
        self, 
        doc_handle: Any, 
        obj_name: str, 
        obj_data: Dict[str, Any]
    ) -> bool:
        """
        Reconstruct a single object in a FreeCAD document.
        
        Args:
            doc_handle: FreeCAD document handle
            obj_name: Name for the object
            obj_data: Object data dictionary
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Extract FreeCAD object data - it's a FreeCADObjectData model
            # The fields are directly in obj_data, not nested under "freecad_data"
            if obj_data:
                # Use type_id field (correct field name from FreeCADObjectData model)
                obj_type = obj_data.get("type_id", "Part::Feature")
                
                # Use document manager to create object
                # This is simplified - actual implementation would need to
                # handle different object types properly
                if hasattr(doc_handle, "addObject"):
                    new_obj = await asyncio.to_thread(
                        doc_handle.addObject,
                        obj_type,
                        obj_name
                    )
                    
                    # Set object properties
                    if new_obj and "properties" in obj_data:
                        for prop_name, prop_value in obj_data["properties"].items():
                            if hasattr(new_obj, prop_name):
                                try:
                                    setattr(new_obj, prop_name, prop_value)
                                except Exception as e:
                                    logger.debug(
                                        "property_set_failed",
                                        property=prop_name,
                                        error=str(e)
                                    )
                    
                    # Handle shape data if present (FreeCADObjectData has shape_data field)
                    if "shape_data" in obj_data:
                        # This would require proper geometry reconstruction
                        # based on the FreeCAD object type
                        pass
                    
                    return True
            
            return False
            
        except Exception as e:
            logger.error(
                "object_reconstruction_failed",
                object_name=obj_name,
                error=str(e)
            )
            return False
    
    async def cleanup(self):
        """Cleanup resources."""
        try:
            await asyncio.to_thread(self.doc_manager.shutdown)
            await self.object_store.cleanup()
            logger.info("model_version_control_cleanup_complete")
        except Exception as e:
            logger.error("cleanup_failed", error=str(e))