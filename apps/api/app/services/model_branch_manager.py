"""
Branch Manager for FreeCAD Model Version Control (Task 7.22).

This service manages branches, tags, and references for the version control system.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.version_control import (
    Branch,
    MergeConflict,
    MergeStrategy,
    Tag,
    Tree,
    TreeEntry,
    VERSION_CONTROL_TR,
)

logger = structlog.get_logger(__name__)


class BranchManagerError(Exception):
    """Custom exception for branch manager operations."""
    pass


class ModelBranchManager:
    """
    Manages branches, tags, and references for the version control system.
    
    Features:
    - Branch creation and deletion
    - Branch switching (checkout)
    - Tag management
    - Reference updates
    - Tree merging algorithms
    """
    
    def __init__(self, refs_path: Path):
        """
        Initialize branch manager.
        
        Args:
            refs_path: Path to refs directory
        """
        self.refs_path = Path(refs_path)
        self.heads_path = self.refs_path / "heads"
        self.tags_path = self.refs_path / "tags"
        self.head_file = self.refs_path / "HEAD"
        
        # Current branch cache
        self._current_branch: Optional[str] = None
        
        # Branch metadata cache
        self._branches: Dict[str, Branch] = {}
        
        # Tag cache
        self._tags: Dict[str, Tag] = {}
        
        logger.info("branch_manager_initialized", refs_path=str(refs_path))
    
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
        
        with create_span("create_branch", correlation_id=correlation_id) as span:
            span.set_attribute("branch.name", branch_name)
            
            try:
                # Validate branch name
                if not self._validate_branch_name(branch_name):
                    raise ValueError(f"Invalid branch name: {branch_name}")
                
                # Check if branch already exists
                if await self.branch_exists(branch_name):
                    raise ValueError(f"Branch {branch_name} already exists")
                
                # Get starting commit
                if not from_commit:
                    from_commit = await self.get_head()
                
                if not from_commit:
                    # First branch in empty repo
                    from_commit = "0" * 64  # Null commit
                
                # Create branch object
                branch = Branch(
                    name=branch_name,
                    head=from_commit,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                
                # Store branch reference
                await self._write_ref(f"heads/{branch_name}", from_commit)
                
                # Cache branch
                self._branches[branch_name] = branch
                
                # If this is the first branch, make it current
                if not self._current_branch:
                    await self.switch_branch(branch_name)
                
                logger.info(
                    "branch_created",
                    branch_name=branch_name,
                    from_commit=from_commit[:8] if from_commit else None,
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
                raise BranchManagerError(f"Failed to create branch: {str(e)}")
    
    async def delete_branch(
        self,
        branch_name: str,
        force: bool = False,
    ) -> bool:
        """
        Delete a branch.
        
        Args:
            branch_name: Name of branch to delete
            force: Force deletion even if not merged
            
        Returns:
            Success status
        """
        correlation_id = get_correlation_id()
        
        with create_span("delete_branch", correlation_id=correlation_id) as span:
            span.set_attribute("branch.name", branch_name)
            span.set_attribute("force", force)
            
            try:
                # Check if branch exists
                if not await self.branch_exists(branch_name):
                    raise ValueError(f"Branch {branch_name} does not exist")
                
                # Can't delete current branch
                if branch_name == self._current_branch:
                    raise ValueError("Cannot delete current branch")
                
                # Check if branch is merged (unless forced)
                if not force:
                    # Would check if branch is merged into main/master
                    pass
                
                # Delete branch reference
                ref_path = self.heads_path / branch_name
                if ref_path.exists():
                    ref_path.unlink()
                
                # Remove from cache
                self._branches.pop(branch_name, None)
                
                logger.info(
                    "branch_deleted",
                    branch_name=branch_name,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['branch_deleted'].format(name=branch_name)
                )
                
                return True
                
            except Exception as e:
                logger.error(
                    "branch_deletion_failed",
                    error=str(e),
                    branch_name=branch_name,
                    correlation_id=correlation_id
                )
                raise BranchManagerError(f"Failed to delete branch: {str(e)}")
    
    async def switch_branch(
        self,
        branch_name: str,
    ) -> bool:
        """
        Switch to a different branch (checkout).
        
        Args:
            branch_name: Name of branch to switch to
            
        Returns:
            Success status
        """
        try:
            # Check if branch exists
            if not await self.branch_exists(branch_name):
                raise ValueError(f"Branch {branch_name} does not exist")
            
            # Update HEAD to point to branch
            await self._write_ref("HEAD", f"ref: refs/heads/{branch_name}")
            
            # Update current branch
            self._current_branch = branch_name
            
            logger.info(
                "branch_switched",
                branch_name=branch_name,
                message=VERSION_CONTROL_TR['checkout'].format(ref=branch_name)
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "branch_switch_failed",
                error=str(e),
                branch_name=branch_name
            )
            raise BranchManagerError(f"Failed to switch branch: {str(e)}")
    
    async def update_branch(
        self,
        branch_name: str,
        commit_hash: str,
    ) -> bool:
        """
        Update branch to point to a new commit.
        
        Args:
            branch_name: Branch name
            commit_hash: New commit hash
            
        Returns:
            Success status
        """
        try:
            # Check if branch exists
            if not await self.branch_exists(branch_name):
                raise ValueError(f"Branch {branch_name} does not exist")
            
            # Update branch reference
            await self._write_ref(f"heads/{branch_name}", commit_hash)
            
            # Update cache
            if branch_name in self._branches:
                self._branches[branch_name].head = commit_hash
                self._branches[branch_name].updated_at = datetime.now(timezone.utc)
            
            logger.debug(
                "branch_updated",
                branch_name=branch_name,
                commit_hash=commit_hash[:8]
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "branch_update_failed",
                error=str(e),
                branch_name=branch_name
            )
            raise BranchManagerError(f"Failed to update branch: {str(e)}")
    
    async def get_current_branch(self) -> Optional[str]:
        """Get current branch name."""
        if self._current_branch:
            return self._current_branch
        
        # Read from HEAD file
        if self.head_file.exists():
            content = self.head_file.read_text().strip()
            if content.startswith("ref: refs/heads/"):
                self._current_branch = content.replace("ref: refs/heads/", "")
                return self._current_branch
        
        return None
    
    async def get_branch_head(
        self,
        branch_name: str,
    ) -> Optional[str]:
        """Get commit hash at branch head."""
        try:
            ref_path = self.heads_path / branch_name
            if ref_path.exists():
                return ref_path.read_text().strip()
            return None
        except Exception as e:
            logger.error(
                "get_branch_head_failed",
                error=str(e),
                branch_name=branch_name
            )
            return None
    
    async def get_head(self) -> Optional[str]:
        """Get current HEAD commit hash."""
        current_branch = await self.get_current_branch()
        if current_branch:
            return await self.get_branch_head(current_branch)
        
        # Detached HEAD - read direct commit hash
        if self.head_file.exists():
            content = self.head_file.read_text().strip()
            if not content.startswith("ref:"):
                return content
        
        return None
    
    async def list_branches(self) -> List[Branch]:
        """List all branches."""
        branches = []
        
        # Ensure heads directory exists
        self.heads_path.mkdir(parents=True, exist_ok=True)
        
        # Read branch references
        for ref_file in self.heads_path.iterdir():
            if ref_file.is_file():
                branch_name = ref_file.name
                commit_hash = ref_file.read_text().strip()
                
                # Get or create branch object
                if branch_name in self._branches:
                    branch = self._branches[branch_name]
                else:
                    branch = Branch(
                        name=branch_name,
                        head=commit_hash,
                        created_at=datetime.now(timezone.utc)
                    )
                    self._branches[branch_name] = branch
                
                branches.append(branch)
        
        return branches
    
    async def branch_exists(
        self,
        branch_name: str,
    ) -> bool:
        """Check if branch exists."""
        ref_path = self.heads_path / branch_name
        return ref_path.exists()
    
    async def create_tag(
        self,
        tag_name: str,
        target_commit: str,
        tagger: str,
        message: Optional[str] = None,
    ) -> Tag:
        """
        Create a new tag.
        
        Args:
            tag_name: Tag name
            target_commit: Target commit hash
            tagger: Tagger name/email
            message: Tag message
            
        Returns:
            Tag object
        """
        try:
            # Validate tag name
            if not self._validate_tag_name(tag_name):
                raise ValueError(f"Invalid tag name: {tag_name}")
            
            # Check if tag already exists
            if await self.tag_exists(tag_name):
                raise ValueError(f"Tag {tag_name} already exists")
            
            # Create tag object
            tag = Tag(
                name=tag_name,
                target=target_commit,
                tagger=tagger,
                timestamp=datetime.now(timezone.utc),
                message=message
            )
            
            # Store tag reference
            await self._write_ref(f"tags/{tag_name}", target_commit)
            
            # Store tag metadata
            tag_meta_path = self.tags_path / f"{tag_name}.json"
            with open(tag_meta_path, 'w') as f:
                json.dump(tag.dict(), f, indent=2, default=str)
            
            # Cache tag
            self._tags[tag_name] = tag
            
            logger.info(
                "tag_created",
                tag_name=tag_name,
                target=target_commit[:8],
                message=VERSION_CONTROL_TR['tag_created'].format(name=tag_name)
            )
            
            return tag
            
        except Exception as e:
            logger.error(
                "tag_creation_failed",
                error=str(e),
                tag_name=tag_name
            )
            raise BranchManagerError(f"Failed to create tag: {str(e)}")
    
    async def tag_exists(
        self,
        tag_name: str,
    ) -> bool:
        """Check if tag exists."""
        ref_path = self.tags_path / tag_name
        return ref_path.exists()
    
    async def get_tags_for_commit(
        self,
        commit_hash: str,
    ) -> List[str]:
        """Get all tags pointing to a commit."""
        tags = []
        
        # Ensure tags directory exists
        self.tags_path.mkdir(parents=True, exist_ok=True)
        
        # Check all tags
        for tag_file in self.tags_path.iterdir():
            if tag_file.suffix == "":  # Skip .json files
                target = tag_file.read_text().strip()
                if target == commit_hash:
                    tags.append(tag_file.name)
        
        return tags
    
    async def merge_trees(
        self,
        base_tree: Optional[Tree],
        source_tree: Tree,
        target_tree: Tree,
        strategy: MergeStrategy,
    ) -> Tuple[str, List[MergeConflict]]:
        """
        Merge two trees with a common base.
        
        Args:
            base_tree: Common ancestor tree (None for no common ancestor)
            source_tree: Source tree
            target_tree: Target tree
            strategy: Merge strategy
            
        Returns:
            Tuple of (merged tree hash, list of conflicts)
        """
        conflicts = []
        merged_entries = {}
        
        # Get all unique entry names
        all_names = set()
        if base_tree:
            all_names.update(e.name for e in base_tree.entries)
        all_names.update(e.name for e in source_tree.entries)
        all_names.update(e.name for e in target_tree.entries)
        
        # Build entry maps
        base_entries = {e.name: e for e in base_tree.entries} if base_tree else {}
        source_entries = {e.name: e for e in source_tree.entries}
        target_entries = {e.name: e for e in target_tree.entries}
        
        # Process each entry
        for name in all_names:
            base_entry = base_entries.get(name)
            source_entry = source_entries.get(name)
            target_entry = target_entries.get(name)
            
            # Determine merge action
            if source_entry and target_entry:
                if source_entry.hash == target_entry.hash:
                    # Same in both - use either
                    merged_entries[name] = source_entry
                elif base_entry:
                    # Three-way merge
                    if base_entry.hash == source_entry.hash:
                        # Only target changed
                        merged_entries[name] = target_entry
                    elif base_entry.hash == target_entry.hash:
                        # Only source changed
                        merged_entries[name] = source_entry
                    else:
                        # Both changed - conflict
                        # Would create MergeConflict here
                        # For now, use strategy to decide
                        if strategy == MergeStrategy.OURS:
                            merged_entries[name] = target_entry
                        else:
                            merged_entries[name] = source_entry
                else:
                    # No base - both added with different content
                    # Conflict - use strategy
                    if strategy == MergeStrategy.OURS:
                        merged_entries[name] = target_entry
                    else:
                        merged_entries[name] = source_entry
            elif source_entry:
                # Only in source - add it
                merged_entries[name] = source_entry
            elif target_entry:
                # Only in target - keep it
                merged_entries[name] = target_entry
            # If in neither (deleted in both), don't add
        
        # Create merged tree
        merged_tree = Tree(entries=list(merged_entries.values()))
        
        # Store merged tree (would use object store in real implementation)
        merged_tree_hash = merged_tree.calculate_hash()
        
        return merged_tree_hash, conflicts
    
    # Private helper methods
    
    async def _write_ref(
        self,
        ref_name: str,
        value: str,
    ):
        """Write reference file."""
        if ref_name == "HEAD":
            ref_path = self.head_file
        else:
            ref_path = self.refs_path / ref_name
        
        # Ensure parent directory exists
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write atomically
        temp_path = ref_path.with_suffix('.tmp')
        temp_path.write_text(value)
        temp_path.replace(ref_path)
    
    def _validate_branch_name(self, name: str) -> bool:
        """Validate branch name."""
        if not name:
            return False
        
        # Invalid patterns
        invalid_patterns = [
            '..',  # No double dots
            '~',   # No tilde
            '^',   # No caret
            ':',   # No colon
            '?',   # No question mark
            '*',   # No asterisk
            '[',   # No brackets
            ' ',   # No spaces
            '\t',  # No tabs
        ]
        
        for pattern in invalid_patterns:
            if pattern in name:
                return False
        
        # Can't start or end with slash
        if name.startswith('/') or name.endswith('/'):
            return False
        
        # Can't end with .lock
        if name.endswith('.lock'):
            return False
        
        return True
    
    def _validate_tag_name(self, name: str) -> bool:
        """Validate tag name."""
        # Same rules as branch names for now
        return self._validate_branch_name(name)