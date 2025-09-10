"""
Model Differ for FreeCAD Model Version Control (Task 7.22).

This service calculates differences between FreeCAD models, including
geometry, properties, and parametric expressions.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.version_control import (
    ChangeType,
    CommitDiff,
    DiffType,
    FreeCADObjectData,
    ObjectDiff,
    PropertyChange,
    ShapeDiff,
    Tree,
    VERSION_CONTROL_TR,
)

logger = structlog.get_logger(__name__)


class ModelDifferError(Exception):
    """Custom exception for differ operations."""
    pass


class ModelDiffer:
    """
    Calculates differences between FreeCAD models.
    
    Features:
    - Property-level diffing
    - Geometric shape comparison
    - Expression change tracking
    - Tree-level diffing
    - Diff statistics
    """
    
    def __init__(self):
        """Initialize model differ."""
        # Tolerance for floating point comparisons
        self.tolerance = 1e-6
        
        logger.info("model_differ_initialized")
    
    def diff_objects(
        self,
        obj1: FreeCADObjectData,
        obj2: FreeCADObjectData,
    ) -> ObjectDiff:
        """
        Calculate differences between two FreeCAD objects.
        
        Args:
            obj1: First object
            obj2: Second object
            
        Returns:
            ObjectDiff with detailed changes
        """
        # Determine diff type
        if obj1 is None and obj2 is not None:
            diff_type = DiffType.ADDED
            object_id = obj2.name
        elif obj1 is not None and obj2 is None:
            diff_type = DiffType.DELETED
            object_id = obj1.name
        else:
            diff_type = DiffType.MODIFIED
            object_id = obj1.name if obj1 else "unknown"
        
        diff = ObjectDiff(
            object_id=object_id,
            diff_type=diff_type,
            property_changes=[],
            shape_diff=None,
            expression_changes={}
        )
        
        # If added or deleted, no need for detailed comparison
        if diff_type in (DiffType.ADDED, DiffType.DELETED):
            return diff
        
        # Compare properties
        diff.property_changes = self._diff_properties(obj1, obj2)
        
        # Compare shapes if applicable
        if obj1.shape_data and obj2.shape_data:
            diff.shape_diff = self._diff_shapes(obj1.shape_data, obj2.shape_data)
        
        # Compare expressions
        diff.expression_changes = self._diff_expressions(
            obj1.expressions,
            obj2.expressions
        )
        
        # If no changes, mark as unmodified
        if (not diff.property_changes and 
            not diff.shape_diff and 
            not diff.expression_changes):
            diff.diff_type = DiffType.MODIFIED  # Actually unchanged
        
        return diff
    
    def _diff_properties(
        self,
        obj1: FreeCADObjectData,
        obj2: FreeCADObjectData,
    ) -> List[PropertyChange]:
        """Compare object properties."""
        changes = []
        
        # Get all property names
        props1 = set(obj1.properties.keys())
        props2 = set(obj2.properties.keys())
        all_props = props1 | props2
        
        for prop_name in all_props:
            val1 = obj1.properties.get(prop_name)
            val2 = obj2.properties.get(prop_name)
            
            if prop_name not in props1:
                # Property added
                changes.append(PropertyChange(
                    property=prop_name,
                    old_value=None,
                    new_value=val2,
                    change_type=ChangeType.ADDITION
                ))
            elif prop_name not in props2:
                # Property deleted
                changes.append(PropertyChange(
                    property=prop_name,
                    old_value=val1,
                    new_value=None,
                    change_type=ChangeType.DELETION
                ))
            elif not self._values_equal(val1, val2):
                # Property changed
                change_type = ChangeType.VALUE_CHANGE
                if type(val1) != type(val2):
                    change_type = ChangeType.TYPE_CHANGE
                
                changes.append(PropertyChange(
                    property=prop_name,
                    old_value=val1,
                    new_value=val2,
                    change_type=change_type
                ))
        
        return changes
    
    def _diff_shapes(
        self,
        shape1: Dict[str, Any],
        shape2: Dict[str, Any],
    ) -> ShapeDiff:
        """
        Compare geometric shapes.
        
        In a real implementation, this would use FreeCAD's Part.Shape
        comparison methods for accurate geometric diffing.
        """
        shape_diff = ShapeDiff()
        
        # Volume comparison
        vol1 = shape1.get("volume", 0)
        vol2 = shape2.get("volume", 0)
        if vol1 > 0:
            shape_diff.volume_change = (vol2 - vol1) / vol1
        
        # Surface area comparison
        area1 = shape1.get("area", 0)
        area2 = shape2.get("area", 0)
        if area1 > 0:
            shape_diff.area_change = (area2 - area1) / area1
        
        # Topology changes
        shape_diff.vertex_count_change = (
            shape2.get("vertex_count", 0) - shape1.get("vertex_count", 0)
        )
        shape_diff.edge_count_change = (
            shape2.get("edge_count", 0) - shape1.get("edge_count", 0)
        )
        shape_diff.face_count_change = (
            shape2.get("face_count", 0) - shape1.get("face_count", 0)
        )
        
        # Additional topology information
        shape_diff.topology_changes = {
            "bounds_changed": shape1.get("bounds") != shape2.get("bounds"),
            "center_of_mass_changed": shape1.get("center_of_mass") != shape2.get("center_of_mass"),
            "orientation_changed": shape1.get("orientation") != shape2.get("orientation")
        }
        
        return shape_diff
    
    def _diff_expressions(
        self,
        expr1: Dict[str, str],
        expr2: Dict[str, str],
    ) -> Dict[str, Dict[str, str]]:
        """Compare parametric expressions."""
        changes = {}
        
        # Get all expression keys
        keys1 = set(expr1.keys())
        keys2 = set(expr2.keys())
        all_keys = keys1 | keys2
        
        for key in all_keys:
            val1 = expr1.get(key)
            val2 = expr2.get(key)
            
            if val1 != val2:
                changes[key] = {
                    "old": val1 or "",
                    "new": val2 or ""
                }
        
        return changes
    
    def _values_equal(
        self,
        val1: Any,
        val2: Any,
    ) -> bool:
        """Check if two values are equal with tolerance for floats."""
        if type(val1) != type(val2):
            return False
        
        if isinstance(val1, float) and isinstance(val2, float):
            return abs(val1 - val2) < self.tolerance
        
        return val1 == val2
    
    async def diff_trees(
        self,
        tree1: Tree,
        tree2: Tree,
    ) -> CommitDiff:
        """
        Calculate differences between two trees.
        
        Args:
            tree1: First tree
            tree2: Second tree
            
        Returns:
            CommitDiff with all object differences
        """
        correlation_id = get_correlation_id()
        
        with create_span("diff_trees", correlation_id=correlation_id) as span:
            try:
                object_diffs = []
                stats = {
                    "added": 0,
                    "modified": 0,
                    "deleted": 0,
                    "renamed": 0
                }
                
                # Build entry maps
                entries1 = {e.name: e for e in tree1.entries} if tree1 else {}
                entries2 = {e.name: e for e in tree2.entries} if tree2 else {}
                
                # Get all unique entry names
                all_names = set(entries1.keys()) | set(entries2.keys())
                
                for name in all_names:
                    entry1 = entries1.get(name)
                    entry2 = entries2.get(name)
                    
                    if entry1 and entry2:
                        if entry1.hash != entry2.hash:
                            # Object modified
                            # Would load and diff actual objects here
                            diff = ObjectDiff(
                                object_id=name,
                                diff_type=DiffType.MODIFIED,
                                property_changes=[],
                                shape_diff=None,
                                expression_changes={}
                            )
                            object_diffs.append(diff)
                            stats["modified"] += 1
                    elif entry2:
                        # Object added
                        diff = ObjectDiff(
                            object_id=name,
                            diff_type=DiffType.ADDED,
                            property_changes=[],
                            shape_diff=None,
                            expression_changes={}
                        )
                        object_diffs.append(diff)
                        stats["added"] += 1
                    else:
                        # Object deleted
                        diff = ObjectDiff(
                            object_id=name,
                            diff_type=DiffType.DELETED,
                            property_changes=[],
                            shape_diff=None,
                            expression_changes={}
                        )
                        object_diffs.append(diff)
                        stats["deleted"] += 1
                
                # Detect renames (simplified - would use similarity detection)
                # For now, skip rename detection
                
                commit_diff = CommitDiff(
                    from_commit=tree1.calculate_hash() if tree1 else "null",
                    to_commit=tree2.calculate_hash() if tree2 else "null",
                    object_diffs=object_diffs,
                    stats=stats
                )
                
                logger.info(
                    "tree_diff_calculated",
                    stats=stats,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['diff_calculated']
                )
                
                return commit_diff
                
            except Exception as e:
                logger.error(
                    "tree_diff_failed",
                    error=str(e),
                    correlation_id=correlation_id
                )
                raise ModelDifferError(f"Failed to diff trees: {str(e)}")
    
    def format_diff(
        self,
        diff: ObjectDiff,
    ) -> str:
        """
        Format diff for display.
        
        Args:
            diff: ObjectDiff to format
            
        Returns:
            Formatted diff string
        """
        lines = []
        
        # Header
        if diff.diff_type == DiffType.ADDED:
            lines.append(f"+++ {diff.object_id} (added)")
        elif diff.diff_type == DiffType.DELETED:
            lines.append(f"--- {diff.object_id} (deleted)")
        else:
            lines.append(f"~~~ {diff.object_id} (modified)")
        
        # Property changes
        if diff.property_changes:
            lines.append("\nProperty changes:")
            for change in diff.property_changes:
                if change.change_type == ChangeType.ADDITION:
                    lines.append(f"  + {change.property}: {change.new_value}")
                elif change.change_type == ChangeType.DELETION:
                    lines.append(f"  - {change.property}: {change.old_value}")
                else:
                    lines.append(f"  ~ {change.property}:")
                    lines.append(f"    - {change.old_value}")
                    lines.append(f"    + {change.new_value}")
        
        # Shape diff
        if diff.shape_diff:
            lines.append("\nGeometry changes:")
            if diff.shape_diff.volume_change is not None:
                lines.append(f"  Volume change: {diff.shape_diff.volume_change:.2%}")
            if diff.shape_diff.area_change is not None:
                lines.append(f"  Area change: {diff.shape_diff.area_change:.2%}")
            if diff.shape_diff.vertex_count_change:
                lines.append(f"  Vertex count change: {diff.shape_diff.vertex_count_change:+d}")
            if diff.shape_diff.edge_count_change:
                lines.append(f"  Edge count change: {diff.shape_diff.edge_count_change:+d}")
            if diff.shape_diff.face_count_change:
                lines.append(f"  Face count change: {diff.shape_diff.face_count_change:+d}")
        
        # Expression changes
        if diff.expression_changes:
            lines.append("\nExpression changes:")
            for key, change in diff.expression_changes.items():
                lines.append(f"  {key}:")
                lines.append(f"    - {change['old']}")
                lines.append(f"    + {change['new']}")
        
        return "\n".join(lines)
    
    def get_diff_summary(
        self,
        commit_diff: CommitDiff,
    ) -> str:
        """
        Get summary of commit diff.
        
        Args:
            commit_diff: CommitDiff to summarize
            
        Returns:
            Summary string
        """
        stats = commit_diff.stats
        parts = []
        
        if stats.get("added", 0) > 0:
            parts.append(f"{stats['added']} added")
        if stats.get("modified", 0) > 0:
            parts.append(f"{stats['modified']} modified")
        if stats.get("deleted", 0) > 0:
            parts.append(f"{stats['deleted']} deleted")
        if stats.get("renamed", 0) > 0:
            parts.append(f"{stats['renamed']} renamed")
        
        if not parts:
            return "No changes"
        
        return f"{len(commit_diff.object_diffs)} objects changed: {', '.join(parts)}"