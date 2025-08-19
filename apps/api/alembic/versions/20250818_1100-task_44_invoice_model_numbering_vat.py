"""
Task 4.4: Invoice numbering scheme, VAT calculation, and invoice model

Revision ID: task_44_invoice_model
Revises: 20250818_1000-task_41_license_domain_model
Create Date: 2025-08-18 11:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "task_44_invoice_model"
down_revision = "20250818_1000-task_41_license_domain_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Task 4.4: Create invoice table with Turkish KDV compliance.

    Features:
    - Invoice numbering scheme: 'YYYYMM-SEQ-CNCAI'
    - 20% Turkish VAT calculation
    - Currency fixed to TRY (Turkish Lira)
    - Payment status tracking with specific enum
    - License and user associations
    """

    # Create PaidStatus enum with safe creation
    # FIXED: Use specific exception handling per Gemini Code Assist feedback
    try:
        paid_status_enum = postgresql.ENUM(
            "unpaid",
            "pending",
            "paid",
            "failed",
            "refunded",
            name="paid_status_enum",
            create_type=False,
        )
        paid_status_enum.create(op.get_bind(), checkfirst=True)
    except sa.exc.ProgrammingError as e:
        # Enum already exists - this is expected in idempotent migrations
        # Log this for debugging but don't fail
        if "already exists" not in str(e):
            # Re-raise if it's a different programming error
            raise
    except sa.exc.OperationalError as e:
        # Database operational issues should be re-raised
        raise

    # Create invoices table
    op.create_table(
        "invoices",
        # Primary key
        sa.Column("id", sa.BigInteger(), nullable=False, comment="Invoice primary key"),
        # Foreign keys - Task 4.4 specification
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="User who owns this invoice"),
        sa.Column(
            "license_id", sa.BigInteger(), nullable=False, comment="License this invoice is for"
        ),
        # Invoice identification - Task 4.4 numbering scheme
        sa.Column(
            "number",
            sa.String(length=20),
            nullable=False,
            comment="Unique invoice number: YYYYMM-SEQ-CNCAI format",
        ),
        # Financial amounts - Task 4.4 specification with NUMERIC(12,2) precision
        sa.Column(
            "amount",
            sa.NUMERIC(precision=12, scale=2),
            nullable=False,
            comment="Invoice base amount before VAT",
        ),
        sa.Column(
            "currency",
            sa.CHAR(length=3),
            server_default=sa.text("'TRY'"),
            nullable=False,
            comment="Invoice currency - fixed to TRY",
        ),
        sa.Column(
            "vat",
            sa.NUMERIC(precision=12, scale=2),
            nullable=False,
            comment="VAT amount at 20% Turkish KDV rate",
        ),
        sa.Column(
            "total",
            sa.NUMERIC(precision=12, scale=2),
            nullable=False,
            comment="Total amount including VAT",
        ),
        # Payment status - Task 4.4 specification
        sa.Column(
            "paid_status",
            paid_status_enum,
            server_default=sa.text("'unpaid'"),
            nullable=False,
            comment="Payment status: unpaid, pending, paid, failed, refunded",
        ),
        # Issued timestamp - Task 4.4: Used in numbering scheme
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="When invoice was issued (UTC)",
        ),
        # PDF generation URL - Task 4.4 specification
        sa.Column("pdf_url", sa.Text(), nullable=True, comment="URL to generated PDF invoice"),
        # Provider payment ID - Task 4.4 specification
        sa.Column(
            "provider_payment_id",
            sa.Text(),
            nullable=True,
            comment="External payment provider transaction ID",
        ),
        # Timestamps from TimestampMixin
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Primary key constraint
        sa.PrimaryKeyConstraint("id"),
        # Foreign key constraints
        sa.ForeignKeyConstraint(["license_id"], ["licenses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        # Task 4.4 Ultra-enterprise constraints
        # Currency constraint - Fixed to TRY only
        sa.CheckConstraint("currency = 'TRY'", name="ck_invoices_currency_try_only"),
        # Financial integrity constraints
        sa.CheckConstraint("amount >= 0", name="ck_invoices_amount_non_negative"),
        sa.CheckConstraint("vat >= 0", name="ck_invoices_vat_non_negative"),
        sa.CheckConstraint("total >= 0", name="ck_invoices_total_non_negative"),
        # VAT calculation constraint - total = amount + vat
        sa.CheckConstraint("total = amount + vat", name="ck_invoices_total_equals_amount_plus_vat"),
        # Invoice numbering format constraint - YYYYMM-SEQ-CNCAI
        sa.CheckConstraint(
            "number ~ '^[0-9]{6}-[0-9]{6}-CNCAI$'", name="ck_invoices_number_format"
        ),
    )

    # Create indexes for performance
    op.create_index("idx_invoices_user_paid_status", "invoices", ["user_id", "paid_status"])
    op.create_index("idx_invoices_license_paid_status", "invoices", ["license_id", "paid_status"])
    op.create_index("idx_invoices_issued_at_desc", "invoices", ["issued_at"])
    op.create_index("idx_invoices_number_unique", "invoices", ["number"], unique=True)

    # Partial index for unpaid invoices
    op.create_index(
        "idx_invoices_unpaid",
        "invoices",
        ["user_id", "issued_at"],
        postgresql_where=sa.text("paid_status = 'unpaid'"),
    )


def downgrade() -> None:
    """Remove invoice table and related constraints."""

    # Drop indexes with safe handling
    # FIXED: Use specific exception handling per Gemini Code Assist feedback
    index_names = [
        "idx_invoices_unpaid",
        "idx_invoices_number_unique",
        "idx_invoices_issued_at_desc",
        "idx_invoices_license_paid_status",
        "idx_invoices_user_paid_status",
    ]

    for index_name in index_names:
        try:
            op.drop_index(index_name, table_name="invoices")
        except sa.exc.ProgrammingError as e:
            # Index doesn't exist - expected in idempotent migrations
            if "does not exist" not in str(e):
                # Re-raise if it's a different programming error
                raise
        except sa.exc.OperationalError as e:
            # Database operational issues should be re-raised
            raise

    # Drop table
    op.drop_table("invoices")

    # Drop enum with safe handling
    # FIXED: Use specific exception handling
    try:
        paid_status_enum = postgresql.ENUM(name="paid_status_enum")
        paid_status_enum.drop(op.get_bind(), checkfirst=True)
    except sa.exc.ProgrammingError as e:
        # Enum doesn't exist or is in use - expected
        if "does not exist" not in str(e) and "cannot be dropped" not in str(e):
            raise
    except sa.exc.OperationalError as e:
        # Database operational issues should be re-raised
        raise
