"""
ERP/MES synchronization model for external system integration.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, ForeignKey, Index,
    DateTime, Enum as SQLEnum, Text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin
from .enums import ErpSystem, SyncDirection, SyncStatus


class ErpMesSync(Base, TimestampMixin):
    """ERP/MES system synchronization tracking."""
    
    __tablename__ = "erp_mes_sync"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # External system
    external_system: Mapped[ErpSystem] = mapped_column(
        SQLEnum(ErpSystem),
        nullable=False
    )
    
    # Entity mapping
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
    entity_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )
    external_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True
    )
    
    # Sync configuration
    sync_direction: Mapped[SyncDirection] = mapped_column(
        SQLEnum(SyncDirection),
        nullable=False
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        SQLEnum(SyncStatus),
        nullable=False,
        index=True
    )
    
    # Sync data
    sync_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Error handling
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    
    # Sync timestamp
    synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_erp_mes_sync_external', 'external_system', 'external_id'),
        Index('idx_erp_mes_sync_entity', 'entity_type', 'entity_id'),
        Index('idx_erp_mes_sync_status', 'sync_status',
              postgresql_where="sync_status != 'synced'"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<ErpMesSync(id={self.id}, system={self.external_system.value}, "
            f"status={self.sync_status.value})>"
        )
    
    @property
    def is_synced(self) -> bool:
        """Check if sync is complete."""
        return self.sync_status == SyncStatus.SYNCED
    
    @property
    def is_failed(self) -> bool:
        """Check if sync has failed."""
        return self.sync_status == SyncStatus.FAILED
    
    @property
    def can_retry(self) -> bool:
        """Check if sync can be retried."""
        return self.is_failed and self.retry_count < 5
    
    def mark_synced(self):
        """Mark sync as successful."""
        self.sync_status = SyncStatus.SYNCED
        self.synced_at = datetime.utcnow()
        self.error_message = None
    
    def mark_failed(self, error: str):
        """Mark sync as failed."""
        self.sync_status = SyncStatus.FAILED
        self.error_message = error
        self.retry_count += 1
    
    def mark_in_progress(self):
        """Mark sync as in progress."""
        self.sync_status = SyncStatus.IN_PROGRESS