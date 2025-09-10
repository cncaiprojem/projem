"""
Tests for FreeCAD Model Version Control System (Task 7.22).

This module tests the Git-like version control functionality for FreeCAD models.
"""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.version_control import (
    Branch,
    Commit,
    ConflictResolutionStrategy,
    FreeCADObjectData,
    MergeConflict,
    MergeStrategy,
    ObjectType,
    Tree,
    TreeEntry,
)
from app.services.model_version_control import ModelVersionControl, ModelVersionControlError
from app.services.model_object_store import ModelObjectStore
from app.services.model_commit_manager import ModelCommitManager
from app.services.model_branch_manager import ModelBranchManager
from app.services.model_differ import ModelDiffer
from app.services.model_conflict_resolver import ModelConflictResolver


@pytest.fixture
def temp_repo_path():
    """Create temporary repository path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def vcs(temp_repo_path):
    """Create ModelVersionControl instance."""
    return ModelVersionControl(repository_path=temp_repo_path, use_real_freecad=False)


@pytest.fixture
def object_store(temp_repo_path):
    """Create ModelObjectStore instance."""
    return ModelObjectStore(temp_repo_path / ".mvcstore")


@pytest.fixture
def sample_freecad_object():
    """Create sample FreeCAD object data."""
    return FreeCADObjectData(
        type_id="Part::Box",
        name="Box001",
        label="Test Box",
        properties={
            "Length": 10.0,
            "Width": 5.0,
            "Height": 3.0,
            "Placement": {
                "Position": [0, 0, 0],
                "Rotation": [0, 0, 0, 1]
            }
        },
        placement=None,
        shape_data={
            "volume": 150.0,
            "area": 190.0,
            "vertex_count": 8,
            "edge_count": 12,
            "face_count": 6
        },
        expressions={
            "Height": "Length * 0.3"
        },
        visibility=True
    )


@pytest.fixture
def sample_tree(sample_freecad_object):
    """Create sample tree with objects."""
    entries = [
        TreeEntry(
            name="Box001",
            hash="abc123def456",
            mode="100644",
            object_type=ObjectType.BLOB
        ),
        TreeEntry(
            name="Cylinder001",
            hash="789xyz012",
            mode="100644",
            object_type=ObjectType.BLOB
        )
    ]
    return Tree(entries=entries)


class TestModelVersionControl:
    """Test ModelVersionControl functionality."""
    
    @pytest.mark.asyncio
    async def test_init_repository(self, vcs):
        """Test repository initialization."""
        # Initialize repository
        repo = await vcs.init_repository(
            name="test_repo",
            description="Test repository"
        )
        
        # Verify repository created
        assert repo.name == "test_repo"
        assert repo.description == "Test repository"
        assert repo.default_branch == "main"
        assert repo.id is not None
        
        # Verify directory structure created
        assert vcs.repo_path.exists()
        assert (vcs.repo_path / ".mvcstore").exists()
        assert (vcs.repo_path / ".mvcstore" / "refs").exists()
    
    @pytest.mark.asyncio
    async def test_commit_changes(self, vcs):
        """Test committing changes."""
        # Initialize repository
        await vcs.init_repository()
        
        # Create and commit changes
        commit_hash = await vcs.commit_changes(
            job_id="job_123",
            message="Initial commit",
            author="Test User <test@example.com>",
            metadata={"version": "1.0"}
        )
        
        # Verify commit created
        assert commit_hash is not None
        assert len(commit_hash) == 64  # SHA-256 hash
        
        # Verify commit can be retrieved
        commit = await vcs.object_store.get_commit(commit_hash)
        assert commit is not None
    
    @pytest.mark.asyncio
    async def test_create_branch(self, vcs):
        """Test branch creation."""
        # Initialize repository
        await vcs.init_repository()
        
        # Create initial commit
        commit_hash = await vcs.commit_changes(
            job_id="job_123",
            message="Initial commit",
            author="Test User"
        )
        
        # Create branch
        branch = await vcs.create_branch(
            branch_name="feature/test",
            from_commit=commit_hash
        )
        
        # Verify branch created
        assert branch.name == "feature/test"
        assert branch.head == commit_hash
        assert branch.created_at is not None
    
    @pytest.mark.asyncio
    async def test_merge_branches_fast_forward(self, vcs):
        """Test fast-forward merge."""
        # Initialize repository
        await vcs.init_repository()
        
        # Create initial commit on main
        commit1 = await vcs.commit_changes(
            job_id="job_123",
            message="Initial commit",
            author="Test User"
        )
        
        # Create feature branch
        await vcs.create_branch("feature/test", commit1)
        await vcs.branch_manager.switch_branch("feature/test")
        
        # Make commit on feature branch
        commit2 = await vcs.commit_changes(
            job_id="job_123",
            message="Feature commit",
            author="Test User"
        )
        
        # Switch back to main
        await vcs.branch_manager.switch_branch("main")
        
        # Merge feature into main (should be fast-forward)
        result = await vcs.merge_branches(
            source_branch="feature/test",
            target_branch="main",
            strategy=MergeStrategy.RECURSIVE
        )
        
        # Verify merge succeeded
        assert result.success is True
        assert result.commit_hash == commit2
        assert len(result.conflicts) == 0
    
    @pytest.mark.asyncio
    async def test_checkout_commit(self, vcs):
        """Test checking out a commit."""
        # Initialize repository
        await vcs.init_repository()
        
        # Create commits
        commit1 = await vcs.commit_changes(
            job_id="job_123",
            message="First commit",
            author="Test User"
        )
        
        commit2 = await vcs.commit_changes(
            job_id="job_123",
            message="Second commit",
            author="Test User"
        )
        
        # Checkout first commit
        result = await vcs.checkout_commit(
            commit_hash=commit1,
            create_branch=True,
            branch_name="rollback"
        )
        
        # Verify checkout succeeded
        assert result.success is True
        assert result.commit_hash == commit1
        assert result.branch == "rollback"
    
    @pytest.mark.asyncio
    async def test_get_history(self, vcs):
        """Test getting commit history."""
        # Initialize repository
        await vcs.init_repository()
        
        # Create multiple commits
        commits = []
        for i in range(5):
            commit_hash = await vcs.commit_changes(
                job_id="job_123",
                message=f"Commit {i+1}",
                author="Test User"
            )
            commits.append(commit_hash)
        
        # Get history
        history = await vcs.get_history(limit=10)
        
        # Verify history
        assert len(history) == 5
        assert history[0].message == "Commit 5"  # Most recent first
        assert history[4].message == "Commit 1"  # Oldest last
    
    @pytest.mark.asyncio
    async def test_rollback_to_commit(self, vcs):
        """Test rolling back to a previous commit."""
        # Initialize repository
        await vcs.init_repository()
        
        # Create commits
        commit1 = await vcs.commit_changes(
            job_id="job_123",
            message="First commit",
            author="Test User"
        )
        
        commit2 = await vcs.commit_changes(
            job_id="job_123",
            message="Second commit",
            author="Test User"
        )
        
        commit3 = await vcs.commit_changes(
            job_id="job_123",
            message="Third commit",
            author="Test User"
        )
        
        # Rollback to first commit
        success = await vcs.rollback_to_commit(commit_hash=commit1)
        
        # Verify rollback
        assert success is True
        
        # Verify current HEAD is at first commit
        current_head = await vcs.branch_manager.get_head()
        assert current_head == commit1


class TestModelObjectStore:
    """Test ModelObjectStore functionality."""
    
    @pytest.mark.asyncio
    async def test_store_and_retrieve_object(self, object_store, sample_freecad_object):
        """Test storing and retrieving objects."""
        # Initialize store
        await object_store.init_store()
        
        # Store object
        obj_hash = await object_store.store_freecad_object(sample_freecad_object)
        
        # Verify hash
        assert obj_hash is not None
        assert len(obj_hash) == 64
        
        # Retrieve object
        retrieved = await object_store.get_freecad_object(obj_hash)
        
        # Verify retrieved object matches (as dict for now)
        assert retrieved is not None
        assert retrieved["name"] == sample_freecad_object.name
        assert retrieved["type_id"] == sample_freecad_object.type_id
    
    @pytest.mark.asyncio
    async def test_store_tree(self, object_store, sample_tree):
        """Test storing and retrieving trees."""
        # Initialize store
        await object_store.init_store()
        
        # Store tree
        tree_hash = await object_store.store_tree(sample_tree)
        
        # Verify hash
        assert tree_hash is not None
        assert len(tree_hash) == 64
        
        # Retrieve tree
        retrieved = await object_store.get_tree(tree_hash)
        
        # Verify retrieved tree
        assert retrieved is not None
        assert len(retrieved["entries"]) == 2
    
    @pytest.mark.asyncio
    async def test_object_compression(self, object_store, sample_freecad_object):
        """Test that objects are compressed."""
        # Initialize store
        await object_store.init_store()
        
        # Store object
        obj_hash = await object_store.store_object(
            sample_freecad_object,
            ObjectType.BLOB
        )
        
        # Check that file is compressed
        path = object_store._get_object_path(obj_hash)
        assert path.exists()
        
        # Read raw file
        with open(path, 'rb') as f:
            data = f.read()
        
        # Verify it's gzip compressed (starts with gzip magic number)
        assert data[:2] == b'\x1f\x8b'


class TestModelDiffer:
    """Test ModelDiffer functionality."""
    
    def test_diff_objects_modified(self, sample_freecad_object):
        """Test diffing modified objects."""
        differ = ModelDiffer()
        
        # Create modified version
        modified = FreeCADObjectData(**sample_freecad_object.model_dump())
        modified.properties["Length"] = 20.0  # Changed
        modified.properties["Color"] = "Red"  # Added
        
        # Calculate diff
        diff = differ.diff_objects(sample_freecad_object, modified)
        
        # Verify diff
        assert diff.object_id == sample_freecad_object.name
        assert len(diff.property_changes) == 2
        
        # Find specific changes
        length_change = next(
            (c for c in diff.property_changes if c.property == "Length"),
            None
        )
        assert length_change is not None
        assert length_change.old_value == 10.0
        assert length_change.new_value == 20.0
    
    def test_diff_shapes(self, sample_freecad_object):
        """Test diffing shapes."""
        differ = ModelDiffer()
        
        # Create modified version with shape changes
        modified = FreeCADObjectData(**sample_freecad_object.model_dump())
        modified.shape_data["volume"] = 200.0  # Increased volume
        modified.shape_data["vertex_count"] = 10  # More vertices
        
        # Calculate diff
        diff = differ.diff_objects(sample_freecad_object, modified)
        
        # Verify shape diff
        assert diff.shape_diff is not None
        assert diff.shape_diff.volume_change == pytest.approx(0.333, rel=0.01)
        assert diff.shape_diff.vertex_count_change == 2


class TestModelConflictResolver:
    """Test ModelConflictResolver functionality."""
    
    @pytest.mark.asyncio
    async def test_resolve_keep_ours(self, sample_freecad_object):
        """Test keeping our version in conflict resolution."""
        resolver = ModelConflictResolver()
        
        # Create conflict
        our_version = FreeCADObjectData(**sample_freecad_object.model_dump())
        their_version = FreeCADObjectData(**sample_freecad_object.model_dump())
        their_version.properties["Length"] = 15.0
        
        conflict = MergeConflict(
            object_id="Box001",
            base_version=sample_freecad_object,
            our_version=our_version,
            their_version=their_version,
            conflict_type="property_conflict",
            auto_resolvable=False
        )
        
        # Resolve keeping ours
        resolved = await resolver.resolve_conflict(
            conflict,
            ConflictResolutionStrategy.OURS
        )
        
        # Verify resolution
        assert resolved.object_data == our_version
        assert resolved.resolution_type == "keep_ours"
    
    @pytest.mark.asyncio
    async def test_auto_resolve_numeric(self, sample_freecad_object):
        """Test automatic resolution of numeric conflicts."""
        resolver = ModelConflictResolver()
        
        # Create numeric conflict
        base = FreeCADObjectData(**sample_freecad_object.model_dump())
        our_version = FreeCADObjectData(**sample_freecad_object.model_dump())
        our_version.properties["Length"] = 12.0
        their_version = FreeCADObjectData(**sample_freecad_object.model_dump())
        their_version.properties["Length"] = 14.0
        
        conflict = MergeConflict(
            object_id="Box001",
            base_version=base,
            our_version=our_version,
            their_version=their_version,
            conflict_type="property_conflict",
            auto_resolvable=True
        )
        
        # Auto-resolve
        resolved = await resolver.resolve_conflict(
            conflict,
            ConflictResolutionStrategy.AUTO
        )
        
        # Verify averaged value
        if resolved.object_data:
            assert resolved.object_data.properties["Length"] == 13.0  # Average of 12 and 14


class TestBranchManager:
    """Test ModelBranchManager functionality."""
    
    @pytest.mark.asyncio
    async def test_branch_operations(self, temp_repo_path):
        """Test branch creation, switching, and deletion."""
        branch_manager = ModelBranchManager(temp_repo_path / ".mvcstore" / "refs")
        
        # Create main branch
        main_branch = await branch_manager.create_branch("main")
        assert main_branch.name == "main"
        
        # Create feature branch
        feature_branch = await branch_manager.create_branch(
            "feature/test",
            from_commit="abc123"
        )
        assert feature_branch.name == "feature/test"
        assert feature_branch.head == "abc123"
        
        # Switch branch
        success = await branch_manager.switch_branch("feature/test")
        assert success is True
        
        # Verify current branch
        current = await branch_manager.get_current_branch()
        assert current == "feature/test"
        
        # List branches
        branches = await branch_manager.list_branches()
        assert len(branches) == 2
        
        # Delete branch (switch to main first)
        await branch_manager.switch_branch("main")
        success = await branch_manager.delete_branch("feature/test")
        assert success is True
        
        # Verify deleted
        branches = await branch_manager.list_branches()
        assert len(branches) == 1


@pytest.mark.asyncio
async def test_end_to_end_workflow(vcs):
    """Test complete version control workflow."""
    # Initialize repository
    repo = await vcs.init_repository(name="e2e_test")
    assert repo is not None
    
    # Make initial commit
    commit1 = await vcs.commit_changes(
        job_id="job_001",
        message="Initial project setup",
        author="Developer <dev@example.com>"
    )
    
    # Create feature branch
    feature_branch = await vcs.create_branch("feature/new-part")
    
    # Switch to feature branch
    await vcs.branch_manager.switch_branch("feature/new-part")
    
    # Make changes on feature branch
    commit2 = await vcs.commit_changes(
        job_id="job_001",
        message="Add new part design",
        author="Developer <dev@example.com>"
    )
    
    # Create another branch from main
    await vcs.branch_manager.switch_branch("main")
    bugfix_branch = await vcs.create_branch("bugfix/dimension-fix")
    
    # Make changes on bugfix branch
    await vcs.branch_manager.switch_branch("bugfix/dimension-fix")
    commit3 = await vcs.commit_changes(
        job_id="job_001",
        message="Fix dimension calculations",
        author="Developer <dev@example.com>"
    )
    
    # Merge bugfix into main
    await vcs.branch_manager.switch_branch("main")
    merge_result1 = await vcs.merge_branches(
        source_branch="bugfix/dimension-fix",
        target_branch="main"
    )
    assert merge_result1.success is True
    
    # Merge feature into main
    merge_result2 = await vcs.merge_branches(
        source_branch="feature/new-part",
        target_branch="main"
    )
    
    # Get final history
    history = await vcs.get_history()
    assert len(history) >= 3  # At least 3 commits
    
    # Verify we can checkout old commits
    checkout_result = await vcs.checkout_commit(commit1)
    assert checkout_result.success is True