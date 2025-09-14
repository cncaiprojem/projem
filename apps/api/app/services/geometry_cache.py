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
        
        # Add basic properties with locale-independent formatting
        hasher.update(f"{shape.Volume:.8f}".encode())
        hasher.update(f"{shape.Area:.8f}".encode())
        hasher.update(f"{shape.Mass:.8f}".encode())
        
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
    
    Implements LRU caching with configurable size limits using compute function pattern.
    """
    
    def __init__(self, cache_size: int = GEOMETRY_CACHE_SIZE):
        self.cache_size = cache_size
        self._volume_cache = OrderedDict()
        self._area_cache = OrderedDict()
        self._mass_cache = OrderedDict()
        self._thickness_cache = OrderedDict()
        self._intersection_cache = OrderedDict()
        self._continuity_cache = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0
    
    def get_or_compute_volume(self, shape: Any, compute_func: Any = None) -> float:
        """Get cached volume or compute if not available."""
        shape_hash = geometry_hash(shape)
        
        if shape_hash in self._volume_cache:
            self._cache_hits += 1
            self._volume_cache.move_to_end(shape_hash)  # LRU update
            return self._volume_cache[shape_hash]
        
        self._cache_misses += 1
        
        # Compute volume
        if compute_func:
            volume = compute_func(shape)
        else:
            # Default computation using FreeCAD shape properties
            volume = shape.Volume if hasattr(shape, 'Volume') else 0.0
        
        # Store in cache with size limit
        if len(self._volume_cache) >= self.cache_size:
            self._volume_cache.popitem(last=False)  # Remove oldest
        
        self._volume_cache[shape_hash] = volume
        return volume
    
    def get_or_compute_area(self, shape: Any, compute_func: Any = None) -> float:
        """Get cached surface area or compute if not available."""
        shape_hash = geometry_hash(shape)
        
        if shape_hash in self._area_cache:
            self._cache_hits += 1
            self._area_cache.move_to_end(shape_hash)  # LRU update
            return self._area_cache[shape_hash]
        
        self._cache_misses += 1
        
        # Compute area
        if compute_func:
            area = compute_func(shape)
        else:
            # Default computation using FreeCAD shape properties
            area = shape.Area if hasattr(shape, 'Area') else 0.0
        
        # Store in cache with size limit
        if len(self._area_cache) >= self.cache_size:
            self._area_cache.popitem(last=False)  # Remove oldest
        
        self._area_cache[shape_hash] = area
        return area
    
    def get_or_compute_mass(
        self, 
        shape: Any, 
        density: float = 1.0, 
        compute_func: Any = None
    ) -> float:
        """Get cached mass or compute if not available."""
        shape_hash = geometry_hash(shape)
        cache_key = f"{shape_hash}_{density}"
        
        if cache_key in self._mass_cache:
            self._cache_hits += 1
            self._mass_cache.move_to_end(cache_key)  # LRU update
            return self._mass_cache[cache_key]
        
        self._cache_misses += 1
        
        # Compute mass
        if compute_func:
            mass = compute_func(shape, density)
        else:
            # Default computation: volume * density
            volume = self.get_or_compute_volume(shape)
            mass = volume * density
        
        # Store in cache with size limit
        if len(self._mass_cache) >= self.cache_size:
            self._mass_cache.popitem(last=False)  # Remove oldest
        
        self._mass_cache[cache_key] = mass
        return mass
    
    def get_or_compute_wall_thickness(
        self,
        shape: Any,
        point: Tuple[float, float, float],
        compute_func: Any
    ) -> float:
        """Get cached wall thickness or compute if not available."""
        shape_hash = geometry_hash(shape)
        cache_key = f"{shape_hash}_{point[0]:.3f}_{point[1]:.3f}_{point[2]:.3f}"
        
        if cache_key in self._thickness_cache:
            self._cache_hits += 1
            self._thickness_cache.move_to_end(cache_key)  # LRU update
            return self._thickness_cache[cache_key]
        
        self._cache_misses += 1
        
        # Compute thickness (must provide compute function)
        if not compute_func:
            logger.warning("No compute function provided for wall thickness")
            return 0.0
            
        thickness = compute_func(shape, point)
        
        # Store in cache with size limit
        if len(self._thickness_cache) >= THICKNESS_CACHE_SIZE:
            self._thickness_cache.popitem(last=False)  # Remove oldest
        
        self._thickness_cache[cache_key] = thickness
        return thickness
    
    def check_or_compute_intersection(
        self,
        face1: Any,
        face2: Any,
        tolerance: float = 0.001,
        compute_func: Any = None
    ) -> bool:
        """Check cached face intersection or compute if not available."""
        hash1 = geometry_hash(face1)
        hash2 = geometry_hash(face2)
        cache_key = f"{min(hash1, hash2)}_{max(hash1, hash2)}_{tolerance}"
        
        if cache_key in self._intersection_cache:
            self._cache_hits += 1
            self._intersection_cache.move_to_end(cache_key)  # LRU update
            return self._intersection_cache[cache_key]
        
        self._cache_misses += 1
        
        # Compute intersection
        if compute_func:
            intersects = compute_func(face1, face2, tolerance)
        else:
            # Default: check if faces share common area
            try:
                common = face1.common(face2)
                intersects = common.Area > tolerance if hasattr(common, 'Area') else False
            except Exception:
                intersects = False
        
        # Store in cache with size limit
        if len(self._intersection_cache) >= INTERSECTION_CACHE_SIZE:
            self._intersection_cache.popitem(last=False)  # Remove oldest
        
        self._intersection_cache[cache_key] = intersects
        return intersects
    
    def check_or_compute_edge_continuity(
        self,
        edge: Any,
        tolerance: float = 0.001,
        compute_func: Any = None
    ) -> bool:
        """Check cached edge continuity or compute if not available."""
        edge_hash = geometry_hash(edge)
        cache_key = f"{edge_hash}_{tolerance}"
        
        if cache_key in self._continuity_cache:
            self._cache_hits += 1
            self._continuity_cache.move_to_end(cache_key)  # LRU update
            return self._continuity_cache[cache_key]
        
        self._cache_misses += 1
        
        # Compute continuity
        if compute_func:
            is_continuous = compute_func(edge, tolerance)
        else:
            # Default: check if edge is closed
            try:
                is_continuous = edge.isClosed() if hasattr(edge, 'isClosed') else True
            except Exception:
                is_continuous = True
        
        # Store in cache with size limit
        if len(self._continuity_cache) >= self.cache_size:
            self._continuity_cache.popitem(last=False)  # Remove oldest
        
        self._continuity_cache[cache_key] = is_continuous
        return is_continuous
    
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
        self._volume_cache.clear()
        self._area_cache.clear()
        self._mass_cache.clear()
        self._thickness_cache.clear()
        self._intersection_cache.clear()
        self._continuity_cache.clear()
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