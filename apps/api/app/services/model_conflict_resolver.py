"""
Conflict Resolver for FreeCAD Model Version Control (Task 7.22).

This service handles conflict resolution during merges, providing various
strategies for resolving conflicts in FreeCAD models.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set

import structlog

from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.version_control import (
    ConflictResolutionStrategy,
    FreeCADObjectData,
    MergeConflict,
    ResolvedObject,
    VERSION_CONTROL_TR,
)

logger = structlog.get_logger(__name__)


class ConflictResolverError(Exception):
    """Custom exception for conflict resolver operations."""
    pass


class ModelConflictResolver:
    """
    Resolves conflicts between different versions of FreeCAD models.
    
    Features:
    - Multiple resolution strategies
    - Automatic conflict resolution for simple cases
    - Property-level merging
    - Geometric conflict detection
    - Interactive conflict resolution support
    """
    
    def __init__(self):
        """Initialize conflict resolver."""
        # Rules for automatic resolution
        self.auto_resolve_rules = {
            "formatting": True,  # Auto-resolve formatting-only changes
            "comments": True,    # Auto-resolve comment-only changes
            "timestamps": True,  # Auto-resolve timestamp conflicts
            "minor_numeric": True,  # Auto-resolve minor numeric differences
        }
        
        # Tolerance for numeric comparisons
        self.numeric_tolerance = 1e-6
        
        logger.info("conflict_resolver_initialized")
    
    async def resolve_conflict(
        self,
        conflict: MergeConflict,
        strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.AUTO,
    ) -> ResolvedObject:
        """
        Resolve a merge conflict.
        
        Args:
            conflict: Merge conflict to resolve
            strategy: Resolution strategy to use
            
        Returns:
            ResolvedObject with resolution details
        """
        correlation_id = get_correlation_id()
        
        with create_span("resolve_conflict", correlation_id=correlation_id) as span:
            span.set_attribute("object.id", conflict.object_id)
            span.set_attribute("strategy", strategy.value)
            
            try:
                # Apply strategy
                if strategy == ConflictResolutionStrategy.OURS:
                    resolved = self._resolve_keep_ours(conflict)
                elif strategy == ConflictResolutionStrategy.THEIRS:
                    resolved = self._resolve_keep_theirs(conflict)
                elif strategy == ConflictResolutionStrategy.UNION:
                    resolved = await self._resolve_union(conflict)
                elif strategy == ConflictResolutionStrategy.AUTO:
                    resolved = await self._resolve_auto(conflict)
                else:  # INTERACTIVE
                    resolved = await self._resolve_interactive(conflict)
                
                if resolved.object_data:
                    logger.info(
                        "conflict_resolved",
                        object_id=conflict.object_id,
                        strategy=strategy.value,
                        resolution_type=resolved.resolution_type,
                        correlation_id=correlation_id,
                        message=VERSION_CONTROL_TR['conflict_resolved']
                    )
                    metrics.freecad_vcs_conflicts_resolved_total.labels(
                        strategy=strategy.value
                    ).inc()
                else:
                    logger.warning(
                        "conflict_unresolved",
                        object_id=conflict.object_id,
                        strategy=strategy.value,
                        correlation_id=correlation_id
                    )
                    metrics.freecad_vcs_conflicts_unresolved_total.inc()
                
                return resolved
                
            except Exception as e:
                logger.error(
                    "conflict_resolution_failed",
                    error=str(e),
                    object_id=conflict.object_id,
                    correlation_id=correlation_id
                )
                raise ConflictResolverError(f"Failed to resolve conflict: {str(e)}")
    
    def _resolve_keep_ours(
        self,
        conflict: MergeConflict,
    ) -> ResolvedObject:
        """Keep our version."""
        return ResolvedObject(
            object_data=conflict.our_version,
            resolution_type="keep_ours",
            conflict_info={"strategy": "ours"}
        )
    
    def _resolve_keep_theirs(
        self,
        conflict: MergeConflict,
    ) -> ResolvedObject:
        """Keep their version."""
        return ResolvedObject(
            object_data=conflict.their_version,
            resolution_type="keep_theirs",
            conflict_info={"strategy": "theirs"}
        )
    
    async def _resolve_union(
        self,
        conflict: MergeConflict,
    ) -> ResolvedObject:
        """
        Resolve by taking union of changes.
        
        This strategy attempts to combine non-conflicting changes
        from both versions.
        """
        try:
            # Start with base version if available
            if conflict.base_version:
                merged = FreeCADObjectData(**conflict.base_version.dict())
            else:
                # No base - start with our version
                merged = FreeCADObjectData(**conflict.our_version.dict())
            
            # Apply non-conflicting changes from both versions
            our_changes = self._get_changes(conflict.base_version, conflict.our_version)
            their_changes = self._get_changes(conflict.base_version, conflict.their_version)
            
            # Find non-conflicting changes
            for prop, our_val in our_changes.items():
                their_val = their_changes.get(prop)
                if their_val is None or our_val == their_val:
                    # No conflict - apply our change
                    if hasattr(merged, prop):
                        setattr(merged, prop, our_val)
                    else:
                        merged.properties[prop] = our_val
            
            for prop, their_val in their_changes.items():
                if prop not in our_changes:
                    # Only in theirs - apply it
                    if hasattr(merged, prop):
                        setattr(merged, prop, their_val)
                    else:
                        merged.properties[prop] = their_val
            
            return ResolvedObject(
                object_data=merged,
                resolution_type="union_merge",
                conflict_info={
                    "strategy": "union",
                    "merged_properties": len(our_changes) + len(their_changes)
                }
            )
            
        except Exception as e:
            logger.warning(
                "union_merge_failed",
                error=str(e),
                object_id=conflict.object_id
            )
            # Fall back to keeping ours
            return self._resolve_keep_ours(conflict)
    
    async def _resolve_auto(
        self,
        conflict: MergeConflict,
    ) -> ResolvedObject:
        """
        Attempt automatic conflict resolution.
        
        Uses heuristics to automatically resolve simple conflicts.
        """
        # Check if conflict is auto-resolvable
        if conflict.auto_resolvable:
            # Use suggested resolution if available
            if conflict.suggested_resolution == "ours":
                return self._resolve_keep_ours(conflict)
            elif conflict.suggested_resolution == "theirs":
                return self._resolve_keep_theirs(conflict)
            elif conflict.suggested_resolution == "union":
                return await self._resolve_union(conflict)
        
        # Analyze conflict type
        conflict_analysis = self._analyze_conflict(conflict)
        
        # Try resolution based on analysis
        if conflict_analysis["type"] == "trivial":
            # Trivial conflicts - timestamps, formatting, etc.
            return self._resolve_trivial(conflict, conflict_analysis)
        elif conflict_analysis["type"] == "numeric":
            # Numeric conflicts - try averaging or other strategies
            return self._resolve_numeric(conflict, conflict_analysis)
        elif conflict_analysis["type"] == "additive":
            # Both added different things - try union
            return await self._resolve_union(conflict)
        else:
            # Cannot auto-resolve
            logger.info(
                "auto_resolve_failed",
                object_id=conflict.object_id,
                conflict_type=conflict_analysis["type"],
                message=VERSION_CONTROL_TR['auto_merge_failed']
            )
            
            return ResolvedObject(
                object_data=None,
                resolution_type="manual_required",
                conflict_info={
                    "reason": "Cannot automatically resolve",
                    "conflict_type": conflict_analysis["type"],
                    "details": conflict_analysis
                }
            )
    
    async def _resolve_interactive(
        self,
        conflict: MergeConflict,
    ) -> ResolvedObject:
        """
        Interactive conflict resolution.
        
        In a real implementation, this would present the conflict
        to the user for manual resolution.
        """
        # Prepare conflict information for user
        conflict_info = self._prepare_conflict_for_display(conflict)
        
        # For now, return unresolved
        return ResolvedObject(
            object_data=None,
            resolution_type="interactive_required",
            conflict_info=conflict_info
        )
    
    def _get_changes(
        self,
        base: Optional[FreeCADObjectData],
        modified: FreeCADObjectData,
    ) -> Dict[str, Any]:
        """Get changes between base and modified versions."""
        changes = {}
        
        if not base:
            # Everything is new
            return modified.properties.copy()
        
        # Compare properties
        for key, value in modified.properties.items():
            base_value = base.properties.get(key)
            if not self._values_equal(base_value, value):
                changes[key] = value
        
        # Check direct attributes
        for attr in ["name", "label", "type_id", "visibility"]:
            modified_val = getattr(modified, attr, None)
            base_val = getattr(base, attr, None)
            if not self._values_equal(base_val, modified_val):
                changes[attr] = modified_val
        
        return changes
    
    def _values_equal(
        self,
        val1: Any,
        val2: Any,
    ) -> bool:
        """Check if two values are equal."""
        if type(val1) != type(val2):
            return False
        
        if isinstance(val1, float) and isinstance(val2, float):
            return abs(val1 - val2) < self.numeric_tolerance
        
        return val1 == val2
    
    def _analyze_conflict(
        self,
        conflict: MergeConflict,
    ) -> Dict[str, Any]:
        """Analyze conflict to determine type and resolution strategy."""
        analysis = {
            "type": "complex",
            "properties_changed": [],
            "geometry_changed": False,
            "expressions_changed": False,
            "can_auto_resolve": False
        }
        
        # Get changes
        our_changes = self._get_changes(conflict.base_version, conflict.our_version)
        their_changes = self._get_changes(conflict.base_version, conflict.their_version)
        
        # Find conflicting properties
        conflicting_props = set(our_changes.keys()) & set(their_changes.keys())
        
        if not conflicting_props:
            analysis["type"] = "additive"
            analysis["can_auto_resolve"] = True
        else:
            # Check if all conflicts are trivial
            all_trivial = True
            all_numeric = True
            
            for prop in conflicting_props:
                our_val = our_changes[prop]
                their_val = their_changes[prop]
                
                if self._is_trivial_conflict(prop, our_val, their_val):
                    continue
                else:
                    all_trivial = False
                
                if not (isinstance(our_val, (int, float)) and 
                       isinstance(their_val, (int, float))):
                    all_numeric = False
            
            if all_trivial:
                analysis["type"] = "trivial"
                analysis["can_auto_resolve"] = True
            elif all_numeric:
                analysis["type"] = "numeric"
                analysis["can_auto_resolve"] = True
        
        analysis["properties_changed"] = list(conflicting_props)
        
        return analysis
    
    def _is_trivial_conflict(
        self,
        prop_name: str,
        val1: Any,
        val2: Any,
    ) -> bool:
        """Check if conflict is trivial and can be auto-resolved."""
        # Timestamp properties
        if "timestamp" in prop_name.lower() or "date" in prop_name.lower():
            return self.auto_resolve_rules.get("timestamps", False)
        
        # Comment properties
        if "comment" in prop_name.lower() or "description" in prop_name.lower():
            return self.auto_resolve_rules.get("comments", False)
        
        # Formatting properties
        if prop_name in ["color", "font", "style"]:
            return self.auto_resolve_rules.get("formatting", False)
        
        return False
    
    def _resolve_trivial(
        self,
        conflict: MergeConflict,
        analysis: Dict[str, Any],
    ) -> ResolvedObject:
        """Resolve trivial conflicts."""
        # For trivial conflicts, we keep their version (the incoming changes)
        # This is a simple resolution strategy that accepts the newer changes
        return self._resolve_keep_theirs(conflict)
    
    def _resolve_numeric(
        self,
        conflict: MergeConflict,
        analysis: Dict[str, Any],
    ) -> ResolvedObject:
        """Resolve numeric conflicts by averaging or other strategies."""
        try:
            # Start with our version
            merged = FreeCADObjectData(**conflict.our_version.dict())
            
            # Average numeric conflicts
            our_changes = self._get_changes(conflict.base_version, conflict.our_version)
            their_changes = self._get_changes(conflict.base_version, conflict.their_version)
            
            for prop in analysis["properties_changed"]:
                if prop in our_changes and prop in their_changes:
                    our_val = our_changes[prop]
                    their_val = their_changes[prop]
                    
                    if isinstance(our_val, (int, float)) and isinstance(their_val, (int, float)):
                        # Average the values
                        avg_val = (our_val + their_val) / 2
                        if isinstance(our_val, int) and isinstance(their_val, int):
                            avg_val = int(avg_val)
                        
                        if hasattr(merged, prop):
                            setattr(merged, prop, avg_val)
                        else:
                            merged.properties[prop] = avg_val
            
            return ResolvedObject(
                object_data=merged,
                resolution_type="numeric_average",
                conflict_info={
                    "strategy": "numeric_averaging",
                    "averaged_properties": analysis["properties_changed"]
                }
            )
            
        except Exception as e:
            logger.warning(
                "numeric_resolve_failed",
                error=str(e),
                object_id=conflict.object_id
            )
            return self._resolve_keep_ours(conflict)
    
    def _prepare_conflict_for_display(
        self,
        conflict: MergeConflict,
    ) -> Dict[str, Any]:
        """Prepare conflict information for user display."""
        our_changes = self._get_changes(conflict.base_version, conflict.our_version)
        their_changes = self._get_changes(conflict.base_version, conflict.their_version)
        
        conflicting_props = set(our_changes.keys()) & set(their_changes.keys())
        
        return {
            "object_id": conflict.object_id,
            "conflict_type": conflict.conflict_type,
            "conflicting_properties": list(conflicting_props),
            "our_changes": our_changes,
            "their_changes": their_changes,
            "base_available": conflict.base_version is not None,
            "auto_resolvable": conflict.auto_resolvable,
            "suggested_resolution": conflict.suggested_resolution
        }