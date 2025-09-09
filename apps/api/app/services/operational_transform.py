"""
Operational Transformation Engine for Real-time Collaborative FreeCAD Model Editing.
Implements conflict-free concurrent operation transformation algorithms.
"""

import numpy as np
from datetime import datetime, UTC
from typing import List, Tuple, Optional, Dict, Any, Union
from enum import Enum
from dataclasses import dataclass, field
import uuid
import json
from decimal import Decimal

from pydantic import BaseModel, Field


class OperationType(str, Enum):
    """Types of operations that can be performed on FreeCAD models."""
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    MOVE = "move"
    ROTATE = "rotate"
    SCALE = "scale"
    PROPERTY_CHANGE = "property_change"
    CONSTRAINT_ADD = "constraint_add"
    CONSTRAINT_REMOVE = "constraint_remove"
    NO_OP = "no_op"


class ConflictResolutionStrategy(str, Enum):
    """Strategies for resolving conflicts between operations."""
    TIMESTAMP = "timestamp"  # Last write wins
    PRIORITY = "priority"  # User priority based
    MERGE = "merge"  # Automatic merge attempt
    MANUAL = "manual"  # Requires user intervention


@dataclass
class Point3D:
    """3D point representation."""
    x: float
    y: float
    z: float
    
    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "Point3D":
        return cls(x=data["x"], y=data["y"], z=data["z"])


@dataclass
class Transform3D:
    """3D transformation matrix."""
    position: Point3D
    rotation: Point3D  # Euler angles in degrees
    scale: Point3D
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "position": self.position.to_dict(),
            "rotation": self.rotation.to_dict(),
            "scale": self.scale.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transform3D":
        return cls(
            position=Point3D.from_dict(data["position"]),
            rotation=Point3D.from_dict(data["rotation"]),
            scale=Point3D.from_dict(data["scale"])
        )


@dataclass
class ModelOperation:
    """Represents an operation on a FreeCAD model."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: OperationType = OperationType.NO_OP
    object_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 0
    parameters: Dict[str, Any] = field(default_factory=dict)
    parent_operation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert operation to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "object_id": self.object_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            "parameters": self.parameters,
            "parent_operation_id": self.parent_operation_id,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelOperation":
        """Create operation from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            type=OperationType(data.get("type", "no_op")),
            object_id=data.get("object_id"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(UTC),
            version=data.get("version", 0),
            parameters=data.get("parameters", {}),
            parent_operation_id=data.get("parent_operation_id"),
            metadata=data.get("metadata", {})
        )
    
    def is_no_op(self) -> bool:
        """Check if this is a no-operation."""
        return self.type == OperationType.NO_OP
    
    def conflicts_with(self, other: "ModelOperation") -> bool:
        """Check if this operation conflicts with another."""
        if self.is_no_op() or other.is_no_op():
            return False
        
        # Same object operations always conflict
        if self.object_id and other.object_id and self.object_id == other.object_id:
            return True
        
        # Check for constraint conflicts
        if self.type in [OperationType.CONSTRAINT_ADD, OperationType.CONSTRAINT_REMOVE]:
            if other.type in [OperationType.CONSTRAINT_ADD, OperationType.CONSTRAINT_REMOVE]:
                # Check if constraints reference same objects
                self_refs = set(self.parameters.get("referenced_objects", []))
                other_refs = set(other.parameters.get("referenced_objects", []))
                if self_refs.intersection(other_refs):
                    return True
        
        return False


class NoOperation(ModelOperation):
    """Represents a no-operation (used when operations cancel out)."""
    def __init__(self):
        super().__init__(type=OperationType.NO_OP)


@dataclass
class TransformResult:
    """Result of transforming two operations."""
    op1_prime: ModelOperation
    op2_prime: ModelOperation
    conflict_resolved: bool = True
    resolution_metadata: Dict[str, Any] = field(default_factory=dict)


class OperationalTransform:
    """
    Transform concurrent operations for conflict-free collaboration.
    Implements the operational transformation algorithm for FreeCAD models.
    """
    
    def __init__(self):
        self.transform_functions = {
            (OperationType.MODIFY, OperationType.MODIFY): self._transform_modify_modify,
            (OperationType.MODIFY, OperationType.DELETE): self._transform_modify_delete,
            (OperationType.DELETE, OperationType.MODIFY): self._transform_delete_modify,
            (OperationType.DELETE, OperationType.DELETE): self._transform_delete_delete,
            (OperationType.CREATE, OperationType.CREATE): self._transform_create_create,
            (OperationType.MOVE, OperationType.MOVE): self._transform_move_move,
            (OperationType.ROTATE, OperationType.ROTATE): self._transform_rotate_rotate,
            (OperationType.SCALE, OperationType.SCALE): self._transform_scale_scale,
            (OperationType.PROPERTY_CHANGE, OperationType.PROPERTY_CHANGE): self._transform_property_property,
            (OperationType.CONSTRAINT_ADD, OperationType.CONSTRAINT_ADD): self._transform_constraint_constraint,
        }
    
    def transform_operation(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.MERGE
    ) -> TransformResult:
        """
        Transform two concurrent operations to maintain consistency.
        
        Args:
            op1: First operation
            op2: Second operation
            strategy: Conflict resolution strategy
            
        Returns:
            TransformResult with transformed operations
        """
        # No-ops pass through unchanged
        if op1.is_no_op():
            return TransformResult(op1, op2)
        if op2.is_no_op():
            return TransformResult(op1, op2)
        
        # Get specific transform function
        transform_key = (op1.type, op2.type)
        if transform_key in self.transform_functions:
            return self.transform_functions[transform_key](op1, op2, strategy)
        
        # Default: operations don't conflict
        return TransformResult(op1, op2)
    
    def _transform_modify_modify(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two modify operations on the same object."""
        if op1.object_id != op2.object_id:
            return TransformResult(op1, op2)
        
        if strategy == ConflictResolutionStrategy.TIMESTAMP:
            # Last write wins
            if op1.timestamp > op2.timestamp:
                return TransformResult(op1, NoOperation())
            else:
                return TransformResult(NoOperation(), op2)
        
        elif strategy == ConflictResolutionStrategy.MERGE:
            # Attempt to merge non-conflicting property changes
            merged_params = self._merge_parameters(op1.parameters, op2.parameters)
            if merged_params is not None:
                # Create merged operation
                merged_op = ModelOperation(
                    type=OperationType.MODIFY,
                    object_id=op1.object_id,
                    parameters=merged_params,
                    metadata={"merged_from": [op1.id, op2.id]}
                )
                return TransformResult(merged_op, NoOperation())
            else:
                # Merge failed, fall back to timestamp
                return self._transform_modify_modify(op1, op2, ConflictResolutionStrategy.TIMESTAMP)
        
        elif strategy == ConflictResolutionStrategy.PRIORITY:
            # Use user priority
            priority1 = op1.metadata.get("user_priority", 0)
            priority2 = op2.metadata.get("user_priority", 0)
            if priority1 >= priority2:
                return TransformResult(op1, NoOperation())
            else:
                return TransformResult(NoOperation(), op2)
        
        # Manual resolution required
        return TransformResult(
            op1, op2,
            conflict_resolved=False,
            resolution_metadata={"requires_manual": True}
        )
    
    def _transform_modify_delete(
        self,
        modify_op: ModelOperation,
        delete_op: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform modify vs delete operations."""
        if modify_op.object_id != delete_op.object_id:
            return TransformResult(modify_op, delete_op)
        
        # Delete typically wins (can't modify deleted object)
        return TransformResult(NoOperation(), delete_op)
    
    def _transform_delete_modify(
        self,
        delete_op: ModelOperation,
        modify_op: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform delete vs modify operations."""
        if delete_op.object_id != modify_op.object_id:
            return TransformResult(delete_op, modify_op)
        
        # Delete wins
        return TransformResult(delete_op, NoOperation())
    
    def _transform_delete_delete(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two delete operations on the same object."""
        if op1.object_id != op2.object_id:
            return TransformResult(op1, op2)
        
        # Both trying to delete same object - only one succeeds
        if op1.timestamp < op2.timestamp:
            return TransformResult(op1, NoOperation())
        else:
            return TransformResult(NoOperation(), op2)
    
    def _transform_create_create(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two create operations."""
        # Check for ID collision
        created_id1 = op1.parameters.get("new_object_id")
        created_id2 = op2.parameters.get("new_object_id")
        
        if created_id1 == created_id2:
            # ID collision - assign new ID to later operation
            if op1.timestamp < op2.timestamp:
                op2.parameters["new_object_id"] = f"{created_id2}_v2"
            else:
                op1.parameters["new_object_id"] = f"{created_id1}_v2"
        
        return TransformResult(op1, op2)
    
    def _transform_move_move(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two move operations on the same object."""
        if op1.object_id != op2.object_id:
            return TransformResult(op1, op2)
        
        if strategy == ConflictResolutionStrategy.MERGE:
            # Combine movements (vector addition)
            pos1 = Point3D.from_dict(op1.parameters.get("position", {"x": 0, "y": 0, "z": 0}))
            pos2 = Point3D.from_dict(op2.parameters.get("position", {"x": 0, "y": 0, "z": 0}))
            
            combined_pos = Point3D(
                x=pos1.x + pos2.x,
                y=pos1.y + pos2.y,
                z=pos1.z + pos2.z
            )
            
            combined_op = ModelOperation(
                type=OperationType.MOVE,
                object_id=op1.object_id,
                parameters={"position": combined_pos.to_dict()},
                metadata={"combined_from": [op1.id, op2.id]}
            )
            
            return TransformResult(combined_op, NoOperation())
        
        # Use timestamp strategy
        return self._transform_modify_modify(op1, op2, ConflictResolutionStrategy.TIMESTAMP)
    
    def _transform_rotate_rotate(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two rotate operations on the same object."""
        if op1.object_id != op2.object_id:
            return TransformResult(op1, op2)
        
        if strategy == ConflictResolutionStrategy.MERGE:
            # Combine rotations using quaternion multiplication
            rot1 = Point3D.from_dict(op1.parameters.get("rotation", {"x": 0, "y": 0, "z": 0}))
            rot2 = Point3D.from_dict(op2.parameters.get("rotation", {"x": 0, "y": 0, "z": 0}))
            
            # Convert Euler angles to quaternions and compose
            q1 = self._euler_to_quaternion(rot1.x, rot1.y, rot1.z)
            q2 = self._euler_to_quaternion(rot2.x, rot2.y, rot2.z)
            
            # Quaternion multiplication (q2 * q1 for applying q1 then q2)
            q_combined = self._quaternion_multiply(q2, q1)
            
            # Convert back to Euler angles
            combined_euler = self._quaternion_to_euler(q_combined)
            
            combined_rot = Point3D(
                x=combined_euler[0],
                y=combined_euler[1],
                z=combined_euler[2]
            )
            
            combined_op = ModelOperation(
                type=OperationType.ROTATE,
                object_id=op1.object_id,
                parameters={"rotation": combined_rot.to_dict()},
                metadata={"combined_from": [op1.id, op2.id], "method": "quaternion"}
            )
            
            return TransformResult(combined_op, NoOperation())
        
        return self._transform_modify_modify(op1, op2, ConflictResolutionStrategy.TIMESTAMP)
    
    def _transform_scale_scale(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two scale operations on the same object."""
        if op1.object_id != op2.object_id:
            return TransformResult(op1, op2)
        
        if strategy == ConflictResolutionStrategy.MERGE:
            # Multiply scales
            scale1 = Point3D.from_dict(op1.parameters.get("scale", {"x": 1, "y": 1, "z": 1}))
            scale2 = Point3D.from_dict(op2.parameters.get("scale", {"x": 1, "y": 1, "z": 1}))
            
            combined_scale = Point3D(
                x=scale1.x * scale2.x,
                y=scale1.y * scale2.y,
                z=scale1.z * scale2.z
            )
            
            combined_op = ModelOperation(
                type=OperationType.SCALE,
                object_id=op1.object_id,
                parameters={"scale": combined_scale.to_dict()},
                metadata={"combined_from": [op1.id, op2.id]}
            )
            
            return TransformResult(combined_op, NoOperation())
        
        return self._transform_modify_modify(op1, op2, ConflictResolutionStrategy.TIMESTAMP)
    
    def _transform_property_property(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two property change operations."""
        if op1.object_id != op2.object_id:
            return TransformResult(op1, op2)
        
        prop1 = op1.parameters.get("property_name")
        prop2 = op2.parameters.get("property_name")
        
        if prop1 != prop2:
            # Different properties - both can apply
            return TransformResult(op1, op2)
        
        # Same property - use resolution strategy
        return self._transform_modify_modify(op1, op2, strategy)
    
    def _transform_constraint_constraint(
        self,
        op1: ModelOperation,
        op2: ModelOperation,
        strategy: ConflictResolutionStrategy
    ) -> TransformResult:
        """Transform two constraint operations."""
        # Check if constraints conflict
        refs1 = set(op1.parameters.get("referenced_objects", []))
        refs2 = set(op2.parameters.get("referenced_objects", []))
        
        if not refs1.intersection(refs2):
            # No shared references - both can apply
            return TransformResult(op1, op2)
        
        # Constraints conflict - use strategy
        if strategy == ConflictResolutionStrategy.TIMESTAMP:
            if op1.timestamp > op2.timestamp:
                return TransformResult(op1, NoOperation())
            else:
                return TransformResult(NoOperation(), op2)
        
        # Manual resolution for complex constraint conflicts
        return TransformResult(
            op1, op2,
            conflict_resolved=False,
            resolution_metadata={"requires_manual": True, "reason": "constraint_conflict"}
        )
    
    def _merge_parameters(self, params1: Dict[str, Any], params2: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Attempt to merge two parameter sets with type checking.
        
        Returns merged parameters if successful, None if conflict detected.
        """
        merged = {}
        all_keys = set(params1.keys()) | set(params2.keys())
        
        for key in all_keys:
            if key in params1 and key in params2:
                # Both have this parameter
                val1, val2 = params1[key], params2[key]
                
                # Check if types match
                if type(val1) != type(val2):
                    # Different types - conflict
                    return None
                
                # If values are the same, no conflict
                if val1 == val2:
                    merged[key] = val1
                # Try to merge if both are dicts
                elif isinstance(val1, dict) and isinstance(val2, dict):
                    sub_merged = self._merge_parameters(val1, val2)
                    if sub_merged is None:
                        return None  # Conflict in nested parameters
                    merged[key] = sub_merged
                # Handle lists - merge if they contain the same elements
                elif isinstance(val1, list) and isinstance(val2, list):
                    # For lists, we'll use union if they contain simple types
                    if all(isinstance(x, (str, int, float, bool)) for x in val1 + val2):
                        # Union of simple values
                        merged[key] = list(set(val1) | set(val2))
                    else:
                        # Complex list conflict
                        return None
                # Handle numeric types specially for precision
                elif isinstance(val1, (int, float, Decimal)) and isinstance(val2, (int, float, Decimal)):
                    # For numeric conflicts, return None (let conflict resolver handle)
                    return None
                else:
                    # Conflict - can't merge different values of same type
                    return None
            elif key in params1:
                merged[key] = params1[key]
            else:
                merged[key] = params2[key]
        
        return merged
    
    def apply_operation_sequence(
        self,
        operations: List[ModelOperation],
        initial_state: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], List[ModelOperation]]:
        """
        Apply a sequence of operations with transformation.
        
        Args:
            operations: List of operations to apply
            initial_state: Initial model state (optional)
            
        Returns:
            Tuple of (final_state, transformed_operations)
        """
        if initial_state is None:
            state = {}
        else:
            state = initial_state.copy()
        
        # Sort operations by timestamp
        sorted_ops = sorted(operations, key=lambda op: op.timestamp)
        
        transformed = []
        for new_op in sorted_ops:
            # Transform against all previously applied operations
            current_op = new_op
            for existing_op in transformed:
                result = self.transform_operation(current_op, existing_op)
                current_op = result.op1_prime
            
            if not current_op.is_no_op():
                transformed.append(current_op)
                # Apply operation to state (simplified - actual implementation would modify FreeCAD document)
                state = self._apply_to_state(state, current_op)
        
        return state, transformed
    
    def _apply_to_state(self, state: Dict[str, Any], operation: ModelOperation) -> Dict[str, Any]:
        """
        Apply an operation to the model state.
        
        This method updates the in-memory state representation that tracks
        the FreeCAD document objects and their properties.
        """
        import copy
        
        # Deep copy the state to avoid mutations
        new_state = copy.deepcopy(state)
        
        if operation.type == OperationType.CREATE:
            # Create new object in state
            obj_id = operation.parameters.get("new_object_id")
            if obj_id:
                object_data = operation.parameters.get("object_data", {})
                new_state[obj_id] = {
                    "id": obj_id,
                    "type": operation.parameters.get("type", "Part::Feature"),
                    "created_at": operation.timestamp.isoformat() if operation.timestamp else None,
                    "created_by": operation.user_id,
                    "properties": object_data,
                    "placement": object_data.get("placement", {
                        "position": {"x": 0, "y": 0, "z": 0},
                        "rotation": {"angle": 0, "axis": {"x": 0, "y": 0, "z": 1}}
                    })
                }
        
        elif operation.type == OperationType.DELETE:
            # Remove object from state
            if operation.object_id and operation.object_id in new_state:
                del new_state[operation.object_id]
        
        elif operation.type == OperationType.MODIFY:
            # Update object properties
            if operation.object_id and operation.object_id in new_state:
                obj = new_state[operation.object_id]
                # Update properties while preserving structure
                if "properties" not in obj:
                    obj["properties"] = {}
                obj["properties"].update(operation.parameters)
                obj["modified_at"] = operation.timestamp.isoformat() if operation.timestamp else None
                obj["modified_by"] = operation.user_id
        
        elif operation.type == OperationType.MOVE:
            # Update object position
            if operation.object_id and operation.object_id in new_state:
                obj = new_state[operation.object_id]
                if "placement" not in obj:
                    obj["placement"] = {
                        "position": {"x": 0, "y": 0, "z": 0},
                        "rotation": {"angle": 0, "axis": {"x": 0, "y": 0, "z": 1}}
                    }
                
                position = operation.parameters.get("position", {})
                if position:
                    obj["placement"]["position"].update(position)
                
                rotation = operation.parameters.get("rotation")
                if rotation:
                    obj["placement"]["rotation"] = rotation
                
                obj["moved_at"] = operation.timestamp.isoformat() if operation.timestamp else None
                obj["moved_by"] = operation.user_id
        
        elif operation.type == OperationType.ROTATE:
            # Update object rotation
            if operation.object_id and operation.object_id in new_state:
                obj = new_state[operation.object_id]
                if "placement" not in obj:
                    obj["placement"] = {
                        "position": {"x": 0, "y": 0, "z": 0},
                        "rotation": {"angle": 0, "axis": {"x": 0, "y": 0, "z": 1}}
                    }
                
                rotation = operation.parameters.get("rotation", {})
                if rotation:
                    # Apply rotation (could be absolute or relative)
                    if operation.parameters.get("relative", False):
                        # Relative rotation - combine with existing
                        current_rot = obj["placement"]["rotation"]
                        # Convert to quaternions, multiply, convert back
                        import numpy as np
                        
                        # Current rotation quaternion
                        curr_angle = current_rot.get("angle", 0)
                        curr_axis = current_rot.get("axis", {"x": 0, "y": 0, "z": 1})
                        curr_quat = self._axis_angle_to_quaternion(
                            curr_axis["x"], curr_axis["y"], curr_axis["z"], curr_angle
                        )
                        
                        # New rotation quaternion
                        new_angle = rotation.get("angle", 0)
                        new_axis = rotation.get("axis", {"x": 0, "y": 0, "z": 1})
                        new_quat = self._axis_angle_to_quaternion(
                            new_axis["x"], new_axis["y"], new_axis["z"], new_angle
                        )
                        
                        # Combine rotations
                        result_quat = self._quaternion_multiply(curr_quat, new_quat)
                        
                        # Convert back to axis-angle
                        axis, angle = self._quaternion_to_axis_angle(result_quat)
                        obj["placement"]["rotation"] = {
                            "angle": angle,
                            "axis": {"x": axis[0], "y": axis[1], "z": axis[2]}
                        }
                    else:
                        # Absolute rotation
                        obj["placement"]["rotation"] = rotation
                
                obj["rotated_at"] = operation.timestamp.isoformat() if operation.timestamp else None
                obj["rotated_by"] = operation.user_id
        
        elif operation.type == OperationType.SCALE:
            # Update object scale
            if operation.object_id and operation.object_id in new_state:
                obj = new_state[operation.object_id]
                scale = operation.parameters.get("scale", 1.0)
                
                if isinstance(scale, (int, float)):
                    obj["scale"] = {"x": scale, "y": scale, "z": scale}
                else:
                    obj["scale"] = scale
                
                obj["scaled_at"] = operation.timestamp.isoformat() if operation.timestamp else None
                obj["scaled_by"] = operation.user_id
        
        elif operation.type == OperationType.GROUP:
            # Group objects
            group_id = operation.parameters.get("group_id")
            object_ids = operation.parameters.get("object_ids", [])
            
            if group_id:
                new_state[group_id] = {
                    "id": group_id,
                    "type": "App::DocumentObjectGroup",
                    "created_at": operation.timestamp.isoformat() if operation.timestamp else None,
                    "created_by": operation.user_id,
                    "members": object_ids,
                    "properties": operation.parameters.get("properties", {})
                }
                
                # Update grouped objects
                for obj_id in object_ids:
                    if obj_id in new_state:
                        new_state[obj_id]["parent_group"] = group_id
        
        elif operation.type == OperationType.UNGROUP:
            # Ungroup objects
            group_id = operation.object_id
            if group_id and group_id in new_state:
                group = new_state[group_id]
                members = group.get("members", [])
                
                # Remove parent reference from members
                for obj_id in members:
                    if obj_id in new_state:
                        new_state[obj_id].pop("parent_group", None)
                
                # Remove the group
                del new_state[group_id]
        
        return new_state
    
    def _axis_angle_to_quaternion(self, x: float, y: float, z: float, angle: float) -> np.ndarray:
        """Convert axis-angle representation to quaternion."""
        import numpy as np
        
        # Normalize axis
        axis = np.array([x, y, z])
        axis_norm = np.linalg.norm(axis)
        if axis_norm > 0:
            axis = axis / axis_norm
        else:
            axis = np.array([0, 0, 1])
        
        # Convert angle to radians if needed
        angle_rad = np.radians(angle) if angle > 2 * np.pi else angle
        
        # Calculate quaternion
        half_angle = angle_rad * 0.5
        s = np.sin(half_angle)
        w = np.cos(half_angle)
        x = axis[0] * s
        y = axis[1] * s
        z = axis[2] * s
        
        return np.array([w, x, y, z])
    
    def _quaternion_to_axis_angle(self, q: np.ndarray) -> Tuple[np.ndarray, float]:
        """Convert quaternion to axis-angle representation."""
        import numpy as np
        
        w, x, y, z = q
        
        # Calculate angle
        angle = 2 * np.arccos(np.clip(w, -1.0, 1.0))
        
        # Calculate axis
        s = np.sin(angle * 0.5)
        if s < 0.001:  # Close to zero, arbitrary axis
            axis = np.array([0, 0, 1])
        else:
            axis = np.array([x, y, z]) / s
        
        # Convert angle to degrees
        angle_deg = np.degrees(angle)
        
        return axis, angle_deg
    
    def compute_operation_checksum(self, operation: ModelOperation) -> str:
        """
        Compute a checksum for an operation for verification.
        
        Args:
            operation: Operation to compute checksum for
            
        Returns:
            Checksum string
        """
        import hashlib
        
        # Create deterministic string representation
        op_string = json.dumps({
            "type": operation.type.value,
            "object_id": operation.object_id,
            "parameters": operation.parameters,
            "version": operation.version
        }, sort_keys=True)
        
        return hashlib.sha256(op_string.encode()).hexdigest()
    
    def _euler_to_quaternion(self, roll: float, pitch: float, yaw: float) -> np.ndarray:
        """
        Convert Euler angles (in degrees) to quaternion.
        Roll (x), pitch (y), yaw (z) in degrees.
        Returns quaternion as [w, x, y, z].
        """
        # Convert degrees to radians
        roll = np.radians(roll)
        pitch = np.radians(pitch)
        yaw = np.radians(yaw)
        
        # Calculate quaternion components
        cy = np.cos(yaw * 0.5)
        sy = np.sin(yaw * 0.5)
        cp = np.cos(pitch * 0.5)
        sp = np.sin(pitch * 0.5)
        cr = np.cos(roll * 0.5)
        sr = np.sin(roll * 0.5)
        
        w = cr * cp * cy + sr * sp * sy
        x = sr * cp * cy - cr * sp * sy
        y = cr * sp * cy + sr * cp * sy
        z = cr * cp * sy - sr * sp * cy
        
        return np.array([w, x, y, z])
    
    def _quaternion_multiply(self, q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
        """
        Multiply two quaternions.
        q1 and q2 are [w, x, y, z] arrays.
        Returns the product quaternion.
        """
        w1, x1, y1, z1 = q1
        w2, x2, y2, z2 = q2
        
        w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
        x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
        y = w1 * y2 + y1 * w2 + z1 * x2 - x1 * z2
        z = w1 * z2 + z1 * w2 + x1 * y2 - y1 * x2
        
        return np.array([w, x, y, z])
    
    def _quaternion_to_euler(self, q: np.ndarray) -> Tuple[float, float, float]:
        """
        Convert quaternion to Euler angles (in degrees).
        q is [w, x, y, z] array.
        Returns (roll, pitch, yaw) in degrees.
        """
        w, x, y, z = q
        
        # Roll (x-axis rotation)
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = np.arctan2(sinr_cosp, cosr_cosp)
        
        # Pitch (y-axis rotation)
        sinp = 2 * (w * y - z * x)
        if np.abs(sinp) >= 1:
            pitch = np.copysign(np.pi / 2, sinp)  # Use 90 degrees if out of range
        else:
            pitch = np.arcsin(sinp)
        
        # Yaw (z-axis rotation)
        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = np.arctan2(siny_cosp, cosy_cosp)
        
        # Convert radians to degrees
        return (np.degrees(roll), np.degrees(pitch), np.degrees(yaw))