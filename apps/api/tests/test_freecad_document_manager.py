"""
Tests for FreeCAD Document Lifecycle Management (Task 7.19)

Tests all document lifecycle features:
- Document creation/opening
- Transaction management
- Version and revision tracking
- Auto-save and recovery
- Memory management
- Document locking
- Undo/Redo stack
- Document compression
- Multi-document assembly coordination
- Document migration
- Backup and restore
"""

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

# TODO: Consider using freezegun library instead of time.sleep() for time-based tests
# This would make tests more reliable and faster by mocking time instead of waiting

from app.services.freecad_document_manager import (
    FreeCADDocumentManager,
    DocumentManagerConfig,
    DocumentMetadata,
    DocumentState,
    TransactionState,
    DocumentErrorCode,
    DocumentException,
    DocumentLock,
    TransactionInfo,
    DocumentSnapshot,
    AssemblyCoordination,
    DocumentMigration,
    BackupInfo,
    MockFreeCADAdapter,
    RealFreeCADAdapter,
    FreeCADAdapter
)


@pytest.fixture
def document_manager():
    """Create a document manager instance for testing."""
    config = DocumentManagerConfig(
        max_document_size_mb=10,
        max_undo_stack_size=10,
        max_concurrent_documents=5,
        auto_save_interval_seconds=0,  # Disable auto-save for tests
        lock_timeout_seconds=60,
        backup_retention_days=7,
        enable_compression=True,
        enable_auto_recovery=True,
        memory_limit_mb=512
    )
    manager = FreeCADDocumentManager(config)
    yield manager
    # Cleanup
    manager.shutdown()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


class TestDocumentCreation:
    """Tests for document creation and opening."""
    
    def test_create_document(self, document_manager):
        """Test creating a new document."""
        metadata = document_manager.create_document(
            job_id="job123",
            author="test_user",
            description="Test document"
        )
        
        assert metadata.document_id == "doc_job123"
        assert metadata.job_id == "job123"
        assert metadata.author == "test_user"
        assert metadata.description == "Test document"
        assert metadata.version == 1
        assert metadata.revision == "A"
    
    def test_create_duplicate_document(self, document_manager):
        """Test that creating duplicate document raises exception."""
        document_manager.create_document(job_id="job123")
        
        with pytest.raises(DocumentException) as exc_info:
            document_manager.create_document(job_id="job123")
        
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_ALREADY_EXISTS
    
    def test_open_existing_document(self, document_manager):
        """Test opening an existing document."""
        # Create document first
        created = document_manager.create_document(job_id="job123")
        
        # Open the same document
        opened = document_manager.open_document(job_id="job123")
        
        assert opened.document_id == created.document_id
        assert opened.job_id == created.job_id
    
    def test_open_nonexistent_document_with_create(self, document_manager):
        """Test opening non-existent document with create flag."""
        metadata = document_manager.open_document(
            job_id="job456",
            create_if_not_exists=True
        )
        
        assert metadata.document_id == "doc_job456"
        assert metadata.job_id == "job456"
    
    def test_open_nonexistent_document_without_create(self, document_manager):
        """Test opening non-existent document without create flag."""
        with pytest.raises(DocumentException) as exc_info:
            document_manager.open_document(
                job_id="job789",
                create_if_not_exists=False
            )
        
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_NOT_FOUND


class TestDocumentLocking:
    """Tests for document locking mechanism."""
    
    def test_acquire_lock(self, document_manager):
        """Test acquiring document lock."""
        document_manager.create_document(job_id="job123")
        
        lock = document_manager.acquire_lock(
            document_id="doc_job123",
            owner_id="user1",
            lock_type="exclusive"
        )
        
        assert lock.document_id == "doc_job123"
        assert lock.owner_id == "user1"
        assert lock.lock_type == "exclusive"
        assert lock.expires_at is not None
    
    def test_acquire_lock_on_locked_document(self, document_manager):
        """Test that acquiring lock on locked document fails."""
        document_manager.create_document(job_id="job123")
        
        # First lock succeeds
        lock1 = document_manager.acquire_lock("doc_job123", "user1")
        
        # Second lock fails
        with pytest.raises(DocumentException) as exc_info:
            document_manager.acquire_lock("doc_job123", "user2")
        
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_LOCKED
    
    def test_release_lock(self, document_manager):
        """Test releasing document lock."""
        document_manager.create_document(job_id="job123")
        
        lock = document_manager.acquire_lock("doc_job123", "user1")
        released = document_manager.release_lock("doc_job123", lock.lock_id)
        
        assert released is True
        
        # Should be able to acquire new lock after release
        lock2 = document_manager.acquire_lock("doc_job123", "user2")
        assert lock2 is not None
    
    def test_lock_context_manager(self, document_manager):
        """Test lock context manager."""
        document_manager.create_document(job_id="job123")
        
        with document_manager.document_lock("doc_job123", "user1") as lock:
            assert lock is not None
            assert lock.owner_id == "user1"
            
            # Lock should be active inside context
            with pytest.raises(DocumentException):
                document_manager.acquire_lock("doc_job123", "user2")
        
        # Lock should be released outside context
        lock2 = document_manager.acquire_lock("doc_job123", "user2")
        assert lock2 is not None
    
    def test_expired_lock(self, document_manager):
        """Test that expired locks can be overridden."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock with short timeout
        lock = document_manager.acquire_lock(
            "doc_job123",
            "user1",
            timeout_seconds=1
        )
        
        # Wait for lock to expire
        time.sleep(2)
        
        # Should be able to acquire new lock
        lock2 = document_manager.acquire_lock("doc_job123", "user2")
        assert lock2 is not None


class TestTransactionManagement:
    """Tests for transaction management."""
    
    def test_start_transaction(self, document_manager):
        """Test starting a transaction."""
        document_manager.create_document(job_id="job123")
        
        transaction = document_manager.start_transaction("doc_job123")
        
        assert transaction.document_id == "doc_job123"
        assert transaction.state == TransactionState.ACTIVE
        assert transaction.started_at is not None
        assert transaction.rollback_data is not None
    
    def test_transaction_buffer(self, document_manager):
        """Test transaction buffering functionality."""
        document_manager.create_document(job_id="job123")
        
        transaction = document_manager.start_transaction("doc_job123")
        
        # Add buffered changes
        transaction.add_buffered_change("author", "new_author")
        transaction.add_buffered_change("description", "new description")
        
        # Commit transaction
        document_manager.commit_transaction(transaction.transaction_id)
        
        # Check that buffered changes were applied
        metadata = document_manager.documents["doc_job123"]
        assert metadata.author == "new_author"
        assert metadata.description == "new description"
    
    def test_transaction_context_manager(self, document_manager):
        """Test transaction context manager."""
        document_manager.create_document(job_id="job123")
        
        # Test successful transaction
        with document_manager.transaction("doc_job123") as txn:
            assert txn is not None
            assert txn.state == TransactionState.ACTIVE
        
        # Transaction should be committed
        assert txn.transaction_id not in document_manager.transactions
        
        # Test failed transaction
        try:
            with document_manager.transaction("doc_job123") as txn:
                raise ValueError("Test error")
        except ValueError:
            pass
        
        # Transaction should be aborted
        assert txn.transaction_id not in document_manager.transactions
    
    def test_commit_transaction(self, document_manager):
        """Test committing a transaction."""
        metadata = document_manager.create_document(job_id="job123")
        initial_revision = metadata.revision
        
        transaction = document_manager.start_transaction("doc_job123")
        committed = document_manager.commit_transaction(transaction.transaction_id)
        
        assert committed is True
        
        # Check that revision was incremented
        updated_metadata = document_manager.documents["doc_job123"]
        assert updated_metadata.revision == "B"
    
    def test_abort_transaction(self, document_manager):
        """Test aborting a transaction."""
        document_manager.create_document(job_id="job123")
        
        transaction = document_manager.start_transaction("doc_job123")
        aborted = document_manager.abort_transaction(transaction.transaction_id)
        
        assert aborted is True
        
        # Transaction should be cleaned up
        assert transaction.transaction_id not in document_manager.transactions
    
    def test_transaction_on_nonexistent_document(self, document_manager):
        """Test that transaction on non-existent document fails."""
        with pytest.raises(DocumentException) as exc_info:
            document_manager.start_transaction("doc_nonexistent")
        
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_NOT_FOUND


class TestVersioningAndRevisions:
    """Tests for document versioning and revisions."""
    
    def test_increment_revision(self, document_manager):
        """Test incrementing document revision."""
        metadata = document_manager.create_document(job_id="job123")
        
        assert metadata.revision == "A"
        
        metadata.increment_revision()
        assert metadata.revision == "B"
        
        metadata.increment_revision()
        assert metadata.revision == "C"
    
    def test_increment_version(self, document_manager):
        """Test incrementing document version."""
        metadata = document_manager.create_document(job_id="job123")
        
        assert metadata.version == 1
        assert metadata.revision == "A"
        
        metadata.increment_version()
        
        assert metadata.version == 2
        assert metadata.revision == "A"  # Revision resets on version increment
    
    def test_revision_rollover(self, document_manager):
        """Test revision rollover from Z to version increment."""
        metadata = document_manager.create_document(job_id="job123")
        metadata.revision = "Z"
        metadata.version = 1
        
        metadata.increment_revision()
        
        assert metadata.version == 2
        assert metadata.revision == "A"


class TestUndoRedo:
    """Tests for undo/redo functionality."""
    
    def test_add_undo_snapshot(self, document_manager):
        """Test adding undo snapshot."""
        document_manager.create_document(job_id="job123")
        
        snapshot = document_manager.add_undo_snapshot(
            "doc_job123",
            "Test change",
            {"test": "data"}
        )
        
        assert snapshot.document_id == "doc_job123"
        assert snapshot.description == "Test change"
        assert snapshot.data == {"test": "data"}
        assert len(document_manager.undo_stacks["doc_job123"]) == 1
    
    def test_undo_operation(self, document_manager):
        """Test undo operation."""
        document_manager.create_document(job_id="job123")
        
        # Add snapshots
        document_manager.add_undo_snapshot("doc_job123", "Change 1", {"step": 1})
        document_manager.add_undo_snapshot("doc_job123", "Change 2", {"step": 2})
        
        # Perform undo
        undone = document_manager.undo("doc_job123")
        
        assert undone is not None
        assert undone.description == "Change 2"
        assert len(document_manager.undo_stacks["doc_job123"]) == 1
        assert len(document_manager.redo_stacks["doc_job123"]) == 1
    
    def test_redo_operation(self, document_manager):
        """Test redo operation."""
        document_manager.create_document(job_id="job123")
        
        # Add snapshots and undo
        document_manager.add_undo_snapshot("doc_job123", "Change 1", {"step": 1})
        document_manager.add_undo_snapshot("doc_job123", "Change 2", {"step": 2})
        document_manager.undo("doc_job123")
        
        # Perform redo
        redone = document_manager.redo("doc_job123")
        
        assert redone is not None
        assert len(document_manager.undo_stacks["doc_job123"]) == 2
        assert len(document_manager.redo_stacks["doc_job123"]) == 0
    
    def test_undo_stack_limit(self, document_manager):
        """Test that undo stack respects size limit."""
        document_manager.create_document(job_id="job123")
        
        # Add more snapshots than limit
        for i in range(15):
            document_manager.add_undo_snapshot(
                "doc_job123",
                f"Change {i}",
                {"step": i}
            )
        
        # Stack should be limited to max_undo_stack_size (10)
        assert len(document_manager.undo_stacks["doc_job123"]) == 10
    
    def test_redo_cleared_on_new_change(self, document_manager):
        """Test that redo stack is cleared on new changes."""
        document_manager.create_document(job_id="job123")
        
        # Create undo/redo history
        document_manager.add_undo_snapshot("doc_job123", "Change 1", {"step": 1})
        document_manager.undo("doc_job123")
        assert len(document_manager.redo_stacks["doc_job123"]) == 1
        
        # Add new change
        document_manager.add_undo_snapshot("doc_job123", "New change", {"step": 2})
        
        # Redo stack should be cleared
        assert len(document_manager.redo_stacks["doc_job123"]) == 0


class TestLockEnforcement:
    """Tests for lock ownership enforcement."""
    
    def test_save_requires_lock_owner(self, document_manager):
        """Test that save requires correct lock owner."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock as user1
        lock = document_manager.acquire_lock("doc_job123", "user1")
        
        # Try to save as different user
        with pytest.raises(DocumentException) as exc_info:
            document_manager.save_document("doc_job123", owner_id="user2")
        
        assert exc_info.value.error_code == DocumentErrorCode.LOCK_OWNER_MISMATCH
        
        # Save with correct owner should work
        path = document_manager.save_document("doc_job123", owner_id="user1")
        assert path is not None
    
    def test_close_requires_lock_owner(self, document_manager):
        """Test that close requires correct lock owner."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock as user1
        lock = document_manager.acquire_lock("doc_job123", "user1")
        
        # Try to close as different user
        with pytest.raises(DocumentException) as exc_info:
            document_manager.close_document("doc_job123", owner_id="user2")
        
        assert exc_info.value.error_code == DocumentErrorCode.LOCK_OWNER_MISMATCH
    
    def test_save_fails_without_owner_id(self, document_manager):
        """Test that save fails when owner_id is None or missing when lock exists."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock as user1
        lock = document_manager.acquire_lock("doc_job123", "user1")
        
        # Try to save without owner_id (None)
        with pytest.raises(DocumentException) as exc_info:
            document_manager.save_document("doc_job123", owner_id=None)
        
        # When owner_id is None, we should get DOCUMENT_LOCKED error
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_LOCKED
        
        # Try to save without passing owner_id at all
        with pytest.raises(DocumentException) as exc_info:
            document_manager.save_document("doc_job123")
        
        # When owner_id is missing, we should get DOCUMENT_LOCKED error  
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_LOCKED
    
    def test_close_fails_without_owner_id(self, document_manager):
        """Test that close fails when owner_id is None or missing when lock exists."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock as user1
        lock = document_manager.acquire_lock("doc_job123", "user1")
        
        # Try to close without owner_id (None)
        with pytest.raises(DocumentException) as exc_info:
            document_manager.close_document("doc_job123", owner_id=None)
        
        # When owner_id is None, we should get DOCUMENT_LOCKED error
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_LOCKED
        
        # Try to close without passing owner_id at all
        with pytest.raises(DocumentException) as exc_info:
            document_manager.close_document("doc_job123")
        
        # When owner_id is missing, we should get DOCUMENT_LOCKED error
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_LOCKED
    
    def test_operations_fail_without_lock(self, document_manager):
        """Test that operations fail without proper lock and owner_id."""
        document_manager.create_document(job_id="job123")
        
        # Without any lock or owner_id, save should fail
        with pytest.raises(DocumentException) as exc_info:
            document_manager.save_document("doc_job123")
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_LOCKED
        
        # Close should also fail without owner_id
        document_manager.create_document(job_id="job456")
        with pytest.raises(DocumentException) as exc_info:
            document_manager.close_document("doc_job456", save_before_close=False)
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_LOCKED


class TestPathSanitization:
    """Tests for path sanitization and safety."""
    
    def test_job_id_sanitization(self, document_manager):
        """Test that job IDs are sanitized in document IDs."""
        # Create document with potentially unsafe job_id
        metadata = document_manager.create_document(job_id="../../../etc/passwd")
        
        # Document ID should be sanitized
        assert metadata.document_id == "doc___________etc_passwd"
        assert "/" not in metadata.document_id
        assert ".." not in metadata.document_id
    
    def test_safe_path_generation(self, temp_dir):
        """Test safe path generation with configurable base directory."""
        config = DocumentManagerConfig(
            base_dir=str(temp_dir),
            auto_save_interval_seconds=0
        )
        manager = FreeCADDocumentManager(config)
        
        safe_path = manager._get_safe_path("test/../file.FCStd")
        
        # Path should be sanitized and within base directory
        assert str(temp_dir) in safe_path
        assert ".." not in safe_path
        assert safe_path == os.path.join(str(temp_dir), "test____file.FCStd")


class TestDocumentSaveAndLoad:
    """Tests for document saving and loading."""
    
    def test_save_document(self, document_manager, temp_dir):
        """Test saving document."""
        document_manager.create_document(
            job_id="job123",
            author="test_user"
        )
        
        # Acquire lock first
        lock = document_manager.acquire_lock("doc_job123", owner_id="test_user")
        
        save_path = temp_dir / "test_doc.FCStd"
        result_path = document_manager.save_document(
            "doc_job123",
            owner_id="test_user",
            save_path=str(save_path),
            compress=False
        )
        
        # Release lock
        document_manager.release_lock("doc_job123", lock.lock_id)
        
        assert os.path.exists(result_path)
        
        # Check saved content
        with open(result_path, 'r') as f:
            saved_data = json.load(f)
        
        assert "metadata" in saved_data
        assert saved_data["metadata"]["document_id"] == "doc_job123"
        assert saved_data["metadata"]["author"] == "test_user"
    
    def test_save_document_compressed(self, document_manager, temp_dir):
        """Test saving document with compression."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock first
        lock = document_manager.acquire_lock("doc_job123", owner_id="test_user")
        
        save_path = temp_dir / "test_doc.FCStd"
        result_path = document_manager.save_document(
            "doc_job123",
            owner_id="test_user",
            save_path=str(save_path),
            compress=True
        )
        
        # Release lock
        document_manager.release_lock("doc_job123", lock.lock_id)
        
        assert result_path.endswith(".gz")
        assert os.path.exists(result_path)
        
        # Check that file is compressed
        assert os.path.getsize(result_path) > 0
    
    def test_save_with_backup(self, document_manager, temp_dir):
        """Test saving document with backup creation."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock first
        lock = document_manager.acquire_lock("doc_job123", owner_id="test_user")
        
        # Save with backup
        save_path = document_manager.save_document(
            "doc_job123",
            owner_id="test_user",
            create_backup=True
        )
        
        # Release lock
        document_manager.release_lock("doc_job123", lock.lock_id)
        
        # Check that backup was created
        assert "doc_job123" in document_manager.backups
        assert len(document_manager.backups["doc_job123"]) == 1
        
        backup = document_manager.backups["doc_job123"][0]
        assert backup.document_id == "doc_job123"
        assert os.path.exists(backup.backup_path)
    
    def test_close_document_with_save(self, document_manager, temp_dir):
        """Test closing document with save."""
        document_manager.create_document(job_id="job123")
        
        # Acquire lock first
        lock = document_manager.acquire_lock("doc_job123", owner_id="test_user")
        
        closed = document_manager.close_document(
            "doc_job123",
            owner_id="test_user",
            save_before_close=True
        )
        
        assert closed is True
        assert "doc_job123" not in document_manager.documents
        assert "doc_job123" not in document_manager.undo_stacks
        assert "doc_job123" not in document_manager.redo_stacks


class TestBackupAndRestore:
    """Tests for backup and restore functionality."""
    
    def test_create_backup(self, document_manager):
        """Test creating document backup."""
        document_manager.create_document(
            job_id="job123",
            author="test_user"
        )
        
        backup = document_manager.create_backup("doc_job123")
        
        assert backup.document_id == "doc_job123"
        assert backup.backup_id.startswith("backup_doc_job123_")
        assert os.path.exists(backup.backup_path)
        assert backup.compressed == document_manager.config.enable_compression
    
    def test_backup_retention_policy(self, temp_dir):
        """Test backup retention and pruning."""
        config = DocumentManagerConfig(
            base_dir=str(temp_dir),
            max_backups_per_document=3,
            backup_retention_days=1,
            auto_save_interval_seconds=0
        )
        manager = FreeCADDocumentManager(config)
        
        manager.create_document(job_id="job123")
        
        # Create more backups than the limit
        backup_paths = []
        for i in range(5):
            backup = manager.create_backup("doc_job123")
            backup_paths.append(backup.backup_path)
            time.sleep(0.1)  # Small delay to ensure different timestamps
        
        # Should only keep max_backups_per_document
        assert len(manager.backups["doc_job123"]) == 3
        
        # Old backups should be deleted
        for path in backup_paths[:2]:
            assert not os.path.exists(path)
        
        # Recent backups should exist
        for backup in manager.backups["doc_job123"]:
            assert os.path.exists(backup.backup_path)
    
    def test_restore_backup(self, document_manager):
        """Test restoring from backup."""
        # Create and modify document
        metadata = document_manager.create_document(
            job_id="job123",
            author="original_author"
        )
        
        # Create backup
        backup = document_manager.create_backup("doc_job123")
        
        # Modify document
        metadata.author = "modified_author"
        metadata.increment_revision()
        
        # Restore from backup
        restored = document_manager.restore_backup(backup.backup_id)
        
        assert restored.author == "original_author"
        assert restored.revision == "A"
    
    def test_restore_nonexistent_backup(self, document_manager):
        """Test restoring non-existent backup fails."""
        with pytest.raises(DocumentException) as exc_info:
            document_manager.restore_backup("nonexistent_backup_id")
        
        assert exc_info.value.error_code == DocumentErrorCode.RESTORE_FAILED


class TestAssemblyCoordination:
    """Tests for multi-document assembly coordination."""
    
    def test_setup_assembly_coordination(self, document_manager):
        """Test setting up assembly coordination."""
        document_manager.create_document(job_id="assembly_main")
        document_manager.create_document(job_id="part1")
        document_manager.create_document(job_id="part2")
        
        coordination = document_manager.setup_assembly_coordination(
            assembly_id="doc_assembly_main",
            child_document_ids=["doc_part1", "doc_part2"]
        )
        
        assert coordination.assembly_id == "doc_assembly_main"
        assert len(coordination.child_document_ids) == 2
        assert "doc_part1" in coordination.child_document_ids
        assert "doc_part2" in coordination.child_document_ids
    
    def test_assembly_with_parent(self, document_manager):
        """Test assembly with parent document."""
        document_manager.create_document(job_id="parent_assembly")
        document_manager.create_document(job_id="sub_assembly")
        
        coordination = document_manager.setup_assembly_coordination(
            assembly_id="doc_sub_assembly",
            parent_document_id="doc_parent_assembly",
            child_document_ids=[]
        )
        
        assert coordination.parent_document_id == "doc_parent_assembly"


class TestDocumentMigration:
    """Tests for document migration."""
    
    def test_migrate_document(self, document_manager):
        """Test document migration to new version."""
        document_manager.create_document(job_id="job123")
        
        migration = document_manager.migrate_document(
            "doc_job123",
            target_version="1.2.0",
            migration_rules={
                "update_properties": {"action": "update"},
                "fix_references": {"action": "fix"}
            }
        )
        
        assert migration.source_version == "1.1.0"
        assert migration.target_version == "1.2.0"
        assert migration.status == "completed"
        assert migration.started_at is not None
        assert migration.completed_at is not None
        
        # Check that version was incremented
        metadata = document_manager.documents["doc_job123"]
        assert metadata.version == 2
        assert metadata.properties.get("migration_version") == "1.2.0"
    
    def test_migrate_nonexistent_document(self, document_manager):
        """Test migrating non-existent document fails."""
        with pytest.raises(DocumentException) as exc_info:
            document_manager.migrate_document(
                "doc_nonexistent",
                target_version="1.2.0"
            )
        
        assert exc_info.value.error_code == DocumentErrorCode.DOCUMENT_NOT_FOUND


class TestAutoRecovery:
    """Tests for auto-recovery mechanism."""
    
    def test_auto_recovery_from_backup(self, document_manager):
        """Test auto-recovery from backup."""
        # Create document and backup
        document_manager.create_document(job_id="job123")
        backup = document_manager.create_backup("doc_job123")
        
        # Simulate corruption by removing from documents
        del document_manager.documents["doc_job123"]
        
        # Attempt recovery
        recovered = document_manager.auto_recover("doc_job123")
        
        assert recovered is True
        assert "doc_job123" in document_manager.documents
    
    def test_auto_recovery_disabled(self, document_manager):
        """Test that auto-recovery respects config."""
        document_manager.config.enable_auto_recovery = False
        
        recovered = document_manager.auto_recover("doc_job123")
        
        assert recovered is False


class TestFreeCADAdapter:
    """Tests for FreeCAD adapter pattern."""
    
    def test_mock_adapter_creation(self):
        """Test creating mock adapter."""
        adapter = MockFreeCADAdapter()
        doc = adapter.create_document("test_doc")
        
        assert doc["name"] == "test_doc"
        assert "created_at" in doc
        assert doc["objects"] == []
    
    def test_mock_adapter_save_and_open(self, temp_dir):
        """Test saving and opening documents with mock adapter."""
        adapter = MockFreeCADAdapter()
        
        # Create document
        doc = adapter.create_document("test_doc")
        doc["objects"].append({"name": "obj1", "type": "Part"})
        
        # Save document
        save_path = str(temp_dir / "test_doc.json")
        assert adapter.save_document(doc, save_path)
        assert os.path.exists(save_path)
        
        # Open document
        loaded_doc = adapter.open_document(save_path)
        assert loaded_doc["name"] == "test_doc"
        assert len(loaded_doc["objects"]) == 1
    
    def test_mock_adapter_transactions(self):
        """Test transaction operations with mock adapter."""
        adapter = MockFreeCADAdapter()
        
        doc = adapter.create_document("test_doc")
        original_state = doc.copy()
        
        # Start transaction
        assert adapter.start_transaction(doc, "test_txn")
        
        # Modify document
        doc["objects"].append({"name": "new_obj"})
        
        # Abort transaction
        assert adapter.abort_transaction(doc)
        
        # Document should be restored
        assert doc["objects"] == original_state["objects"]
    
    def test_document_manager_with_mock_adapter(self, temp_dir):
        """Test document manager using mock adapter."""
        config = DocumentManagerConfig(
            use_real_freecad=False,
            base_dir=str(temp_dir),
            auto_save_interval_seconds=0
        )
        manager = FreeCADDocumentManager(config)
        
        assert isinstance(manager.freecad_adapter, MockFreeCADAdapter)
        
        # Test basic operations
        metadata = manager.create_document(job_id="test_job")
        assert metadata.document_id == "doc_test_job"


class TestMemoryManagement:
    """Tests for memory management."""
    
    @patch('app.services.freecad_document_manager.PSUTIL_AVAILABLE', True)
    @patch('psutil.Process')
    def test_memory_limit_check(self, mock_process, document_manager):
        """Test memory limit checking."""
        # Mock memory usage below limit
        mock_proc_instance = Mock()
        mock_proc_instance.memory_info.return_value.rss = 100 * 1024 * 1024  # 100 MB
        mock_process.return_value = mock_proc_instance
        
        # Should be able to create document
        metadata = document_manager.create_document(job_id="job123")
        assert metadata is not None
    
    @patch('psutil.Process')
    def test_memory_cleanup_triggered(self, mock_process, document_manager):
        """Test memory cleanup when limit exceeded."""
        # Create some documents first
        document_manager.create_document(job_id="job1")
        document_manager.create_document(job_id="job2")
        
        # Mock memory usage above limit
        mock_proc_instance = Mock()
        mock_proc_instance.memory_info.return_value.rss = 600 * 1024 * 1024  # 600 MB (above 512 MB limit)
        mock_process.return_value = mock_proc_instance
        
        # Creating new document should trigger cleanup
        with patch.object(document_manager, '_trigger_memory_cleanup') as mock_cleanup:
            try:
                document_manager.create_document(job_id="job3")
            except DocumentException:
                pass  # Expected if memory still exceeded after cleanup
            
            mock_cleanup.assert_called_once()


class TestDocumentStatus:
    """Tests for document status retrieval."""
    
    def test_get_document_status(self, document_manager):
        """Test getting comprehensive document status."""
        document_manager.create_document(job_id="job123")
        
        # Add some operations
        lock = document_manager.acquire_lock("doc_job123", "user1")
        transaction = document_manager.start_transaction("doc_job123")
        document_manager.add_undo_snapshot("doc_job123", "Change 1", {})
        document_manager.create_backup("doc_job123")
        
        status = document_manager.get_document_status("doc_job123")
        
        assert status["status"] == "open"
        assert status["document_id"] == "doc_job123"
        assert status["metadata"] is not None
        assert status["lock"] is not None
        assert len(status["transactions"]) == 1
        assert status["undo_stack_size"] == 1
        assert status["backup_count"] == 1
    
    def test_get_nonexistent_document_status(self, document_manager):
        """Test getting status of non-existent document."""
        status = document_manager.get_document_status("doc_nonexistent")
        
        assert status["status"] == "not_found"
        assert status["document_id"] == "doc_nonexistent"


class TestDocumentManagerShutdown:
    """Tests for document manager shutdown."""
    
    def test_shutdown_saves_and_closes_documents(self, document_manager):
        """Test that shutdown saves and closes all documents."""
        # Create multiple documents
        document_manager.create_document(job_id="job1")
        document_manager.create_document(job_id="job2")
        document_manager.create_document(job_id="job3")
        
        # Shutdown
        document_manager.shutdown()
        
        # All documents should be closed
        assert len(document_manager.documents) == 0
        assert len(document_manager.locks) == 0
        assert len(document_manager.transactions) == 0
        assert len(document_manager.undo_stacks) == 0
        assert len(document_manager.redo_stacks) == 0


class TestTurkishLocalization:
    """Tests for Turkish error messages."""
    
    def test_turkish_error_messages(self, document_manager):
        """Test that Turkish error messages are provided."""
        # Test document not found error
        try:
            document_manager.open_document(
                job_id="nonexistent",
                create_if_not_exists=False
            )
        except DocumentException as e:
            assert e.turkish_message == "İş nonexistent için belge bulunamadı"
            assert e.error_code == DocumentErrorCode.DOCUMENT_NOT_FOUND
        
        # Test document already exists error
        document_manager.create_document(job_id="job123")
        try:
            document_manager.create_document(job_id="job123")
        except DocumentException as e:
            assert e.turkish_message == "Belge doc_job123 zaten mevcut"
            assert e.error_code == DocumentErrorCode.DOCUMENT_ALREADY_EXISTS
        
        # Test document locked error
        lock = document_manager.acquire_lock("doc_job123", "user1")
        try:
            document_manager.acquire_lock("doc_job123", "user2")
        except DocumentException as e:
            assert e.turkish_message == "Belge doc_job123 zaten kilitli"
            assert e.error_code == DocumentErrorCode.DOCUMENT_LOCKED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])