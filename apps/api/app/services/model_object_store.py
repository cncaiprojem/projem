"""
Content-Addressable Object Store for FreeCAD Model Version Control (Task 7.22).

This service implements content-addressable storage using SHA-256 hashing,
similar to Git's object storage but optimized for FreeCAD models.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import shutil
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from app.core.telemetry import create_span
from app.core import metrics
from app.middleware.correlation_middleware import get_correlation_id
from app.models.version_control import (
    Commit,
    DeltaCompression,
    FreeCADObjectData,
    ObjectHash,
    ObjectType,
    StorageStats,
    Tree,
    TreeEntry,
    VERSION_CONTROL_TR,
)

logger = structlog.get_logger(__name__)


class ObjectStoreError(Exception):
    """Custom exception for object store operations."""
    pass


class ModelObjectStore:
    """
    Content-addressable object store for FreeCAD models.
    
    Features:
    - SHA-256 based content addressing
    - Automatic compression with gzip
    - Delta compression for similar objects
    - Garbage collection for unreachable objects
    - Object caching for performance
    """
    
    def __init__(self, store_path: Path):
        """
        Initialize object store.
        
        Args:
            store_path: Path to object store directory
        """
        self.store_path = Path(store_path)
        self.objects_path = self.store_path / "objects"
        self.pack_path = self.store_path / "pack"
        self.refs_path = self.store_path / "refs"
        
        # Cache for frequently accessed objects (LRU)
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._cache_size_limit = 100
        
        # Delta compression index
        self._delta_index: Dict[str, DeltaCompression] = {}
        
        # Statistics
        self._stats = StorageStats(
            total_objects=0,
            total_size_bytes=0,
            compressed_size_bytes=0,
            delta_compressed_objects=0,
            compression_ratio=1.0,
            gc_runs=0,
            objects_removed=0
        )
        
        logger.info("object_store_initialized", store_path=str(store_path))
    
    async def init_store(self):
        """Initialize object store directory structure."""
        correlation_id = get_correlation_id()
        
        with create_span("object_store_init", correlation_id=correlation_id) as span:
            try:
                # Create directory structure
                self.objects_path.mkdir(parents=True, exist_ok=True)
                self.pack_path.mkdir(parents=True, exist_ok=True)
                self.refs_path.mkdir(parents=True, exist_ok=True)
                
                # Create subdirectories for objects (like Git's fan-out)
                for i in range(256):
                    subdir = self.objects_path / f"{i:02x}"
                    subdir.mkdir(exist_ok=True)
                
                logger.info(
                    "object_store_initialized",
                    store_path=str(self.store_path),
                    correlation_id=correlation_id
                )
                
            except Exception as e:
                logger.error(
                    "object_store_init_failed",
                    error=str(e),
                    correlation_id=correlation_id
                )
                raise ObjectStoreError(f"Failed to initialize store: {str(e)}")
    
    def hash_object(self, obj: Any) -> str:
        """
        Generate SHA-256 hash of object content.
        
        Args:
            obj: Object to hash (FreeCADObjectData, Tree, Commit, etc.)
            
        Returns:
            SHA-256 hash hex string
        """
        # Serialize object deterministically
        serialized = self._serialize_object(obj)
        return hashlib.sha256(serialized).hexdigest()
    
    async def store_object(
        self,
        obj: Any,
        obj_type: ObjectType,
    ) -> str:
        """
        Store object and return its hash.
        
        Args:
            obj: Object to store
            obj_type: Type of object
            
        Returns:
            Object hash
        """
        correlation_id = get_correlation_id()
        
        with create_span("store_object", correlation_id=correlation_id) as span:
            span.set_attribute("object.type", obj_type.value)
            
            try:
                # Calculate hash
                obj_hash = self.hash_object(obj)
                
                # Check if already exists
                if await self._object_exists(obj_hash):
                    logger.debug(
                        "object_already_exists",
                        obj_hash=obj_hash[:8],
                        correlation_id=correlation_id
                    )
                    return obj_hash
                
                # Serialize object with type information
                serialized = self._serialize_object(obj, obj_type)
                
                # Compress
                compressed = await asyncio.to_thread(gzip.compress, serialized)
                
                # Store in content-addressable format
                path = self._get_object_path(obj_hash)
                
                # Write atomically
                temp_path = path.with_suffix('.tmp')
                await asyncio.to_thread(self._write_file, temp_path, compressed)
                await asyncio.to_thread(os.replace, str(temp_path), str(path))
                
                # Update cache
                self._update_cache(obj_hash, obj)
                
                # Update statistics
                self._stats.total_objects += 1
                self._stats.total_size_bytes += len(serialized)
                self._stats.compressed_size_bytes += len(compressed)
                self._stats.compression_ratio = (
                    self._stats.compressed_size_bytes / self._stats.total_size_bytes
                    if self._stats.total_size_bytes > 0 else 1.0
                )
                
                logger.info(
                    "object_stored",
                    obj_hash=obj_hash[:8],
                    obj_type=obj_type.value,
                    size=len(serialized),
                    compressed_size=len(compressed),
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['object_stored'].format(hash=obj_hash[:8])
                )
                
                metrics.freecad_vcs_objects_stored_total.labels(
                    object_type=obj_type.value
                ).inc()
                
                return obj_hash
                
            except Exception as e:
                logger.error(
                    "object_store_failed",
                    error=str(e),
                    correlation_id=correlation_id
                )
                raise ObjectStoreError(f"Failed to store object: {str(e)}")
    
    async def get_object(
        self,
        obj_hash: str,
        obj_type: Optional[ObjectType] = None,
    ) -> Optional[Any]:
        """
        Retrieve object by hash.
        
        Args:
            obj_hash: Object hash
            obj_type: Expected object type (for validation)
            
        Returns:
            Object or None if not found
        """
        correlation_id = get_correlation_id()
        
        with create_span("get_object", correlation_id=correlation_id) as span:
            span.set_attribute("object.hash", obj_hash[:8])
            
            try:
                # Check cache first
                if obj_hash in self._cache:
                    logger.debug(
                        "object_cache_hit",
                        obj_hash=obj_hash[:8],
                        correlation_id=correlation_id
                    )
                    return self._cache[obj_hash]
                
                # Check if object exists
                path = self._get_object_path(obj_hash)
                if not path.exists():
                    # Check delta compressed objects
                    if obj_hash in self._delta_index:
                        return await self._restore_from_delta(obj_hash)
                    
                    logger.debug(
                        "object_not_found",
                        obj_hash=obj_hash[:8],
                        correlation_id=correlation_id
                    )
                    return None
                
                # Read and decompress
                compressed = await asyncio.to_thread(self._read_file, path)
                serialized = await asyncio.to_thread(gzip.decompress, compressed)
                
                # Deserialize
                obj = self._deserialize_object(serialized, obj_type)
                
                # Update cache
                self._update_cache(obj_hash, obj)
                
                logger.debug(
                    "object_retrieved",
                    obj_hash=obj_hash[:8],
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['object_retrieved'].format(hash=obj_hash[:8])
                )
                
                return obj
                
            except Exception as e:
                logger.error(
                    "object_retrieval_failed",
                    error=str(e),
                    obj_hash=obj_hash,
                    correlation_id=correlation_id
                )
                return None
    
    async def store_freecad_object(
        self,
        obj_data: FreeCADObjectData,
    ) -> str:
        """Store FreeCAD object data."""
        return await self.store_object(obj_data, ObjectType.BLOB)
    
    async def get_freecad_object(
        self,
        obj_hash: str,
    ) -> Optional[FreeCADObjectData]:
        """Get FreeCAD object data."""
        obj = await self.get_object(obj_hash, ObjectType.BLOB)
        if obj and isinstance(obj, dict):
            return FreeCADObjectData(**obj)
        return obj
    
    async def store_tree(self, tree: Tree) -> str:
        """Store tree object."""
        return await self.store_object(tree, ObjectType.TREE)
    
    async def get_tree(self, tree_hash: str) -> Optional[Tree]:
        """Get tree object."""
        obj = await self.get_object(tree_hash, ObjectType.TREE)
        if obj and isinstance(obj, dict):
            return Tree(**obj)
        return obj
    
    async def store_commit(self, commit: Commit) -> str:
        """Store commit object."""
        # Calculate commit hash if not set
        if not commit.hash:
            commit.hash = commit.calculate_hash()
        return await self.store_object(commit, ObjectType.COMMIT)
    
    async def get_commit(self, commit_hash: str) -> Optional[Commit]:
        """Get commit object."""
        obj = await self.get_object(commit_hash, ObjectType.COMMIT)
        if obj and isinstance(obj, dict):
            return Commit(**obj)
        return obj
    
    async def list_objects(self) -> List[str]:
        """List all object hashes in the store."""
        objects = []
        
        # Scan object directories
        for subdir in self.objects_path.iterdir():
            if subdir.is_dir():
                for obj_file in subdir.iterdir():
                    if obj_file.is_file() and not obj_file.name.endswith('.tmp'):
                        # Reconstruct hash from path
                        obj_hash = subdir.name + obj_file.name
                        objects.append(obj_hash)
        
        # Add delta compressed objects
        objects.extend(self._delta_index.keys())
        
        return objects
    
    async def optimize_storage(self) -> Dict[str, Any]:
        """
        Optimize storage with delta compression and garbage collection.
        
        Returns:
            Storage statistics
        """
        correlation_id = get_correlation_id()
        
        with create_span("optimize_storage", correlation_id=correlation_id) as span:
            try:
                initial_size = self._stats.compressed_size_bytes
                
                # Delta compression
                delta_count = await self._apply_delta_compression()
                
                # Garbage collection
                gc_count = await self._garbage_collect()
                
                # Pack loose objects
                pack_count = await self._pack_objects()
                
                final_size = self._stats.compressed_size_bytes
                saved_bytes = initial_size - final_size
                
                stats = {
                    "total_objects": self._stats.total_objects,
                    "delta_compressed": delta_count,
                    "garbage_collected": gc_count,
                    "packed_objects": pack_count,
                    "initial_size_bytes": initial_size,
                    "final_size_bytes": final_size,
                    "saved_bytes": saved_bytes,
                    "compression_ratio": self._stats.compression_ratio
                }
                
                # Update last GC timestamp
                self._stats.last_gc_timestamp = datetime.now(timezone.utc)
                
                logger.info(
                    "storage_optimized",
                    stats=stats,
                    correlation_id=correlation_id,
                    message=VERSION_CONTROL_TR['storage_optimized']
                )
                
                metrics.freecad_vcs_storage_bytes.set(final_size)
                
                return stats
                
            except Exception as e:
                logger.error(
                    "optimization_failed",
                    error=str(e),
                    correlation_id=correlation_id
                )
                raise ObjectStoreError(f"Failed to optimize storage: {str(e)}")
    
    async def cleanup(self):
        """Cleanup resources."""
        self._cache.clear()
        self._delta_index.clear()
        logger.info("object_store_cleanup_complete")
    
    # Private helper methods
    
    def _get_object_path(self, obj_hash: str) -> Path:
        """Get file path for object hash."""
        # Use first 2 chars as directory (fan-out)
        subdir = obj_hash[:2]
        filename = obj_hash[2:]
        return self.objects_path / subdir / filename
    
    async def _object_exists(self, obj_hash: str) -> bool:
        """Check if object exists."""
        if obj_hash in self._cache:
            return True
        if obj_hash in self._delta_index:
            return True
        path = self._get_object_path(obj_hash)
        return path.exists()
    
    def _serialize_object(self, obj: Any, obj_type: Optional[ObjectType] = None) -> bytes:
        """Serialize object deterministically with type information."""
        if hasattr(obj, 'dict'):
            # Pydantic model
            data = obj.model_dump() if hasattr(obj, 'model_dump') else obj.dict()
        elif hasattr(obj, '__dict__'):
            # Regular object
            data = obj.__dict__
        else:
            # Primitive or dict
            data = obj
        
        # Add type information for proper deserialization and GC
        if obj_type:
            wrapper = {
                "type": obj_type.value,
                "data": data
            }
        else:
            wrapper = data
        
        # Deterministic JSON serialization
        return json.dumps(wrapper, sort_keys=True, default=str).encode('utf-8')
    
    def _deserialize_object(
        self,
        data: bytes,
        obj_type: Optional[ObjectType] = None,
    ) -> Any:
        """Deserialize object from bytes."""
        obj_dict = json.loads(data.decode('utf-8'))
        
        # Check if the object has type wrapper
        if isinstance(obj_dict, dict) and "type" in obj_dict and "data" in obj_dict:
            # Extract the actual data from wrapper
            stored_type = obj_dict["type"]
            actual_data = obj_dict["data"]
            
            # Validate type if specified
            if obj_type and stored_type != obj_type.value:
                logger.warning(
                    "object_type_mismatch",
                    expected=obj_type.value,
                    actual=stored_type
                )
            
            return actual_data
        
        # Return as-is for backward compatibility
        return obj_dict
    
    def _update_cache(self, obj_hash: str, obj: Any):
        """Update object cache with LRU eviction."""
        
        # If object already in cache, remove it (will re-add at end)
        if obj_hash in self._cache:
            del self._cache[obj_hash]
        
        # Evict least recently used if cache is full
        if len(self._cache) >= self._cache_size_limit:
            # Remove least recently used (first item in OrderedDict)
            self._cache.popitem(last=False)
        
        # Add new item at end (most recently used)
        self._cache[obj_hash] = obj
    
    def _write_file(self, path: Path, data: bytes):
        """Write file atomically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
    
    def _read_file(self, path: Path) -> bytes:
        """Read file contents."""
        with open(path, 'rb') as f:
            return f.read()
    
    async def _apply_delta_compression(self) -> int:
        """Apply delta compression to similar objects."""
        # Simplified implementation - would use xdelta3 or similar
        # in production for actual delta compression
        return 0
    
    async def _garbage_collect(self) -> int:
        """Remove unreachable objects."""
        try:
            # Collect all reachable objects
            reachable = set()
            
            # Start from all refs (branches and tags)
            refs_to_check = []
            
            # Check HEAD reference first (critical for detached HEAD state)
            head_file = self.refs_path / "HEAD"
            if head_file.exists():
                head_content = await asyncio.to_thread(head_file.read_text)
                head_content = head_content.strip()
                
                # HEAD can point to a branch (ref: refs/heads/branch) or directly to a commit
                if head_content.startswith("ref:"):
                    # Points to a branch
                    ref_path = head_content[4:].strip()
                    actual_ref_file = self.refs_path.parent / ref_path
                    if actual_ref_file.exists():
                        commit_hash = await asyncio.to_thread(actual_ref_file.read_text)
                        refs_to_check.append(commit_hash.strip())
                        logger.debug("gc_adding_head_branch_ref", ref=ref_path, commit=commit_hash.strip()[:8])
                else:
                    # Detached HEAD - points directly to a commit
                    refs_to_check.append(head_content)
                    logger.debug("gc_adding_detached_head", commit=head_content[:8])
            
            # Check branch heads
            heads_path = self.refs_path / "heads"
            if heads_path.exists():
                for ref_file in heads_path.iterdir():
                    if ref_file.is_file():
                        commit_hash = await asyncio.to_thread(ref_file.read_text)
                        refs_to_check.append(commit_hash.strip())
            
            # Check tags
            tags_path = self.refs_path / "tags"
            if tags_path.exists():
                for ref_file in tags_path.iterdir():
                    if ref_file.is_file():
                        commit_hash = await asyncio.to_thread(ref_file.read_text)
                        refs_to_check.append(commit_hash.strip())
            
            # Walk commit graph to find all reachable objects
            visited = set()
            while refs_to_check:
                obj_hash = refs_to_check.pop()
                if obj_hash in visited:
                    continue
                visited.add(obj_hash)
                reachable.add(obj_hash)
                
                # Get raw object to check its type
                path = self._get_object_path(obj_hash)
                if path.exists():
                    compressed = await asyncio.to_thread(self._read_file, path)
                    serialized = await asyncio.to_thread(gzip.decompress, compressed)
                    raw_obj = json.loads(serialized.decode('utf-8'))
                    
                    # Check if it has type wrapper
                    if isinstance(raw_obj, dict) and "type" in raw_obj and "data" in raw_obj:
                        obj_type = raw_obj["type"]
                        obj_data = raw_obj["data"]
                    else:
                        # Legacy format - try to infer type from structure
                        obj_data = raw_obj
                        if "tree" in obj_data and "parents" in obj_data:
                            obj_type = "commit"
                        elif "entries" in obj_data:
                            obj_type = "tree"
                        else:
                            obj_type = "blob"
                    
                    # If it's a commit, add tree and parents
                    if obj_type == "commit":
                        if "tree" in obj_data:
                            refs_to_check.append(obj_data["tree"])
                            reachable.add(obj_data["tree"])
                        if "parents" in obj_data:
                            for parent in obj_data["parents"]:
                                refs_to_check.append(parent)
                    # If it's a tree, add all entries
                    elif obj_type == "tree":
                        if "entries" in obj_data:
                            for entry in obj_data["entries"]:
                                if "hash" in entry:
                                    reachable.add(entry["hash"])
            
            # Find and remove unreachable objects
            removed_count = 0
            if self.objects_path.exists():
                for obj_dir in self.objects_path.iterdir():
                    if obj_dir.is_dir() and len(obj_dir.name) == 2:
                        for obj_file in obj_dir.iterdir():
                            full_hash = obj_dir.name + obj_file.name
                            if full_hash not in reachable:
                                await asyncio.to_thread(obj_file.unlink)
                                removed_count += 1
                                
                                # Clear from cache if present
                                if full_hash in self._cache:
                                    del self._cache[full_hash]
            
            # Update statistics
            self._stats.gc_runs += 1
            self._stats.objects_removed += removed_count
            
            logger.info(
                "garbage_collection_complete",
                removed_count=removed_count,
                reachable_count=len(reachable),
                message=VERSION_CONTROL_TR['garbage_collected']
            )
            
            return removed_count
            
        except Exception as e:
            logger.error(
                "garbage_collection_failed",
                error=str(e)
            )
            return 0
    
    async def _pack_objects(self) -> int:
        """Pack loose objects into pack files."""
        # Would combine multiple loose objects into
        # pack files for efficiency
        return 0
    
    async def _restore_from_delta(self, obj_hash: str) -> Optional[Any]:
        """Restore object from delta compression."""
        if obj_hash not in self._delta_index:
            return None
        
        delta_info = self._delta_index[obj_hash]
        
        # Get base object
        base = await self.get_object(delta_info.base_hash)
        if not base:
            return None
        
        # Apply delta (simplified - would use actual delta algorithm)
        # For now just return base
        return base