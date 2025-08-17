"""Task 2.5: Billing tables enterprise financial precision

Revision ID: 20250817_1600
Revises: 20250817_1500
Create Date: 2025-08-17 16:00:00.000000

This migration implements billing tables (invoices, payments) with enterprise-grade
financial precision, multi-currency support, and comprehensive audit capabilities
for Task Master ERD strict compliance.

Key Features:
- invoices: Monetary precision using amount_cents (BigInteger), unique number field,
  multi-currency constraints, comprehensive indexing for billing queries
- payments: Provider integration with unique reference tracking, amount_cents precision,
  comprehensive status tracking with paid_at timestamps
- Currency constraints: Configurable multi-currency support via app.multi_currency setting
- Enterprise security: RESTRICT cascades, non-negative amount constraints
- Performance optimization: Specialized indexes for billing query patterns

Financial Integrity:
- All monetary values stored as cents (BigInteger) to prevent floating-point errors
- Multi-currency constraint logic for flexible deployment scenarios
- Comprehensive audit trail with timezone-aware timestamps
- Business logic constraints for data integrity
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250817_1600'
down_revision = '20250817_1500'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Create billing tables with enterprise financial precision."""
    
    # Create enums first
    currency_enum = postgresql.ENUM('TRY', 'USD', 'EUR', name='currency_enum', create_type=True)
    currency_enum.create(op.get_bind(), checkfirst=True)
    
    invoice_status_enum = postgresql.ENUM(
        'DRAFT', 'SENT', 'VIEWED', 'PAID', 'PARTIAL', 'OVERDUE', 'CANCELLED', 'REFUNDED',
        name='invoice_status_enum', create_type=True
    )
    invoice_status_enum.create(op.get_bind(), checkfirst=True)
    
    payment_status_enum = postgresql.ENUM(
        'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELLED', 'REFUNDED', 'PARTIAL_REFUND', 'DISPUTED',
        name='payment_status_enum', create_type=True
    )
    payment_status_enum.create(op.get_bind(), checkfirst=True)
    
    # Create invoices table
    op.create_table(
        'invoices',
        # Primary key with BigInteger for enterprise scale
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        
        # Foreign keys with enterprise security (RESTRICT to prevent data loss)
        sa.Column(
            'user_id', 
            sa.BigInteger(), 
            sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_invoices_user_id'),
            nullable=False,
            comment='User who owns this invoice'
        ),
        
        # Invoice identification (unique business identifier)
        sa.Column(
            'number', 
            sa.String(50), 
            nullable=False, 
            unique=True,
            comment='Unique invoice number for business identification'
        ),
        
        # Financial details with cent precision for accuracy
        sa.Column(
            'amount_cents', 
            sa.BigInteger(), 
            nullable=False,
            comment='Invoice amount in smallest currency unit (cents)'
        ),
        
        # Currency with multi-currency constraint support
        sa.Column(
            'currency', 
            currency_enum, 
            nullable=False,
            server_default=sa.text("'TRY'"),
            comment='Invoice currency code'
        ),
        
        # Invoice lifecycle status
        sa.Column(
            'status', 
            invoice_status_enum, 
            nullable=False,
            server_default=sa.text("'DRAFT'"),
            comment='Current invoice status'
        ),
        
        # Timestamps for billing workflow
        sa.Column(
            'issued_at', 
            sa.DateTime(timezone=True), 
            nullable=True,
            comment='When invoice was issued to customer'
        ),
        sa.Column(
            'due_at', 
            sa.DateTime(timezone=True), 
            nullable=True,
            comment='Payment due date'
        ),
        
        # Flexible metadata storage for invoice details
        sa.Column(
            'meta', 
            postgresql.JSONB(astext_type=sa.Text()), 
            nullable=True,
            server_default=sa.text("'{}'"),
            comment='Invoice metadata: line items, tax details, etc.'
        ),
        
        # Audit trail timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    
    # Create payments table
    op.create_table(
        'payments',
        # Primary key with BigInteger for enterprise scale
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        
        # Foreign keys with enterprise security (RESTRICT to prevent data loss)
        sa.Column(
            'invoice_id', 
            sa.BigInteger(), 
            sa.ForeignKey('invoices.id', ondelete='RESTRICT', name='fk_payments_invoice_id'),
            nullable=False,
            comment='Invoice this payment belongs to'
        ),
        
        # Payment provider integration
        sa.Column(
            'provider', 
            sa.String(50), 
            nullable=False,
            comment='Payment provider identifier (stripe, iyzico, etc.)'
        ),
        sa.Column(
            'provider_ref', 
            sa.String(255), 
            nullable=False,
            unique=True,
            comment='Unique provider transaction reference'
        ),
        
        # Financial details with cent precision for accuracy
        sa.Column(
            'amount_cents', 
            sa.BigInteger(), 
            nullable=False,
            comment='Payment amount in smallest currency unit (cents)'
        ),
        
        # Currency with multi-currency constraint support
        sa.Column(
            'currency', 
            currency_enum, 
            nullable=False,
            server_default=sa.text("'TRY'"),
            comment='Payment currency code'
        ),
        
        # Payment lifecycle status
        sa.Column(
            'status', 
            payment_status_enum, 
            nullable=False,
            server_default=sa.text("'PENDING'"),
            comment='Current payment status'
        ),
        
        # Payment completion timestamp
        sa.Column(
            'paid_at', 
            sa.DateTime(timezone=True), 
            nullable=True,
            comment='When payment was successfully completed'
        ),
        
        # Flexible metadata storage for payment details
        sa.Column(
            'meta', 
            postgresql.JSONB(astext_type=sa.Text()), 
            nullable=True,
            server_default=sa.text("'{}'"),
            comment='Payment metadata: provider details, transaction info, etc.'
        ),
        
        # Audit trail timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    
    # Add constraints
    
    # Invoices constraints
    op.create_check_constraint(
        'ck_invoices_currency_policy',
        'invoices',
        """(
            current_setting('app.multi_currency', true)::text = 'on' 
            OR currency = 'TRY'
        )""",
        info={'comment': 'Multi-currency constraint: allows all currencies if multi_currency setting is on, otherwise restricts to TRY only'}
    )
    
    op.create_check_constraint(
        'ck_invoices_amount_non_negative',
        'invoices',
        'amount_cents >= 0',
        info={'comment': 'Ensure invoice amounts are non-negative'}
    )
    
    op.create_check_constraint(
        'ck_invoices_due_after_issued',
        'invoices',
        '(issued_at IS NULL OR due_at IS NULL OR issued_at <= due_at)',
        info={'comment': 'Ensure due date is not before issue date'}
    )
    
    # Payments constraints
    op.create_check_constraint(
        'ck_payments_currency_policy',
        'payments',
        """(
            current_setting('app.multi_currency', true)::text = 'on' 
            OR currency = 'TRY'
        )""",
        info={'comment': 'Multi-currency constraint: allows all currencies if multi_currency setting is on, otherwise restricts to TRY only'}
    )
    
    op.create_check_constraint(
        'ck_payments_amount_positive',
        'payments',
        'amount_cents > 0',
        info={'comment': 'Ensure payment amounts are positive'}
    )
    
    op.create_check_constraint(
        'ck_payments_completed_has_paid_at',
        'payments',
        "(status != 'COMPLETED' OR paid_at IS NOT NULL)",
        info={'comment': 'Ensure completed payments have paid_at timestamp'}
    )
    
    # Create indexes for optimal billing query performance
    
    # Invoices indexes
    op.create_index(
        'idx_invoices_user_id',
        'invoices',
        ['user_id']
    )
    
    op.create_index(
        'idx_invoices_status',
        'invoices',
        ['status']
    )
    
    op.create_index(
        'idx_invoices_issued_at',
        'invoices',
        ['issued_at'],
        postgresql_where=sa.text('issued_at IS NOT NULL')
    )
    
    op.create_index(
        'idx_invoices_user_status',
        'invoices',
        ['user_id', 'status'],
        postgresql_where=sa.text("status IN ('SENT', 'OVERDUE', 'PARTIAL')")
    )
    
    op.create_index(
        'idx_invoices_due_at',
        'invoices',
        ['due_at'],
        postgresql_where=sa.text("due_at IS NOT NULL AND status NOT IN ('PAID', 'CANCELLED')")
    )
    
    # Payments indexes
    op.create_index(
        'idx_payments_invoice_id',
        'payments',
        ['invoice_id']
    )
    
    op.create_index(
        'idx_payments_status',
        'payments',
        ['status']
    )
    
    op.create_index(
        'idx_payments_paid_at',
        'payments',
        ['paid_at'],
        postgresql_where=sa.text('paid_at IS NOT NULL')
    )
    
    op.create_index(
        'idx_payments_invoice_status',
        'payments',
        ['invoice_id', 'status'],
        postgresql_where=sa.text("status IN ('PENDING', 'PROCESSING')")
    )
    
    op.create_index(
        'idx_payments_provider',
        'payments',
        ['provider', 'status'],
        postgresql_where=sa.text("status = 'PENDING'")
    )


def downgrade() -> None:
    """Drop billing tables and related objects."""
    
    # Drop tables (constraints and indexes are dropped automatically)
    op.drop_table('payments')
    op.drop_table('invoices')
    
    # Drop enums
    payment_status_enum = postgresql.ENUM(name='payment_status_enum')
    payment_status_enum.drop(op.get_bind(), checkfirst=True)
    
    invoice_status_enum = postgresql.ENUM(name='invoice_status_enum')
    invoice_status_enum.drop(op.get_bind(), checkfirst=True)
    
    currency_enum = postgresql.ENUM(name='currency_enum')
    currency_enum.drop(op.get_bind(), checkfirst=True)