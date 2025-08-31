"""
Collision Detection for Task 7.6

Provides collision detection functionality:
- AABB (Axis-Aligned Bounding Box) broad phase with BVH
- BRepAlgoAPI narrow phase for accurate collision
- Collision volume and contact point calculation
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ...core.logging import get_logger

logger = get_logger(__name__)


class AABB(BaseModel):
    """Axis-aligned bounding box."""
    min_point: List[float] = Field(description="Minimum corner [x, y, z]")
    max_point: List[float] = Field(description="Maximum corner [x, y, z]")
    
    def overlaps(self, other: "AABB") -> bool:
        """Check if this AABB overlaps with another."""
        for i in range(3):
            if self.max_point[i] < other.min_point[i] or self.min_point[i] > other.max_point[i]:
                return False
        return True
    
    def expand(self, margin: float):
        """Expand AABB by margin in all directions."""
        for i in range(3):
            self.min_point[i] -= margin
            self.max_point[i] += margin


class CollisionPair(BaseModel):
    """Collision between two objects."""
    object_a: str = Field(description="First object ID")
    object_b: str = Field(description="Second object ID")
    collision_volume: float = Field(description="Intersection volume in mm³")
    contact_bbox: Optional[AABB] = Field(default=None, description="Contact region bounding box")
    contact_points: List[List[float]] = Field(default_factory=list, description="Contact points")


class BVHNode:
    """Bounding Volume Hierarchy node for spatial partitioning."""
    
    def __init__(self, objects: List[Tuple[str, Any, AABB]]):
        """
        Initialize BVH node.
        
        Args:
            objects: List of (id, shape, aabb) tuples
        """
        self.objects = objects
        self.aabb = self._compute_aabb(objects)
        self.left = None
        self.right = None
        
        # Split if more than threshold objects
        if len(objects) > 2:
            self._split()
    
    def _compute_aabb(self, objects: List[Tuple[str, Any, AABB]]) -> AABB:
        """Compute combined AABB for all objects."""
        if not objects:
            return AABB(min_point=[0, 0, 0], max_point=[0, 0, 0])
        
        min_pt = list(objects[0][2].min_point)
        max_pt = list(objects[0][2].max_point)
        
        for _, _, aabb in objects[1:]:
            for i in range(3):
                min_pt[i] = min(min_pt[i], aabb.min_point[i])
                max_pt[i] = max(max_pt[i], aabb.max_point[i])
        
        return AABB(min_point=min_pt, max_point=max_pt)
    
    def _split(self):
        """Split node into two children."""
        # Find longest axis
        extent = [
            self.aabb.max_point[i] - self.aabb.min_point[i]
            for i in range(3)
        ]
        split_axis = extent.index(max(extent))
        
        # Sort objects by center along split axis
        sorted_objects = sorted(
            self.objects,
            key=lambda obj: (obj[2].min_point[split_axis] + obj[2].max_point[split_axis]) / 2
        )
        
        # Split the sorted objects for recursion
        # Note: We're guaranteed to have > 2 objects here due to check at line 66
        mid = len(sorted_objects) // 2
        self.left = BVHNode(sorted_objects[:mid])
        self.right = BVHNode(sorted_objects[mid:])
        self.objects = []  # Clear objects in internal nodes
    
    def get_potential_collisions(self, query_aabb: AABB) -> List[Tuple[str, Any, AABB]]:
        """Get objects that potentially collide with query AABB."""
        if not self.aabb.overlaps(query_aabb):
            return []
        
        # Leaf node: return objects
        if not self.left and not self.right:
            return [
                obj for obj in self.objects
                if obj[2].overlaps(query_aabb)
            ]
        
        # Internal node: recurse
        results = []
        if self.left:
            results.extend(self.left.get_potential_collisions(query_aabb))
        if self.right:
            results.extend(self.right.get_potential_collisions(query_aabb))
        
        return results


class CollisionDetector:
    """Detect collisions between FreeCAD shapes."""
    
    def __init__(self, collision_threshold: float = 1e-6):
        """
        Initialize collision detector.
        
        Args:
            collision_threshold: Minimum volume for collision (mm³)
        """
        self.collision_threshold = collision_threshold
        self._freecad_available = self._check_freecad()
    
    def _check_freecad(self) -> bool:
        """Check if FreeCAD is available."""
        try:
            import FreeCAD
            import Part
            return True
        except ImportError:
            logger.warning("FreeCAD not available for collision detection")
            return False
    
    def detect_collisions(
        self,
        shapes: List[Tuple[str, Any]],
        use_bvh: bool = True
    ) -> List[CollisionPair]:
        """
        Detect collisions between shapes.
        
        Args:
            shapes: List of (id, shape) tuples
            use_bvh: Whether to use BVH for broad phase
        
        Returns:
            List of collision pairs
        """
        if not self._freecad_available:
            logger.error("FreeCAD required for collision detection")
            return []
        
        import Part
        
        collisions = []
        
        # Compute AABBs for all shapes
        shape_data = []
        for obj_id, shape in shapes:
            if shape and not shape.isNull():
                aabb = self._compute_aabb(shape)
                shape_data.append((obj_id, shape, aabb))
        
        if not shape_data:
            return []
        
        if use_bvh and len(shape_data) > 10:
            # Use BVH for broad phase when many objects
            collisions = self._detect_with_bvh(shape_data)
        else:
            # Brute force for small numbers
            collisions = self._detect_brute_force(shape_data)
        
        return collisions
    
    def _compute_aabb(self, shape: Any) -> AABB:
        """Compute AABB for a shape."""
        bbox = shape.BoundBox
        return AABB(
            min_point=[bbox.XMin, bbox.YMin, bbox.ZMin],
            max_point=[bbox.XMax, bbox.YMax, bbox.ZMax]
        )
    
    def _detect_with_bvh(self, shape_data: List[Tuple[str, Any, AABB]]) -> List[CollisionPair]:
        """Detect collisions using BVH acceleration."""
        # Build BVH
        bvh = BVHNode(shape_data)
        
        collisions = []
        checked_pairs = set()
        
        # Check each object against BVH
        for i, (id_a, shape_a, aabb_a) in enumerate(shape_data):
            # Get potential collisions from BVH
            candidates = bvh.get_potential_collisions(aabb_a)
            
            for id_b, shape_b, aabb_b in candidates:
                if id_a == id_b:
                    continue
                
                # Skip if already checked
                pair_key = tuple(sorted([id_a, id_b]))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                
                # Narrow phase collision check
                collision = self._check_narrow_phase(
                    id_a, shape_a,
                    id_b, shape_b
                )
                
                if collision:
                    collisions.append(collision)
        
        return collisions
    
    def _detect_brute_force(self, shape_data: List[Tuple[str, Any, AABB]]) -> List[CollisionPair]:
        """Detect collisions using brute force O(n²) approach."""
        collisions = []
        
        for i in range(len(shape_data)):
            id_a, shape_a, aabb_a = shape_data[i]
            
            for j in range(i + 1, len(shape_data)):
                id_b, shape_b, aabb_b = shape_data[j]
                
                # Broad phase: check AABB overlap
                if not aabb_a.overlaps(aabb_b):
                    continue
                
                # Narrow phase: accurate collision check
                collision = self._check_narrow_phase(
                    id_a, shape_a,
                    id_b, shape_b
                )
                
                if collision:
                    collisions.append(collision)
        
        return collisions
    
    def _check_narrow_phase(
        self,
        id_a: str, shape_a: Any,
        id_b: str, shape_b: Any
    ) -> Optional[CollisionPair]:
        """
        Perform accurate collision check using BRepAlgoAPI.
        
        Args:
            id_a: First object ID
            shape_a: First shape
            id_b: Second object ID
            shape_b: Second shape
        
        Returns:
            CollisionPair if collision detected, None otherwise
        """
        try:
            import Part
            
            # Compute intersection using BRepAlgoAPI_Common
            intersection = shape_a.common(shape_b)
            
            if intersection.isNull():
                return None
            
            # Check volume
            volume = intersection.Volume
            if volume < self.collision_threshold:
                return None
            
            # Get contact information
            contact_bbox = self._compute_aabb(intersection)
            
            # Sample contact points (simplified)
            contact_points = []
            if intersection.Vertexes:
                for vertex in intersection.Vertexes[:10]:  # Limit to 10 points
                    contact_points.append([
                        vertex.Point.x,
                        vertex.Point.y,
                        vertex.Point.z
                    ])
            
            return CollisionPair(
                object_a=id_a,
                object_b=id_b,
                collision_volume=volume,
                contact_bbox=contact_bbox,
                contact_points=contact_points
            )
            
        except Exception as e:
            logger.debug(f"Narrow phase collision check failed: {e}")
            return None
    
    def check_clearance(
        self,
        shapes: List[Tuple[str, Any]],
        min_clearance: float = 1.0
    ) -> List[Dict[str, Any]]:
        """
        Check minimum clearance between shapes.
        
        Args:
            shapes: List of (id, shape) tuples
            min_clearance: Minimum required clearance in mm
        
        Returns:
            List of clearance violations
        """
        violations = []
        
        for i in range(len(shapes)):
            id_a, shape_a = shapes[i]
            
            for j in range(i + 1, len(shapes)):
                id_b, shape_b = shapes[j]
                
                try:
                    # Compute distance between shapes
                    dist_result = shape_a.distToShape(shape_b)
                    if isinstance(dist_result, tuple) and len(dist_result) > 0:
                        distance = dist_result[0]
                        
                        if distance < min_clearance:
                            violations.append({
                                "object_a": id_a,
                                "object_b": id_b,
                                "distance": distance,
                                "required": min_clearance,
                                "violation": min_clearance - distance
                            })
                except Exception as e:
                    logger.debug(f"Clearance check failed for {id_a}-{id_b}: {e}")
        
        return violations
    
    def compute_penetration_depth(
        self,
        shape_a: Any,
        shape_b: Any
    ) -> float:
        """
        Compute penetration depth between two colliding shapes.
        
        Args:
            shape_a: First shape
            shape_b: Second shape
        
        Returns:
            Maximum penetration depth in mm
        """
        try:
            # Compute intersection
            intersection = shape_a.common(shape_b)
            
            if intersection.isNull():
                return 0.0
            
            # Estimate penetration depth from intersection bounding box
            bbox = intersection.BoundBox
            depths = [
                bbox.XLength,
                bbox.YLength,
                bbox.ZLength
            ]
            
            return min(depths)  # Minimum dimension approximates penetration
            
        except Exception as e:
            logger.debug(f"Penetration depth calculation failed: {e}")
            return 0.0


# Global collision detector instance
collision_detector = CollisionDetector()