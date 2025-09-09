"""
Conflict Resolution System for Collaborative FreeCAD Editing.
Implements multiple resolution strategies including automatic merge and manual resolution.
"""

import logging
import numpy as np
from datetime import datetime, UTC
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import uuid
import json
from decimal import Decimal

from app.services.operational_transform import (
    ModelOperation,
    OperationType,
    Point3D,
    Transform3D
)
from app.utils.quaternion_math import (
    euler_to_quaternion,
    quaternion_to_euler,
    quaternion_multiply
)

logger = logging.getLogger(__name__)


class ResolutionStrategy(str, Enum):
    """Conflict resolution strategies."""
    TIMESTAMP = "timestamp"  # Last write wins
    PRIORITY = "priority"  # User priority based
    MERGE = "merge"  # Automatic merge attempt
    MANUAL = "manual"  # User intervention required
    VOTING = "voting"  # Democratic resolution
    EXPERT = "expert"  # Expert user decides


class ConflictType(str, Enum):
    """Types of conflicts."""
    PROPERTY_CONFLICT = "property_conflict"
    POSITION_CONFLICT = "position_conflict"
    DELETION_CONFLICT = "deletion_conflict"
    CONSTRAINT_CONFLICT = "constraint_conflict"
    HIERARCHY_CONFLICT = "hierarchy_conflict"
    SEMANTIC_CONFLICT = "semantic_conflict"


@dataclass
class ModelConflict:
    """Represents a conflict between operations."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: ConflictType = ConflictType.PROPERTY_CONFLICT
    operation1: ModelOperation = None
    operation2: ModelOperation = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    affected_objects: List[str] = field(default_factory=list)
    severity: str = "medium"  # low, medium, high, critical
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "operation1": self.operation1.to_dict() if self.operation1 else None,
            "operation2": self.operation2.to_dict() if self.operation2 else None,
            "detected_at": self.detected_at.isoformat(),
            "affected_objects": self.affected_objects,
            "severity": self.severity,
            "metadata": self.metadata
        }


@dataclass
class Resolution:
    """Result of conflict resolution."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conflict_id: str = None
    success: bool = False
    pending: bool = False
    failed: bool = False
    strategy_used: Optional[ResolutionStrategy] = None
    resolved_operation: Optional[ModelOperation] = None
    resolution_metadata: Dict[str, Any] = field(default_factory=dict)
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_by: Optional[str] = None  # User ID if manual resolution
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "conflict_id": self.conflict_id,
            "success": self.success,
            "pending": self.pending,
            "failed": self.failed,
            "strategy_used": self.strategy_used.value if self.strategy_used else None,
            "resolved_operation": self.resolved_operation.to_dict() if self.resolved_operation else None,
            "resolution_metadata": self.resolution_metadata,
            "resolved_at": self.resolved_at.isoformat(),
            "resolved_by": self.resolved_by
        }


class ConflictResolver:
    """
    Resolves conflicts between concurrent operations in collaborative editing.
    """
    
    def __init__(self):
        self.pending_conflicts: Dict[str, ModelConflict] = {}
        self.resolution_history: List[Resolution] = []
        self.manual_resolution_queue: List[ModelConflict] = []
        
        # Strategy implementations
        self.strategies = {
            ResolutionStrategy.TIMESTAMP: self._resolve_by_timestamp,
            ResolutionStrategy.PRIORITY: self._resolve_by_priority,
            ResolutionStrategy.MERGE: self._resolve_by_merge,
            ResolutionStrategy.MANUAL: self._queue_for_manual,
            ResolutionStrategy.VOTING: self._resolve_by_voting,
            ResolutionStrategy.EXPERT: self._resolve_by_expert
        }
    
    async def resolve_conflict(
        self,
        conflict: ModelConflict,
        strategy: ResolutionStrategy = ResolutionStrategy.MERGE,
        context: Optional[Dict[str, Any]] = None
    ) -> Resolution:
        """
        Resolve a conflict using the specified strategy.
        
        Args:
            conflict: The conflict to resolve
            strategy: Resolution strategy to use
            context: Additional context for resolution
            
        Returns:
            Resolution result
        """
        logger.info(f"Resolving conflict {conflict.id} using {strategy} strategy")
        
        # Store conflict
        self.pending_conflicts[conflict.id] = conflict
        
        # Get resolution function
        resolve_func = self.strategies.get(strategy, self._resolve_by_merge)
        
        # Attempt resolution
        try:
            resolution = await resolve_func(conflict, context or {})
            resolution.conflict_id = conflict.id
            resolution.strategy_used = strategy
            
            # Store resolution
            self.resolution_history.append(resolution)
            
            # Clean up if resolved
            if resolution.success:
                del self.pending_conflicts[conflict.id]
            
            return resolution
            
        except Exception as e:
            logger.error(f"Error resolving conflict {conflict.id}: {e}")
            return Resolution(
                conflict_id=conflict.id,
                failed=True,
                resolution_metadata={"error": str(e)}
            )
    
    async def _resolve_by_timestamp(
        self,
        conflict: ModelConflict,
        context: Dict[str, Any]
    ) -> Resolution:
        """Resolve conflict using timestamp (last write wins)."""
        op1, op2 = conflict.operation1, conflict.operation2
        
        if not op1 or not op2:
            return Resolution(failed=True, resolution_metadata={"reason": "missing_operations"})
        
        # Choose operation with later timestamp
        if op1.timestamp > op2.timestamp:
            winner = op1
            loser = op2
        else:
            winner = op2
            loser = op1
        
        logger.debug(f"Timestamp resolution: {winner.id} wins over {loser.id}")
        
        return Resolution(
            success=True,
            resolved_operation=winner,
            resolution_metadata={
                "winner_id": winner.id,
                "loser_id": loser.id,
                "winner_timestamp": winner.timestamp.isoformat(),
                "loser_timestamp": loser.timestamp.isoformat()
            }
        )
    
    async def _resolve_by_priority(
        self,
        conflict: ModelConflict,
        context: Dict[str, Any]
    ) -> Resolution:
        """Resolve conflict based on user priority."""
        op1, op2 = conflict.operation1, conflict.operation2
        
        if not op1 or not op2:
            return Resolution(failed=True, resolution_metadata={"reason": "missing_operations"})
        
        # Get user priorities from context or metadata
        priority1 = context.get(f"user_priority_{op1.user_id}", 
                               op1.metadata.get("user_priority", 0))
        priority2 = context.get(f"user_priority_{op2.user_id}",
                               op2.metadata.get("user_priority", 0))
        
        if priority1 > priority2:
            winner = op1
        elif priority2 > priority1:
            winner = op2
        else:
            # Same priority - fall back to timestamp
            return await self._resolve_by_timestamp(conflict, context)
        
        logger.debug(f"Priority resolution: {winner.id} wins (priority: {max(priority1, priority2)})")
        
        return Resolution(
            success=True,
            resolved_operation=winner,
            resolution_metadata={
                "winner_id": winner.id,
                "winner_priority": max(priority1, priority2),
                "priorities": {op1.id: priority1, op2.id: priority2}
            }
        )
    
    async def _resolve_by_merge(
        self,
        conflict: ModelConflict,
        context: Dict[str, Any]
    ) -> Resolution:
        """Attempt automatic merge of conflicting operations."""
        op1, op2 = conflict.operation1, conflict.operation2
        
        if not op1 or not op2:
            return Resolution(failed=True, resolution_metadata={"reason": "missing_operations"})
        
        # Try different merge strategies based on conflict type
        if conflict.type == ConflictType.PROPERTY_CONFLICT:
            merged = await self._merge_property_conflict(op1, op2)
        elif conflict.type == ConflictType.POSITION_CONFLICT:
            merged = await self._merge_position_conflict(op1, op2)
        elif conflict.type == ConflictType.CONSTRAINT_CONFLICT:
            merged = await self._merge_constraint_conflict(op1, op2)
        else:
            # Can't merge this type - fall back to timestamp
            return await self._resolve_by_timestamp(conflict, context)
        
        if merged:
            logger.debug(f"Merge successful for conflict {conflict.id}")
            return Resolution(
                success=True,
                resolved_operation=merged,
                resolution_metadata={
                    "merge_type": conflict.type.value,
                    "merged_from": [op1.id, op2.id]
                }
            )
        else:
            # Merge failed - need manual resolution
            return await self._queue_for_manual(conflict, context)
    
    async def _merge_property_conflict(
        self,
        op1: ModelOperation,
        op2: ModelOperation
    ) -> Optional[ModelOperation]:
        """Merge conflicting property changes."""
        if op1.type != OperationType.PROPERTY_CHANGE or op2.type != OperationType.PROPERTY_CHANGE:
            return None
        
        prop1 = op1.parameters.get("property_name")
        prop2 = op2.parameters.get("property_name")
        
        # Different properties - both can apply
        if prop1 != prop2:
            # Create combined operation
            merged = ModelOperation(
                type=OperationType.MODIFY,
                object_id=op1.object_id,
                parameters={
                    prop1: op1.parameters.get("new_value"),
                    prop2: op2.parameters.get("new_value")
                },
                metadata={
                    "merged_from": [op1.id, op2.id],
                    "merge_type": "property_combination"
                }
            )
            return merged
        
        # Same property - try to merge values
        val1 = op1.parameters.get("new_value")
        val2 = op2.parameters.get("new_value")
        
        # If numeric (including Decimal), average them
        if isinstance(val1, (int, float, Decimal)) and isinstance(val2, (int, float, Decimal)):
            # Convert to Decimal for precision if any value is Decimal
            if isinstance(val1, Decimal) or isinstance(val2, Decimal):
                val1 = Decimal(str(val1)) if not isinstance(val1, Decimal) else val1
                val2 = Decimal(str(val2)) if not isinstance(val2, Decimal) else val2
                merged_value = (val1 + val2) / 2
            else:
                merged_value = (val1 + val2) / 2
            merged = ModelOperation(
                type=OperationType.PROPERTY_CHANGE,
                object_id=op1.object_id,
                parameters={
                    "property_name": prop1,
                    "new_value": merged_value
                },
                metadata={
                    "merged_from": [op1.id, op2.id],
                    "merge_type": "numeric_average"
                }
            )
            return merged
        
        # If strings, concatenate with separator
        if isinstance(val1, str) and isinstance(val2, str):
            merged_value = f"{val1} | {val2}"
            merged = ModelOperation(
                type=OperationType.PROPERTY_CHANGE,
                object_id=op1.object_id,
                parameters={
                    "property_name": prop1,
                    "new_value": merged_value
                },
                metadata={
                    "merged_from": [op1.id, op2.id],
                    "merge_type": "string_concatenation"
                }
            )
            return merged
        
        return None
    
    async def _merge_position_conflict(
        self,
        op1: ModelOperation,
        op2: ModelOperation
    ) -> Optional[ModelOperation]:
        """Merge conflicting position changes."""
        if op1.type not in [OperationType.MOVE, OperationType.ROTATE, OperationType.SCALE]:
            return None
        
        if op1.type == OperationType.MOVE and op2.type == OperationType.MOVE:
            # Average the positions
            pos1 = Point3D.from_dict(op1.parameters.get("position", {"x": 0, "y": 0, "z": 0}))
            pos2 = Point3D.from_dict(op2.parameters.get("position", {"x": 0, "y": 0, "z": 0}))
            
            merged_pos = Point3D(
                x=(pos1.x + pos2.x) / 2,
                y=(pos1.y + pos2.y) / 2,
                z=(pos1.z + pos2.z) / 2
            )
            
            merged = ModelOperation(
                type=OperationType.MOVE,
                object_id=op1.object_id,
                parameters={"position": merged_pos.to_dict()},
                metadata={
                    "merged_from": [op1.id, op2.id],
                    "merge_type": "position_average"
                }
            )
            return merged
        
        elif op1.type == OperationType.ROTATE and op2.type == OperationType.ROTATE:
            # Combine rotations using quaternion multiplication
            rot1 = Point3D.from_dict(op1.parameters.get("rotation", {"x": 0, "y": 0, "z": 0}))
            rot2 = Point3D.from_dict(op2.parameters.get("rotation", {"x": 0, "y": 0, "z": 0}))
            
            # Convert Euler angles to quaternions and compose
            q1 = euler_to_quaternion(rot1.x, rot1.y, rot1.z)
            q2 = euler_to_quaternion(rot2.x, rot2.y, rot2.z)
            
            # Quaternion multiplication (q2 * q1 for applying q1 then q2)
            q_combined = quaternion_multiply(q2, q1)
            
            # Convert back to Euler angles
            combined_euler = quaternion_to_euler(q_combined)
            
            merged_rot = Point3D(
                x=combined_euler[0],
                y=combined_euler[1],
                z=combined_euler[2]
            )
            
            merged = ModelOperation(
                type=OperationType.ROTATE,
                object_id=op1.object_id,
                parameters={"rotation": merged_rot.to_dict()},
                metadata={
                    "merged_from": [op1.id, op2.id],
                    "merge_type": "quaternion_rotation_combination"
                }
            )
            return merged
        
        return None
    
    async def _merge_constraint_conflict(
        self,
        op1: ModelOperation,
        op2: ModelOperation
    ) -> Optional[ModelOperation]:
        """Merge conflicting constraint operations."""
        if op1.type != OperationType.CONSTRAINT_ADD or op2.type != OperationType.CONSTRAINT_ADD:
            return None
        
        # Check if constraints are compatible
        type1 = op1.parameters.get("constraint_type")
        type2 = op2.parameters.get("constraint_type")
        
        # Some constraints can coexist
        compatible_pairs = [
            ("distance", "angle"),
            ("parallel", "perpendicular"),
            ("horizontal", "vertical")
        ]
        
        if (type1, type2) in compatible_pairs or (type2, type1) in compatible_pairs:
            # Create compound constraint
            merged = ModelOperation(
                type=OperationType.CONSTRAINT_ADD,
                object_id=op1.object_id,
                parameters={
                    "constraint_type": "compound",
                    "constraints": [
                        {"type": type1, "params": op1.parameters},
                        {"type": type2, "params": op2.parameters}
                    ]
                },
                metadata={
                    "merged_from": [op1.id, op2.id],
                    "merge_type": "constraint_combination"
                }
            )
            return merged
        
        return None
    
    async def _queue_for_manual(
        self,
        conflict: ModelConflict,
        context: Dict[str, Any]
    ) -> Resolution:
        """Queue conflict for manual resolution."""
        self.manual_resolution_queue.append(conflict)
        
        logger.info(f"Conflict {conflict.id} queued for manual resolution")
        
        return Resolution(
            pending=True,
            resolution_metadata={
                "reason": "requires_manual_resolution",
                "queue_position": len(self.manual_resolution_queue)
            }
        )
    
    async def _resolve_by_voting(
        self,
        conflict: ModelConflict,
        context: Dict[str, Any]
    ) -> Resolution:
        """Resolve conflict by voting (requires user input)."""
        # This would integrate with a voting system
        votes = context.get("votes", {})
        
        if not votes:
            return await self._queue_for_manual(conflict, context)
        
        # Count votes
        op1_votes = votes.get(conflict.operation1.id, 0)
        op2_votes = votes.get(conflict.operation2.id, 0)
        
        if op1_votes > op2_votes:
            winner = conflict.operation1
        elif op2_votes > op1_votes:
            winner = conflict.operation2
        else:
            # Tie - use timestamp
            return await self._resolve_by_timestamp(conflict, context)
        
        return Resolution(
            success=True,
            resolved_operation=winner,
            resolution_metadata={
                "winner_id": winner.id,
                "votes": votes,
                "total_votes": op1_votes + op2_votes
            }
        )
    
    async def _resolve_by_expert(
        self,
        conflict: ModelConflict,
        context: Dict[str, Any]
    ) -> Resolution:
        """Resolve conflict by expert decision."""
        expert_decision = context.get("expert_decision")
        
        if not expert_decision:
            return await self._queue_for_manual(conflict, context)
        
        # Expert chose an operation
        chosen_op_id = expert_decision.get("chosen_operation_id")
        
        if chosen_op_id == conflict.operation1.id:
            winner = conflict.operation1
        elif chosen_op_id == conflict.operation2.id:
            winner = conflict.operation2
        else:
            # Expert provided custom resolution
            custom_op = ModelOperation.from_dict(expert_decision.get("custom_operation"))
            return Resolution(
                success=True,
                resolved_operation=custom_op,
                resolved_by=expert_decision.get("expert_id"),
                resolution_metadata={
                    "expert_id": expert_decision.get("expert_id"),
                    "expert_notes": expert_decision.get("notes")
                }
            )
        
        return Resolution(
            success=True,
            resolved_operation=winner,
            resolved_by=expert_decision.get("expert_id"),
            resolution_metadata={
                "expert_id": expert_decision.get("expert_id"),
                "expert_notes": expert_decision.get("notes")
            }
        )
    
    async def apply_manual_resolution(
        self,
        conflict_id: str,
        resolution_data: Dict[str, Any],
        user_id: str
    ) -> Resolution:
        """Apply a manual resolution to a queued conflict."""
        # Find conflict
        conflict = self.pending_conflicts.get(conflict_id)
        if not conflict:
            return Resolution(
                failed=True,
                resolution_metadata={"reason": "conflict_not_found"}
            )
        
        # Remove from manual queue
        self.manual_resolution_queue = [
            c for c in self.manual_resolution_queue if c.id != conflict_id
        ]
        
        # Create resolved operation
        resolved_op = ModelOperation.from_dict(resolution_data.get("operation"))
        
        resolution = Resolution(
            conflict_id=conflict_id,
            success=True,
            resolved_operation=resolved_op,
            resolved_by=user_id,
            strategy_used=ResolutionStrategy.MANUAL,
            resolution_metadata={
                "manual_resolution": True,
                "user_notes": resolution_data.get("notes", "")
            }
        )
        
        # Store and clean up
        self.resolution_history.append(resolution)
        del self.pending_conflicts[conflict_id]
        
        logger.info(f"Manual resolution applied to conflict {conflict_id} by user {user_id}")
        
        return resolution
    
    def get_pending_manual_conflicts(self) -> List[ModelConflict]:
        """Get conflicts awaiting manual resolution."""
        return self.manual_resolution_queue.copy()
    
    def get_conflict_statistics(self) -> Dict[str, Any]:
        """Get statistics about conflict resolution."""
        total_resolved = len(self.resolution_history)
        
        if total_resolved == 0:
            return {
                "total_resolved": 0,
                "pending_conflicts": len(self.pending_conflicts),
                "manual_queue_size": len(self.manual_resolution_queue)
            }
        
        # Calculate statistics
        strategy_counts = {}
        success_count = 0
        
        for resolution in self.resolution_history:
            if resolution.strategy_used:
                strategy_counts[resolution.strategy_used.value] = \
                    strategy_counts.get(resolution.strategy_used.value, 0) + 1
            if resolution.success:
                success_count += 1
        
        return {
            "total_resolved": total_resolved,
            "success_rate": success_count / total_resolved,
            "pending_conflicts": len(self.pending_conflicts),
            "manual_queue_size": len(self.manual_resolution_queue),
            "strategy_usage": strategy_counts,
            "recent_resolutions": [
                r.to_dict() for r in self.resolution_history[-10:]
            ]
        }
    
    async def detect_conflict(
        self,
        op1: ModelOperation,
        op2: ModelOperation
    ) -> Optional[ModelConflict]:
        """
        Detect if two operations conflict.
        
        Returns:
            ModelConflict if conflict detected, None otherwise
        """
        # No conflict with no-ops
        if op1.is_no_op() or op2.is_no_op():
            return None
        
        # Check for object-level conflicts
        if op1.object_id == op2.object_id:
            # Same object operations
            if op1.type == OperationType.DELETE or op2.type == OperationType.DELETE:
                return ModelConflict(
                    type=ConflictType.DELETION_CONFLICT,
                    operation1=op1,
                    operation2=op2,
                    affected_objects=[op1.object_id],
                    severity="high"
                )
            
            if op1.type == OperationType.MODIFY and op2.type == OperationType.MODIFY:
                # Check if they modify same properties
                props1 = set(op1.parameters.keys())
                props2 = set(op2.parameters.keys())
                
                if props1.intersection(props2):
                    return ModelConflict(
                        type=ConflictType.PROPERTY_CONFLICT,
                        operation1=op1,
                        operation2=op2,
                        affected_objects=[op1.object_id],
                        severity="medium"
                    )
            
            if op1.type in [OperationType.MOVE, OperationType.ROTATE, OperationType.SCALE]:
                if op2.type in [OperationType.MOVE, OperationType.ROTATE, OperationType.SCALE]:
                    return ModelConflict(
                        type=ConflictType.POSITION_CONFLICT,
                        operation1=op1,
                        operation2=op2,
                        affected_objects=[op1.object_id],
                        severity="low"
                    )
        
        # Check for constraint conflicts
        if op1.type in [OperationType.CONSTRAINT_ADD, OperationType.CONSTRAINT_REMOVE]:
            if op2.type in [OperationType.CONSTRAINT_ADD, OperationType.CONSTRAINT_REMOVE]:
                refs1 = set(op1.parameters.get("referenced_objects", []))
                refs2 = set(op2.parameters.get("referenced_objects", []))
                
                if refs1.intersection(refs2):
                    return ModelConflict(
                        type=ConflictType.CONSTRAINT_CONFLICT,
                        operation1=op1,
                        operation2=op2,
                        affected_objects=list(refs1.union(refs2)),
                        severity="medium"
                    )
        
        return None