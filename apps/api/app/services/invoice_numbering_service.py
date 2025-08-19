"""
Invoice numbering service with atomic sequence generation.
Task 4.11: Ensures unique, sequential invoice numbers with concurrency protection.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..models.invoice import Invoice

logger = get_logger(__name__)


class InvoiceNumberingService:
    """Generate unique invoice numbers with atomic operations and retry logic.
    
    Invoice number format: YYYYMM-NNNNN-CNCAI
    - YYYYMM: Year and month
    - NNNNN: Sequential number padded to 5 digits
    - CNCAI: Company identifier suffix
    
    Uses PostgreSQL sequences and advisory locks for concurrency control.
    """

    COMPANY_SUFFIX = "CNCAI"
    MAX_RETRIES = 5
    BACKOFF_BASE = 0.1  # 100ms initial backoff

    def __init__(self):
        self.logger = logger

    def generate_invoice_number(
        self,
        db: Session,
        invoice_date: datetime | None = None
    ) -> str:
        """Generate a unique invoice number with concurrency protection.
        
        Args:
            db: Database session
            invoice_date: Date for the invoice (defaults to current date)
            
        Returns:
            Unique invoice number in format YYYYMM-NNNNN-CNCAI
            
        Raises:
            RuntimeError: If unable to generate unique number after retries
        """
        if not invoice_date:
            invoice_date = datetime.now(UTC)

        year_month = invoice_date.strftime("%Y%m")

        # Try to generate with retry logic
        import random
        import time

        for attempt in range(self.MAX_RETRIES):
            try:
                # Get next number using advisory lock
                seq_number = self._get_next_sequence_number(db, year_month)

                # Format invoice number
                invoice_number = f"{year_month}-{seq_number:05d}-{self.COMPANY_SUFFIX}"

                # Verify uniqueness (should not fail if sequence is working correctly)
                existing = db.query(Invoice).filter(
                    Invoice.number == invoice_number
                ).first()

                if existing:
                    self.logger.warning(
                        f"Invoice number collision detected: {invoice_number}, retrying",
                        extra={
                            "attempt": attempt + 1,
                            "invoice_number": invoice_number
                        }
                    )
                    # Exponential backoff with jitter
                    backoff_time = self.BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.1)
                    time.sleep(backoff_time)
                    continue

                self.logger.info(
                    f"Generated invoice number: {invoice_number}",
                    extra={
                        "invoice_number": invoice_number,
                        "year_month": year_month,
                        "sequence": seq_number
                    }
                )

                return invoice_number

            except OperationalError as e:
                self.logger.error(
                    f"Database error generating invoice number, attempt {attempt + 1}",
                    exc_info=True,
                    extra={
                        "attempt": attempt + 1,
                        "year_month": year_month,
                        "error": str(e)
                    }
                )

                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff with jitter
                    backoff_time = self.BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.1)
                    time.sleep(backoff_time)
                    db.rollback()  # Clear any failed transaction
                else:
                    raise RuntimeError(
                        f"Fatura numarası oluşturulamadı: {str(e)}"
                    )

        raise RuntimeError(
            f"Fatura numarası oluşturulamadı: Maksimum deneme sayısına ulaşıldı ({self.MAX_RETRIES})"
        )

    def _get_next_sequence_number(self, db: Session, year_month: str) -> int:
        """Get next sequence number for given year-month with advisory lock.
        
        Uses PostgreSQL advisory locks to ensure atomic sequence generation.
        Creates sequence if it doesn't exist.
        
        Args:
            db: Database session
            year_month: Year-month string (YYYYMM)
            
        Returns:
            Next sequence number for the period
        """
        # Create a unique lock ID based on year-month
        # Use hash to convert string to integer for advisory lock
        lock_id = hash(f"invoice_seq_{year_month}") & 0x7FFFFFFF  # Ensure positive int32

        try:
            # Acquire advisory lock (waits if another process has it)
            db.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})

            # Sequence name for this period
            seq_name = f"invoice_seq_{year_month}"

            # Check if sequence exists
            seq_exists = db.execute(
                text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_sequences 
                        WHERE schemaname = 'public' 
                        AND sequencename = :seq_name
                    )
                """),
                {"seq_name": seq_name}
            ).scalar()

            if not seq_exists:
                # Create sequence starting at 1
                db.execute(
                    text(f"""
                        CREATE SEQUENCE IF NOT EXISTS {seq_name}
                        START WITH 1
                        INCREMENT BY 1
                        NO MAXVALUE
                        NO CYCLE
                    """)
                )
                db.commit()

                self.logger.info(
                    f"Created new invoice sequence: {seq_name}",
                    extra={"sequence_name": seq_name}
                )

            # Get next value from sequence
            next_val = db.execute(
                text(f"SELECT nextval('{seq_name}')")
            ).scalar()

            return int(next_val)

        finally:
            # Always release advisory lock
            try:
                db.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
            except Exception as e:
                self.logger.warning(
                    f"Failed to release advisory lock: {e}",
                    extra={"lock_id": lock_id}
                )

    def reset_sequence_for_period(
        self,
        db: Session,
        year_month: str,
        start_value: int = 1
    ) -> None:
        """Reset sequence for a given period (admin operation).
        
        Args:
            db: Database session
            year_month: Year-month string (YYYYMM)
            start_value: New starting value for sequence
        """
        seq_name = f"invoice_seq_{year_month}"

        try:
            # Drop and recreate sequence
            db.execute(text(f"DROP SEQUENCE IF EXISTS {seq_name} CASCADE"))
            db.execute(
                text(f"""
                    CREATE SEQUENCE {seq_name}
                    START WITH :start_value
                    INCREMENT BY 1
                    NO MAXVALUE
                    NO CYCLE
                """),
                {"start_value": start_value}
            )
            db.commit()

            self.logger.info(
                f"Reset invoice sequence: {seq_name} to {start_value}",
                extra={
                    "sequence_name": seq_name,
                    "start_value": start_value
                }
            )

        except Exception as e:
            db.rollback()
            self.logger.error(
                f"Failed to reset invoice sequence: {seq_name}",
                exc_info=True,
                extra={
                    "sequence_name": seq_name,
                    "error": str(e)
                }
            )
            raise

    def get_current_sequence_value(
        self,
        db: Session,
        year_month: str
    ) -> int | None:
        """Get current value of sequence without incrementing.
        
        Args:
            db: Database session
            year_month: Year-month string (YYYYMM)
            
        Returns:
            Current sequence value or None if sequence doesn't exist
        """
        seq_name = f"invoice_seq_{year_month}"

        try:
            result = db.execute(
                text("""
                    SELECT last_value, is_called
                    FROM pg_sequences
                    WHERE schemaname = 'public'
                    AND sequencename = :seq_name
                """),
                {"seq_name": seq_name}
            ).first()

            if result:
                last_value, is_called = result
                # If sequence has been called, return last_value
                # Otherwise, it would be last_value - 1 (but we return None for unused)
                return last_value if is_called else None

            return None

        except Exception as e:
            self.logger.error(
                f"Failed to get sequence value: {seq_name}",
                exc_info=True,
                extra={
                    "sequence_name": seq_name,
                    "error": str(e)
                }
            )
            return None


# Singleton instance
invoice_numbering_service = InvoiceNumberingService()
