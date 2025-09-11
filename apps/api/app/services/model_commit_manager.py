"""
Commit Manager for FreeCAD Model Version Control (Task 7.22).

This service manages commit creation, tree building, and commit operations
for the version control system.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import uuid4

import structlog

from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.version_control import (
    Commit,
    FreeCADObjectData,
    ObjectType,
    Tree,
    TreeEntry,
    VERSION_CONTROL_TR,
)
from app.services.model_object_store import ModelObjectStore

if TYPE_CHECKING:
    from app.services.freecad_document_manager import FreeCADDocumentManager

logger = structlog.get_logger(__name__)


class CommitManagerError(Exception):
    """Custom exception for commit manager operations."""
    pass


class ModelCommitManager:
    """
    Manages commit operations for the version control system.
    
    Features:
    - Commit creation with tree structures
    - Tree building from FreeCAD documents
    - Merge commit support
    - Commit validation and integrity checks
    """
    
    def __init__(self, object_store: ModelObjectStore, document_manager: 'FreeCADDocumentManager'):
        """
        Initialize commit manager.
        
        Args:
            object_store: Object store for content storage
            document_manager: Document manager for FreeCAD operations (required)
        """
        self.object_store = object_store
        self.document_manager = document_manager
        
        logger.info("commit_manager_initialized")
    
    def create_commit(
        self,
        tree_hash: str,
        parent_hashes: List[str],
        author: str,
        message: str,
        committer: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Commit:
        """
        Create a new commit object.
        
        Args:
            tree_hash: Hash of the tree object
            parent_hashes: List of parent commit hashes
            author: Author name/email
            message: Commit message
            committer: Committer if different from author
            metadata: Additional metadata
            
        Returns:
            Commit object
        """
        commit = Commit(
            id=uuid4(),
            tree=tree_hash,
            parents=parent_hashes,
            author=author,
            committer=committer,
            timestamp=datetime.now(timezone.utc),
            message=message,
            metadata=metadata or {}
        )
        
        # Calculate commit hash
        commit.hash = commit.calculate_hash()
        
        logger.debug(
            "commit_created",
            commit_hash=commit.hash[:8] if commit.hash else None,
            tree=tree_hash[:8],
            parents=[p[:8] for p in parent_hashes],
            author=author
        )
        
        return commit
    
    async def commit_document(
        self,
        document_id: str,
        message: str,
        author: str,
        parent_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Commit current document state.
        
        Args:
            document_id: Document ID to commit
            message: Commit message
            author: Author name/email
            parent_hash: Parent commit hash (if any)
            metadata: Additional metadata
            
        Returns:
            Commit hash
        """
        correlation_id = get_correlation_id()
        
        with create_span("commit_document", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            span.set_attribute("author", author)
            
            try:
                # Build tree from document
                tree = await self.build_tree_from_document(document_id)
                
                # Store tree
                tree_hash = await self.object_store.store_tree(tree)
                
                # Create commit
                parent_hashes = [parent_hash] if parent_hash else []
                commit = self.create_commit(
                    tree_hash=tree_hash,
                    parent_hashes=parent_hashes,
                    author=author,
                    message=message,
                    metadata=metadata
                )
                
                # Store commit
                commit_hash = await self.object_store.store_commit(commit)
                
                logger.info(
                    "document_committed",
                    commit_hash=commit_hash[:8],
                    document_id=document_id,
                    tree_hash=tree_hash[:8],
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['commit_created'].format(hash=commit_hash[:8])
                )
                
                metrics.freecad_vcs_commits_total.inc()
                
                return commit_hash
                
            except Exception as e:
                logger.error(
                    "commit_failed",
                    error=str(e),
                    document_id=document_id,
                    correlation_id=correlation_id
                )
                raise CommitManagerError(f"Failed to commit document: {str(e)}")
    
    async def create_merge_commit(
        self,
        tree_hash: str,
        parent_hashes: List[str],
        message: str,
        author: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a merge commit with multiple parents.
        
        Args:
            tree_hash: Hash of merged tree
            parent_hashes: List of parent commit hashes (usually 2)
            message: Merge commit message
            author: Author name/email
            metadata: Additional metadata
            
        Returns:
            Merge commit hash
        """
        correlation_id = get_correlation_id()
        
        with create_span("create_merge_commit", correlation_id=correlation_id) as span:
            span.set_attribute("parents.count", len(parent_hashes))
            
            try:
                # Validate parents
                if len(parent_hashes) < 2:
                    raise ValueError("Merge commit requires at least 2 parents")
                
                # Create merge commit
                commit = self.create_commit(
                    tree_hash=tree_hash,
                    parent_hashes=parent_hashes,
                    author=author,
                    message=message,
                    metadata={
                        **(metadata or {}),
                        "is_merge": True,
                        "merge_timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
                
                # Store commit
                commit_hash = await self.object_store.store_commit(commit)
                
                logger.info(
                    "merge_commit_created",
                    commit_hash=commit_hash[:8],
                    parents=[p[:8] for p in parent_hashes],
                    correlation_id=correlation_id
                )
                
                metrics.freecad_vcs_merge_commits_total.inc()
                
                return commit_hash
                
            except Exception as e:
                logger.error(
                    "merge_commit_failed",
                    error=str(e),
                    correlation_id=correlation_id
                )
                raise CommitManagerError(f"Failed to create merge commit: {str(e)}")
    
    async def build_tree_from_document(
        self,
        document_id: str,
    ) -> Tree:
        """
        Build tree object from FreeCAD document.
        
        Args:
            document_id: Document ID
            
        Returns:
            Tree object
        """
        correlation_id = get_correlation_id()
        
        with create_span("build_tree_from_document", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            
            try:
                # Get document from document manager
                doc_manager = self.document_manager
                
                # Check if document exists
                if document_id not in doc_manager.documents:
                    raise ValueError(f"Document {document_id} not found")
                
                # Get document handle if available
                doc_handle = doc_manager._doc_handles.get(document_id)
                
                entries = []
                
                if doc_handle:
                    # Real FreeCAD document
                    objects = await self._extract_freecad_objects(doc_handle)
                    
                    for obj_name, obj_data in objects.items():
                        # Store object
                        obj_hash = await self.object_store.store_freecad_object(obj_data)
                        
                        # Create tree entry
                        entry = TreeEntry(
                            name=obj_name,
                            hash=obj_hash,
                            mode="100644",  # Regular file mode
                            object_type=ObjectType.BLOB
                        )
                        entries.append(entry)
                else:
                    # Mock document - use metadata
                    metadata = doc_manager.documents[document_id]
                    
                    # Create a single entry for document metadata
                    meta_data = FreeCADObjectData(
                        type_id="Document.Metadata",
                        name=document_id,
                        label=f"Document {document_id}",
                        properties=metadata.model_dump() if hasattr(metadata, 'model_dump') else metadata.dict(),
                        placement=None,
                        shape_data=None,
                        expressions={},
                        visibility=True
                    )
                    
                    meta_hash = await self.object_store.store_freecad_object(meta_data)
                    
                    entry = TreeEntry(
                        name="metadata",
                        hash=meta_hash,
                        mode="100644",
                        object_type=ObjectType.BLOB
                    )
                    entries.append(entry)
                
                # Create tree
                tree = Tree(entries=entries)
                
                logger.debug(
                    "tree_built",
                    document_id=document_id,
                    entries=len(entries),
                    correlation_id=correlation_id
                )
                
                return tree
                
            except Exception as e:
                logger.error(
                    "tree_build_failed",
                    error=str(e),
                    document_id=document_id,
                    correlation_id=correlation_id
                )
                raise CommitManagerError(f"Failed to build tree: {str(e)}")
    
    async def get_commit_tree(
        self,
        commit_hash: str,
    ) -> Optional[Tree]:
        """
        Get tree object for a commit.
        
        Args:
            commit_hash: Commit hash
            
        Returns:
            Tree object or None if not found
        """
        try:
            # Get commit
            commit = await self.object_store.get_commit(commit_hash)
            if not commit:
                return None
            
            # Get tree
            tree = await self.object_store.get_tree(commit.tree)
            return tree
            
        except Exception as e:
            logger.error(
                "get_commit_tree_failed",
                error=str(e),
                commit_hash=commit_hash
            )
            return None
    
    async def validate_commit(
        self,
        commit_hash: str,
    ) -> bool:
        """
        Validate commit integrity.
        
        Args:
            commit_hash: Commit hash to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # Get commit
            commit = await self.object_store.get_commit(commit_hash)
            if not commit:
                return False
            
            # Verify hash
            calculated_hash = commit.calculate_hash()
            if calculated_hash != commit.hash:
                logger.warning(
                    "commit_hash_mismatch",
                    stored_hash=commit.hash,
                    calculated_hash=calculated_hash
                )
                return False
            
            # Verify tree exists
            tree = await self.object_store.get_tree(commit.tree)
            if not tree:
                logger.warning(
                    "commit_tree_missing",
                    commit_hash=commit_hash,
                    tree_hash=commit.tree
                )
                return False
            
            # Verify parent commits exist
            for parent_hash in commit.parents:
                parent = await self.object_store.get_commit(parent_hash)
                if not parent:
                    logger.warning(
                        "commit_parent_missing",
                        commit_hash=commit_hash,
                        parent_hash=parent_hash
                    )
                    return False
            
            return True
            
        except Exception as e:
            logger.error(
                "commit_validation_failed",
                error=str(e),
                commit_hash=commit_hash
            )
            return False
    
    async def get_commit_history(
        self,
        commit_hash: str,
        limit: int = 100,
    ) -> List[Commit]:
        """
        Get commit history starting from a commit.
        
        Args:
            commit_hash: Starting commit hash
            limit: Maximum number of commits to return
            
        Returns:
            List of commits in history
        """
        history = []
        visited = set()
        current = commit_hash
        
        while current and len(history) < limit:
            # Avoid cycles
            if current in visited:
                break
            visited.add(current)
            
            # Get commit
            commit = await self.object_store.get_commit(current)
            if not commit:
                break
            
            history.append(commit)
            
            # Move to first parent
            current = commit.parents[0] if commit.parents else None
        
        return history
    
    # Private helper methods
    
    async def _extract_freecad_objects(
        self,
        doc_handle: Any,
    ) -> Dict[str, FreeCADObjectData]:
        """Extract FreeCAD objects from document."""
        objects = {}
        
        try:
            # Import FreeCAD adapter
            from app.services.freecad_document_manager import RealFreeCADAdapter
            adapter = RealFreeCADAdapter()
            
            # Take snapshot
            snapshot = adapter.take_snapshot(doc_handle)
            
            # Convert objects to FreeCADObjectData
            for obj_data in snapshot.get("objects", []):
                obj = FreeCADObjectData(
                    type_id=obj_data.get("TypeId", "Unknown"),
                    name=obj_data.get("Name", ""),
                    label=obj_data.get("Label", ""),
                    properties=obj_data.get("Properties", {}),
                    placement=None,  # Would extract placement data
                    shape_data=None,  # Would extract shape data
                    expressions={},  # Would extract expressions
                    visibility=True
                )
                objects[obj.name] = obj
                
        except Exception as e:
            logger.warning(
                "freecad_object_extraction_failed",
                error=str(e)
            )
        
        return objects