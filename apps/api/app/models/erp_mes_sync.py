"""ERP/MES synchronization model for external system integration.

Enterprise-grade synchronization tracking with strict Task Master ERD compliance.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ErpMesSync(Base, TimestampMixin):
    """ERP/MES system synchronization tracking.
    
    Task Master ERD Compliance:
    - external_id string field for external system reference
    - entity_type string field for entity classification
    - entity_id integer field for local entity reference
    - status string field for synchronization status
    - last_sync_at timestamp for sync tracking
    - payload JSONB for sync data
    - Enterprise security and audit trail
    """

    __tablename__ = "erp_mes_sync"

    # Primary key
    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # External system reference (Task Master ERD requirement)
    external_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True
    )

    # Entity mapping (Task Master ERD requirement)
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True
    )

    entity_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    # Synchronization status (Task Master ERD requirement)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True
    )

    # Last sync timestamp (Task Master ERD requirement)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Synchronization data (Task Master ERD requirement)
    payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True
    )

    # Enterprise-grade indexing strategy
    __table_args__ = (
        Index(
            'idx_erp_mes_sync_entity',
            'entity_type',
            'entity_id'
        ),
        Index(
            'idx_erp_mes_sync_external_id',
            'external_id'
        ),
        Index(
            'idx_erp_mes_sync_status',
            'status',
            postgresql_where="status IN ('pending', 'failed')"
        ),
        Index(
            'idx_erp_mes_sync_last_sync',
            'last_sync_at',
            postgresql_where="last_sync_at IS NOT NULL"
        ),
        Index(
            'idx_erp_mes_sync_created_at',
            'created_at'
        )
    )

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"<ErpMesSync(id={self.id}, external_id={self.external_id}, "
            f"entity_type={self.entity_type}, entity_id={self.entity_id}, "
            f"status={self.status})>"
        )

    def __str__(self) -> str:
        """User-friendly representation."""
        return f"ERP/MES Sync #{self.id} - {self.entity_type}:{self.entity_id} ({self.status})"

    @property
    def is_pending(self) -> bool:
        """Check if sync is pending."""
        return self.status == 'pending'

    @property
    def is_synced(self) -> bool:
        """Check if sync completed successfully."""
        return self.status == 'synced'

    @property
    def is_failed(self) -> bool:
        """Check if sync failed."""
        return self.status == 'failed'

    @property
    def needs_sync(self) -> bool:
        """Check if entity needs synchronization."""
        return self.status in ['pending', 'failed']

    @property
    def sync_age_hours(self) -> float | None:
        """Get hours since last successful sync."""
        if not self.last_sync_at:
            return None
        delta = datetime.now(UTC) - self.last_sync_at
        return delta.total_seconds() / 3600.0

    def get_payload(self, key: str, default=None):
        """Get payload value safely."""
        if not self.payload:
            return default
        return self.payload.get(key, default)

    def set_payload(self, key: str, value) -> None:
        """Set payload value safely."""
        if self.payload is None:
            self.payload = {}
        self.payload[key] = value

    def mark_as_synced(self, sync_data: dict | None = None) -> None:
        """Mark sync as successful."""
        self.status = 'synced'
        self.last_sync_at = datetime.now(UTC)
        if sync_data:
            self.set_payload('sync_result', sync_data)
            self.set_payload('synced_at', self.last_sync_at.isoformat())

    def mark_as_failed(self, error_message: str, error_details: dict | None = None) -> None:
        """Mark sync as failed."""
        self.status = 'failed'
        self.set_payload('error_message', error_message)
        if error_details:
            self.set_payload('error_details', error_details)
        self.set_payload('failed_at', datetime.now(UTC).isoformat())

    def mark_as_pending(self, sync_data: dict | None = None) -> None:
        """Mark sync as pending."""
        self.status = 'pending'
        if sync_data:
            self.set_payload('pending_data', sync_data)
        self.set_payload('pending_at', datetime.now(UTC).isoformat())

    def add_sync_attempt(
        self,
        attempt_number: int,
        response_data: dict | None = None,
        error_message: str | None = None
    ) -> None:
        """Add sync attempt metadata."""
        if not self.payload:
            self.payload = {}

        if 'attempts' not in self.payload:
            self.payload['attempts'] = []

        attempt_data = {
            'attempt_number': attempt_number,
            'attempted_at': datetime.now(UTC).isoformat(),
            'response_data': response_data,
            'error_message': error_message
        }

        self.payload['attempts'].append(attempt_data)
