"""
Geometry Caching Module for FreeCAD Operations

Provides LRU caching for expensive geometric calculations to improve performance.
Based on FreeCAD's recommended caching patterns.
"""

from functools import lru_cache
from typing import Any, Tuple, Optional, Dict
from collections import OrderedDict
import hashlib
import json
from decimal import Decimal

from ..core.logging import get_logger

logger = get_logger(__name__)

# Cache configuration constants
GEOMETRY_CACHE_SIZE = 128  # Number of cached geometry results
THICKNESS_CACHE_SIZE = 256  # Number of cached thickness measurements
INTERSECTION_CACHE_SIZE = 512  # Number of cached intersection results
DEFAULT_CACHE_TTL = 3600  # Cache TTL in seconds (1 hour)


def geometry_hash(shape: Any) -> str:
    """
    Generate a hash for a FreeCAD shape object for caching.
    
    Uses shape properties that uniquely identify the geometry.
    """
    try:
        # Create a hash from shape properties
        hasher = hashlib.sha256()
        
        # Add basic properties
        hasher.update(str(shape.Volume).encode())
        hasher.update(str(shape.Area).encode())
        hasher.update(str(shape.Mass).encode())
        
        # Add bounding box
        bbox = shape.BoundBox
        hasher.update(f"{bbox.XMin},{bbox.YMin},{bbox.ZMin}".encode())
        hasher.update(f"{bbox.XMax},{bbox.YMax},{bbox.ZMax}".encode())
        
        # Add vertex count for uniqueness
        if hasattr(shape, 'Vertexes'):
            hasher.update(str(len(shape.Vertexes)).encode())
        
        return hasher.hexdigest()[:16]  # Use first 16 chars for efficiency
        
    except Exception as e:
        logger.warning(f"Failed to generate geometry hash: {e}")
        return str(id(shape))  # Fallback to object ID


class GeometryCache:
    """
    Caching layer for expensive geometric calculations.
    
    Implements LRU caching with configurable size limits.
    """
    
    def __init__(self, cache_size: int = GEOMETRY_CACHE_SIZE):
        self.cache_size = cache_size
        self._cache_hits = 0
        self._cache_misses = 0
    
    @lru_cache(maxsize=GEOMETRY_CACHE_SIZE)
    def get_volume(self, shape_hash: str) -> Optional[float]:
        """Cache volume calculations."""
        return None  # Will be overridden by actual calculation
    
    @lru_cache(maxsize=GEOMETRY_CACHE_SIZE)
    def get_area(self, shape_hash: str) -> Optional[float]:
        """Cache surface area calculations."""
        return None  # Will be overridden by actual calculation
    
    @lru_cache(maxsize=GEOMETRY_CACHE_SIZE)
    def get_mass(self, shape_hash: str, density: float = 1.0) -> Optional[float]:
        """Cache mass calculations with density."""
        return None  # Will be overridden by actual calculation
    
    @lru_cache(maxsize=THICKNESS_CACHE_SIZE)
    def get_wall_thickness(
        self, 
        shape_hash: str, 
        point_x: float, 
        point_y: float, 
        point_z: float
    ) -> Optional[float]:
        """Cache wall thickness measurements at specific points."""
        return None  # Will be overridden by actual calculation
    
    @lru_cache(maxsize=INTERSECTION_CACHE_SIZE)
    def get_face_intersection(
        self,
        face1_hash: str,
        face2_hash: str,
        tolerance: float = 0.001
    ) -> bool:
        """Cache face intersection results."""
        return None  # Will be overridden by actual calculation
    
    @lru_cache(maxsize=GEOMETRY_CACHE_SIZE)
    def get_edge_continuity(
        self,
        edge_hash: str,
        tolerance: float = 0.001
    ) -> bool:
        """Cache edge continuity check results."""
        return None  # Will be overridden by actual calculation
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": self._cache_hits / max(1, self._cache_hits + self._cache_misses),
            "size": self.cache_size
        }
    
    def clear(self):
        """Clear all caches."""
        self.get_volume.cache_clear()
        self.get_area.cache_clear()
        self.get_mass.cache_clear()
        self.get_wall_thickness.cache_clear()
        self.get_face_intersection.cache_clear()
        self.get_edge_continuity.cache_clear()
        self._cache_hits = 0
        self._cache_misses = 0


class WallThicknessCache:
    """
    Specialized cache for wall thickness analysis.
    
    Caches thickness measurements to avoid repeated ray casting.
    """
    
    def __init__(self, cache_size: int = THICKNESS_CACHE_SIZE):
        self._cache = OrderedDict()
        self._max_size = cache_size
    
    def get_or_compute(
        self,
        shape: Any,
        point: Tuple[float, float, float],
        compute_func: Any
    ) -> float:
        """
        Get cached thickness or compute if not in cache.
        
        Args:
            shape: FreeCAD shape object
            point: 3D point coordinates
            compute_func: Function to compute thickness if not cached
        
        Returns:
            Wall thickness at the point
        """
        # Generate cache key
        shape_hash = geometry_hash(shape)
        cache_key = f"{shape_hash}_{point[0]:.3f}_{point[1]:.3f}_{point[2]:.3f}"
        
        # Check cache
        if cache_key in self._cache:
            logger.debug(f"Wall thickness cache hit for {cache_key}")
            # Move to end (most recently used) for LRU
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]
        
        # Compute if not in cache
        thickness = compute_func(shape, point)
        
        # Store in cache (with size limit)
        if len(self._cache) >= self._max_size:
            # Remove least recently used (first item) for proper LRU
            self._cache.popitem(last=False)
        
        self._cache[cache_key] = thickness
        logger.debug(f"Wall thickness computed and cached for {cache_key}")
        
        return thickness
    
    def clear(self):
        """Clear the cache."""
        self._cache.clear()


class FaceIntersectionCache:
    """
    Cache for face intersection checks.
    
    Speeds up topology validation by caching intersection results.
    """
    
    def __init__(self, cache_size: int = INTERSECTION_CACHE_SIZE):
        self._cache = OrderedDict()
        self._max_size = cache_size
    
    def check_intersection(
        self,
        face1: Any,
        face2: Any,
        compute_func: Any,
        tolerance: float = 0.001
    ) -> bool:
        """
        Check if two faces intersect, using cache if available.
        
        Args:
            face1: First face
            face2: Second face
            compute_func: Function to compute intersection
            tolerance: Intersection tolerance
        
        Returns:
            True if faces intersect
        """
        # Generate cache key (order-independent)
        hash1 = geometry_hash(face1)
        hash2 = geometry_hash(face2)
        cache_key = f"{min(hash1, hash2)}_{max(hash1, hash2)}_{tolerance}"
        
        # Check cache
        if cache_key in self._cache:
            logger.debug(f"Face intersection cache hit")
            # Move to end (most recently used) for LRU
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]
        
        # Compute if not in cache
        intersects = compute_func(face1, face2, tolerance)
        
        # Store in cache
        if len(self._cache) >= self._max_size:
            # Remove least recently used (first item) for proper LRU
            self._cache.popitem(last=False)
        
        self._cache[cache_key] = intersects
        
        return intersects
    
    def clear(self):
        """Clear the cache."""
        self._cache.clear()


# Global cache instances
geometry_cache = GeometryCache()
wall_thickness_cache = WallThicknessCache()
face_intersection_cache = FaceIntersectionCache()


def clear_all_caches():
    """Clear all geometry caches."""
    geometry_cache.clear()
    wall_thickness_cache.clear()
    face_intersection_cache.clear()
    logger.info("All geometry caches cleared")