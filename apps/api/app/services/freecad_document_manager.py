"""
Ultra-Enterprise FreeCAD Document Lifecycle Management for Task 7.19

This module implements comprehensive document lifecycle management with:
- Document creation/opening with deterministic naming (job_id based)
- Transaction management: openTransaction/commitTransaction/abortTransaction
- Document versioning and revision tracking
- Auto-save and recovery mechanisms
- Memory management and cleanup (close documents, gc.collect)
- Document locking for concurrent access prevention
- Document metadata and properties management
- Undo/Redo stack management
- Document compression and storage optimization
- Multi-document coordination for assemblies
- Document migration for version upgrades
- Backup and restore functionality

Features:
- Ultra-enterprise quality with full error handling
- Turkish localization for all error messages
- Integration with existing FreeCAD service
- Connection with Task 7 and all subtasks
- Atomic operations, recoverable, memory-efficient
- Support concurrent job processing without conflicts
- Use Pydantic models for all data structures
- Comprehensive logging and metrics
"""

from __future__ import annotations

import gc
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from functools import wraps

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from pydantic.functional_validators import AfterValidator
from typing_extensions import Annotated
from sqlalchemy.orm import Session

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id

logger = get_logger(__name__)

# Try to import psutil, provide fallback if not available
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, memory management features limited")


class DocumentState(str, Enum):
    """Document state enumeration."""
    NEW = "new"
    OPENING = "opening"
    OPEN = "open"
    MODIFIED = "modified"
    SAVING = "saving"
    CLOSED = "closed"
    ERROR = "error"
    RECOVERING = "recovering"


class TransactionState(str, Enum):
    """Transaction state enumeration."""
    NONE = "none"
    ACTIVE = "active"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ABORTING = "aborting"
    ABORTED = "aborted"


class DocumentErrorCode(str, Enum):
    """Standardized error codes for document operations."""
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    DOCUMENT_ALREADY_EXISTS = "DOCUMENT_ALREADY_EXISTS"
    DOCUMENT_LOCKED = "DOCUMENT_LOCKED"
    DOCUMENT_CORRUPT = "DOCUMENT_CORRUPT"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    SAVE_FAILED = "SAVE_FAILED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    INVALID_METADATA = "INVALID_METADATA"
    BACKUP_FAILED = "BACKUP_FAILED"
    RESTORE_FAILED = "RESTORE_FAILED"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    ASSEMBLY_COORDINATION_FAILED = "ASSEMBLY_COORDINATION_FAILED"
    LOCK_OWNER_MISMATCH = "LOCK_OWNER_MISMATCH"


class FreeCADAdapter(ABC):
    """Abstract adapter for FreeCAD operations to enable testing and real implementation."""
    
    @abstractmethod
    def create_document(self, name: str) -> Any:
        """Create a new FreeCAD document."""
        pass
    
    @abstractmethod
    def open_document(self, filepath: str) -> Any:
        """Open an existing FreeCAD document."""
        pass
    
    @abstractmethod
    def save_document(self, doc: Any, filepath: str) -> bool:
        """Save a FreeCAD document to file."""
        pass
    
    @abstractmethod
    def close_document(self, doc: Any) -> bool:
        """Close a FreeCAD document."""
        pass
    
    @abstractmethod
    def take_snapshot(self, doc: Any) -> Dict[str, Any]:
        """Take a snapshot of the current document state."""
        pass
    
    @abstractmethod
    def restore_snapshot(self, doc: Any, snapshot: Dict[str, Any]) -> bool:
        """Restore document from a snapshot."""
        pass
    
    @abstractmethod
    def start_transaction(self, doc: Any, name: str) -> bool:
        """Start a transaction in the document."""
        pass
    
    @abstractmethod
    def commit_transaction(self, doc: Any) -> bool:
        """Commit the active transaction."""
        pass
    
    @abstractmethod
    def abort_transaction(self, doc: Any) -> bool:
        """Abort the active transaction."""
        pass


class MockFreeCADAdapter(FreeCADAdapter):
    """Mock adapter for testing that uses JSON storage."""
    
    def __init__(self):
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.transactions: Dict[str, List[Dict[str, Any]]] = {}
    
    def create_document(self, name: str) -> Dict[str, Any]:
        """Create a mock document."""
        doc = {
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "objects": [],
            "properties": {}
        }
        self.documents[name] = doc
        return doc
    
    def open_document(self, filepath: str) -> Dict[str, Any]:
        """Open a mock document from JSON file."""
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                doc = json.load(f)
                self.documents[doc.get("name", filepath)] = doc
                return doc
        return self.create_document(os.path.basename(filepath))
    
    def save_document(self, doc: Any, filepath: str) -> bool:
        """Save mock document to JSON file."""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(doc, f, indent=2, default=str)
            return True
        except Exception:
            return False
    
    def close_document(self, doc: Any) -> bool:
        """Close mock document."""
        if isinstance(doc, dict) and "name" in doc:
            self.documents.pop(doc["name"], None)
            return True
        return False
    
    def take_snapshot(self, doc: Any) -> Dict[str, Any]:
        """Take snapshot of mock document."""
        if isinstance(doc, dict):
            import copy
            return copy.deepcopy(doc)
        return {}
    
    def restore_snapshot(self, doc: Any, snapshot: Dict[str, Any]) -> bool:
        """Restore mock document from snapshot."""
        if isinstance(doc, dict) and isinstance(snapshot, dict):
            doc.clear()
            doc.update(snapshot)
            return True
        return False
    
    def start_transaction(self, doc: Any, name: str) -> bool:
        """Start mock transaction."""
        if isinstance(doc, dict):
            doc_name = doc.get("name", "unknown")
            if doc_name not in self.transactions:
                self.transactions[doc_name] = []
            self.transactions[doc_name].append({
                "name": name,
                "snapshot": self.take_snapshot(doc)
            })
            return True
        return False
    
    def commit_transaction(self, doc: Any) -> bool:
        """Commit mock transaction."""
        if isinstance(doc, dict):
            doc_name = doc.get("name", "unknown")
            if doc_name in self.transactions and self.transactions[doc_name]:
                self.transactions[doc_name].pop()
                return True
        return False
    
    def abort_transaction(self, doc: Any) -> bool:
        """Abort mock transaction."""
        if isinstance(doc, dict):
            doc_name = doc.get("name", "unknown")
            if doc_name in self.transactions and self.transactions[doc_name]:
                txn = self.transactions[doc_name].pop()
                return self.restore_snapshot(doc, txn["snapshot"])
        return False


class RealFreeCADAdapter(FreeCADAdapter):
    """Real adapter that interfaces with actual FreeCAD API."""
    
    def __init__(self):
        # Import FreeCAD only when using real adapter
        try:
            import FreeCAD as App
            self.App = App
        except ImportError:
            raise ImportError("FreeCAD module not available. Install FreeCAD or use MockFreeCADAdapter.")
    
    def create_document(self, name: str) -> Any:
        """Create a new FreeCAD document using App.newDocument."""
        return self.App.newDocument(name)
    
    def open_document(self, filepath: str) -> Any:
        """Open an existing FreeCAD document using App.open."""
        return self.App.open(filepath)
    
    def save_document(self, doc: Any, filepath: str) -> bool:
        """Save FreeCAD document using doc.saveAs."""
        try:
            doc.saveAs(filepath)
            return True
        except Exception:
            return False
    
    def close_document(self, doc: Any) -> bool:
        """Close FreeCAD document using App.closeDocument."""
        try:
            self.App.closeDocument(doc.Name)
            return True
        except Exception:
            return False
    
    def take_snapshot(self, doc: Any) -> Dict[str, Any]:
        """Take snapshot of FreeCAD document state."""
        return {
            "name": doc.Name,
            "objects": [obj.Name for obj in doc.Objects],
            "properties": dict(doc.PropertiesList) if hasattr(doc, 'PropertiesList') else {}
        }
    
    def restore_snapshot(self, doc: Any, snapshot: Dict[str, Any]) -> bool:
        """Restore FreeCAD document from snapshot (limited functionality)."""
        # Note: Full restoration would require recreating objects
        # This is a simplified version
        try:
            # Clear existing objects if possible
            for obj in doc.Objects:
                doc.removeObject(obj.Name)
            # Would need to recreate objects from snapshot here
            return True
        except Exception:
            return False
    
    def start_transaction(self, doc: Any, name: str) -> bool:
        """Start transaction using doc.openTransaction."""
        try:
            doc.openTransaction(name)
            return True
        except Exception:
            return False
    
    def commit_transaction(self, doc: Any) -> bool:
        """Commit transaction using doc.commitTransaction."""
        try:
            doc.commitTransaction()
            return True
        except Exception:
            return False
    
    def abort_transaction(self, doc: Any) -> bool:
        """Abort transaction using doc.abortTransaction."""
        try:
            doc.abortTransaction()
            return True
        except Exception:
            return False


def requires_lock(func):
    """Decorator to enforce lock ownership for state-changing operations."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Extract document_id and owner_id from arguments
        document_id = None
        owner_id = kwargs.get('owner_id')
        
        # Try to get document_id from various argument positions
        if 'document_id' in kwargs:
            document_id = kwargs['document_id']
        elif len(args) > 0:
            document_id = args[0]
        
        # Check if lock exists and matches owner
        if document_id and document_id in self.locks:
            lock = self.locks[document_id]
            if owner_id and lock.owner_id != owner_id:
                raise DocumentException(
                    f"Lock owner mismatch for document {document_id}",
                    DocumentErrorCode.LOCK_OWNER_MISMATCH,
                    f"Belge {document_id} için kilit sahibi uyuşmazlığı",
                    {"expected_owner": lock.owner_id, "provided_owner": owner_id}
                )
        
        return func(self, *args, **kwargs)
    return wrapper


class DocumentException(Exception):
    """Document operation exception with Turkish support."""
    def __init__(
        self,
        message: str,
        error_code: DocumentErrorCode,
        turkish_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.turkish_message = turkish_message or message
        self.details = details or {}


class DocumentMetadata(BaseModel):
    """Document metadata model."""
    model_config = ConfigDict(validate_assignment=True)
    
    document_id: str = Field(description="Unique document identifier")
    job_id: str = Field(description="Associated job ID")
    version: int = Field(default=1, description="Document version number")
    revision: str = Field(default="A", description="Document revision letter")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    author: Optional[str] = Field(default=None, description="Document author")
    license: Optional[str] = Field(default=None, description="Document license")
    description: Optional[str] = Field(default=None, description="Document description")
    tags: List[str] = Field(default_factory=list, description="Document tags")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Custom properties")
    file_size_bytes: Optional[int] = Field(default=None, description="File size in bytes")
    sha256_hash: Optional[str] = Field(default=None, description="Document SHA256 hash")
    compressed: bool = Field(default=False, description="Whether document is compressed")
    
    @field_validator('revision')
    @classmethod
    def validate_revision(cls, v: str) -> str:
        """Validate revision format (single letter A-Z)."""
        if not v or not v.isalpha() or len(v) != 1 or not v.isupper():
            raise ValueError("Revision must be a single uppercase letter (A-Z)")
        return v
    
    def increment_version(self):
        """Increment version number and reset revision."""
        self.version += 1
        self.revision = "A"
        self.modified_at = datetime.now(timezone.utc)
    
    def increment_revision(self):
        """Increment revision letter (A->B, Z->version+1, revision='A')."""
        if self.revision == 'Z':
            # When revision reaches Z, increment version and reset revision to A
            self.increment_version()
        else:
            self.revision = chr(ord(self.revision) + 1)
        self.modified_at = datetime.now(timezone.utc)


class DocumentLock(BaseModel):
    """Document lock information."""
    document_id: str = Field(description="Locked document ID")
    lock_id: str = Field(description="Unique lock identifier")
    owner_id: str = Field(description="Lock owner identifier")
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None, description="Lock expiration time")
    lock_type: str = Field(default="exclusive", description="Lock type (exclusive/shared)")
    
    def is_expired(self) -> bool:
        """Check if lock has expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at


class TransactionInfo(BaseModel):
    """Transaction information model."""
    model_config = ConfigDict(validate_assignment=True)
    
    transaction_id: str = Field(description="Unique transaction identifier")
    document_id: str = Field(description="Document in transaction")
    state: TransactionState = Field(default=TransactionState.NONE)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    operations: List[Dict[str, Any]] = Field(default_factory=list, description="Transaction operations")
    rollback_data: Optional[Dict[str, Any]] = Field(default=None, description="Data for rollback")
    buffer: Dict[str, Any] = Field(default_factory=dict, description="Buffered changes during transaction")
    
    def add_operation(self, operation: Dict[str, Any]):
        """Add operation to transaction log."""
        self.operations.append({
            **operation,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    def add_buffered_change(self, key: str, value: Any):
        """Add a change to the transaction buffer."""
        self.buffer[key] = value
    
    def get_buffered_changes(self) -> Dict[str, Any]:
        """Get all buffered changes."""
        return self.buffer.copy()
    
    def clear_buffer(self):
        """Clear the transaction buffer."""
        self.buffer.clear()


class DocumentSnapshot(BaseModel):
    """Document snapshot for undo/redo."""
    snapshot_id: str = Field(description="Unique snapshot identifier")
    document_id: str = Field(description="Document ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    description: str = Field(description="Snapshot description")
    data: Dict[str, Any] = Field(description="Snapshot data")
    size_bytes: int = Field(description="Snapshot size in bytes")


class AssemblyCoordination(BaseModel):
    """Assembly document coordination information."""
    assembly_id: str = Field(description="Assembly document ID")
    parent_document_id: Optional[str] = Field(default=None, description="Parent document ID")
    child_document_ids: List[str] = Field(default_factory=list, description="Child document IDs")
    constraints: List[Dict[str, Any]] = Field(default_factory=list, description="Assembly constraints")
    transform_matrix: Optional[List[List[float]]] = Field(default=None, description="4x4 transform matrix")


class DocumentMigration(BaseModel):
    """Document migration information."""
    migration_id: str = Field(description="Migration identifier")
    source_version: str = Field(description="Source FreeCAD version")
    target_version: str = Field(description="Target FreeCAD version")
    status: str = Field(default="pending", description="Migration status")
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    changes_applied: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class BackupInfo(BaseModel):
    """Document backup information."""
    backup_id: str = Field(description="Backup identifier")
    document_id: str = Field(description="Original document ID")
    backup_path: str = Field(description="Backup file path")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    size_bytes: int = Field(description="Backup size in bytes")
    metadata: DocumentMetadata = Field(description="Document metadata at backup time")
    compressed: bool = Field(default=True, description="Whether backup is compressed")
    retention_days: int = Field(default=30, description="Backup retention in days")


class DocumentManagerConfig(BaseModel):
    """Document manager configuration."""
    model_config = ConfigDict(validate_assignment=True)
    
    max_document_size_mb: int = Field(default=100, description="Maximum document size in MB")
    max_undo_stack_size: int = Field(default=50, description="Maximum undo stack size")
    max_concurrent_documents: int = Field(default=10, description="Maximum concurrent open documents")
    auto_save_interval_seconds: int = Field(default=300, description="Auto-save interval in seconds")
    lock_timeout_seconds: int = Field(default=3600, description="Document lock timeout in seconds")
    backup_retention_days: int = Field(default=30, description="Backup retention period in days")
    max_backups_per_document: int = Field(default=10, description="Maximum number of backups per document")
    enable_compression: bool = Field(default=True, description="Enable document compression")
    enable_auto_recovery: bool = Field(default=True, description="Enable auto-recovery")
    memory_limit_mb: int = Field(default=2048, description="Memory limit for documents in MB")
    base_dir: str = Field(default_factory=lambda: tempfile.gettempdir(), description="Base directory for document storage")
    use_real_freecad: bool = Field(default=False, description="Use real FreeCAD API instead of mock")


class FreeCADDocumentManager:
    """Ultra-enterprise FreeCAD document lifecycle manager."""
    
    def __init__(self, config: Optional[DocumentManagerConfig] = None):
        self.config = config or DocumentManagerConfig()
        self.documents: Dict[str, DocumentMetadata] = {}
        self.locks: Dict[str, DocumentLock] = {}
        self.transactions: Dict[str, TransactionInfo] = {}
        self.undo_stacks: Dict[str, List[DocumentSnapshot]] = {}
        self.redo_stacks: Dict[str, List[DocumentSnapshot]] = {}
        self.assemblies: Dict[str, AssemblyCoordination] = {}
        self.backups: Dict[str, List[BackupInfo]] = {}
        self._lock = threading.RLock()
        self._auto_save_threads: Dict[str, threading.Thread] = {}
        self._recovery_data: Dict[str, Dict[str, Any]] = {}
        
        # Initialize FreeCAD adapter
        if self.config.use_real_freecad:
            try:
                self.freecad_adapter = RealFreeCADAdapter()
                logger.info("Using RealFreeCADAdapter")
            except ImportError:
                logger.warning("FreeCAD not available, falling back to MockFreeCADAdapter")
                self.freecad_adapter = MockFreeCADAdapter()
        else:
            self.freecad_adapter = MockFreeCADAdapter()
            logger.info("Using MockFreeCADAdapter")
        
        # Turkish error messages
        self.turkish_errors = {
            DocumentErrorCode.DOCUMENT_NOT_FOUND: "Belge bulunamadı",
            DocumentErrorCode.DOCUMENT_ALREADY_EXISTS: "Belge zaten mevcut",
            DocumentErrorCode.DOCUMENT_LOCKED: "Belge kilitli",
            DocumentErrorCode.DOCUMENT_CORRUPT: "Belge bozuk",
            DocumentErrorCode.VERSION_MISMATCH: "Sürüm uyuşmazlığı",
            DocumentErrorCode.TRANSACTION_FAILED: "İşlem başarısız",
            DocumentErrorCode.SAVE_FAILED: "Kaydetme başarısız",
            DocumentErrorCode.RECOVERY_FAILED: "Kurtarma başarısız",
            DocumentErrorCode.MEMORY_LIMIT_EXCEEDED: "Bellek sınırı aşıldı",
            DocumentErrorCode.INVALID_METADATA: "Geçersiz metadata",
            DocumentErrorCode.BACKUP_FAILED: "Yedekleme başarısız",
            DocumentErrorCode.RESTORE_FAILED: "Geri yükleme başarısız",
            DocumentErrorCode.MIGRATION_FAILED: "Geçiş başarısız",
            DocumentErrorCode.ASSEMBLY_COORDINATION_FAILED: "Montaj koordinasyonu başarısız",
            DocumentErrorCode.LOCK_OWNER_MISMATCH: "Kilit sahibi uyuşmazlığı"
        }
    
    def _generate_document_id(self, job_id: str, suffix: Optional[str] = None) -> str:
        """Generate deterministic document ID based on job_id."""
        # Sanitize job_id to prevent path injection
        import re
        safe_job_id = re.sub(r'[^\w\-_]', '_', job_id)
        base_id = f"doc_{safe_job_id}"
        if suffix:
            safe_suffix = re.sub(r'[^\w\-_]', '_', suffix)
            return f"{base_id}_{safe_suffix}"
        return base_id
    
    def _get_safe_path(self, filename: str) -> str:
        """Get safe file path with sanitized filename and configurable base directory."""
        import re
        # Sanitize filename
        safe_filename = re.sub(r'[^\w\-_.]', '_', filename)
        # Use configured base directory
        return os.path.join(self.config.base_dir, safe_filename)
    
    def _generate_lock_id(self, document_id: str, owner_id: str) -> str:
        """Generate unique lock ID using UUID."""
        return f"lock_{document_id}_{owner_id}_{uuid.uuid4().hex}"
    
    def _generate_transaction_id(self, document_id: str) -> str:
        """Generate unique transaction ID using UUID."""
        return f"txn_{document_id}_{uuid.uuid4().hex}"
    
    def _generate_snapshot_id(self, document_id: str) -> str:
        """Generate unique snapshot ID using UUID."""
        return f"snap_{document_id}_{uuid.uuid4().hex}"
    
    def _generate_backup_id(self, document_id: str) -> str:
        """Generate unique backup ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"backup_{document_id}_{timestamp}"
    
    def _check_memory_limit(self) -> bool:
        """Check if memory usage is within limits."""
        if not PSUTIL_AVAILABLE:
            # If psutil is not available, assume memory is OK
            return True
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            return memory_mb < self.config.memory_limit_mb
        except Exception as e:
            logger.warning(f"Could not check memory limit: {e}")
            return True  # Assume OK if check fails
    
    @contextmanager
    def document_lock(self, document_id: str, owner_id: str, lock_type: str = "exclusive"):
        """Context manager for document locking."""
        lock = None
        try:
            lock = self.acquire_lock(document_id, owner_id, lock_type)
            yield lock
        finally:
            if lock:
                self.release_lock(document_id, lock.lock_id)
    
    @contextmanager
    def transaction(self, document_id: str):
        """Context manager for document transactions."""
        transaction = None
        try:
            transaction = self.start_transaction(document_id)
            yield transaction
        except Exception as e:
            if transaction:
                self.abort_transaction(transaction.transaction_id)
            raise
        else:
            if transaction:
                self.commit_transaction(transaction.transaction_id)
    
    def acquire_lock(
        self, 
        document_id: str, 
        owner_id: str, 
        lock_type: str = "exclusive",
        timeout_seconds: Optional[int] = None
    ) -> DocumentLock:
        """Acquire document lock with timeout."""
        correlation_id = get_correlation_id()
        
        with create_span("document_lock_acquire", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            span.set_attribute("lock.owner", owner_id)
            span.set_attribute("lock.type", lock_type)
            
            timeout = timeout_seconds or self.config.lock_timeout_seconds
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout)
            
            with self._lock:
                # Check for existing locks
                if document_id in self.locks:
                    existing_lock = self.locks[document_id]
                    if not existing_lock.is_expired():
                        raise DocumentException(
                            f"Document {document_id} is already locked",
                            DocumentErrorCode.DOCUMENT_LOCKED,
                            f"Belge {document_id} zaten kilitli",
                            {"existing_lock": existing_lock.dict()}
                        )
                
                # Create new lock
                lock = DocumentLock(
                    document_id=document_id,
                    lock_id=self._generate_lock_id(document_id, owner_id),
                    owner_id=owner_id,
                    lock_type=lock_type,
                    expires_at=expires_at
                )
                
                self.locks[document_id] = lock
                
                logger.info("document_lock_acquired",
                          document_id=document_id,
                          lock_id=lock.lock_id,
                          owner_id=owner_id,
                          correlation_id=correlation_id)
                
                metrics.freecad_document_locks_active.inc()
                
                return lock
    
    def release_lock(self, document_id: str, lock_id: str) -> bool:
        """Release document lock."""
        correlation_id = get_correlation_id()
        
        with create_span("document_lock_release", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            span.set_attribute("lock.id", lock_id)
            
            with self._lock:
                if document_id in self.locks:
                    lock = self.locks[document_id]
                    if lock.lock_id == lock_id:
                        del self.locks[document_id]
                        
                        logger.info("document_lock_released",
                                  document_id=document_id,
                                  lock_id=lock_id,
                                  correlation_id=correlation_id)
                        
                        metrics.freecad_document_locks_active.dec()
                        return True
                
                logger.warning("document_lock_not_found",
                             document_id=document_id,
                             lock_id=lock_id,
                             correlation_id=correlation_id)
                return False
    
    def create_document(
        self,
        job_id: str,
        author: Optional[str] = None,
        description: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> DocumentMetadata:
        """Create new FreeCAD document with metadata."""
        correlation_id = get_correlation_id()
        
        with create_span("document_create", correlation_id=correlation_id) as span:
            span.set_attribute("job.id", job_id)
            
            document_id = self._generate_document_id(job_id)
            
            # Check if document already exists
            if document_id in self.documents:
                raise DocumentException(
                    f"Document {document_id} already exists",
                    DocumentErrorCode.DOCUMENT_ALREADY_EXISTS,
                    f"Belge {document_id} zaten mevcut"
                )
            
            # Check memory limit
            if not self._check_memory_limit():
                self._trigger_memory_cleanup()
                if not self._check_memory_limit():
                    raise DocumentException(
                        "Memory limit exceeded",
                        DocumentErrorCode.MEMORY_LIMIT_EXCEEDED,
                        "Bellek sınırı aşıldı"
                    )
            
            # Create metadata
            metadata = DocumentMetadata(
                document_id=document_id,
                job_id=job_id,
                author=author,
                description=description,
                properties=properties or {}
            )
            
            with self._lock:
                self.documents[document_id] = metadata
                self.undo_stacks[document_id] = []
                self.redo_stacks[document_id] = []
            
            # Start auto-save if enabled
            if self.config.auto_save_interval_seconds > 0:
                self._start_auto_save(document_id)
            
            logger.info("document_created",
                      document_id=document_id,
                      job_id=job_id,
                      correlation_id=correlation_id)
            
            metrics.freecad_documents_total.labels(operation="create").inc()
            
            return metadata
    
    def open_document(
        self,
        job_id: str,
        document_path: Optional[str] = None,
        create_if_not_exists: bool = True
    ) -> DocumentMetadata:
        """Open existing document or create new one."""
        correlation_id = get_correlation_id()
        
        with create_span("document_open", correlation_id=correlation_id) as span:
            span.set_attribute("job.id", job_id)
            span.set_attribute("create_if_not_exists", create_if_not_exists)
            
            document_id = self._generate_document_id(job_id)
            
            # Check if already open
            if document_id in self.documents:
                logger.debug("document_already_open", document_id=document_id)
                return self.documents[document_id]
            
            # Try to load from storage
            if document_path and os.path.exists(document_path):
                metadata = self._load_document_from_file(document_path)
                metadata.document_id = document_id
                metadata.job_id = job_id
                
                with self._lock:
                    self.documents[document_id] = metadata
                
                logger.info("document_opened",
                          document_id=document_id,
                          path=document_path,
                          correlation_id=correlation_id)
                
                metrics.freecad_documents_total.labels(operation="open").inc()
                
                return metadata
            
            # Create new if requested
            if create_if_not_exists:
                return self.create_document(job_id)
            
            raise DocumentException(
                f"Document for job {job_id} not found",
                DocumentErrorCode.DOCUMENT_NOT_FOUND,
                f"İş {job_id} için belge bulunamadı"
            )
    
    def start_transaction(self, document_id: str) -> TransactionInfo:
        """Start document transaction."""
        correlation_id = get_correlation_id()
        
        with create_span("transaction_start", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            
            if document_id not in self.documents:
                raise DocumentException(
                    f"Document {document_id} not found",
                    DocumentErrorCode.DOCUMENT_NOT_FOUND,
                    f"Belge {document_id} bulunamadı"
                )
            
            transaction_id = self._generate_transaction_id(document_id)
            
            # Save current state for rollback
            rollback_data = self._create_document_snapshot(document_id)
            
            transaction = TransactionInfo(
                transaction_id=transaction_id,
                document_id=document_id,
                state=TransactionState.ACTIVE,
                started_at=datetime.now(timezone.utc),
                rollback_data=rollback_data
            )
            
            with self._lock:
                self.transactions[transaction_id] = transaction
            
            logger.info("transaction_started",
                      transaction_id=transaction_id,
                      document_id=document_id,
                      correlation_id=correlation_id)
            
            metrics.freecad_transactions_total.labels(operation="start").inc()
            
            return transaction
    
    def commit_transaction(self, transaction_id: str, owner_id: Optional[str] = None) -> bool:
        """Commit document transaction and apply buffered changes."""
        correlation_id = get_correlation_id()
        
        with create_span("transaction_commit", correlation_id=correlation_id) as span:
            span.set_attribute("transaction.id", transaction_id)
            
            if transaction_id not in self.transactions:
                raise DocumentException(
                    f"Transaction {transaction_id} not found",
                    DocumentErrorCode.TRANSACTION_FAILED,
                    f"İşlem {transaction_id} bulunamadı"
                )
            
            transaction = self.transactions[transaction_id]
            
            if transaction.state != TransactionState.ACTIVE:
                raise DocumentException(
                    f"Transaction {transaction_id} is not active",
                    DocumentErrorCode.TRANSACTION_FAILED,
                    f"İşlem {transaction_id} aktif değil"
                )
            
            try:
                transaction.state = TransactionState.COMMITTING
                
                # Apply buffered changes
                buffered_changes = transaction.get_buffered_changes()
                if buffered_changes and transaction.document_id in self.documents:
                    metadata = self.documents[transaction.document_id]
                    for key, value in buffered_changes.items():
                        if hasattr(metadata, key):
                            setattr(metadata, key, value)
                        else:
                            metadata.properties[key] = value
                
                # Update document metadata
                if transaction.document_id in self.documents:
                    metadata = self.documents[transaction.document_id]
                    metadata.increment_revision()
                
                transaction.state = TransactionState.COMMITTED
                transaction.ended_at = datetime.now(timezone.utc)
                
                # Clear redo stack on new change
                with self._lock:
                    if transaction.document_id in self.redo_stacks:
                        self.redo_stacks[transaction.document_id].clear()
                
                logger.info("transaction_committed",
                          transaction_id=transaction_id,
                          document_id=transaction.document_id,
                          operations=len(transaction.operations),
                          correlation_id=correlation_id)
                
                metrics.freecad_transactions_total.labels(operation="commit").inc()
                
                return True
                
            except Exception as e:
                logger.error("transaction_commit_failed",
                           transaction_id=transaction_id,
                           error=str(e),
                           correlation_id=correlation_id)
                
                transaction.state = TransactionState.ACTIVE
                raise DocumentException(
                    f"Failed to commit transaction: {str(e)}",
                    DocumentErrorCode.TRANSACTION_FAILED,
                    f"İşlem kaydetme başarısız: {str(e)}"
                )
            finally:
                # Clean up completed or failed transaction to prevent memory leak
                if transaction.state == TransactionState.COMMITTED:
                    with self._lock:
                        del self.transactions[transaction_id]
                elif transaction.state == TransactionState.ACTIVE:
                    # Clean up failed transaction to prevent memory leak
                    logger.warning("cleaning_up_failed_transaction",
                                 transaction_id=transaction_id,
                                 correlation_id=correlation_id)
                    with self._lock:
                        if transaction_id in self.transactions:
                            del self.transactions[transaction_id]
    
    def abort_transaction(self, transaction_id: str) -> bool:
        """Abort document transaction and rollback changes."""
        correlation_id = get_correlation_id()
        
        with create_span("transaction_abort", correlation_id=correlation_id) as span:
            span.set_attribute("transaction.id", transaction_id)
            
            if transaction_id not in self.transactions:
                logger.warning("transaction_not_found_for_abort",
                             transaction_id=transaction_id,
                             correlation_id=correlation_id)
                return False
            
            transaction = self.transactions[transaction_id]
            
            try:
                transaction.state = TransactionState.ABORTING
                
                # Restore from rollback data
                if transaction.rollback_data:
                    self._restore_document_snapshot(
                        transaction.document_id,
                        transaction.rollback_data
                    )
                
                transaction.state = TransactionState.ABORTED
                transaction.ended_at = datetime.now(timezone.utc)
                
                logger.info("transaction_aborted",
                          transaction_id=transaction_id,
                          document_id=transaction.document_id,
                          correlation_id=correlation_id)
                
                metrics.freecad_transactions_total.labels(operation="abort").inc()
                
                return True
                
            except Exception as e:
                logger.error("transaction_abort_failed",
                           transaction_id=transaction_id,
                           error=str(e),
                           correlation_id=correlation_id)
                
                transaction.state = TransactionState.ACTIVE
                return False
            finally:
                # Clean up aborted transaction
                if transaction.state == TransactionState.ABORTED:
                    with self._lock:
                        del self.transactions[transaction_id]
    
    @requires_lock
    def save_document(
        self,
        document_id: str,
        save_path: Optional[str] = None,
        compress: bool = None,
        create_backup: bool = True,
        owner_id: Optional[str] = None
    ) -> str:
        """Save document with optional compression and backup."""
        correlation_id = get_correlation_id()
        
        with create_span("document_save", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            span.set_attribute("compress", compress if compress is not None else self.config.enable_compression)
            span.set_attribute("create_backup", create_backup)
            
            if document_id not in self.documents:
                raise DocumentException(
                    f"Document {document_id} not found",
                    DocumentErrorCode.DOCUMENT_NOT_FOUND,
                    f"Belge {document_id} bulunamadı"
                )
            
            metadata = self.documents[document_id]
            
            # Create backup if requested
            if create_backup:
                try:
                    self._create_backup(document_id)
                except Exception as e:
                    logger.warning("backup_creation_failed",
                                 document_id=document_id,
                                 error=str(e),
                                 correlation_id=correlation_id)
            
            # Determine save path using temp directory
            if not save_path:
                save_path = os.path.join(tempfile.gettempdir(), f"{document_id}.FCStd")
            
            # Prepare save data
            save_data = {
                "metadata": metadata.dict(),
                "undo_stack": [snap.dict() for snap in self.undo_stacks.get(document_id, [])],
                "assembly": self.assemblies.get(document_id, {})
            }
            
            # Compress if requested
            should_compress = compress if compress is not None else self.config.enable_compression
            
            try:
                if should_compress:
                    save_path = self._save_compressed(save_path, save_data)
                    metadata.compressed = True
                else:
                    save_path = self._save_uncompressed(save_path, save_data)
                    metadata.compressed = False
                
                # Update metadata
                metadata.file_size_bytes = os.path.getsize(save_path)
                metadata.sha256_hash = self._compute_file_hash(save_path)
                
                logger.info("document_saved",
                          document_id=document_id,
                          path=save_path,
                          size_bytes=metadata.file_size_bytes,
                          compressed=metadata.compressed,
                          correlation_id=correlation_id)
                
                metrics.freecad_document_saves_total.labels(
                    compressed=str(metadata.compressed)
                ).inc()
                
                return save_path
                
            except Exception as e:
                logger.error("document_save_failed",
                           document_id=document_id,
                           error=str(e),
                           correlation_id=correlation_id,
                           exc_info=True)
                
                raise DocumentException(
                    f"Failed to save document: {str(e)}",
                    DocumentErrorCode.SAVE_FAILED,
                    f"Belge kaydetme başarısız: {str(e)}"
                )
    
    @requires_lock
    def close_document(
        self,
        document_id: str,
        save_before_close: bool = True,
        force: bool = False,
        owner_id: Optional[str] = None
    ) -> bool:
        """Close document with cleanup."""
        correlation_id = get_correlation_id()
        
        with create_span("document_close", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            span.set_attribute("save_before_close", save_before_close)
            span.set_attribute("force", force)
            
            if document_id not in self.documents:
                logger.warning("document_not_open",
                             document_id=document_id,
                             correlation_id=correlation_id)
                return False
            
            # Check for active transactions
            active_transactions = [
                txn_id for txn_id, txn in self.transactions.items()
                if txn.document_id == document_id and txn.state == TransactionState.ACTIVE
            ]
            
            if active_transactions and not force:
                raise DocumentException(
                    f"Document has active transactions: {active_transactions}",
                    DocumentErrorCode.TRANSACTION_FAILED,
                    f"Belgede aktif işlemler var: {active_transactions}"
                )
            
            # Save if requested
            if save_before_close:
                try:
                    self.save_document(document_id)
                except Exception as e:
                    if not force:
                        raise
                    logger.warning("save_before_close_failed",
                                 document_id=document_id,
                                 error=str(e),
                                 correlation_id=correlation_id)
            
            # Stop auto-save
            self._stop_auto_save(document_id)
            
            # Clean up resources
            with self._lock:
                del self.documents[document_id]
                
                # Clean up related data
                self.undo_stacks.pop(document_id, None)
                self.redo_stacks.pop(document_id, None)
                self.assemblies.pop(document_id, None)
                self.locks.pop(document_id, None)
                
                # Abort active transactions if forced
                if force:
                    for txn_id in active_transactions:
                        self.abort_transaction(txn_id)
            
            # Trigger garbage collection
            gc.collect()
            
            logger.info("document_closed",
                      document_id=document_id,
                      forced=force,
                      correlation_id=correlation_id)
            
            metrics.freecad_documents_total.labels(operation="close").inc()
            
            return True
    
    def add_undo_snapshot(
        self,
        document_id: str,
        description: str,
        data: Optional[Dict[str, Any]] = None
    ) -> DocumentSnapshot:
        """Add snapshot to undo stack."""
        if document_id not in self.documents:
            raise DocumentException(
                f"Document {document_id} not found",
                DocumentErrorCode.DOCUMENT_NOT_FOUND,
                f"Belge {document_id} bulunamadı"
            )
        
        snapshot_data = data or self._create_document_snapshot(document_id)
        
        # Calculate actual size for snapshot
        snapshot_size = len(json.dumps(snapshot_data, default=str))
        
        snapshot = DocumentSnapshot(
            snapshot_id=self._generate_snapshot_id(document_id),
            document_id=document_id,
            description=description,
            data=snapshot_data,
            size_bytes=snapshot_size
        )
        
        with self._lock:
            if document_id not in self.undo_stacks:
                self.undo_stacks[document_id] = []
            
            # Limit stack size
            if len(self.undo_stacks[document_id]) >= self.config.max_undo_stack_size:
                self.undo_stacks[document_id].pop(0)
            
            self.undo_stacks[document_id].append(snapshot)
            
            # Clear redo stack on new change
            self.redo_stacks[document_id] = []
        
        logger.debug("undo_snapshot_added",
                   document_id=document_id,
                   snapshot_id=snapshot.snapshot_id,
                   description=description)
        
        return snapshot
    
    def undo(self, document_id: str) -> Optional[DocumentSnapshot]:
        """Undo last operation."""
        with self._lock:
            if document_id not in self.undo_stacks or not self.undo_stacks[document_id]:
                logger.debug("no_undo_available", document_id=document_id)
                return None
            
            # Pop from undo stack
            snapshot = self.undo_stacks[document_id].pop()
            
            # Save current state to redo stack
            current_data = self._create_document_snapshot(document_id)
            # Calculate actual size for current snapshot
            current_size = len(json.dumps(current_data, default=str))
            
            current_snapshot = DocumentSnapshot(
                snapshot_id=self._generate_snapshot_id(document_id),
                document_id=document_id,
                description=f"Before undo: {snapshot.description}",
                data=current_data,
                size_bytes=current_size
            )
            
            if document_id not in self.redo_stacks:
                self.redo_stacks[document_id] = []
            
            self.redo_stacks[document_id].append(current_snapshot)
            
            # Restore snapshot
            self._restore_document_snapshot(document_id, snapshot.data)
            
            logger.info("undo_performed",
                      document_id=document_id,
                      snapshot_id=snapshot.snapshot_id,
                      description=snapshot.description)
            
            return snapshot
    
    def redo(self, document_id: str) -> Optional[DocumentSnapshot]:
        """Redo last undone operation."""
        with self._lock:
            if document_id not in self.redo_stacks or not self.redo_stacks[document_id]:
                logger.debug("no_redo_available", document_id=document_id)
                return None
            
            # Pop from redo stack
            snapshot = self.redo_stacks[document_id].pop()
            
            # Save current state to undo stack
            current_data = self._create_document_snapshot(document_id)
            # Calculate actual size for current snapshot
            current_size = len(json.dumps(current_data, default=str))
            
            current_snapshot = DocumentSnapshot(
                snapshot_id=self._generate_snapshot_id(document_id),
                document_id=document_id,
                description=f"Before redo: {snapshot.description}",
                data=current_data,
                size_bytes=current_size
            )
            
            self.undo_stacks[document_id].append(current_snapshot)
            
            # Restore snapshot
            self._restore_document_snapshot(document_id, snapshot.data)
            
            logger.info("redo_performed",
                      document_id=document_id,
                      snapshot_id=snapshot.snapshot_id,
                      description=snapshot.description)
            
            return snapshot
    
    def setup_assembly_coordination(
        self,
        assembly_id: str,
        parent_document_id: Optional[str] = None,
        child_document_ids: Optional[List[str]] = None
    ) -> AssemblyCoordination:
        """Setup multi-document coordination for assemblies."""
        correlation_id = get_correlation_id()
        
        with create_span("assembly_coordination_setup", correlation_id=correlation_id) as span:
            span.set_attribute("assembly.id", assembly_id)
            
            coordination = AssemblyCoordination(
                assembly_id=assembly_id,
                parent_document_id=parent_document_id,
                child_document_ids=child_document_ids or []
            )
            
            with self._lock:
                self.assemblies[assembly_id] = coordination
            
            logger.info("assembly_coordination_setup",
                      assembly_id=assembly_id,
                      parent=parent_document_id,
                      children=len(child_document_ids or []),
                      correlation_id=correlation_id)
            
            return coordination
    
    def migrate_document(
        self,
        document_id: str,
        target_version: str,
        migration_rules: Optional[Dict[str, Any]] = None
    ) -> DocumentMigration:
        """Migrate document to new FreeCAD version."""
        correlation_id = get_correlation_id()
        
        with create_span("document_migration", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            span.set_attribute("target.version", target_version)
            
            if document_id not in self.documents:
                raise DocumentException(
                    f"Document {document_id} not found",
                    DocumentErrorCode.DOCUMENT_NOT_FOUND,
                    f"Belge {document_id} bulunamadı"
                )
            
            metadata = self.documents[document_id]
            
            # Get source version from metadata if available
            source_version = metadata.properties.get("freecad_version", "1.1.0")
            
            migration = DocumentMigration(
                migration_id=f"mig_{document_id}_{int(time.time())}",
                source_version=source_version,
                target_version=target_version,
                started_at=datetime.now(timezone.utc)
            )
            
            try:
                # Create backup before migration
                self._create_backup(document_id)
                
                # Apply migration rules
                if migration_rules:
                    for rule_name, rule_config in migration_rules.items():
                        try:
                            self._apply_migration_rule(
                                document_id, rule_name, rule_config
                            )
                            migration.changes_applied.append({
                                "rule": rule_name,
                                "status": "success"
                            })
                        except Exception as e:
                            migration.warnings.append(
                                f"Rule {rule_name} failed: {str(e)}"
                            )
                            migration.changes_applied.append({
                                "rule": rule_name,
                                "status": "failed",
                                "error": str(e)
                            })
                
                # Update metadata
                metadata.increment_version()
                metadata.properties["migration_version"] = target_version
                
                migration.status = "completed"
                migration.completed_at = datetime.now(timezone.utc)
                
                logger.info("document_migrated",
                          document_id=document_id,
                          migration_id=migration.migration_id,
                          target_version=target_version,
                          changes=len(migration.changes_applied),
                          warnings=len(migration.warnings),
                          correlation_id=correlation_id)
                
                metrics.freecad_document_migrations_total.labels(
                    status="success"
                ).inc()
                
                return migration
                
            except Exception as e:
                migration.status = "failed"
                migration.errors.append(str(e))
                migration.completed_at = datetime.now(timezone.utc)
                
                logger.error("document_migration_failed",
                           document_id=document_id,
                           migration_id=migration.migration_id,
                           error=str(e),
                           correlation_id=correlation_id)
                
                metrics.freecad_document_migrations_total.labels(
                    status="failed"
                ).inc()
                
                raise DocumentException(
                    f"Migration failed: {str(e)}",
                    DocumentErrorCode.MIGRATION_FAILED,
                    f"Geçiş başarısız: {str(e)}"
                )
    
    def create_backup(self, document_id: str) -> BackupInfo:
        """Create document backup."""
        return self._create_backup(document_id)
    
    def restore_backup(self, backup_id: str) -> DocumentMetadata:
        """Restore document from backup."""
        correlation_id = get_correlation_id()
        
        with create_span("backup_restore", correlation_id=correlation_id) as span:
            span.set_attribute("backup.id", backup_id)
            
            # Optimize backup lookup by extracting document_id from backup_id
            # backup_id format: "backup_{document_id}_{YYYYMMDD}_{HHMMSS}"
            backup_info = None
            parts = backup_id.split('_')
            if len(parts) >= 4 and parts[0] == 'backup':
                # The last two parts are date and time, so exclude them
                potential_doc_id = '_'.join(parts[1:-2])  # Handle doc IDs with underscores
                if potential_doc_id in self.backups:
                    for backup in self.backups[potential_doc_id]:
                        if backup.backup_id == backup_id:
                            backup_info = backup
                            break
            
            # Fallback to exhaustive search if optimized lookup fails
            if not backup_info:
                for doc_backups in self.backups.values():
                    for backup in doc_backups:
                        if backup.backup_id == backup_id:
                            backup_info = backup
                            break
            
            if not backup_info:
                raise DocumentException(
                    f"Backup {backup_id} not found",
                    DocumentErrorCode.RESTORE_FAILED,
                    f"Yedek {backup_id} bulunamadı"
                )
            
            try:
                # Load backup data
                if backup_info.compressed:
                    with gzip.open(backup_info.backup_path, 'rb') as f:
                        backup_data = json.loads(f.read().decode('utf-8'))
                else:
                    with open(backup_info.backup_path, 'r') as f:
                        backup_data = json.load(f)
                
                # Restore metadata
                metadata = DocumentMetadata(**backup_data['metadata'])
                
                # Close current document if open
                if metadata.document_id in self.documents:
                    self.close_document(metadata.document_id, save_before_close=False)
                
                # Restore document
                with self._lock:
                    self.documents[metadata.document_id] = metadata
                    
                    if 'undo_stack' in backup_data:
                        self.undo_stacks[metadata.document_id] = [
                            DocumentSnapshot(**snap) for snap in backup_data['undo_stack']
                        ]
                
                logger.info("backup_restored",
                          backup_id=backup_id,
                          document_id=metadata.document_id,
                          correlation_id=correlation_id)
                
                metrics.freecad_backup_restores_total.labels(
                    status="success"
                ).inc()
                
                return metadata
                
            except Exception as e:
                logger.error("backup_restore_failed",
                           backup_id=backup_id,
                           error=str(e),
                           correlation_id=correlation_id)
                
                metrics.freecad_backup_restores_total.labels(
                    status="failed"
                ).inc()
                
                raise DocumentException(
                    f"Restore failed: {str(e)}",
                    DocumentErrorCode.RESTORE_FAILED,
                    f"Geri yükleme başarısız: {str(e)}"
                )
    
    def auto_recover(self, document_id: str) -> bool:
        """Attempt auto-recovery of corrupted document."""
        correlation_id = get_correlation_id()
        
        with create_span("document_auto_recover", correlation_id=correlation_id) as span:
            span.set_attribute("document.id", document_id)
            
            if not self.config.enable_auto_recovery:
                logger.debug("auto_recovery_disabled", document_id=document_id)
                return False
            
            try:
                # Try to recover from recovery data
                if document_id in self._recovery_data:
                    recovery_data = self._recovery_data[document_id]
                    self._restore_document_snapshot(document_id, recovery_data)
                    
                    logger.info("document_recovered_from_memory",
                              document_id=document_id,
                              correlation_id=correlation_id)
                    return True
                
                # Try to recover from latest backup
                if document_id in self.backups and self.backups[document_id]:
                    latest_backup = sorted(
                        self.backups[document_id],
                        key=lambda b: b.created_at,
                        reverse=True
                    )[0]
                    
                    self.restore_backup(latest_backup.backup_id)
                    
                    logger.info("document_recovered_from_backup",
                              document_id=document_id,
                              backup_id=latest_backup.backup_id,
                              correlation_id=correlation_id)
                    return True
                
                logger.warning("no_recovery_data_available",
                             document_id=document_id,
                             correlation_id=correlation_id)
                return False
                
            except Exception as e:
                logger.error("auto_recovery_failed",
                           document_id=document_id,
                           error=str(e),
                           correlation_id=correlation_id)
                
                raise DocumentException(
                    f"Recovery failed: {str(e)}",
                    DocumentErrorCode.RECOVERY_FAILED,
                    f"Kurtarma başarısız: {str(e)}"
                )
    
    def get_document_status(self, document_id: str) -> Dict[str, Any]:
        """Get comprehensive document status."""
        if document_id not in self.documents:
            return {"status": "not_found", "document_id": document_id}
        
        metadata = self.documents[document_id]
        
        # Check for locks - return dict format for compatibility
        lock_info = None
        if document_id in self.locks:
            lock = self.locks[document_id]
            lock_info = {
                "locked": True,
                "lock_id": lock.lock_id,
                "owner": lock.owner_id,
                "expires_at": lock.expires_at.isoformat() if lock.expires_at else None,
                "is_expired": lock.is_expired()
            }
        
        # Check for transactions
        active_transactions = [
            {
                "transaction_id": txn.transaction_id,
                "state": txn.state.value,
                "started_at": txn.started_at.isoformat() if txn.started_at else None,
                "operations": len(txn.operations)
            }
            for txn in self.transactions.values()
            if txn.document_id == document_id
        ]
        
        # Check undo/redo stacks
        undo_available = len(self.undo_stacks.get(document_id, []))
        redo_available = len(self.redo_stacks.get(document_id, []))
        
        # Check for assembly coordination
        assembly_info = None
        if document_id in self.assemblies:
            assembly = self.assemblies[document_id]
            assembly_info = {
                "is_assembly": True,
                "parent": assembly.parent_document_id,
                "children": assembly.child_document_ids,
                "constraints": len(assembly.constraints)
            }
        
        return {
            "status": "open",
            "document_id": document_id,
            "metadata": metadata.dict(),
            "lock": lock_info,
            "transactions": active_transactions,
            "undo_stack_size": undo_available,
            "redo_stack_size": redo_available,
            "assembly": assembly_info,
            "backup_count": len(self.backups.get(document_id, []))
        }
    
    # Private helper methods
    def _create_document_snapshot(self, document_id: str) -> Dict[str, Any]:
        """Create snapshot of document state."""
        if document_id not in self.documents:
            return {}
        
        metadata = self.documents[document_id]
        
        return {
            "metadata": metadata.dict(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "undo_stack_size": len(self.undo_stacks.get(document_id, [])),
            "redo_stack_size": len(self.redo_stacks.get(document_id, []))
        }
    
    def _restore_document_snapshot(self, document_id: str, snapshot_data: Dict[str, Any]):
        """Restore document from snapshot."""
        if not snapshot_data:
            return
        
        if 'metadata' in snapshot_data:
            metadata = DocumentMetadata(**snapshot_data['metadata'])
            with self._lock:
                self.documents[document_id] = metadata
    
    def _save_compressed(self, save_path: str, data: Dict[str, Any]) -> str:
        """Save document with gzip compression."""
        compressed_path = save_path + ".gz"
        
        with gzip.open(compressed_path, 'wb') as f:
            f.write(json.dumps(data, indent=2).encode('utf-8'))
        
        return compressed_path
    
    def _save_uncompressed(self, save_path: str, data: Dict[str, Any]) -> str:
        """Save document without compression."""
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        return save_path
    
    def _load_document_from_file(self, file_path: str) -> DocumentMetadata:
        """Load document metadata from file."""
        if file_path.endswith('.gz'):
            with gzip.open(file_path, 'rb') as f:
                data = json.loads(f.read().decode('utf-8'))
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        return DocumentMetadata(**data.get('metadata', {}))
    
    def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def _start_auto_save(self, document_id: str):
        """Start auto-save thread for document."""
        if document_id in self._auto_save_threads:
            return
        
        def auto_save_loop():
            while document_id in self.documents:
                time.sleep(self.config.auto_save_interval_seconds)
                
                if document_id not in self.documents:
                    break
                
                try:
                    # Save recovery data
                    self._recovery_data[document_id] = self._create_document_snapshot(document_id)
                    
                    logger.debug("auto_save_checkpoint", document_id=document_id)
                except Exception as e:
                    logger.error("auto_save_failed",
                               document_id=document_id,
                               error=str(e))
        
        thread = threading.Thread(target=auto_save_loop, daemon=True)
        thread.start()
        self._auto_save_threads[document_id] = thread
    
    def _stop_auto_save(self, document_id: str):
        """Stop auto-save thread for document."""
        if document_id in self._auto_save_threads:
            # Thread will stop when document is removed from self.documents
            del self._auto_save_threads[document_id]
            
            # Clean up recovery data
            self._recovery_data.pop(document_id, None)
    
    def _create_backup(self, document_id: str) -> BackupInfo:
        """Create backup of document."""
        if document_id not in self.documents:
            raise DocumentException(
                f"Document {document_id} not found",
                DocumentErrorCode.DOCUMENT_NOT_FOUND,
                f"Belge {document_id} bulunamadı"
            )
        
        metadata = self.documents[document_id]
        backup_id = self._generate_backup_id(document_id)
        # Use proper backup directory in temp folder
        backup_dir = os.path.join(tempfile.gettempdir(), "freecad_backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"{backup_id}.json")
        
        # Prepare backup data
        backup_data = {
            "metadata": metadata.dict(),
            "undo_stack": [snap.dict() for snap in self.undo_stacks.get(document_id, [])],
            "assembly": self.assemblies.get(document_id, {})
        }
        
        # Save backup
        if self.config.enable_compression:
            backup_path = self._save_compressed(backup_path, backup_data)
        else:
            backup_path = self._save_uncompressed(backup_path, backup_data)
        
        backup_info = BackupInfo(
            backup_id=backup_id,
            document_id=document_id,
            backup_path=backup_path,
            size_bytes=os.path.getsize(backup_path),
            metadata=metadata,
            compressed=self.config.enable_compression,
            retention_days=self.config.backup_retention_days
        )
        
        with self._lock:
            if document_id not in self.backups:
                self.backups[document_id] = []
            self.backups[document_id].append(backup_info)
        
        logger.info("backup_created",
                  backup_id=backup_id,
                  document_id=document_id,
                  size_bytes=backup_info.size_bytes)
        
        metrics.freecad_backups_total.inc()
        
        # Prune old backups
        self._prune_backups(document_id)
        
        return backup_info
    
    def _prune_backups(self, document_id: str):
        """Prune old backups based on retention policy."""
        if document_id not in self.backups:
            return
        
        backups = self.backups[document_id]
        
        # Remove backups older than retention days
        retention_cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.backup_retention_days)
        backups_to_keep = []
        
        for backup in backups:
            if backup.created_at > retention_cutoff:
                backups_to_keep.append(backup)
            else:
                # Delete old backup file
                try:
                    if os.path.exists(backup.backup_path):
                        os.remove(backup.backup_path)
                    logger.debug("Pruned old backup", backup_id=backup.backup_id)
                except Exception as e:
                    logger.warning("Failed to delete old backup",
                                 backup_id=backup.backup_id,
                                 error=str(e))
        
        # Keep only max number of backups
        if len(backups_to_keep) > self.config.max_backups_per_document:
            # Sort by creation time (newest first)
            backups_to_keep.sort(key=lambda b: b.created_at, reverse=True)
            
            # Remove excess old backups
            for backup in backups_to_keep[self.config.max_backups_per_document:]:
                try:
                    if os.path.exists(backup.backup_path):
                        os.remove(backup.backup_path)
                    logger.debug("Pruned excess backup", backup_id=backup.backup_id)
                except Exception as e:
                    logger.warning("Failed to delete excess backup",
                                 backup_id=backup.backup_id,
                                 error=str(e))
            
            # Keep only the allowed number
            backups_to_keep = backups_to_keep[:self.config.max_backups_per_document]
        
        self.backups[document_id] = backups_to_keep
    
    def _apply_migration_rule(
        self,
        document_id: str,
        rule_name: str,
        rule_config: Dict[str, Any]
    ):
        """Apply specific migration rule to document."""
        # Implementation would depend on specific migration rules
        # This is a placeholder for the pattern
        logger.debug("applying_migration_rule",
                   document_id=document_id,
                   rule_name=rule_name)
        
        # Example rules:
        # - Update property names
        # - Convert old format to new format
        # - Fix deprecated features
        # - Update references
        pass
    
    def _trigger_memory_cleanup(self):
        """Trigger memory cleanup by closing least recently used documents."""
        with self._lock:
            # Sort documents by last modified time
            sorted_docs = sorted(
                self.documents.items(),
                key=lambda x: x[1].modified_at
            )
            
            # Close oldest documents until memory is available
            for doc_id, metadata in sorted_docs[:len(sorted_docs)//2]:
                try:
                    self.close_document(doc_id, save_before_close=True)
                    logger.info("document_closed_for_memory",
                              document_id=doc_id)
                except Exception as e:
                    logger.warning("memory_cleanup_close_failed",
                                 document_id=doc_id,
                                 error=str(e))
        
        # Force garbage collection
        gc.collect()
    
    def shutdown(self):
        """Shutdown document manager and cleanup."""
        logger.info("document_manager_shutdown_initiated")
        
        # Save and close all open documents
        for document_id in list(self.documents.keys()):
            try:
                self.close_document(document_id, save_before_close=True)
            except Exception as e:
                logger.error("shutdown_close_failed",
                           document_id=document_id,
                           error=str(e))
        
        # Clear all data
        with self._lock:
            self.documents.clear()
            self.locks.clear()
            self.transactions.clear()
            self.undo_stacks.clear()
            self.redo_stacks.clear()
            self.assemblies.clear()
            self.backups.clear()
            self._recovery_data.clear()
        
        logger.info("document_manager_shutdown_completed")


# Global document manager instance
document_manager = FreeCADDocumentManager()