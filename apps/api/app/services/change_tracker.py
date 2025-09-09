"""
Change Tracking and History Management for Collaborative FreeCAD Editing.
Implements undo/redo functionality with cascade handling.
"""

import logging
import json
from datetime import datetime, UTC
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from collections import deque
import uuid

from app.services.operational_transform import ModelOperation, OperationType

logger = logging.getLogger(__name__)


@dataclass
class ModelChange:
    """Represents a change to the FreeCAD model."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = None
    operation: ModelOperation = None
    before_state: Dict[str, Any] = field(default_factory=dict)
    after_state: Dict[str, Any] = field(default_factory=dict)
    affected_objects: List[str] = field(default_factory=list)
    dependent_changes: List[str] = field(default_factory=list)  # IDs of changes that depend on this
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "operation": self.operation.to_dict() if self.operation else None,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "affected_objects": self.affected_objects,
            "dependent_changes": self.dependent_changes,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelChange":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            user_id=data.get("user_id"),
            operation=ModelOperation.from_dict(data["operation"]) if data.get("operation") else None,
            before_state=data.get("before_state", {}),
            after_state=data.get("after_state", {}),
            affected_objects=data.get("affected_objects", []),
            dependent_changes=data.get("dependent_changes", []),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(UTC),
            metadata=data.get("metadata", {})
        )


@dataclass
class ChangeGroup:
    """Groups related changes for atomic undo/redo."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    changes: List[ModelChange] = field(default_factory=list)
    description: str = ""
    user_id: str = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def add_change(self, change: ModelChange):
        """Add a change to the group."""
        self.changes.append(change)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "changes": [c.to_dict() for c in self.changes],
            "description": self.description,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat()
        }


class ChangeTracker:
    """
    Tracks changes to FreeCAD models with undo/redo support.
    """
    
    def __init__(self, max_history_size: int = 1000):
        self.change_log: deque = deque(maxlen=max_history_size)
        self.undo_stack: deque = deque(maxlen=max_history_size)
        self.redo_stack: deque = deque(maxlen=max_history_size)
        self.change_index: Dict[str, ModelChange] = {}  # Quick lookup by ID
        self.object_changes: Dict[str, List[str]] = {}  # object_id -> change_ids
        self.user_changes: Dict[str, List[str]] = {}  # user_id -> change_ids
        self.dependency_graph: Dict[str, Set[str]] = {}  # change_id -> dependent_change_ids
        self.current_group: Optional[ChangeGroup] = None
        
    def start_change_group(self, description: str = "", user_id: Optional[str] = None):
        """Start grouping changes for atomic operations."""
        if self.current_group:
            self.end_change_group()
        
        self.current_group = ChangeGroup(
            description=description,
            user_id=user_id
        )
        
        logger.debug(f"Started change group: {description}")
    
    def end_change_group(self):
        """End the current change group and add to history."""
        if not self.current_group:
            return
        
        if self.current_group.changes:
            # Add all changes from group to history
            for change in self.current_group.changes:
                self._add_to_history(change)
            
            # Add group to undo stack
            self.undo_stack.append(self.current_group)
            
            logger.debug(f"Ended change group with {len(self.current_group.changes)} changes")
        
        self.current_group = None
    
    def record_change(
        self,
        change: ModelChange,
        track_dependencies: bool = True
    ) -> str:
        """
        Record a change with full context.
        
        Args:
            change: The change to record
            track_dependencies: Whether to track dependencies
            
        Returns:
            Change ID
        """
        # Add to current group if active
        if self.current_group:
            self.current_group.add_change(change)
        else:
            # Single change - wrap in group
            group = ChangeGroup(user_id=change.user_id)
            group.add_change(change)
            self.undo_stack.append(group)
        
        # Add to history
        self._add_to_history(change)
        
        # Clear redo stack (new changes invalidate redo)
        self.redo_stack.clear()
        
        # Track dependencies if needed
        if track_dependencies:
            self._track_dependencies(change)
        
        logger.debug(f"Recorded change {change.id} by user {change.user_id}")
        
        return change.id
    
    def _add_to_history(self, change: ModelChange):
        """Add change to internal tracking structures."""
        # Add to main log
        self.change_log.append(change)
        
        # Index by ID
        self.change_index[change.id] = change
        
        # Track by object
        for obj_id in change.affected_objects:
            if obj_id not in self.object_changes:
                self.object_changes[obj_id] = []
            self.object_changes[obj_id].append(change.id)
        
        # Track by user
        if change.user_id:
            if change.user_id not in self.user_changes:
                self.user_changes[change.user_id] = []
            self.user_changes[change.user_id].append(change.id)
    
    def _track_dependencies(self, change: ModelChange):
        """Track dependencies between changes."""
        # Find changes that this depends on
        for obj_id in change.affected_objects:
            # Get previous changes to same objects
            prev_changes = self.object_changes.get(obj_id, [])
            
            for prev_change_id in prev_changes:
                if prev_change_id != change.id:
                    # This change depends on previous changes
                    if prev_change_id not in self.dependency_graph:
                        self.dependency_graph[prev_change_id] = set()
                    self.dependency_graph[prev_change_id].add(change.id)
                    
                    # Update dependent_changes list
                    prev_change = self.change_index.get(prev_change_id)
                    if prev_change:
                        prev_change.dependent_changes.append(change.id)
    
    async def undo(self, user_id: Optional[str] = None) -> Optional[ChangeGroup]:
        """
        Undo the last change or change group.
        
        Args:
            user_id: If specified, undo last change by this user
            
        Returns:
            The undone change group, or None if nothing to undo
        """
        if not self.undo_stack:
            logger.debug("Nothing to undo")
            return None
        
        # Find change to undo
        if user_id:
            # Find last change by specific user
            group_to_undo = None
            for i in range(len(self.undo_stack) - 1, -1, -1):
                group = self.undo_stack[i]
                if group.user_id == user_id:
                    group_to_undo = group
                    self.undo_stack.remove(group)
                    break
            
            if not group_to_undo:
                logger.debug(f"No changes to undo for user {user_id}")
                return None
        else:
            # Undo last change
            group_to_undo = self.undo_stack.pop()
        
        # Check for dependent changes
        dependent_groups = await self._find_dependent_groups(group_to_undo)
        
        if dependent_groups:
            # Handle cascade undo
            await self._cascade_undo(group_to_undo, dependent_groups)
        else:
            # Simple undo
            await self._apply_inverse_operations(group_to_undo)
        
        # Add to redo stack
        self.redo_stack.append(group_to_undo)
        
        logger.info(f"Undid change group {group_to_undo.id}")
        
        return group_to_undo
    
    async def redo(self, user_id: Optional[str] = None) -> Optional[ChangeGroup]:
        """
        Redo the last undone change.
        
        Args:
            user_id: If specified, redo last undone change by this user
            
        Returns:
            The redone change group, or None if nothing to redo
        """
        if not self.redo_stack:
            logger.debug("Nothing to redo")
            return None
        
        # Find change to redo
        if user_id:
            group_to_redo = None
            for i in range(len(self.redo_stack) - 1, -1, -1):
                group = self.redo_stack[i]
                if group.user_id == user_id:
                    group_to_redo = group
                    self.redo_stack.remove(group)
                    break
            
            if not group_to_redo:
                logger.debug(f"No changes to redo for user {user_id}")
                return None
        else:
            group_to_redo = self.redo_stack.pop()
        
        # Reapply operations
        await self._reapply_operations(group_to_redo)
        
        # Add back to undo stack
        self.undo_stack.append(group_to_redo)
        
        logger.info(f"Redid change group {group_to_redo.id}")
        
        return group_to_redo
    
    async def undo_specific_change(self, change_id: str) -> bool:
        """
        Undo a specific change with cascade handling.
        
        Args:
            change_id: ID of change to undo
            
        Returns:
            True if successful, False otherwise
        """
        change = self.change_index.get(change_id)
        if not change:
            logger.error(f"Change {change_id} not found")
            return False
        
        # Find dependent changes
        dependents = self.find_dependent_changes(change_id)
        
        if dependents:
            # Need cascade undo
            logger.info(f"Undoing change {change_id} with {len(dependents)} dependent changes")
            
            # Create temporary group for cascade
            cascade_group = ChangeGroup(
                description=f"Cascade undo of {change_id}",
                user_id=change.user_id
            )
            cascade_group.add_change(change)
            
            for dep_id in dependents:
                dep_change = self.change_index.get(dep_id)
                if dep_change:
                    cascade_group.add_change(dep_change)
            
            await self._cascade_undo(cascade_group, [])
        else:
            # Simple undo
            temp_group = ChangeGroup()
            temp_group.add_change(change)
            await self._apply_inverse_operations(temp_group)
        
        return True
    
    def find_dependent_changes(self, change_id: str) -> List[str]:
        """Find all changes that depend on a given change."""
        dependents = set()
        
        # Direct dependents
        if change_id in self.dependency_graph:
            dependents.update(self.dependency_graph[change_id])
        
        # Transitive dependents
        to_check = list(dependents)
        while to_check:
            dep_id = to_check.pop()
            if dep_id in self.dependency_graph:
                new_deps = self.dependency_graph[dep_id] - dependents
                dependents.update(new_deps)
                to_check.extend(new_deps)
        
        return list(dependents)
    
    async def _find_dependent_groups(self, group: ChangeGroup) -> List[ChangeGroup]:
        """Find change groups that depend on the given group."""
        dependent_groups = []
        dependent_change_ids = set()
        
        # Find all dependent changes
        for change in group.changes:
            deps = self.find_dependent_changes(change.id)
            dependent_change_ids.update(deps)
        
        # Group dependent changes
        if dependent_change_ids:
            # Find which groups contain these changes
            for stack_group in self.undo_stack:
                group_change_ids = {c.id for c in stack_group.changes}
                if group_change_ids.intersection(dependent_change_ids):
                    dependent_groups.append(stack_group)
        
        return dependent_groups
    
    async def _cascade_undo(self, group: ChangeGroup, dependent_groups: List[ChangeGroup]):
        """Perform cascade undo of a group and its dependents."""
        logger.info(f"Performing cascade undo for group {group.id} with {len(dependent_groups)} dependent groups")
        
        # Undo dependents first (in reverse order)
        for dep_group in reversed(dependent_groups):
            await self._apply_inverse_operations(dep_group)
            # Remove from undo stack
            if dep_group in self.undo_stack:
                self.undo_stack.remove(dep_group)
            # Add to redo stack
            self.redo_stack.append(dep_group)
        
        # Then undo the original group
        await self._apply_inverse_operations(group)
    
    async def _apply_inverse_operations(self, group: ChangeGroup):
        """Apply inverse operations to undo changes."""
        # Apply in reverse order
        for change in reversed(group.changes):
            await self._apply_inverse_operation(change)
    
    async def _apply_inverse_operation(self, change: ModelChange):
        """Apply the inverse of a single operation."""
        if not change.operation:
            return
        
        op = change.operation
        
        # Import here to avoid circular imports
        from app.services.freecad_document_manager import document_manager
        import asyncio
        
        # Create inverse operation based on type
        if op.type == OperationType.CREATE:
            # Inverse of create is delete
            inverse_op = ModelOperation(
                type=OperationType.DELETE,
                object_id=op.parameters.get("new_object_id"),
                user_id=op.user_id,
                metadata={"inverse_of": op.id}
            )
        
        elif op.type == OperationType.DELETE:
            # Inverse of delete is create (restore)
            inverse_op = ModelOperation(
                type=OperationType.CREATE,
                parameters={
                    "new_object_id": op.object_id,
                    "object_data": change.before_state
                },
                user_id=op.user_id,
                metadata={"inverse_of": op.id}
            )
        
        elif op.type == OperationType.MODIFY:
            # Inverse of modify is restore previous state
            inverse_op = ModelOperation(
                type=OperationType.MODIFY,
                object_id=op.object_id,
                parameters=change.before_state,
                user_id=op.user_id,
                metadata={"inverse_of": op.id}
            )
        
        elif op.type == OperationType.MOVE:
            # Inverse of move is move back
            if "position" in change.before_state:
                inverse_op = ModelOperation(
                    type=OperationType.MOVE,
                    object_id=op.object_id,
                    parameters={"position": change.before_state["position"]},
                    user_id=op.user_id,
                    metadata={"inverse_of": op.id}
                )
            else:
                return
        
        else:
            # For other operations, try to restore before state
            inverse_op = ModelOperation(
                type=OperationType.MODIFY,
                object_id=op.object_id,
                parameters=change.before_state,
                user_id=op.user_id,
                metadata={"inverse_of": op.id}
            )
        
        # Apply inverse operation to FreeCAD document
        try:
            # Get document ID from metadata or change
            doc_id = change.metadata.get("document_id") or inverse_op.metadata.get("document_id")
            if not doc_id:
                logger.warning(f"No document ID found for inverse operation {inverse_op.id}")
                return
            
            # Apply the operation based on type
            if inverse_op.type == OperationType.CREATE:
                # Create object in document
                object_data = inverse_op.parameters.get("object_data", {})
                object_type = object_data.get("type", "Part::Feature")
                
                # Use asyncio.to_thread for blocking FreeCAD operations
                await asyncio.to_thread(
                    self._create_object_in_document,
                    doc_id,
                    inverse_op.parameters.get("new_object_id"),
                    object_type,
                    object_data
                )
                
            elif inverse_op.type == OperationType.DELETE:
                # Delete object from document
                await asyncio.to_thread(
                    self._delete_object_from_document,
                    doc_id,
                    inverse_op.object_id
                )
                
            elif inverse_op.type == OperationType.MODIFY:
                # Modify object properties
                await asyncio.to_thread(
                    self._modify_object_in_document,
                    doc_id,
                    inverse_op.object_id,
                    inverse_op.parameters
                )
                
            elif inverse_op.type == OperationType.MOVE:
                # Move object to new position
                position = inverse_op.parameters.get("position")
                if position:
                    await asyncio.to_thread(
                        self._move_object_in_document,
                        doc_id,
                        inverse_op.object_id,
                        position
                    )
            
            logger.debug(f"Applied inverse operation {inverse_op.id} successfully")
            
        except Exception as e:
            logger.error(f"Failed to apply inverse operation {inverse_op.id}: {e}")
            # Don't raise to allow partial undo/redo
    
    def _create_object_in_document(self, doc_id: str, object_id: str, object_type: str, object_data: Dict[str, Any]):
        """Create an object in the FreeCAD document (blocking operation)."""
        from app.services.freecad_document_manager import document_manager
        
        doc_handle = document_manager.get_document(doc_id)
        if not doc_handle:
            logger.warning(f"Document {doc_id} not found")
            return
        
        # Access the actual FreeCAD document
        doc = doc_handle.document
        if hasattr(doc, "addObject"):
            # Create FreeCAD object
            obj = doc.addObject(object_type, object_id)
            
            # Apply properties from object_data
            for prop_name, prop_value in object_data.items():
                if prop_name not in ["type", "id"] and hasattr(obj, prop_name):
                    try:
                        setattr(obj, prop_name, prop_value)
                    except Exception as e:
                        logger.warning(f"Could not set property {prop_name} on object {object_id}: {e}")
            
            # Recompute document
            doc.recompute()
    
    def _delete_object_from_document(self, doc_id: str, object_id: str):
        """Delete an object from the FreeCAD document (blocking operation)."""
        from app.services.freecad_document_manager import document_manager
        
        doc_handle = document_manager.get_document(doc_id)
        if not doc_handle:
            logger.warning(f"Document {doc_id} not found")
            return
        
        doc = doc_handle.document
        if hasattr(doc, "removeObject") and hasattr(doc, "getObject"):
            obj = doc.getObject(object_id)
            if obj:
                doc.removeObject(object_id)
                doc.recompute()
    
    def _modify_object_in_document(self, doc_id: str, object_id: str, parameters: Dict[str, Any]):
        """Modify object properties in the FreeCAD document (blocking operation)."""
        from app.services.freecad_document_manager import document_manager
        
        doc_handle = document_manager.get_document(doc_id)
        if not doc_handle:
            logger.warning(f"Document {doc_id} not found")
            return
        
        doc = doc_handle.document
        if hasattr(doc, "getObject"):
            obj = doc.getObject(object_id)
            if obj:
                # Apply parameter changes
                for prop_name, prop_value in parameters.items():
                    if hasattr(obj, prop_name):
                        try:
                            setattr(obj, prop_name, prop_value)
                        except Exception as e:
                            logger.warning(f"Could not modify property {prop_name} on object {object_id}: {e}")
                
                doc.recompute()
    
    def _move_object_in_document(self, doc_id: str, object_id: str, position: Dict[str, Any]):
        """Move an object in the FreeCAD document (blocking operation)."""
        from app.services.freecad_document_manager import document_manager
        
        doc_handle = document_manager.get_document(doc_id)
        if not doc_handle:
            logger.warning(f"Document {doc_id} not found")
            return
        
        doc = doc_handle.document
        if hasattr(doc, "getObject"):
            obj = doc.getObject(object_id)
            if obj and hasattr(obj, "Placement"):
                # Update placement with new position
                import FreeCAD
                placement = obj.Placement
                if "x" in position and "y" in position and "z" in position:
                    placement.Base = FreeCAD.Vector(
                        position["x"],
                        position["y"],
                        position["z"]
                    )
                    obj.Placement = placement
                    doc.recompute()
    
    async def _reapply_operations(self, group: ChangeGroup):
        """Reapply operations for redo."""
        import asyncio
        from app.services.freecad_document_manager import document_manager
        
        for change in group.changes:
            if change.operation:
                op = change.operation
                
                try:
                    # Get document ID from metadata
                    doc_id = change.metadata.get("document_id") or op.metadata.get("document_id")
                    if not doc_id:
                        logger.warning(f"No document ID found for operation {op.id}")
                        continue
                    
                    # Apply the operation based on type
                    if op.type == OperationType.CREATE:
                        # Create object in document
                        object_data = op.parameters.get("object_data", {})
                        object_type = object_data.get("type", "Part::Feature")
                        
                        await asyncio.to_thread(
                            self._create_object_in_document,
                            doc_id,
                            op.parameters.get("new_object_id"),
                            object_type,
                            object_data
                        )
                        
                    elif op.type == OperationType.DELETE:
                        # Delete object from document
                        await asyncio.to_thread(
                            self._delete_object_from_document,
                            doc_id,
                            op.object_id
                        )
                        
                    elif op.type == OperationType.MODIFY:
                        # Modify object properties
                        await asyncio.to_thread(
                            self._modify_object_in_document,
                            doc_id,
                            op.object_id,
                            op.parameters
                        )
                        
                    elif op.type == OperationType.MOVE:
                        # Move object to new position
                        position = op.parameters.get("position")
                        if position:
                            await asyncio.to_thread(
                                self._move_object_in_document,
                                doc_id,
                                op.object_id,
                                position
                            )
                    
                    # Store the after state for future reference
                    if op.object_id:
                        doc_handle = document_manager.get_document(doc_id)
                        if doc_handle and hasattr(doc_handle.document, "getObject"):
                            obj = doc_handle.document.getObject(op.object_id)
                            if obj:
                                change.after_state = await asyncio.to_thread(
                                    self._capture_object_state, obj
                                )
                    
                    logger.debug(f"Reapplied operation {op.id} successfully")
                    
                except Exception as e:
                    logger.error(f"Failed to reapply operation {op.id}: {e}")
                    # Don't raise to allow partial redo
    
    def _capture_object_state(self, obj) -> Dict[str, Any]:
        """Capture the current state of a FreeCAD object."""
        state = {}
        
        # Capture basic properties
        if hasattr(obj, "Name"):
            state["name"] = obj.Name
        if hasattr(obj, "Label"):
            state["label"] = obj.Label
        if hasattr(obj, "Placement"):
            placement = obj.Placement
            state["placement"] = {
                "base": {
                    "x": placement.Base.x,
                    "y": placement.Base.y,
                    "z": placement.Base.z
                },
                "rotation": {
                    "angle": placement.Rotation.Angle,
                    "axis": {
                        "x": placement.Rotation.Axis.x,
                        "y": placement.Rotation.Axis.y,
                        "z": placement.Rotation.Axis.z
                    }
                }
            }
        
        # Capture type-specific properties
        if hasattr(obj, "Shape"):
            shape = obj.Shape
            if shape:
                state["shape_type"] = shape.ShapeType
                state["volume"] = shape.Volume if hasattr(shape, "Volume") else 0
                state["area"] = shape.Area if hasattr(shape, "Area") else 0
        
        # Capture custom properties
        if hasattr(obj, "PropertiesList"):
            custom_props = {}
            for prop_name in obj.PropertiesList:
                if not prop_name.startswith("_"):  # Skip internal properties
                    try:
                        prop_value = getattr(obj, prop_name)
                        # Only capture serializable properties
                        if isinstance(prop_value, (str, int, float, bool, list, dict)):
                            custom_props[prop_name] = prop_value
                    except Exception:
                        pass  # Skip properties that can't be accessed
            
            if custom_props:
                state["properties"] = custom_props
        
        return state
    
    def get_change_history(
        self,
        limit: int = 100,
        user_id: Optional[str] = None,
        object_id: Optional[str] = None
    ) -> List[ModelChange]:
        """
        Get change history with optional filters.
        
        Args:
            limit: Maximum number of changes to return
            user_id: Filter by user
            object_id: Filter by affected object
            
        Returns:
            List of changes
        """
        changes = list(self.change_log)
        
        # Apply filters
        if user_id:
            changes = [c for c in changes if c.user_id == user_id]
        
        if object_id:
            changes = [c for c in changes if object_id in c.affected_objects]
        
        # Return most recent changes
        return changes[-limit:]
    
    def get_object_history(self, object_id: str) -> List[ModelChange]:
        """Get all changes affecting a specific object."""
        change_ids = self.object_changes.get(object_id, [])
        return [self.change_index[cid] for cid in change_ids if cid in self.change_index]
    
    def get_user_history(self, user_id: str) -> List[ModelChange]:
        """Get all changes by a specific user."""
        change_ids = self.user_changes.get(user_id, [])
        return [self.change_index[cid] for cid in change_ids if cid in self.change_index]
    
    def can_undo(self, user_id: Optional[str] = None) -> bool:
        """Check if undo is possible."""
        if not self.undo_stack:
            return False
        
        if user_id:
            # Check if user has any changes to undo
            return any(g.user_id == user_id for g in self.undo_stack)
        
        return True
    
    def can_redo(self, user_id: Optional[str] = None) -> bool:
        """Check if redo is possible."""
        if not self.redo_stack:
            return False
        
        if user_id:
            # Check if user has any changes to redo
            return any(g.user_id == user_id for g in self.redo_stack)
        
        return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about change tracking."""
        total_changes = len(self.change_index)
        
        if total_changes == 0:
            return {
                "total_changes": 0,
                "undo_stack_size": 0,
                "redo_stack_size": 0
            }
        
        # Calculate statistics
        user_counts = {}
        object_counts = {}
        operation_counts = {}
        
        for change in self.change_index.values():
            # Count by user
            if change.user_id:
                user_counts[change.user_id] = user_counts.get(change.user_id, 0) + 1
            
            # Count by object
            for obj_id in change.affected_objects:
                object_counts[obj_id] = object_counts.get(obj_id, 0) + 1
            
            # Count by operation type
            if change.operation:
                op_type = change.operation.type.value
                operation_counts[op_type] = operation_counts.get(op_type, 0) + 1
        
        return {
            "total_changes": total_changes,
            "undo_stack_size": len(self.undo_stack),
            "redo_stack_size": len(self.redo_stack),
            "changes_by_user": user_counts,
            "most_modified_objects": sorted(
                object_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10],
            "operation_distribution": operation_counts,
            "dependency_graph_size": len(self.dependency_graph)
        }
    
    def export_history(self) -> List[Dict[str, Any]]:
        """Export complete change history as JSON-serializable data."""
        return [change.to_dict() for change in self.change_log]
    
    def import_history(self, history_data: List[Dict[str, Any]]):
        """Import change history from exported data."""
        self.clear()
        
        for change_data in history_data:
            change = ModelChange.from_dict(change_data)
            self._add_to_history(change)
            self._track_dependencies(change)
    
    def clear(self):
        """Clear all change history."""
        self.change_log.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.change_index.clear()
        self.object_changes.clear()
        self.user_changes.clear()
        self.dependency_graph.clear()
        self.current_group = None
        
        logger.info("Cleared all change history")