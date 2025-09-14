"""
Task 7.26: Incremental Backup System

Delta calculation, block-level deduplication, and efficient storage.
Implements content-defined chunking (CDC) for optimal deduplication.

Features:
- Content-defined chunking with Rabin fingerprinting
- Block-level deduplication with content hashing
- Delta encoding for incremental changes
- Snapshot chain management
- Efficient storage with reference counting
- Backup verification and consistency checks
- Turkish localization for all messages
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import aiofiles
from pydantic import BaseModel, Field

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..services.profiling_state_manager import state_manager

logger = get_logger(__name__)


class ChunkingAlgorithm(str, Enum):
    """Chunking algorithms for deduplication."""
    FIXED = "fixed"              # Fixed-size chunks
    RABIN = "rabin"              # Content-defined chunking with Rabin fingerprint
    BUZHASH = "buzhash"          # Rolling hash with BuzHash
    FASTCDC = "fastcdc"          # Fast content-defined chunking


class DeltaAlgorithm(str, Enum):
    """Delta encoding algorithms."""
    XDELTA3 = "xdelta3"          # Binary delta encoding
    RSYNC = "rsync"              # Rsync-style rolling checksums
    BSDIFF = "bsdiff"            # Binary diff for executables
    SIMPLE = "simple"            # Simple byte-level diff


class BackupType(str, Enum):
    """Backup types."""
    FULL = "full"                # Complete backup
    INCREMENTAL = "incremental"  # Changes since last backup
    DIFFERENTIAL = "differential" # Changes since last full backup
    SYNTHETIC = "synthetic"      # Constructed from incrementals


@dataclass
class ChunkInfo:
    """Information about a data chunk."""
    chunk_id: str               # Unique chunk identifier (hash)
    offset: int                 # Offset in original data
    size: int                   # Chunk size in bytes
    checksum: str              # Content checksum
    ref_count: int = 1         # Reference count for deduplication


class ChunkingConfig(BaseModel):
    """Configuration for chunking."""
    algorithm: ChunkingAlgorithm = Field(default=ChunkingAlgorithm.RABIN)
    target_chunk_size: int = Field(default=64 * 1024, description="Target chunk size in bytes (64KB)")
    min_chunk_size: int = Field(default=16 * 1024, description="Minimum chunk size (16KB)")
    max_chunk_size: int = Field(default=256 * 1024, description="Maximum chunk size (256KB)")
    window_size: int = Field(default=48, description="Sliding window size for Rabin")
    prime: int = Field(default=3, description="Prime for polynomial rolling hash")
    modulus: int = Field(default=2**16 - 1, description="Modulus for hash operations")
    mask: int = Field(default=0x1FFF, description="Mask for chunk boundary detection")


class IncrementalBackupConfig(BaseModel):
    """Configuration for incremental backup."""
    chunking_config: ChunkingConfig = Field(default_factory=ChunkingConfig)
    enable_deduplication: bool = Field(default=True)
    enable_compression: bool = Field(default=True)
    delta_algorithm: DeltaAlgorithm = Field(default=DeltaAlgorithm.SIMPLE)
    max_chain_length: int = Field(default=10, description="Max incremental chain length")
    synthetic_full_interval: int = Field(default=7, description="Create synthetic full every N incrementals")
    verify_chunks: bool = Field(default=True)
    parallel_chunks: int = Field(default=4, ge=1, le=16)
    cache_chunk_index: bool = Field(default=True)


class BackupSnapshot(BaseModel):
    """Represents a backup snapshot."""
    snapshot_id: str = Field(description="Unique snapshot identifier")
    parent_id: Optional[str] = Field(default=None, description="Parent snapshot for incremental")
    backup_type: BackupType
    source_id: str = Field(description="Source document/model ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    chunks: List[str] = Field(default_factory=list, description="List of chunk IDs")
    chunk_map: Dict[int, str] = Field(default_factory=dict, description="Offset to chunk ID mapping")
    total_size: int = Field(default=0, description="Total data size")
    unique_size: int = Field(default=0, description="Unique data size (after dedup)")
    dedup_ratio: float = Field(default=0.0, description="Deduplication ratio")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChunkStore:
    """Storage for deduplicated chunks."""

    def __init__(self):
        self.chunks: Dict[str, bytes] = {}  # chunk_id -> data
        self.chunk_info: Dict[str, ChunkInfo] = {}  # chunk_id -> info
        self.ref_counts: Dict[str, int] = defaultdict(int)  # chunk_id -> count
        self._lock = asyncio.Lock()

    async def add_chunk(self, data: bytes, offset: int) -> ChunkInfo:
        """Add chunk to store with deduplication."""
        chunk_id = hashlib.sha256(data).hexdigest()

        async with self._lock:
            if chunk_id in self.chunks:
                # Chunk exists, increment reference count
                self.ref_counts[chunk_id] += 1
                info = self.chunk_info[chunk_id]
                info.ref_count = self.ref_counts[chunk_id]
                logger.debug("Chunk deduplicated", chunk_id=chunk_id[:8], ref_count=info.ref_count)
                return info

            # New chunk
            checksum = hashlib.md5(data).hexdigest()
            info = ChunkInfo(
                chunk_id=chunk_id,
                offset=offset,
                size=len(data),
                checksum=checksum,
                ref_count=1
            )

            self.chunks[chunk_id] = data
            self.chunk_info[chunk_id] = info
            self.ref_counts[chunk_id] = 1

            logger.debug("New chunk stored", chunk_id=chunk_id[:8], size=len(data))
            return info

    async def get_chunk(self, chunk_id: str) -> Optional[bytes]:
        """Get chunk data by ID."""
        return self.chunks.get(chunk_id)

    async def remove_chunk(self, chunk_id: str) -> bool:
        """Remove chunk if no references remain."""
        async with self._lock:
            if chunk_id not in self.ref_counts:
                return False

            self.ref_counts[chunk_id] -= 1

            if self.ref_counts[chunk_id] <= 0:
                # No more references, remove chunk
                self.chunks.pop(chunk_id, None)
                self.chunk_info.pop(chunk_id, None)
                del self.ref_counts[chunk_id]
                logger.debug("Chunk removed", chunk_id=chunk_id[:8])
                return True

            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get chunk store statistics."""
        total_chunks = len(self.chunks)
        total_size = sum(len(data) for data in self.chunks.values())
        total_refs = sum(self.ref_counts.values())

        return {
            "total_chunks": total_chunks,
            "total_size_bytes": total_size,
            "total_references": total_refs,
            "average_chunk_size": total_size / total_chunks if total_chunks > 0 else 0,
            "dedup_ratio": total_refs / total_chunks if total_chunks > 0 else 1.0
        }


class RabinChunker:
    """Rabin fingerprint-based content-defined chunking."""

    def __init__(self, config: ChunkingConfig):
        self.config = config
        self.window_size = config.window_size
        self.prime = config.prime
        self.modulus = config.modulus
        self.mask = config.mask

        # Precompute powers of prime for efficiency
        self.prime_power = self.prime ** (self.window_size - 1) % self.modulus

    def chunk(self, data: bytes) -> List[Tuple[int, bytes]]:
        """Split data into content-defined chunks."""
        chunks = []
        offset = 0
        data_len = len(data)

        while offset < data_len:
            chunk_start = offset
            chunk_end = min(offset + self.config.max_chunk_size, data_len)

            # Find chunk boundary using rolling hash
            if offset + self.config.min_chunk_size < data_len:
                boundary = self._find_boundary(
                    data[offset:chunk_end],
                    self.config.min_chunk_size
                )

                if boundary > 0:
                    chunk_end = offset + boundary

            chunk = data[chunk_start:chunk_end]
            chunks.append((chunk_start, chunk))
            offset = chunk_end

        return chunks

    def _find_boundary(self, data: bytes, min_size: int) -> int:
        """Find chunk boundary using Rabin fingerprint."""
        if len(data) < min_size:
            return 0

        # Initialize rolling hash
        window = data[:self.window_size]
        hash_val = 0

        for byte in window:
            hash_val = (hash_val * self.prime + byte) % self.modulus

        # Roll through data looking for boundary
        for i in range(self.window_size, len(data)):
            if i >= min_size and (hash_val & self.mask) == 0:
                return i  # Found boundary

            # Update rolling hash
            old_byte = data[i - self.window_size]
            new_byte = data[i]

            hash_val = (
                (hash_val - old_byte * self.prime_power) * self.prime + new_byte
            ) % self.modulus

        return 0  # No boundary found


class SimpleDelta:
    """Simple byte-level delta encoding."""

    @staticmethod
    def create_delta(old_data: bytes, new_data: bytes) -> Dict[str, Any]:
        """Create delta between old and new data."""
        operations = []
        old_len = len(old_data)
        new_len = len(new_data)

        # Simple algorithm: find common prefix and suffix
        common_prefix = 0
        while common_prefix < min(old_len, new_len):
            if old_data[common_prefix] != new_data[common_prefix]:
                break
            common_prefix += 1

        common_suffix = 0
        while common_suffix < min(old_len - common_prefix, new_len - common_prefix):
            if old_data[old_len - 1 - common_suffix] != new_data[new_len - 1 - common_suffix]:
                break
            common_suffix += 1

        # Record operations
        if common_prefix > 0:
            operations.append({
                "op": "copy",
                "offset": 0,
                "length": common_prefix
            })

        middle_old_start = common_prefix
        middle_old_end = old_len - common_suffix
        middle_new_start = common_prefix
        middle_new_end = new_len - common_suffix

        if middle_new_end > middle_new_start:
            # Insert new data
            operations.append({
                "op": "insert",
                "data": new_data[middle_new_start:middle_new_end].hex()
            })

        if common_suffix > 0:
            operations.append({
                "op": "copy",
                "offset": old_len - common_suffix,
                "length": common_suffix
            })

        return {
            "old_size": old_len,
            "new_size": new_len,
            "operations": operations,
            "compression": 1 - (len(json.dumps(operations)) / new_len) if new_len > 0 else 0
        }

    @staticmethod
    def apply_delta(old_data: bytes, delta: Dict[str, Any]) -> bytes:
        """Apply delta to reconstruct new data."""
        result = bytearray()

        for op in delta["operations"]:
            if op["op"] == "copy":
                offset = op["offset"]
                length = op["length"]
                result.extend(old_data[offset:offset + length])
            elif op["op"] == "insert":
                data = bytes.fromhex(op["data"])
                result.extend(data)

        return bytes(result)


class IncrementalBackupManager:
    """Manages incremental backups with deduplication."""

    def __init__(self, config: Optional[IncrementalBackupConfig] = None):
        self.config = config or IncrementalBackupConfig()
        self.chunk_store = ChunkStore()
        self.snapshots: Dict[str, BackupSnapshot] = {}
        self.snapshot_chains: Dict[str, List[str]] = defaultdict(list)  # source_id -> snapshot_ids

        # Initialize chunker
        if self.config.chunking_config.algorithm == ChunkingAlgorithm.RABIN:
            self.chunker = RabinChunker(self.config.chunking_config)
        else:
            # Fallback to fixed-size chunking
            self.chunker = None

        # Initialize delta encoder
        if self.config.delta_algorithm == DeltaAlgorithm.SIMPLE:
            self.delta_encoder = SimpleDelta()
        else:
            self.delta_encoder = SimpleDelta()  # Default

    async def create_backup(
        self,
        data: bytes,
        source_id: str,
        force_full: bool = False
    ) -> BackupSnapshot:
        """Create incremental or full backup."""
        correlation_id = get_correlation_id()

        with create_span("incremental_backup_create", correlation_id=correlation_id) as span:
            span.set_attribute("source_id", source_id)
            span.set_attribute("data_size", len(data))

            # Determine backup type
            chain = self.snapshot_chains.get(source_id, [])
            needs_full = (
                force_full or
                len(chain) == 0 or
                len(chain) >= self.config.max_chain_length or
                (len(chain) > 0 and len(chain) % self.config.synthetic_full_interval == 0)
            )

            backup_type = BackupType.FULL if needs_full else BackupType.INCREMENTAL
            parent_id = None if needs_full else chain[-1]

            span.set_attribute("backup_type", backup_type.value)

            # Create snapshot
            snapshot_id = f"snap_{source_id}_{int(time.time() * 1000)}"
            snapshot = BackupSnapshot(
                snapshot_id=snapshot_id,
                parent_id=parent_id,
                backup_type=backup_type,
                source_id=source_id,
                total_size=len(data)
            )

            # Chunk data
            if self.config.enable_deduplication:
                chunks = await self._chunk_and_store(data)
                snapshot.chunks = [c.chunk_id for c in chunks]

                # Build chunk map
                for chunk in chunks:
                    snapshot.chunk_map[chunk.offset] = chunk.chunk_id

                # Calculate deduplication stats
                unique_size = sum(c.size for c in chunks if c.ref_count == 1)
                snapshot.unique_size = unique_size
                snapshot.dedup_ratio = 1 - (unique_size / len(data)) if len(data) > 0 else 0

            else:
                # Store as single chunk without dedup
                chunk = await self.chunk_store.add_chunk(data, 0)
                snapshot.chunks = [chunk.chunk_id]
                snapshot.unique_size = len(data)

            # Store snapshot
            self.snapshots[snapshot_id] = snapshot
            self.snapshot_chains[source_id].append(snapshot_id)

            # Store in Redis for persistence
            await self._persist_snapshot(snapshot)

            logger.info(
                "Artımlı yedekleme oluşturuldu",
                snapshot_id=snapshot_id,
                type=backup_type.value,
                size=len(data),
                unique_size=snapshot.unique_size,
                dedup_ratio=f"{snapshot.dedup_ratio:.2%}"
            )

            metrics.incremental_backup_created.labels(
                type=backup_type.value
            ).inc()

            metrics.deduplication_ratio.observe(snapshot.dedup_ratio)

            return snapshot

    async def restore_snapshot(self, snapshot_id: str) -> bytes:
        """Restore data from snapshot."""
        correlation_id = get_correlation_id()

        with create_span("incremental_backup_restore", correlation_id=correlation_id) as span:
            span.set_attribute("snapshot_id", snapshot_id)

            snapshot = self.snapshots.get(snapshot_id)
            if not snapshot:
                # Try loading from Redis
                snapshot = await self._load_snapshot(snapshot_id)
                if not snapshot:
                    raise ValueError(f"Anlık görüntü bulunamadı: {snapshot_id}")

            # Reconstruct data from chunks
            data_parts = []
            for chunk_id in snapshot.chunks:
                chunk_data = await self.chunk_store.get_chunk(chunk_id)
                if not chunk_data:
                    raise ValueError(f"Chunk bulunamadı: {chunk_id}")
                data_parts.append(chunk_data)

            restored_data = b''.join(data_parts)

            logger.info(
                "Anlık görüntü geri yüklendi",
                snapshot_id=snapshot_id,
                size=len(restored_data)
            )

            metrics.incremental_backup_restored.inc()

            return restored_data

    async def create_synthetic_full(self, source_id: str) -> BackupSnapshot:
        """Create synthetic full backup from incremental chain."""
        correlation_id = get_correlation_id()

        with create_span("synthetic_full_create", correlation_id=correlation_id) as span:
            span.set_attribute("source_id", source_id)

            chain = self.snapshot_chains.get(source_id, [])
            if not chain:
                raise ValueError(f"Yedekleme zinciri bulunamadı: {source_id}")

            # Find last full backup in chain
            full_snapshot_id = None
            for snap_id in chain:
                snap = self.snapshots.get(snap_id)
                if snap and snap.backup_type == BackupType.FULL:
                    full_snapshot_id = snap_id

            if not full_snapshot_id:
                raise ValueError(f"Tam yedekleme bulunamadı: {source_id}")

            # Restore from full and apply incrementals
            current_data = await self.restore_snapshot(full_snapshot_id)

            # Apply each incremental in sequence
            start_idx = chain.index(full_snapshot_id) + 1
            for snap_id in chain[start_idx:]:
                snap = self.snapshots.get(snap_id)
                if snap and snap.backup_type == BackupType.INCREMENTAL:
                    # Apply incremental delta to current data
                    incremental_data = await self.restore_snapshot(snap_id)

                    # Apply delta if we have parent data
                    if snap.parent_id and self.config.delta_algorithm == DeltaAlgorithm.SIMPLE:
                        # Create delta between current and incremental
                        delta = self.delta_encoder.create_delta(current_data, incremental_data)
                        # Apply the delta to get the new state
                        current_data = self.delta_encoder.apply_delta(current_data, delta)
                    else:
                        # Fallback: use incremental data directly
                        current_data = incremental_data

            # Create new full backup from reconstructed data
            synthetic_id = f"synthetic_{source_id}_{int(time.time() * 1000)}"
            synthetic_snapshot = BackupSnapshot(
                snapshot_id=synthetic_id,
                backup_type=BackupType.SYNTHETIC,
                source_id=source_id,
                total_size=len(current_data)
            )

            # Store as new full backup
            chunks = await self._chunk_and_store(current_data)
            synthetic_snapshot.chunks = [c.chunk_id for c in chunks]

            self.snapshots[synthetic_id] = synthetic_snapshot

            logger.info(
                "Sentetik tam yedekleme oluşturuldu",
                snapshot_id=synthetic_id,
                source_id=source_id,
                size=len(current_data)
            )

            return synthetic_snapshot

    async def _chunk_and_store(self, data: bytes) -> List[ChunkInfo]:
        """Chunk data and store with deduplication."""
        chunks = []

        if self.chunker:
            # Content-defined chunking
            chunk_list = self.chunker.chunk(data)
        else:
            # Fixed-size chunking
            chunk_size = self.config.chunking_config.target_chunk_size
            chunk_list = [
                (i, data[i:i + chunk_size])
                for i in range(0, len(data), chunk_size)
            ]

        # Store chunks in parallel
        tasks = []
        for offset, chunk_data in chunk_list:
            tasks.append(self.chunk_store.add_chunk(chunk_data, offset))

        chunks = await asyncio.gather(*tasks)

        return chunks

    async def _persist_snapshot(self, snapshot: BackupSnapshot):
        """Persist snapshot metadata to Redis."""
        key = f"snapshot:{snapshot.snapshot_id}"
        data = snapshot.dict()

        await state_manager.add_memory_snapshot({
            "snapshot_id": snapshot.snapshot_id,
            "type": "incremental_backup",
            "data": data
        })

    async def _load_snapshot(self, snapshot_id: str) -> Optional[BackupSnapshot]:
        """Load snapshot metadata from Redis."""
        snapshots = await state_manager.get_memory_snapshots(limit=100)

        for snap_data in snapshots:
            if snap_data.get("snapshot_id") == snapshot_id:
                return BackupSnapshot(**snap_data.get("data", {}))

        return None

    async def verify_chain(self, source_id: str) -> Dict[str, Any]:
        """Verify integrity of backup chain."""
        chain = self.snapshot_chains.get(source_id, [])
        results = {
            "source_id": source_id,
            "chain_length": len(chain),
            "valid": True,
            "errors": []
        }

        for snapshot_id in chain:
            snapshot = self.snapshots.get(snapshot_id)
            if not snapshot:
                results["errors"].append(f"Anlık görüntü eksik: {snapshot_id}")
                results["valid"] = False
                continue

            # Verify all chunks exist
            for chunk_id in snapshot.chunks:
                if not await self.chunk_store.get_chunk(chunk_id):
                    results["errors"].append(f"Chunk eksik: {chunk_id} in {snapshot_id}")
                    results["valid"] = False

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get backup statistics."""
        total_snapshots = len(self.snapshots)
        total_chains = len(self.snapshot_chains)
        chunk_stats = self.chunk_store.get_stats()

        return {
            "total_snapshots": total_snapshots,
            "total_chains": total_chains,
            "snapshots_by_type": self._count_by_type(),
            "chunk_stats": chunk_stats,
            "average_chain_length": sum(len(c) for c in self.snapshot_chains.values()) / total_chains if total_chains > 0 else 0
        }

    def _count_by_type(self) -> Dict[str, int]:
        """Count snapshots by type."""
        counts = defaultdict(int)
        for snapshot in self.snapshots.values():
            counts[snapshot.backup_type.value] += 1
        return dict(counts)


# Global incremental backup manager
incremental_manager = IncrementalBackupManager()


# Add metrics
if not hasattr(metrics, 'incremental_backup_created'):
    from prometheus_client import Counter, Histogram, Gauge

    metrics.incremental_backup_created = Counter(
        'incremental_backup_created_total',
        'Total number of incremental backups created',
        ['type']
    )

    metrics.incremental_backup_restored = Counter(
        'incremental_backup_restored_total',
        'Total number of incremental backups restored'
    )

    metrics.deduplication_ratio = Histogram(
        'backup_deduplication_ratio',
        'Deduplication ratio achieved',
        buckets=(0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
    )

    metrics.chunk_store_size = Gauge(
        'chunk_store_size_bytes',
        'Total size of chunk store in bytes'
    )