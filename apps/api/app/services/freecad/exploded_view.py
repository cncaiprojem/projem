"""
Exploded View Generation for Task 7.6

Provides exploded view functionality:
- Manual offset specification
- Automatic radial explosion from COM
- Collision avoidance during explosion
- GLB/STEP snapshot export
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)

# Constants for exploded view calculations
MIN_DIRECTION_LENGTH = 0.001  # Minimum vector length to consider direction valid
DEFAULT_UPWARD_DISTANCE = 1.0  # Default Z-axis distance for centered components


class ExplodedComponent(BaseModel):
    """Component with exploded view offset."""
    component_id: str = Field(description="Component identifier")
    original_position: List[float] = Field(description="Original position [x, y, z]")
    exploded_position: List[float] = Field(description="Exploded position [x, y, z]")
    offset_vector: List[float] = Field(description="Offset vector [dx, dy, dz]")
    explosion_distance: float = Field(description="Distance moved from original")


class ExplodedViewConfig(BaseModel):
    """Configuration for exploded view generation."""
    mode: str = Field(default="auto", description="Mode: auto or manual")
    explosion_factor: float = Field(default=2.0, description="Explosion distance multiplier")
    radial_mode: bool = Field(default=True, description="Use radial explosion from COM")
    avoid_collisions: bool = Field(default=True, description="Avoid collisions during explosion")
    manual_offsets: Optional[Dict[str, List[float]]] = Field(
        default=None,
        description="Manual offset vectors by component ID"
    )


class ExplodedView(BaseModel):
    """Complete exploded view definition."""
    components: List[ExplodedComponent] = Field(description="Exploded components")
    center_of_mass: List[float] = Field(description="Assembly center of mass")
    bounding_box: Dict[str, float] = Field(description="Assembly bounding box")
    total_explosion_distance: float = Field(description="Maximum explosion distance")


class ExplodedViewGenerator:
    """Generate exploded views for assemblies."""
    
    # Class constant for collision avoidance
    COLLISION_AVOIDANCE_FACTOR = 1.2  # Factor for collision avoidance (20% margin)
    
    def __init__(self):
        """Initialize exploded view generator."""
        self._freecad_available = self._check_freecad()
    
    def _check_freecad(self) -> bool:
        """Check if FreeCAD is available."""
        try:
            import FreeCAD
            import Part
            return True
        except ImportError:
            logger.warning("FreeCAD not available for exploded view generation")
            return False
    
    def generate_exploded_view(
        self,
        document: Any,
        config: Optional[ExplodedViewConfig] = None
    ) -> ExplodedView:
        """
        Generate exploded view for assembly.
        
        Args:
            document: FreeCAD document
            config: Exploded view configuration
        
        Returns:
            Exploded view definition
        """
        if not self._freecad_available:
            raise RuntimeError("FreeCAD is required for exploded view generation")
        
        import FreeCAD
        import Part
        
        if config is None:
            config = ExplodedViewConfig()
        
        # Get all components with shapes
        components = self._get_components(document)
        
        if not components:
            raise ValueError("No components found in assembly")
        
        # Calculate assembly center of mass
        com = self._calculate_center_of_mass(components)
        
        # Calculate bounding box
        bbox = self._calculate_bounding_box(components)
        
        # Generate explosion offsets
        if config.mode == "manual" and config.manual_offsets:
            exploded_components = self._apply_manual_offsets(
                components, config.manual_offsets
            )
        else:
            exploded_components = self._generate_auto_explosion(
                components, com, bbox, config
            )
        
        # Calculate total explosion distance
        max_distance = max(
            comp.explosion_distance for comp in exploded_components
        ) if exploded_components else 0.0
        
        return ExplodedView(
            components=exploded_components,
            center_of_mass=com,
            bounding_box=bbox,
            total_explosion_distance=max_distance
        )
    
    def _get_components(self, document: Any) -> List[Tuple[str, Any, List[float]]]:
        """
        Get all components from document.
        
        Returns:
            List of (id, object, position) tuples
        """
        components = []
        
        for obj in document.Objects:
            if hasattr(obj, 'Shape') and obj.Shape and not obj.Shape.isNull():
                # Get position
                if hasattr(obj, 'Placement'):
                    pos = obj.Placement.Base
                    position = [pos.x, pos.y, pos.z]
                else:
                    position = [0.0, 0.0, 0.0]
                
                # Use Label as ID
                comp_id = obj.Label if hasattr(obj, 'Label') else str(id(obj))
                
                components.append((comp_id, obj, position))
        
        return components
    
    def _calculate_center_of_mass(
        self,
        components: List[Tuple[str, Any, List[float]]]
    ) -> List[float]:
        """Calculate assembly center of mass."""
        if not components:
            return [0.0, 0.0, 0.0]
        
        total_mass = 0.0
        weighted_sum = [0.0, 0.0, 0.0]
        
        for comp_id, obj, pos in components:
            if hasattr(obj, 'Shape') and obj.Shape:
                try:
                    # Use volume as proxy for mass
                    volume = obj.Shape.Volume
                    if volume > 0:
                        # Get component COM
                        shape_com = obj.Shape.CenterOfMass
                        comp_com = [
                            pos[0] + shape_com.x,
                            pos[1] + shape_com.y,
                            pos[2] + shape_com.z
                        ]
                        
                        # Add to weighted sum
                        for i in range(3):
                            weighted_sum[i] += comp_com[i] * volume
                        total_mass += volume
                except Exception as e:
                    logger.debug(f"Could not calculate COM for {comp_id}: {e}")
        
        if total_mass > 0:
            return [weighted_sum[i] / total_mass for i in range(3)]
        else:
            # Fallback to geometric center
            center = [0.0, 0.0, 0.0]
            for _, _, pos in components:
                for i in range(3):
                    center[i] += pos[i]
            return [center[i] / len(components) for i in range(3)]
    
    def _calculate_bounding_box(
        self,
        components: List[Tuple[str, Any, List[float]]]
    ) -> Dict[str, float]:
        """Calculate assembly bounding box."""
        if not components:
            return {"x": 0, "y": 0, "z": 0}
        
        min_pt = [float('inf')] * 3
        max_pt = [float('-inf')] * 3
        
        for comp_id, obj, pos in components:
            if hasattr(obj, 'Shape') and obj.Shape:
                try:
                    bbox = obj.Shape.BoundBox
                    comp_min = [
                        pos[0] + bbox.XMin,
                        pos[1] + bbox.YMin,
                        pos[2] + bbox.ZMin
                    ]
                    comp_max = [
                        pos[0] + bbox.XMax,
                        pos[1] + bbox.YMax,
                        pos[2] + bbox.ZMax
                    ]
                    
                    for i in range(3):
                        min_pt[i] = min(min_pt[i], comp_min[i])
                        max_pt[i] = max(max_pt[i], comp_max[i])
                except Exception as e:
                    logger.debug(f"Could not get bbox for {comp_id}: {e}")
        
        return {
            "x": max_pt[0] - min_pt[0],
            "y": max_pt[1] - min_pt[1],
            "z": max_pt[2] - min_pt[2]
        }
    
    def _apply_manual_offsets(
        self,
        components: List[Tuple[str, Any, List[float]]],
        manual_offsets: Dict[str, List[float]]
    ) -> List[ExplodedComponent]:
        """Apply manual offset vectors to components."""
        exploded = []
        
        for comp_id, obj, pos in components:
            offset = manual_offsets.get(comp_id, [0.0, 0.0, 0.0])
            
            exploded_pos = [pos[i] + offset[i] for i in range(3)]
            distance = math.sqrt(sum(offset[i]**2 for i in range(3)))
            
            exploded.append(ExplodedComponent(
                component_id=comp_id,
                original_position=pos,
                exploded_position=exploded_pos,
                offset_vector=offset,
                explosion_distance=distance
            ))
        
        return exploded
    
    def _generate_auto_explosion(
        self,
        components: List[Tuple[str, Any, List[float]]],
        com: List[float],
        bbox: Dict[str, float],
        config: ExplodedViewConfig
    ) -> List[ExplodedComponent]:
        """Generate automatic explosion offsets."""
        exploded = []
        
        # Calculate explosion scale based on bounding box
        max_dim = max(bbox.values())
        base_explosion = max_dim * config.explosion_factor * 0.3
        
        for comp_id, obj, pos in components:
            if config.radial_mode:
                # Radial explosion from COM
                offset = self._calculate_radial_offset(
                    pos, com, base_explosion
                )
            else:
                # Directional explosion (e.g., along Z axis)
                offset = self._calculate_directional_offset(
                    comp_id, components, base_explosion
                )
            
            exploded_pos = [pos[i] + offset[i] for i in range(3)]
            distance = math.sqrt(sum(offset[i]**2 for i in range(3)))
            
            # Check for collisions if enabled
            if config.avoid_collisions:
                exploded_pos = self._adjust_for_collisions(
                    comp_id, obj, exploded_pos, exploded, components
                )
                # Recalculate offset after adjustment
                offset = [exploded_pos[i] - pos[i] for i in range(3)]
                distance = math.sqrt(sum(offset[i]**2 for i in range(3)))
            
            exploded.append(ExplodedComponent(
                component_id=comp_id,
                original_position=pos,
                exploded_position=exploded_pos,
                offset_vector=offset,
                explosion_distance=distance
            ))
        
        return exploded
    
    def _calculate_radial_offset(
        self,
        position: List[float],
        center: List[float],
        base_distance: float
    ) -> List[float]:
        """Calculate radial offset from center."""
        # Vector from center to component
        direction = [position[i] - center[i] for i in range(3)]
        
        # Normalize direction
        length = math.sqrt(sum(d**2 for d in direction))
        if length < MIN_DIRECTION_LENGTH:  # Component at center
            # Use default upward direction
            direction = [0.0, 0.0, DEFAULT_UPWARD_DISTANCE]
            length = DEFAULT_UPWARD_DISTANCE
        
        normalized = [d / length for d in direction]
        
        # Apply explosion distance
        offset = [normalized[i] * base_distance for i in range(3)]
        
        return offset
    
    def _calculate_directional_offset(
        self,
        comp_id: str,
        components: List[Tuple[str, Any, List[float]]],
        base_distance: float
    ) -> List[float]:
        """Calculate directional offset (e.g., vertical explosion)."""
        # Simple vertical explosion with different levels
        comp_index = next(
            (i for i, (cid, _, _) in enumerate(components) if cid == comp_id),
            0
        )
        
        # Stack components vertically
        z_offset = base_distance * (comp_index + 1)
        
        return [0.0, 0.0, z_offset]
    
    def _adjust_for_collisions(
        self,
        comp_id: str,
        obj: Any,
        exploded_pos: List[float],
        already_exploded: List[ExplodedComponent],
        all_components: List[Tuple[str, Any, List[float]]]
    ) -> List[float]:
        """Adjust position to avoid collisions with other exploded components using BVH-based collision detection."""
        from .collision import CollisionDetector
        
        if not hasattr(obj, 'Shape') or not obj.Shape:
            return exploded_pos
        
        try:
            # Initialize collision detector
            detector = CollisionDetector()
            
            # Create lookup dictionary once for O(1) access to avoid O(N²) performance issue
            # This optimization prevents recreating the dictionary on every collision check
            component_lookup = {cid: component_obj for cid, component_obj, _ in all_components}
            
            # Build list of transformed shapes for collision detection
            import FreeCAD
            shapes = []
            
            # Add current object transformed to proposed position
            current_shape = obj.Shape.copy()
            current_placement = FreeCAD.Placement(
                FreeCAD.Vector(exploded_pos[0], exploded_pos[1], exploded_pos[2]),
                FreeCAD.Rotation()
            )
            current_shape.transformShape(current_placement.toMatrix())
            shapes.append((comp_id, current_shape))
            
            # Add already exploded components transformed to their positions
            # Since ExplodedComponent doesn't have a 'shape' attribute, retrieve the shape from the original component
            for other in already_exploded:
                # Use O(1) lookup instead of O(N) linear search
                orig_obj = component_lookup.get(other.component_id)
                if orig_obj and hasattr(orig_obj, 'Shape') and orig_obj.Shape:
                    # Transform shape to exploded position
                    transformed_shape = orig_obj.Shape.copy()
                    placement = FreeCAD.Placement(
                        FreeCAD.Vector(other.exploded_position[0], other.exploded_position[1], other.exploded_position[2]),
                        FreeCAD.Rotation()
                    )
                    transformed_shape.transformShape(placement.toMatrix())
                    shapes.append((other.component_id, transformed_shape))
            
            # Detect collisions using BVH-based detector with transformed shapes
            collisions = detector.detect_collisions(shapes)
            
            # If collisions detected with current component, adjust position
            current_collisions = [c for c in collisions if comp_id in [c.object_a, c.object_b]]
            
            if current_collisions:
                # Calculate adjustment based on collision volume
                bbox = obj.Shape.BoundBox
                size = max(bbox.XLength, bbox.YLength, bbox.ZLength)
                
                # Apply additional separation to avoid collision
                # Calculate minimum separation based on current object size
                min_separation = size * self.COLLISION_AVOIDANCE_FACTOR
                
                for collision in current_collisions:
                    # Get the other object in collision
                    other_id = collision.object_b if collision.object_a == comp_id else collision.object_a
                    
                    # Find the other component's position and size
                    for other in already_exploded:
                        if other.component_id == other_id:
                            # Get the other object's size from the lookup
                            other_obj = component_lookup.get(other_id)
                            if other_obj and hasattr(other_obj, 'Shape') and other_obj.Shape:
                                other_bbox = other_obj.Shape.BoundBox
                                other_size = max(other_bbox.XLength, other_bbox.YLength, other_bbox.ZLength)
                                
                                # Calculate minimum separation based on BOTH objects' sizes
                                # This ensures adequate clearance considering dimensions of both colliding objects
                                combined_min_separation = (size + other_size) / 2 * self.COLLISION_AVOIDANCE_FACTOR
                            else:
                                # Fallback to single object size if other object size unavailable
                                combined_min_separation = min_separation
                            
                            # Calculate direction vector away from collision
                            direction = [
                                exploded_pos[i] - other.exploded_position[i]
                                for i in range(3)
                            ]
                            
                            # Normalize and apply combined minimum separation
                            distance = math.sqrt(sum(d**2 for d in direction))
                            if distance > 0:
                                factor = combined_min_separation / distance
                                exploded_pos = [
                                    exploded_pos[i] + direction[i] * factor
                                    for i in range(3)
                                ]
                            break
            
            return exploded_pos
            
        except ImportError:
            # Fallback to simplified distance-based check if CollisionDetector not available
            logger.warning("CollisionDetector not available, using simplified collision avoidance")
            
            bbox = obj.Shape.BoundBox
            size = max(bbox.XLength, bbox.YLength, bbox.ZLength)
            
            # Check distance to other exploded components
            # Initial minimum separation based on current object size
            min_separation = size * self.COLLISION_AVOIDANCE_FACTOR
            
            # Get component lookup for size retrieval
            component_lookup = {cid: component_obj for cid, component_obj, _ in all_components}
            
            for other in already_exploded:
                # Get the other object's size
                other_obj = component_lookup.get(other.component_id)
                if other_obj and hasattr(other_obj, 'Shape') and other_obj.Shape:
                    other_bbox = other_obj.Shape.BoundBox
                    other_size = max(other_bbox.XLength, other_bbox.YLength, other_bbox.ZLength)
                    
                    # Calculate minimum separation based on BOTH objects' sizes
                    # This provides proper clearance considering both colliding objects
                    combined_min_separation = (size + other_size) / 2 * self.COLLISION_AVOIDANCE_FACTOR
                else:
                    # Fallback to single object size if other size unavailable
                    combined_min_separation = min_separation
                
                distance = math.sqrt(
                    sum((exploded_pos[i] - other.exploded_position[i])**2 for i in range(3))
                )
                
                if distance < combined_min_separation:
                    # Push further away
                    direction = [
                        exploded_pos[i] - other.exploded_position[i]
                        for i in range(3)
                    ]
                    
                    # Normalize
                    dir_length = math.sqrt(sum(d**2 for d in direction))
                    if dir_length > 0.001:
                        normalized = [d / dir_length for d in direction]
                        adjustment = [
                            normalized[i] * (combined_min_separation - distance)
                            for i in range(3)
                        ]
                        exploded_pos = [
                            exploded_pos[i] + adjustment[i]
                            for i in range(3)
                        ]
        except Exception as e:
            logger.warning(f"Collision adjustment failed for {comp_id}: {e}", exc_info=True)
        
        return exploded_pos
    
    def apply_exploded_view(
        self,
        document: Any,
        exploded_view: ExplodedView,
        create_group: bool = True
    ) -> Any:
        """
        Apply exploded view to document.
        
        Args:
            document: FreeCAD document
            exploded_view: Exploded view definition
            create_group: Whether to create a new group for exploded view
        
        Returns:
            Exploded view group or document
        """
        if not self._freecad_available:
            raise RuntimeError("FreeCAD is required to apply exploded view")
        
        import FreeCAD
        
        # Create exploded view group if requested
        if create_group:
            exploded_group = document.addObject(
                "App::DocumentObjectGroup",
                "ExplodedView"
            )
        else:
            exploded_group = document
        
        # Apply offsets to components
        for comp in exploded_view.components:
            obj = document.getObjectsByLabel(comp.component_id)
            if obj:
                obj = obj[0]  # Get first match
                
                # Clone object for exploded view if in group
                if create_group:
                    # Create link to original
                    link = document.addObject("App::Link", f"{comp.component_id}_Exploded")
                    link.LinkedObject = obj
                    exploded_group.addObject(link)
                    obj = link
                
                # Apply exploded position
                if hasattr(obj, 'Placement'):
                    import FreeCAD
                    obj.Placement.Base = FreeCAD.Vector(*comp.exploded_position)
        
        document.recompute()
        
        return exploded_group if create_group else document
    
    def export_exploded_snapshot(
        self,
        document: Any,
        exploded_view: ExplodedView,
        base_path: Path,
        formats: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Export snapshot of exploded view.
        
        Args:
            document: FreeCAD document
            exploded_view: Exploded view definition
            base_path: Base path for output files
            formats: Export formats (default: ["STEP", "GLB"])
        
        Returns:
            Export results
        """
        if formats is None:
            formats = ["STEP", "GLB"]
        
        # Apply exploded view temporarily
        original_positions = []
        
        # Save original positions
        for comp in exploded_view.components:
            obj = document.getObjectsByLabel(comp.component_id)
            if obj:
                obj = obj[0]
                if hasattr(obj, 'Placement'):
                    original_positions.append({
                        "id": comp.component_id,
                        "placement": obj.Placement.copy()
                    })
                    # Apply exploded position
                    import FreeCAD
                    obj.Placement.Base = FreeCAD.Vector(*comp.exploded_position)
        
        document.recompute()
        
        # Export using exporter module
        from .exporter import deterministic_exporter
        
        try:
            results = deterministic_exporter.export_all(
                document,
                base_path.with_stem(f"{base_path.stem}_exploded"),
                formats
            )
        finally:
            # Restore original positions
            for orig in original_positions:
                obj = document.getObjectsByLabel(orig["id"])
                if obj:
                    obj[0].Placement = orig["placement"]
            document.recompute()
        
        return results


# Global exploded view generator instance
exploded_view_generator = ExplodedViewGenerator()