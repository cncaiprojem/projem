"""
Offline Synchronization for Collaborative FreeCAD Editing.
Handles reconnection scenarios and offline operation transformation.
"""

import logging
import json
from datetime import datetime, UTC, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from collections import deque
import uuid
import hashlib

from app.services.operational_transform import (
    OperationalTransform,
    ModelOperation,
    OperationType,
    ConflictResolutionStrategy
)
from app.services.conflict_resolver import ConflictResolver, ModelConflict

logger = logging.getLogger(__name__)


@dataclass
class SyncState:
    """Represents synchronization state for a client."""
    client_id: str
    document_id: str
    last_sync_version: int = 0
    last_sync_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    offline_since: Optional[datetime] = None
    online_since: Optional[datetime] = None
    pending_operations: List[ModelOperation] = field(default_factory=list)
    checksum: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_online(self) -> bool:
        """Check if client is currently online."""
        return self.online_since is not None and self.offline_since is None
    
    def mark_offline(self):
        """Mark client as offline."""
        self.offline_since = datetime.now(UTC)
        self.online_since = None
    
    def mark_online(self):
        """Mark client as online."""
        self.online_since = datetime.now(UTC)
        self.offline_since = None
    
    def get_offline_duration(self) -> Optional[timedelta]:
        """Get duration client was offline."""
        if self.offline_since and self.online_since:
            return self.online_since - self.offline_since
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "document_id": self.document_id,
            "last_sync_version": self.last_sync_version,
            "last_sync_timestamp": self.last_sync_timestamp.isoformat(),
            "offline_since": self.offline_since.isoformat() if self.offline_since else None,
            "online_since": self.online_since.isoformat() if self.online_since else None,
            "pending_operations": [op.to_dict() for op in self.pending_operations],
            "checksum": self.checksum,
            "metadata": self.metadata
        }


@dataclass
class SyncResult:
    """Result of a synchronization attempt."""
    success: bool = False
    operations_applied: int = 0
    operations_rejected: int = 0
    conflicts_resolved: int = 0
    new_version: int = 0
    new_checksum: Optional[str] = None
    transformed_operations: List[ModelOperation] = field(default_factory=list)
    failed_operations: List[ModelOperation] = field(default_factory=list)
    conflicts: List[ModelConflict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "operations_applied": self.operations_applied,
            "operations_rejected": self.operations_rejected,
            "conflicts_resolved": self.conflicts_resolved,
            "new_version": self.new_version,
            "new_checksum": self.new_checksum,
            "transformed_operations": [op.to_dict() for op in self.transformed_operations],
            "failed_operations": [op.to_dict() for op in self.failed_operations],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "metadata": self.metadata
        }


@dataclass
class OperationBuffer:
    """Buffer for offline operations."""
    max_size: int = 10000
    operations: deque = field(default_factory=lambda: deque(maxlen=10000))
    operation_index: Dict[str, ModelOperation] = field(default_factory=dict)
    
    def add(self, operation: ModelOperation):
        """Add operation to buffer."""
        self.operations.append(operation)
        self.operation_index[operation.id] = operation
    
    def get_since(self, version: int) -> List[ModelOperation]:
        """Get operations since a specific version."""
        return [op for op in self.operations if op.version > version]
    
    def clear(self):
        """Clear the buffer."""
        self.operations.clear()
        self.operation_index.clear()
    
    def size(self) -> int:
        """Get buffer size."""
        return len(self.operations)


class OfflineSync:
    """
    Manages offline synchronization for collaborative editing.
    """
    
    def __init__(self):
        self.sync_states: Dict[str, SyncState] = {}  # client_id -> SyncState
        self.operation_buffers: Dict[str, OperationBuffer] = {}  # document_id -> buffer
        self.operation_transform = OperationalTransform()
        self.conflict_resolver = ConflictResolver()
        self.version_vectors: Dict[str, Dict[str, int]] = {}  # document_id -> client_id -> version
        self.conflict_history: Dict[str, List[Dict[str, Any]]] = {}  # document_id -> list of conflicts
        
    def register_client(
        self,
        client_id: str,
        document_id: str
    ) -> SyncState:
        """Register a new client for synchronization."""
        if client_id not in self.sync_states:
            state = SyncState(
                client_id=client_id,
                document_id=document_id
            )
            state.mark_online()
            self.sync_states[client_id] = state
            
            # Initialize version vector
            if document_id not in self.version_vectors:
                self.version_vectors[document_id] = {}
            self.version_vectors[document_id][client_id] = 0
            
            logger.info(f"Registered client {client_id} for document {document_id}")
        
        return self.sync_states[client_id]
    
    def mark_client_offline(self, client_id: str):
        """Mark a client as offline."""
        if client_id in self.sync_states:
            self.sync_states[client_id].mark_offline()
            logger.info(f"Client {client_id} marked as offline")
    
    def mark_client_online(self, client_id: str):
        """Mark a client as online."""
        if client_id in self.sync_states:
            self.sync_states[client_id].mark_online()
            logger.info(f"Client {client_id} marked as online")
    
    async def handle_reconnection(
        self,
        client_id: str,
        offline_operations: List[ModelOperation],
        client_checksum: Optional[str] = None
    ) -> SyncResult:
        """
        Handle client reconnection and sync offline changes.
        
        Args:
            client_id: Client identifier
            offline_operations: Operations performed while offline
            client_checksum: Client's document checksum for verification
            
        Returns:
            SyncResult with synchronization outcome
        """
        logger.info(f"Handling reconnection for client {client_id} with {len(offline_operations)} offline operations")
        
        # Get sync state
        if client_id not in self.sync_states:
            return SyncResult(
                success=False,
                metadata={"error": "Client not registered"}
            )
        
        state = self.sync_states[client_id]
        state.mark_online()
        
        # Get document operations since last sync
        document_id = state.document_id
        server_operations = await self._get_operations_since(
            document_id,
            state.last_sync_version
        )
        
        logger.debug(f"Found {len(server_operations)} server operations since version {state.last_sync_version}")
        
        # Verify checksum if provided
        if client_checksum and state.checksum:
            if not self._verify_checksum(client_checksum, state.checksum):
                logger.warning(f"Checksum mismatch for client {client_id}")
                # Full resync needed
                return await self._full_resync(client_id)
        
        # Transform offline operations against server operations
        result = await self._transform_and_apply(
            offline_operations,
            server_operations,
            state
        )
        
        # Update sync state
        if result.success:
            state.last_sync_version = result.new_version
            state.last_sync_timestamp = datetime.now(UTC)
            state.checksum = result.new_checksum
            state.pending_operations.clear()
        else:
            # Store failed operations for retry
            state.pending_operations = result.failed_operations
        
        # Log offline duration
        offline_duration = state.get_offline_duration()
        if offline_duration:
            logger.info(f"Client {client_id} was offline for {offline_duration.total_seconds():.1f} seconds")
            result.metadata["offline_duration"] = offline_duration.total_seconds()
        
        return result
    
    async def _transform_and_apply(
        self,
        offline_operations: List[ModelOperation],
        server_operations: List[ModelOperation],
        state: SyncState
    ) -> SyncResult:
        """Transform offline operations against server operations and apply."""
        result = SyncResult()
        
        # Transform each offline operation against all server operations
        transformed_operations = []
        conflicts = []
        
        for offline_op in offline_operations:
            current_op = offline_op
            
            # Transform against each server operation
            for server_op in server_operations:
                transform_result = self.operation_transform.transform_operation(
                    current_op,
                    server_op,
                    ConflictResolutionStrategy.MERGE
                )
                
                current_op = transform_result.op1_prime
                
                # Check for conflicts
                if not transform_result.conflict_resolved:
                    conflict = ModelConflict(
                        operation1=offline_op,
                        operation2=server_op,
                        affected_objects=[offline_op.object_id] if offline_op.object_id else []
                    )
                    conflicts.append(conflict)
            
            # Add transformed operation if not no-op
            if not current_op.is_no_op():
                transformed_operations.append(current_op)
        
        # Resolve conflicts
        for conflict in conflicts:
            resolution = await self.conflict_resolver.resolve_conflict(
                conflict,
                ConflictResolutionStrategy.MERGE
            )
            
            if resolution.success:
                result.conflicts_resolved += 1
                if resolution.resolved_operation:
                    transformed_operations.append(resolution.resolved_operation)
            else:
                result.conflicts.append(conflict)
        
        # Apply transformed operations
        for op in transformed_operations:
            success = await self._apply_operation(state.document_id, op)
            
            if success:
                result.operations_applied += 1
                result.transformed_operations.append(op)
            else:
                result.operations_rejected += 1
                result.failed_operations.append(op)
        
        # Calculate new version and checksum
        if result.operations_applied > 0:
            result.new_version = state.last_sync_version + len(server_operations) + result.operations_applied
            result.new_checksum = self._calculate_checksum(state.document_id)
            result.success = True
        else:
            result.new_version = state.last_sync_version + len(server_operations)
            result.new_checksum = state.checksum
            result.success = result.operations_rejected == 0
        
        logger.info(f"Sync result: {result.operations_applied} applied, {result.operations_rejected} rejected, {result.conflicts_resolved} conflicts resolved")
        
        return result
    
    async def _get_operations_since(
        self,
        document_id: str,
        version: int
    ) -> List[ModelOperation]:
        """Get operations that occurred since a specific version."""
        if document_id not in self.operation_buffers:
            self.operation_buffers[document_id] = OperationBuffer()
        
        buffer = self.operation_buffers[document_id]
        return buffer.get_since(version)
    
    async def _apply_operation(
        self,
        document_id: str,
        operation: ModelOperation
    ) -> bool:
        """
        Apply an operation to the document.
        
        This would integrate with FreeCADDocumentManager.
        """
        try:
            # TODO: Integrate with FreeCADDocumentManager
            # For now, just add to buffer
            if document_id not in self.operation_buffers:
                self.operation_buffers[document_id] = OperationBuffer()
            
            self.operation_buffers[document_id].add(operation)
            
            # Update version vector
            if operation.user_id:
                if document_id not in self.version_vectors:
                    self.version_vectors[document_id] = {}
                
                current_version = self.version_vectors[document_id].get(operation.user_id, 0)
                self.version_vectors[document_id][operation.user_id] = current_version + 1
            
            return True
            
        except Exception as e:
            logger.error(f"Error applying operation {operation.id}: {e}")
            return False
    
    async def _full_resync(self, client_id: str) -> SyncResult:
        """Perform full resynchronization for a client."""
        logger.info(f"Performing full resync for client {client_id}")
        
        state = self.sync_states[client_id]
        
        # Get current document state
        # TODO: Get from FreeCADDocumentManager
        
        result = SyncResult()
        result.success = True
        result.new_version = self._get_current_version(state.document_id)
        result.new_checksum = self._calculate_checksum(state.document_id)
        result.metadata["full_resync"] = True
        
        # Update state
        state.last_sync_version = result.new_version
        state.last_sync_timestamp = datetime.now(UTC)
        state.checksum = result.new_checksum
        state.pending_operations.clear()
        
        return result
    
    def _calculate_checksum(self, document_id: str) -> str:
        """Calculate checksum for document state."""
        # TODO: Calculate from actual document state
        # For now, use version vector with deterministic JSON serialization
        if document_id in self.version_vectors:
            # Use sort_keys=True and ensure_ascii=True for deterministic output
            # Also use separators without spaces for consistency across platforms
            data = json.dumps(
                self.version_vectors[document_id], 
                sort_keys=True,
                ensure_ascii=True,
                separators=(',', ':')  # No spaces for consistency
            )
            return hashlib.sha256(data.encode('utf-8')).hexdigest()
        return ""
    
    def _verify_checksum(self, checksum1: str, checksum2: str) -> bool:
        """Verify if two checksums match."""
        return checksum1 == checksum2
    
    def _get_current_version(self, document_id: str) -> int:
        """Get current version for document."""
        if document_id in self.version_vectors:
            # Sum of all client versions
            return sum(self.version_vectors[document_id].values())
        return 0
    
    async def store_operation(
        self,
        document_id: str,
        operation: ModelOperation
    ):
        """Store an operation in the buffer."""
        if document_id not in self.operation_buffers:
            self.operation_buffers[document_id] = OperationBuffer()
        
        self.operation_buffers[document_id].add(operation)
    
    async def get_sync_status(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get synchronization status for a client."""
        if client_id not in self.sync_states:
            return None
        
        state = self.sync_states[client_id]
        
        status = {
            "client_id": client_id,
            "document_id": state.document_id,
            "is_online": state.is_online(),
            "last_sync_version": state.last_sync_version,
            "last_sync_timestamp": state.last_sync_timestamp.isoformat(),
            "pending_operations": len(state.pending_operations),
            "checksum": state.checksum
        }
        
        if state.offline_since:
            status["offline_since"] = state.offline_since.isoformat()
        
        if state.online_since:
            status["online_since"] = state.online_since.isoformat()
        
        offline_duration = state.get_offline_duration()
        if offline_duration:
            status["offline_duration_seconds"] = offline_duration.total_seconds()
        
        return status
    
    async def handle_partial_sync(
        self,
        client_id: str,
        operations: List[ModelOperation],
        from_version: int,
        to_version: int
    ) -> SyncResult:
        """
        Handle partial synchronization for specific version range.
        
        Args:
            client_id: Client identifier
            operations: Operations to sync
            from_version: Starting version
            to_version: Target version
            
        Returns:
            SyncResult
        """
        if client_id not in self.sync_states:
            return SyncResult(
                success=False,
                metadata={"error": "Client not registered"}
            )
        
        state = self.sync_states[client_id]
        
        # Get server operations in range
        server_ops = [
            op for op in await self._get_operations_since(state.document_id, from_version)
            if op.version <= to_version
        ]
        
        # Transform and apply
        result = await self._transform_and_apply(operations, server_ops, state)
        
        # Update version to target
        if result.success:
            state.last_sync_version = to_version
        
        return result
    
    async def compact_operation_buffer(self, document_id: str):
        """Compact operation buffer by merging compatible operations with conflict detection."""
        if document_id not in self.operation_buffers:
            return
        
        buffer = self.operation_buffers[document_id]
        operations = list(buffer.operations)
        
        if len(operations) < 2:
            return
        
        # Group operations by object
        object_ops: Dict[str, List[ModelOperation]] = {}
        
        for op in operations:
            if op.object_id:
                if op.object_id not in object_ops:
                    object_ops[op.object_id] = []
                object_ops[op.object_id].append(op)
        
        # Compact operations for each object
        compacted = []
        conflicts_detected = []
        
        for obj_id, ops in object_ops.items():
            if len(ops) == 1:
                compacted.append(ops[0])
            else:
                # Check for conflicts before merging
                has_conflict = False
                
                # Check if operations from different users modify the same object
                user_ids = set(op.user_id for op in ops if op.user_id)
                if len(user_ids) > 1:
                    # Multiple users modifying same object - potential conflict
                    logger.warning(f"Conflict detected: Multiple users ({user_ids}) modifying object {obj_id}")
                    has_conflict = True
                    conflicts_detected.append({
                        "object_id": obj_id,
                        "user_ids": list(user_ids),
                        "operations": [op.to_dict() for op in ops]
                    })
                
                # Check for conflicting operation types
                op_types = set(op.type for op in ops)
                if OperationType.DELETE in op_types and len(op_types) > 1:
                    # DELETE operation conflicts with other operations
                    logger.warning(f"Conflict detected: DELETE operation conflicts with other operations on object {obj_id}")
                    has_conflict = True
                    conflicts_detected.append({
                        "object_id": obj_id,
                        "conflict_type": "delete_conflict",
                        "operation_types": [t.value for t in op_types]
                    })
                
                if has_conflict:
                    # Don't merge conflicting operations, keep them separate
                    compacted.extend(ops)
                else:
                    # Try to merge operations
                    merged = self._merge_operations(ops)
                    compacted.extend(merged)
        
        # Update buffer with compacted operations
        buffer.clear()
        for op in compacted:
            buffer.add(op)
        
        # Log results
        if conflicts_detected:
            logger.warning(f"Compaction completed with {len(conflicts_detected)} conflicts detected")
            # Store conflicts for later resolution
            if document_id not in self.conflict_history:
                self.conflict_history[document_id] = []
            self.conflict_history[document_id].extend(conflicts_detected)
        else:
            logger.debug(f"Compacted operation buffer from {len(operations)} to {len(compacted)} operations")
    
    def _merge_operations(self, operations: List[ModelOperation]) -> List[ModelOperation]:
        """Merge compatible operations."""
        if not operations:
            return []
        
        # Sort by timestamp
        operations.sort(key=lambda op: op.timestamp)
        
        merged = []
        current = operations[0]
        
        for op in operations[1:]:
            # Try to merge with current
            if self._can_merge(current, op):
                current = self._merge_two_operations(current, op)
            else:
                merged.append(current)
                current = op
        
        merged.append(current)
        return merged
    
    def _can_merge(self, op1: ModelOperation, op2: ModelOperation) -> bool:
        """Check if two operations can be merged."""
        # Same object and compatible types
        if op1.object_id != op2.object_id:
            return False
        
        # Both are modifications
        if op1.type == OperationType.MODIFY and op2.type == OperationType.MODIFY:
            return True
        
        # Sequential moves
        if op1.type == OperationType.MOVE and op2.type == OperationType.MOVE:
            return True
        
        return False
    
    def _merge_two_operations(
        self,
        op1: ModelOperation,
        op2: ModelOperation
    ) -> ModelOperation:
        """Merge two operations into one."""
        # Create merged operation
        merged = ModelOperation(
            type=op2.type,  # Use later type
            object_id=op1.object_id,
            user_id=op2.user_id,  # Use later user
            timestamp=op2.timestamp,  # Use later timestamp
            version=op2.version,  # Use later version
            parameters={**op1.parameters, **op2.parameters},  # Merge parameters
            metadata={
                "merged_from": [op1.id, op2.id],
                "merge_type": "compaction"
            }
        )
        
        return merged
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get synchronization statistics."""
        total_clients = len(self.sync_states)
        online_clients = sum(1 for state in self.sync_states.values() if state.is_online())
        offline_clients = total_clients - online_clients
        
        total_buffered_ops = sum(
            buffer.size() for buffer in self.operation_buffers.values()
        )
        
        pending_ops = sum(
            len(state.pending_operations) for state in self.sync_states.values()
        )
        
        return {
            "total_clients": total_clients,
            "online_clients": online_clients,
            "offline_clients": offline_clients,
            "total_buffered_operations": total_buffered_ops,
            "total_pending_operations": pending_ops,
            "documents_tracked": len(self.operation_buffers),
            "version_vectors": {
                doc_id: sum(versions.values())
                for doc_id, versions in self.version_vectors.items()
            }
        }