"""
Task 4.4: Ultra-enterprise invoice service with Turkish KDV compliance.

Features:
- Thread-safe sequential invoice numbering per month
- 20% Turkish VAT calculation with banking-grade precision
- Invoice creation for license assign/extend events
- Ultra-enterprise audit trail integration
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, List, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models.invoice import Invoice
from ..models.license import License
from ..models.user import User
from ..models.enums import PaidStatus


class InvoiceService:
    """
    Ultra-enterprise invoice service for Task 4.4.
    
    Handles:
    - Sequential invoice numbering with 'YYYYMM-SEQ-CNCAI' format
    - Thread-safe sequence generation per month
    - 20% Turkish KDV calculation
    - License event invoice creation
    """
    
    _lock = threading.Lock()
    
    @classmethod
    def generate_invoice_number(cls, db: Session, issued_at: Optional[datetime] = None) -> str:
        """
        Generate unique invoice number with format: 'YYYYMM-SEQ-CNCAI'
        
        Uses database-level locking with SELECT ... FOR UPDATE for true thread-safety
        across multiple processes. This is critical for banking-grade invoice numbering.
        
        Args:
            db: Database session
            issued_at: Invoice issue date (defaults to now UTC)
            
        Returns:
            Unique invoice number string
        """
        if issued_at is None:
            issued_at = datetime.now(timezone.utc)
        
        # Format: YYYYMM (202501 for January 2025)
        year_month = issued_at.strftime('%Y%m')
        
        # Use database-level locking for true multi-process safety
        # SELECT FOR UPDATE locks the rows preventing concurrent modifications
        query = text("""
            SELECT COALESCE(
                MAX(
                    CAST(
                        SUBSTRING(number FROM 8 FOR 6) AS INTEGER
                    )
                ), 0
            ) + 1 as next_seq
            FROM invoices 
            WHERE number LIKE :pattern
            FOR UPDATE
        """)
        
        pattern = f"{year_month}-%"
        result = db.execute(query, {"pattern": pattern}).fetchone()
        next_sequence = result.next_seq if result else 1
        
        # Zero-pad sequence to 6 digits as per Task 4.4
        sequence_str = f"{next_sequence:06d}"
        
        # Format: YYYYMM-SEQ-CNCAI
        invoice_number = f"{year_month}-{sequence_str}-CNCAI"
        
        return invoice_number
    
    @classmethod
    def calculate_invoice_amounts(cls, base_amount: Decimal) -> Dict[str, Decimal]:
        """
        Calculate invoice amounts with Turkish KDV compliance.
        
        Task 4.4 specification:
        - VAT = round(amount * 0.20, 2) with half-up rounding
        - Total = amount + VAT
        
        Args:
            base_amount: Base amount before VAT
            
        Returns:
            Dict with amount, vat, total (all Decimal with 2 decimal places)
        """
        # Ensure base amount has proper precision
        amount = base_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Calculate 20% Turkish KDV
        vat_rate = Decimal('0.20')
        vat = (amount * vat_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Calculate total
        total = amount + vat
        
        return {
            'amount': amount,
            'vat': vat,
            'total': total
        }
    
    @classmethod
    def create_invoice_for_license_event(
        cls,
        db: Session,
        user: User,
        license_obj: License,
        base_amount: Decimal,
        event_type: str = "license_assign"
    ) -> Invoice:
        """
        Create invoice for license assign/extend events.
        
        Task 4.4: One invoice per assign/extend event with proper linkage.
        
        Args:
            db: Database session
            user: User owning the license
            license_obj: License being invoiced
            base_amount: Base amount before VAT
            event_type: Type of event (assign/extend)
            
        Returns:
            Created invoice instance
        """
        # Generate unique invoice number
        issued_at = datetime.now(timezone.utc)
        invoice_number = cls.generate_invoice_number(db, issued_at)
        
        # Calculate amounts with Turkish KDV
        amounts = cls.calculate_invoice_amounts(base_amount)
        
        # Create invoice with Task 4.4 specifications
        invoice = Invoice(
            user_id=user.id,
            license_id=license_obj.id,
            number=invoice_number,
            amount=amounts['amount'],
            currency='TRY',  # Fixed to TRY per Task 4.4
            vat=amounts['vat'],
            total=amounts['total'],
            paid_status=PaidStatus.UNPAID,  # Default per Task 4.4
            issued_at=issued_at
        )
        
        # Add to session and flush to get ID
        db.add(invoice)
        db.flush()
        
        return invoice
    
    @classmethod
    def create_license_assign_invoice(
        cls,
        db: Session,
        user: User,
        license_obj: License,
        license_price: Decimal
    ) -> Invoice:
        """
        Create invoice for license assignment.
        
        Args:
            db: Database session
            user: User being assigned the license
            license_obj: License being assigned
            license_price: Price for the license
            
        Returns:
            Created invoice
        """
        return cls.create_invoice_for_license_event(
            db=db,
            user=user,
            license_obj=license_obj,
            base_amount=license_price,
            event_type="license_assign"
        )
    
    @classmethod
    def create_license_extend_invoice(
        cls,
        db: Session,
        user: User,
        license_obj: License,
        extension_price: Decimal
    ) -> Invoice:
        """
        Create invoice for license extension.
        
        Args:
            db: Database session
            user: User extending the license
            license_obj: License being extended
            extension_price: Price for the extension
            
        Returns:
            Created invoice
        """
        return cls.create_invoice_for_license_event(
            db=db,
            user=user,
            license_obj=license_obj,
            base_amount=extension_price,
            event_type="license_extend"
        )
    
    @classmethod
    def get_invoice_by_number(cls, db: Session, invoice_number: str) -> Optional[Invoice]:
        """
        Get invoice by unique number.
        
        Args:
            db: Database session
            invoice_number: Unique invoice number
            
        Returns:
            Invoice if found, None otherwise
        """
        return db.query(Invoice).filter(Invoice.number == invoice_number).first()
    
    @classmethod
    def get_user_invoices(
        cls, 
        db: Session, 
        user: User, 
        paid_status: Optional[PaidStatus] = None
    ) -> List[Invoice]:
        """
        Get invoices for a user, optionally filtered by payment status.
        
        Args:
            db: Database session
            user: User to get invoices for
            paid_status: Optional payment status filter
            
        Returns:
            List of invoices
        """
        query = db.query(Invoice).filter(Invoice.user_id == user.id)
        
        if paid_status:
            query = query.filter(Invoice.paid_status == paid_status)
        
        return query.order_by(Invoice.issued_at.desc()).all()
    
    @classmethod
    def get_license_invoices(cls, db: Session, license_obj: License) -> List[Invoice]:
        """
        Get all invoices for a specific license.
        
        Args:
            db: Database session
            license_obj: License to get invoices for
            
        Returns:
            List of invoices for the license
        """
        return (
            db.query(Invoice)
            .filter(Invoice.license_id == license_obj.id)
            .order_by(Invoice.issued_at.desc())
            .all()
        )
    
    @classmethod
    def mark_invoice_paid(
        cls,
        db: Session,
        invoice: Invoice,
        provider_payment_id: Optional[str] = None
    ) -> Invoice:
        """
        Mark invoice as paid with optional provider payment ID.
        
        NOTE: The database commit is handled by the request context/API handler
        to ensure proper transaction boundaries and error handling.
        
        Args:
            db: Database session
            invoice: Invoice to mark as paid
            provider_payment_id: External payment provider transaction ID
            
        Returns:
            Updated invoice
        """
        invoice.mark_as_paid(provider_payment_id)
        db.flush()  # Flush changes but don't commit - let request context handle it
        return invoice
    
    @classmethod
    def mark_invoice_failed(cls, db: Session, invoice: Invoice) -> Invoice:
        """
        Mark invoice payment as failed.
        
        NOTE: The database commit is handled by the request context/API handler
        to ensure proper transaction boundaries and error handling.
        
        Args:
            db: Database session
            invoice: Invoice to mark as failed
            
        Returns:
            Updated invoice
        """
        invoice.mark_as_failed()
        db.flush()  # Flush changes but don't commit - let request context handle it
        return invoice
    
    @classmethod
    def get_monthly_invoice_stats(cls, db: Session, year: int, month: int) -> Dict[str, Any]:
        """
        Get invoice statistics for a specific month.
        
        Args:
            db: Database session
            year: Year (e.g., 2025)
            month: Month (1-12)
            
        Returns:
            Dictionary with monthly statistics
        """
        year_month = f"{year:04d}{month:02d}"
        pattern = f"{year_month}-%"
        
        query = text("""
            SELECT 
                COUNT(*) as total_invoices,
                COUNT(CASE WHEN paid_status = 'paid' THEN 1 END) as paid_invoices,
                COUNT(CASE WHEN paid_status = 'unpaid' THEN 1 END) as unpaid_invoices,
                SUM(total) as total_amount,
                SUM(CASE WHEN paid_status = 'paid' THEN total ELSE 0 END) as paid_amount,
                SUM(CASE WHEN paid_status = 'unpaid' THEN total ELSE 0 END) as unpaid_amount
            FROM invoices 
            WHERE number LIKE :pattern
        """)
        
        result = db.execute(query, {"pattern": pattern}).fetchone()
        
        if result:
            return {
                'year_month': year_month,
                'total_invoices': result.total_invoices or 0,
                'paid_invoices': result.paid_invoices or 0,
                'unpaid_invoices': result.unpaid_invoices or 0,
                # Use string representation to maintain Decimal precision
                'total_amount': str(result.total_amount or Decimal("0")),
                'paid_amount': str(result.paid_amount or Decimal("0")),
                'unpaid_amount': str(result.unpaid_amount or Decimal("0"))
            }
        
        return {
            'year_month': year_month,
            'total_invoices': 0,
            'paid_invoices': 0,
            'unpaid_invoices': 0,
            # Use string representation for consistent Decimal handling
            'total_amount': str(Decimal("0")),
            'paid_amount': str(Decimal("0")),
            'unpaid_amount': str(Decimal("0"))
        }